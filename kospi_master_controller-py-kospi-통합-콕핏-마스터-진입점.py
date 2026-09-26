# -*- coding: utf-8 -*-
"""
kospi_master_controller.py
=======================================================================
KOSPI 통합 퀀트 콕핏 - Master Controller (단일 진입점)

세 개의 독립 프로그램을 하나의 프로세스에서 병렬 구동하고, 하나의 통합
대시보드(브라우저)로 모은다.

  1) kospi_model_arena_observatory_v2.py  (Arena: 모델 경쟁 + OOS Ledger)
  2) kospi_cockpit_sensor_hub_v1.1.py     (3센서: TIR/Friction/State-Space + Cascade Gate)
  3) tir_reflection_backtest_v1.py        (TIR v1 기준선, 허브가 import해 사용)
  4) market_runtime_kospi_v3_consolidated.py (핵심 로직 요약본: 실제 동작 인터페이스인
     SessionClock/Phase 장 구간 상태머신과 market_context.json 계약만 연결.
     R_dynamic은 실제 계산이 아니므로 ReferenceFormulas 예시 재현값만 표시)

주의) import 문에서 '.v'나 '.1' 같은 문자는 모듈명에 쓸 수 없으므로, 실제
배포 시 파일명에서 점을 빼거나(kospi_cockpit_sensor_hub_v11.py) 아래의
importlib 로딩 방식을 그대로 사용한다. 아래 코드는 점이 있는 파일명도
안전하게 불러오는 importlib 방식을 기본으로 한다.

연결부 검증 결과 (2026-09-25, 업로드 원본 기준 정적 검증)
----------------------------------------------------
- Arena: generate_demo_data/normalize_bars/Arena.run_backtest_replay(horizon=5)/
  evaluate_current(provider, quality) 및 ArenaResult 필드(regime, current_priority,
  oos_leader, current_reason, market_state, predictions, oos) 모두 확인됨.
- Cockpit Hub: generate_mock_daily_bars(n_days)/generate_mock_intraday_bars(n_bars,
  start)/KospiCockpitSensorHub.run(df_intraday, df_daily)/tir_sensor.compute/
  using_real_module/using_real_engine 및 FINAL_COLUMNS(tir_event, Q_z, friction_score,
  friction_spike, x_t, v_t, a_t, cascade_label, regime_alert) 모두 확인됨.
- 운영 주의 1: Arena의 run_backtest_replay는 720바 walk-forward(약 645회 x 4모델)로
  첫 사이클에 수십 초~수 분이 걸릴 수 있다. 대시보드 "계산 대기 중" 표시가 오래
  지속되면 --interval을 늘리거나 첫 렌더 완료를 기다린다.
- 운영 주의 2: CockpitGate.fuse는 정렬된(오름차순) 타임스탬프를 가정한다.
  실데이터 연동 시 분봉/일봉 모드 시간 오름차순 정렬 후 hub.run()에 전달한다.
- 운영 주의 3: friction_engine.py가 없으면 매 사이클 RuntimeWarning 폴백 경고가
  stdout에 출력된다(정상 동작, 실제 엔진 연결 시 소멸).

실행
----
    python kospi_master_controller.py
    python kospi_master_controller.py --port 8765 --no-browser
    python kospi_master_controller.py --interval 30        # 30초마다 재계산

설계 원칙 (기존 프로젝트 원칙 유지)
----------------------------------
- 각 모듈은 "그대로 import"해서 재사용한다. 어떤 모듈도 수정/덮어쓰지 않는다.
- Arena(예측 모델)와 센서(TIR/Friction/State-Space)는 서로 다른 것을 측정하는
  독립 계층이므로 하나의 점수로 합치지 않는다. 통합 대시보드는 "같은 화면에
  나란히 보여줄" 뿐이다.
- 센서 간 계산 순서 의존 없음(병렬). 결합은 CockpitGate의 조건부 cascade로만.
- 데모는 synthetic replay. LIVE 표시는 실제 데이터 원천이 연결될 때만.
- 공유 상태는 state.json(디스크)으로 주고받는다 - 외부 프로세스(consolidated
  엔진 등)가 나중에 붙어도 같은 계약을 따르면 된다.
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import os
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


# ======================================================================
# 0. 의존 모듈 로드 (파일명에 점이 있어도 안전하게 import)
# ======================================================================

def _load_module(filename: str, alias: str):
    """같은 폴더의 .py 파일을 모듈로 로드. 없으면 None."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    if not os.path.exists(path):
        return None
    spec = importlib.util.spec_from_file_location(alias, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


observatory = _load_module("kospi_model_arena_observatory_v2.py", "observatory")
cockpit = _load_module("kospi_cockpit_sensor_hub_v1.1.py", "cockpit")

if observatory is None or cockpit is None:
    raise SystemExit(
        "필수 모듈을 찾을 수 없습니다. 다음 파일들을 이 스크립트와 같은 폴더에 두세요:\n"
        "  - kospi_model_arena_observatory_v2.py\n"
        "  - kospi_cockpit_sensor_hub_v1.1.py\n"
        "  - tir_reflection_backtest_v1.py (센서 허브가 import)"
    )


# ======================================================================
# 1. 통합 상태 (공유 계약)
# ======================================================================

@dataclass
class MasterState:
    """모든 워커가 갱신하는 통합 스냅샷. 대시보드는 이것만 읽어 렌더링한다."""
    lock: threading.Lock = field(default_factory=threading.Lock)
    updated_at: str = ""
    # Arena 계층
    regime: str = ""
    current_priority: Optional[str] = None
    oos_leader: Optional[str] = None
    priority_reason: str = ""
    market_state: Dict[str, float] = field(default_factory=dict)
    predictions: List[Dict[str, Any]] = field(default_factory=list)
    oos_table: List[Dict[str, Any]] = field(default_factory=list)
    # 센서 계층 (Cockpit Hub)
    cockpit_summary: Dict[str, Any] = field(default_factory=dict)
    cascade_counts: Dict[str, int] = field(default_factory=dict)
    latest_alerts: List[Dict[str, Any]] = field(default_factory=list)
    # Consolidated 엔진 슬롯
    consolidated: Dict[str, Any] = field(default_factory=dict)
    consolidated_available: bool = False
    # 데이터 원천
    provider: str = "demo_replay"
    quality: str = "GOOD"

    def to_json(self) -> str:
        with self.lock:
            return json.dumps({
                "updated_at": self.updated_at,
                "regime": self.regime,
                "current_priority": self.current_priority,
                "oos_leader": self.oos_leader,
                "priority_reason": self.priority_reason,
                "market_state": self.market_state,
                "predictions": self.predictions,
                "oos_table": self.oos_table,
                "cockpit_summary": self.cockpit_summary,
                "cascade_counts": self.cascade_counts,
                "latest_alerts": self.latest_alerts,
                "consolidated": self.consolidated,
                "consolidated_available": self.consolidated_available,
                "provider": self.provider,
                "quality": self.quality,
            }, ensure_ascii=False, default=str)


STATE = MasterState()


# ======================================================================
# 2. 워커 A: Arena (옵저버토리 v2 재사용)
# ======================================================================

def arena_worker(interval: float) -> None:
    """Arena를 주기적으로 재계산한다. 모듈을 수정하지 않고 재사용만 한다."""
    bars = observatory.generate_demo_data()
    while True:
        try:
            arena = observatory.Arena()
            df = observatory.normalize_bars(bars, "demo_replay")
            arena.run_backtest_replay(df, horizon=5)          # OOS Ledger 채움
            result = arena.evaluate_current(df, "demo_replay", "GOOD")

            oos_records = []
            if not result.oos.empty:
                oos_records = result.oos.to_dict(orient="records")

            preds = []
            for p in result.predictions:
                preds.append({
                    "model": p["model"],
                    "signal": p.get("direction", p.get("signal", "?")),
                    "strength": float(p.get("strength", 0)),
                    "fit": observatory.REGIME_FIT.get(p["model"], {}).get(result.regime, 0.5),
                })

            with STATE.lock:
                STATE.updated_at = str(pd.Timestamp.now(tz="Asia/Seoul"))
                STATE.regime = result.regime
                STATE.current_priority = result.current_priority
                STATE.oos_leader = result.oos_leader
                STATE.priority_reason = result.current_reason
                STATE.market_state = dict(result.market_state)
                STATE.predictions = preds
                STATE.oos_table = oos_records
        except Exception as exc:  # 워커는 죽지 않는다
            with STATE.lock:
                STATE.priority_reason = f"[arena error] {exc}"
        time.sleep(interval)


# ======================================================================
# 3. 워커 B: Cockpit Sensor Hub (v1.1 재사용)
# ======================================================================

def cockpit_worker(interval: float) -> None:
    """
    센서 허브 v1.1을 주기적으로 재계산한다.
    실전에서는 df_intraday/df_daily를 ProviderHub가 공급하지만, 데모에서는
    허브 자체의 mock 생성기를 사용한다(모듈 수정 없이 재사용).
    """
    while True:
        try:
            df_daily = cockpit.generate_mock_daily_bars(n_days=250)
            hub = cockpit.KospiCockpitSensorHub()

            # TIR 이벤트 발생일에 분봉을 맞춰 cascade가 실제로 관측되게 한다
            tir_daily = hub.tir_sensor.compute(df_daily)
            event_days = tir_daily.index[tir_daily["tir_event"].fillna(False)]
            demo_date = event_days[-1] if len(event_days) > 0 else df_daily.index[-1]
            df_intraday = cockpit.generate_mock_intraday_bars(
                n_bars=500, start=f"{demo_date.date()} 09:00")

            result = hub.run(df_intraday, df_daily)

            summary = {
                "tir_sensor_real_module": bool(hub.tir_sensor.using_real_module),
                "friction_real_engine": bool(hub.friction_adapter.using_real_engine),
                "n_records": int(len(result)),
                "n_valid": int(result["cascade_label"].notna().sum()),
            }
            tail = result.dropna(subset=["friction_score"]).tail(1)
            if not tail.empty:
                row = tail.iloc[0]
                summary.update({
                    "x_t": float(row.get("x_t", np.nan)),
                    "v_t": float(row.get("v_t", np.nan)),
                    "a_t": float(row.get("a_t", np.nan)),
                    "Q_z": float(row.get("Q_z", np.nan)),
                    "friction_score": float(row.get("friction_score", np.nan)),
                    "friction_spike": bool(row.get("friction_spike", False)),
                    "tir_event": bool(row.get("tir_event", False)),
                    "cascade_label": str(row.get("cascade_label", "")),
                    "regime_alert": bool(row.get("regime_alert", False)),
                })

            counts = result["cascade_label"].value_counts().to_dict()
            alerts = []
            alert_rows = result[result["regime_alert"] == True]  # noqa: E712
            for _, r in alert_rows.head(5).iterrows():
                alerts.append({
                    "timestamp": str(r.name),
                    "Q_z": float(r.get("Q_z", np.nan)),
                    "friction_score": float(r.get("friction_score", np.nan)),
                    "x_t": float(r.get("x_t", np.nan)),
                    "cascade_label": str(r.get("cascade_label", "")),
                })

            with STATE.lock:
                STATE.cockpit_summary = summary
                STATE.cascade_counts = {str(k): int(v) for k, v in counts.items()}
                STATE.latest_alerts = alerts
        except Exception as exc:
            with STATE.lock:
                STATE.cockpit_summary = {"error": str(exc)}
        time.sleep(interval)


# ======================================================================
# 4. 워커 C: Consolidated 엔진 슬롯 (market_runtime_kospi_v3_consolidated.py)
# ======================================================================

def consolidated_worker(interval: float) -> None:
    """
    market_runtime_kospi_v3_consolidated.py 연결 워커 (v3 요약본 기준, 2026-09-25 확정).

    파일 성격 확인 결과: 이 파일은 '실행 엔진'이 아니라 핵심 로직 요약본이며,
    원문 스스로 "실제 배포본은 02_engine/ 원본 모듈을 사용하라"고 명시한다.
    따라서 이 워커는 다음 두 가지 '실제 동작하는' 인터페이스만 사용한다:

      1) SessionClock / Phase : KST 장 구간 상태머신 (OFF/PREOPEN/OPEN/AUCTION/POSTCLOSE)
         - TradingCalendar에 휴장일 파일(04_data/krx_holidays_v1.json)이 있으면 로드,
           없으면 주말만 제외하는 기본 달력으로 동작한다.
      2) read_context / validate_context : market_context.json 계약
         - 파일이 있으면 유효성·낡음(asof_date)을 검사해 상태만 보고한다.
         - 정식 컨텍스트 빌더는 이 컨트롤러가 대체하지 않는다(원본 01_strategy/ 역할).
         - 없으면 "context file not found"를 있는 그대로 표시한다 (기본값을
           지어내지 않는다 - 원본 계약 원칙).

    R_dynamic 표기 원칙(사용자 합의 유지):
      - 실제 계산 코드가 아니므로 ReferenceFormulas.example_r_dynamic()의
        '예시 재현값'을 표시하되 R_dynamic_verified=False, 출처를 명시한다.
      - 실제 운영값은 원본 Decision Engine(02_engine/)이 연결될 때만 노출한다.
    """
    module = _load_module("market_runtime_kospi_v3_consolidated.py", "consolidated")

    if module is None:
        with STATE.lock:
            STATE.consolidated_available = False
            STATE.consolidated = {
                "status": "SLOT_UNAVAILABLE",
                "message": "market_runtime_kospi_v3_consolidated.py 미연결 (파일을 같은 폴더에 추가하면 자동 인식)",
            }
        return  # 데모에서는 재시도하지 않는다. 재연결은 재기동으로.

    # 세션 시계 구성: 휴장일 파일이 있으면 로드, 없으면 주말만 제외(휴장일 미관리 상태 표시)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    holidays_path = os.path.join(base_dir, "04_data", "krx_holidays_v1.json")
    holidays_managed = False
    try:
        from pathlib import Path as _P
        calendar = module.TradingCalendar.from_file(_P(holidays_path))
        holidays_managed = True
    except Exception:
        calendar = module.TradingCalendar()
    clock = module.SessionClock(module.SessionConfig(), calendar)

    from pathlib import Path as _P2
    ctx_file = _P2(os.path.join(base_dir, "market_context.json"))

    with STATE.lock:
        STATE.consolidated_available = True

    while True:
        try:
            now = datetime.now(module.KST)
            phase = clock.phase(now)

            # market_context.json 계약 상태 읽기 (기본값 지어내지 않음)
            ctx_status = "CONTEXT_NOT_FOUND"
            ctx_stale = False
            ctx_regime = None
            ctx_engine_level = None
            ctx_problems = []
            if ctx_file.exists():
                read = module.read_context(ctx_file, expected_asof=now.date())
                if read.ctx is None:
                    ctx_status = "CONTEXT_INVALID"
                    ctx_problems = read.problems
                elif read.stale:
                    ctx_status = "CONTEXT_STALE"
                    ctx_regime = read.ctx.get("regime")
                    ctx_engine_level = read.ctx.get("engine_level")
                    ctx_stale = True
                    ctx_problems = read.problems
                elif read.problems:
                    ctx_status = "CONTEXT_PROBLEMS"
                    ctx_problems = read.problems
                else:
                    ctx_status = "CONTEXT_OK"
                    ctx_regime = read.ctx.get("regime")
                    ctx_engine_level = read.ctx.get("engine_level")

            payload = {
                "status": "CONNECTED",
                "phase": phase.value,
                "phase_kst": now.isoformat(),
                "holidays_managed": holidays_managed,
                "context_status": ctx_status,
                "context_stale": ctx_stale,
                "context_regime": ctx_regime,
                "context_engine_level": ctx_engine_level,
                "context_problems": ctx_problems,
                # R_dynamic: 실제 계산 아님 - ReferenceFormulas 예시 재현값만 표시
                "R_dynamic": None,
                "R_dynamic_example": round(module.ReferenceFormulas.example_r_dynamic(), 2),
                "R_dynamic_verified": False,
                "message": "v3 요약본 인터페이스(세션 시계·컨텍스트 계약) 연결. "
                           "R_dynamic은 원본 Decision Engine 연결 전까지 예시 재현값만 표시.",
            }
            with STATE.lock:
                STATE.consolidated = payload
        except Exception as exc:
            with STATE.lock:
                STATE.consolidated = {"status": "ERROR", "message": str(exc)}
        time.sleep(min(interval, 60.0))  # 장 구간은 최대 60초 주기로 갱신


# ======================================================================
# 5. 상태 파일 동기화 (외부 프로세스와의 공유 계약)
# ======================================================================

def state_file_worker(path: str = "state.json", interval: float = 2.0) -> None:
    """통합 상태를 state.json으로 계속 내려쓴다. 외부 스크립트가 읽을 수 있다."""
    while True:
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(STATE.to_json())
            os.replace(tmp, path)
        except Exception:
            pass
        time.sleep(interval)


# ======================================================================
# 6. 통합 대시보드 (단일 HTML, 단일 포트)
# ======================================================================

CSS = """
:root{--bg:#07111f;--panel:#0d1b2a;--line:#20384f;--text:#e9f1f7;--muted:#8fa7ba;--good:#42d392;--warn:#f4c95d;--bad:#ff6b6b;--blue:#55a7ff}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(135deg,#06101c,#0b1b2b 55%,#07111f);color:var(--text);font-family:Inter,'Malgun Gothic',Arial,sans-serif}
.wrap{max-width:1500px;margin:auto;padding:24px}.title{font-size:30px;font-weight:800}.sub{color:var(--muted);margin-top:5px}
.grid{display:grid;gap:14px}.top{grid-template-columns:repeat(6,1fr);margin:20px 0}.two{grid-template-columns:1.2fr .8fr}.three{grid-template-columns:1fr 1fr 1fr}
.card{background:rgba(13,27,42,.94);border:1px solid var(--line);border-radius:14px;padding:17px;box-shadow:0 10px 30px #0003}
.label{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}
.value{font-size:22px;font-weight:750;margin-top:7px}.big{font-size:32px}
.good{color:var(--good)}.warn{color:var(--warn)}.bad{color:var(--bad)}
table{width:100%;border-collapse:collapse}th,td{padding:10px 8px;border-bottom:1px solid var(--line);text-align:left;font-size:13px}th{color:var(--muted)}
.bar{height:8px;background:#142c42;border-radius:10px;overflow:hidden}.fill{height:100%;background:var(--blue);border-radius:10px}
.reason{font-size:14px;line-height:1.6;color:#cfe0ec}.pill{display:inline-block;padding:4px 8px;border-radius:999px;background:#16324a;margin:2px;font-size:11px}
.footer{color:#7890a4;font-size:11px;margin-top:18px}
@media(max-width:1000px){.top{grid-template-columns:1fr 1fr 1fr}.two,.three{grid-template-columns:1fr 1fr}}@media(max-width:650px){.top,.two,.three{grid-template-columns:1fr}}
"""


def _fmt(v, digits=2):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "N/A"
    return f"{v:.{digits}f}"


def _pct(v):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "N/A"
    return f"{v:.1%}"


def render_page() -> str:
    with STATE.lock:
        s = {
            "updated_at": STATE.updated_at, "regime": STATE.regime,
            "current_priority": STATE.current_priority, "oos_leader": STATE.oos_leader,
            "priority_reason": STATE.priority_reason, "market_state": STATE.market_state or {},
            "predictions": STATE.predictions or [], "oos_table": STATE.oos_table or [],
            "cockpit_summary": STATE.cockpit_summary or {},
            "cascade_counts": STATE.cascade_counts or {}, "latest_alerts": STATE.latest_alerts or [],
            "consolidated": STATE.consolidated or {"status": "SLOT_UNAVAILABLE"},
        }

    cs = s["cockpit_summary"]
    cascade = str(cs.get("cascade_label", "N/A"))
    cascade_cls = "bad" if cs.get("regime_alert") else ("warn" if cascade.startswith("TIR") else "good")

    pred_rows = []
    ranked = sorted(s["predictions"], key=lambda p: -(p.get("strength", 0) * p.get("fit", 0)))
    for i, p in enumerate(ranked, 1):
        obs = p.get("strength", 0) * p.get("fit", 0)
        pred_rows.append(
            f"<tr><td><b>#{i}</b></td><td><b>{html.escape(p['model'])}</b></td>"
            f"<td>{html.escape(str(p['signal']))}</td><td>{_fmt(p.get('strength'))}</td>"
            f"<td>{_fmt(p.get('fit'))}</td>"
            f"<td><div class='bar'><div class='fill' style='width:{obs*100:.0f}%'></div></div></td></tr>"
        )

    oos_rows = []
    for r in s["oos_table"]:
        oos_rows.append(
            f"<tr><td><b>{html.escape(str(r.get('model')))}</b></td><td>{int(r.get('n') or 0)}</td>"
            f"<td>{_pct(r.get('directional_accuracy'))}</td><td>{_fmt(r.get('brier'), 3)}</td>"
            f"<td>{_fmt(r.get('mae'), 4)}</td><td>{_fmt(r.get('profit_factor'))}</td>"
            f"<td><span class='pill'>{html.escape(str(r.get('status')))}</span></td></tr>"
        )

    cascade_rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{v}건</td></tr>" for k, v in s["cascade_counts"].items()
    ) or "<tr><td colspan='2'>계산 대기 중</td></tr>"

    alert_rows = "".join(
        f"<tr><td>{html.escape(a['timestamp'])}</td><td>{_fmt(a.get('Q_z'))}</td>"
        f"<td>{_fmt(a.get('friction_score'), 4)}</td><td>{_fmt(a.get('x_t'))}</td>"
        f"<td><span class='pill'>{html.escape(a['cascade_label'])}</span></td></tr>"
        for a in s["latest_alerts"]
    ) or "<tr><td colspan='5'>이번 구간에서 붕괴 이벤트 없음 (데모 시드에 따라 다름)</td></tr>"

    cons = s["consolidated"]
    cons_status = html.escape(str(cons.get("status", "SLOT_UNAVAILABLE")))
    cons_cls = "good" if cons_status == "CONNECTED" else "warn"
    r_dyn = _fmt(cons.get("R_dynamic"))
    if r_dyn == "N/A" and cons.get("R_dynamic_example") is not None:
        r_dyn = f"{_fmt(cons.get('R_dynamic_example'))} <span style='font-size:11px;color:#8fa7ba'>(예시 재현값, 미검증)</span>"
    cons_msg = html.escape(str(cons.get("message", "")))
    phase_val = html.escape(str(cons.get("phase", "-")))
    phase_cls = "good" if phase_val in ("OPEN", "AUCTION") else ("warn" if phase_val == "PREOPEN" else "")
    ctx_val = html.escape(str(cons.get("context_status", "-")))
    ctx_cls = "good" if ctx_val == "CONTEXT_OK" else ("warn" if ctx_val == "CONTEXT_STALE" else "bad" if ctx_val == "CONTEXT_INVALID" else "")

    ms = s["market_state"]
    tir_real = "실제 v1 모듈" if cs.get("tir_sensor_real_module") else "폴백 proxy"
    fric_real = "실제 엔진" if cs.get("friction_real_engine") else "폴백 proxy"

    return f"""<!doctype html><html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>KOSPI Master Cockpit - 통합 대시보드</title><style>{CSS}</style></head>
<body><div class='wrap'>
<div class='title'>🛰 KOSPI MASTER COCKPIT — 통합 대시보드</div>
<div class='sub'>Arena(예측 경쟁) + Cockpit Hub(3센서 cascade) + Consolidated 슬롯을 한 화면에서 관찰합니다.</div>

<div class='grid top'>
<div class='card'><div class='label'>REGIME</div><div class='value'>{html.escape(s['regime'] or '...')}</div></div>
<div class='card'><div class='label'>CURRENT PRIORITY</div><div class='value big good'>{html.escape(s['current_priority'] or '...')}</div></div>
<div class='card'><div class='label'>OOS LEADER</div><div class='value'>{html.escape(s['oos_leader'] or 'UNVERIFIED')}</div></div>
<div class='card'><div class='label'>CASCADE 상태</div><div class='value {cascade_cls}'>{html.escape(cascade)}</div></div>
<div class='card'><div class='label'>장 구간 (SESSION)</div><div class='value {phase_cls}'>{phase_val}</div><div class='sub'>{ctx_val} · R_dyn {r_dyn}</div></div>
<div class='card'><div class='label'>DATA</div><div class='value'>{html.escape('demo_replay')}</div><div class='sub'>updated {html.escape(s['updated_at'] or '-')}</div></div>
</div>

<div class='grid two'>
<div class='card'><div class='label'>WHY PRIORITY?</div><div class='reason'>{html.escape(s['priority_reason'] or '계산 대기 중...')}</div></div>
<div class='card'><div class='label'>MARKET STATE</div><div class='reason'>
Trend <b>{_fmt(ms.get('trend'))}</b> · Momentum <b>{_fmt(ms.get('momentum'))}</b> ·
Volatility <b>{_fmt(ms.get('volatility'))}</b> · MA distance <b>{_fmt(ms.get('distance_ma'), 4)}</b></div></div>
</div>

<div class='card' style='margin-top:14px'><div class='label'>ARENA — 현재 관측 (신호강도 × Regime 적합도)</div>
<table><thead><tr><th>Rank</th><th>Model</th><th>Signal</th><th>Strength</th><th>Regime Fit</th><th>Obs</th></tr></thead>
<tbody>{''.join(pred_rows) or "<tr><td colspan='6'>계산 대기 중</td></tr>"}</tbody></table></div>

<div class='grid three' style='margin-top:14px'>
<div class='card'><div class='label'>센서 1 — TIR (일봉)</div>
<div class='value'>{'ACTIVE' if cs.get('tir_event') else 'NORMAL'}</div>
<div class='sub'>소스: {tir_real} · Q_z {_fmt(cs.get('Q_z'))}</div></div>
<div class='card'><div class='label'>센서 2 — FRICTION (분봉)</div>
<div class='value {'bad' if cs.get('friction_spike') else 'good'}'>{'SPIKE' if cs.get('friction_spike') else 'NORMAL'}</div>
<div class='sub'>score {_fmt(cs.get('friction_score'), 4)} · 소스: {fric_real}</div></div>
<div class='card'><div class='label'>센서 3 — STATE-SPACE (분봉)</div>
<div class='value'>x {_fmt(cs.get('x_t'))} · v {_fmt(cs.get('v_t'))}</div>
<div class='sub'>a {_fmt(cs.get('a_t'))} · 유효레코드 {cs.get('n_valid', '...')}</div></div>
</div>

<div class='grid two' style='margin-top:14px'>
<div class='card'><div class='label'>CASCADE LABEL 분포 (이번 구간)</div>
<table><thead><tr><th>Label</th><th>건수</th></tr></thead><tbody>{cascade_rows}</tbody></table></div>
<div class='card'><div class='label'>⚠ 저항붕괴 상태전이 알림 (regime_alert)</div>
<table><thead><tr><th>시점</th><th>Q_z</th><th>Friction</th><th>x_t</th><th>Label</th></tr></thead>
<tbody>{alert_rows}</tbody></table></div>
</div>

<div class='card' style='margin-top:14px'><div class='label'>OOS VALIDATION LAYER (walk-forward)</div>
<table><thead><tr><th>Model</th><th>N</th><th>Directional Acc</th><th>Brier</th><th>MAE</th><th>PF</th><th>Status</th></tr></thead>
<tbody>{''.join(oos_rows) or "<tr><td colspan='7'>아직 평가된 OOS 예측 없음</td></tr>"}</tbody></table></div>

<div class='card' style='margin-top:14px'><div class='label'>MARKET RUNTIME v3 — 세션 시계 · 컨텍스트 계약</div>
<div class='reason'>
장 구간: <b>{phase_val}</b> · KST {html.escape(str(cons.get('phase_kst', '-')))} ·
휴장일 관리: {html.escape(str(cons.get('holidays_managed', '-')))}<br>
market_context.json: <b>{ctx_val}</b> · regime {html.escape(str(cons.get('context_regime') or '-'))} ·
engine_level {html.escape(str(cons.get('context_engine_level') or '-'))}<br>
R_dynamic: {r_dyn}<br>
status: <b>{cons_status}</b> · {cons_msg}</div></div>

<div class='footer'>데모는 synthetic replay이며 실제 KOSPI 성능을 의미하지 않습니다. 원본 모듈은 수정 없이 재사용됩니다. (10초마다 자동 새로고침)</div>
</div></body></html>"""


class MasterHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in {"/", "/index.html"}:
            body = render_page().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Refresh", "10")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/state.json":
            body = STATE.to_json().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        return


# ======================================================================
# 7. MAIN — 스레드 기동 + 단일 서버
# ======================================================================

def main():
    parser = argparse.ArgumentParser(description="KOSPI Master Cockpit (통합 진입점)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--interval", type=float, default=60.0,
                        help="Arena/Cockpit 재계산 주기(초)")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    print("=" * 70)
    print(" KOSPI MASTER COCKPIT — 통합 런타임 기동")
    print("=" * 70)

    threads = [
        threading.Thread(target=arena_worker, args=(args.interval,), daemon=True, name="arena"),
        threading.Thread(target=cockpit_worker, args=(args.interval,), daemon=True, name="cockpit"),
        threading.Thread(target=consolidated_worker, args=(args.interval,), daemon=True, name="consolidated"),
        threading.Thread(target=state_file_worker, daemon=True, name="state-file"),
    ]
    for t in threads:
        t.start()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), MasterHandler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"통합 대시보드: {url}")
    print(f"상태 API     : {url}state.json  (외부 프로세스용 계약)")
    print("종료: Ctrl+C\n")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n시스템을 안전하게 종료합니다.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()