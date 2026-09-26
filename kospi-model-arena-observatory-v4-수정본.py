# -*- coding: utf-8 -*-
"""
KOSPI Model Arena Observatory v4
================================

v2 검증 결과의 수정 사항을 반영한 단일 파일 Observatory.

v3 후속 수정 (7차 — TIR 원본 실물 반영, 2026-09-26)
----------------------------------
[F7-3] TIR import를 함수 기반으로 수정: 원본 tir_reflection_backtest_v1.py에는
       TIRReflectionV1 클래스가 없고 run_backtest_v1/compute_tir_proxies
       함수가 있다(실물 확인). import tir_reflection_backtest_v1 후
       run_backtest_v1()을 호출하는 TIRV1External 래퍼 추가 — 이제 원본이
       있으면 실제 frozen baseline이 쓰인다(기존 코드는 존재하지 않는
       클래스를 import해 항상 폴백으로 떨어졌음).
       폴백 컬럼명도 원본과 동일(tir_score/tir_signal)로 통일.
[F7-4] TIR_v2 상태 매핑을 원본 classify_v2_states 4분류에 일치:
       TRAPPED(TIR+Slow) / LEAK_WARNING(TIR+Fast) / NORMAL(미충족+Slow,
       원본 '일반') / BREAKOUT_후보(미충족+Fast). 임계값도 원본과 동일하게
       |v_proxy| expanding quantile(0.70)+shift(1).

v3 후속 수정 (6차 검증 반영)
----------------------------------
[F4-11] _fingerprint_subset dict 인덱싱 크래시(TypeError: unhashable
       type: 'list') 수정 — 전체 이중 루프를 폐지하고
       (timestamp, model, horizon, price, p_up) groupby 후 그룹 내
       심볼 비교로 O(n) 근사 재작성. 가격·p_up까지 같은 지문만 중복.

v3 후속 수정 (5차 검증 반영)
----------------------------------
[F4-8] 통계 방어선 강화: 중복 검사를 심볼/소스와 무관한 '내용 지문'
       (timestamp, model, horizon, price_at_prediction, p_up)으로
       변경하고 symbol="UNKNOWN"을 wildcard 취급. --legacy-symbol을
       빠뜨려도 구형+신규 중복이 VERIFIED로 통과하지 않는다.
[F4-9] 원장 키(기록 계층, source 포함)와 통계 검사(시장 시점 기준,
       source 무시)의 역할 분담을 주석에 명시. 같은 시각·모델·가격의
       예측이 source만 다르게 존재하면 DUPLICATED_SAMPLE로 탈락 —
       같은 시장 시점을 두 번 세지 않는다.
[F4-10] .gitignore 안내 축소: *.jsonl 전체가 아닌 원장 전용 폴더
       (observatory_ledger/)와 ledger*.jsonl만 제외.

v3 후속 수정 (4차 검증 반영)
----------------------------------
[F4-6] 구형 원장 중복 방지: load(legacy_symbol=...)가 UNKNOWN 심볼을
       승격(--legacy-symbol KOSPI)해 새 리플레이와 키 충돌 방지.
       추가로 OOSAnalyzer가 (model, symbol, timestamp, horizon)
       유일성을 검사해 중복 표본이 있으면 VERIFIED 대신
       DUPLICATED_SAMPLE를 부여 — 원장 형식과 무관한 통계 방어선.
[F4-7] save()가 신규 레코드를 쓸 때 _saved_status를 함께 기록해
       리플레이에서 record 409줄 + update 409줄(2배 파일)이
       붙던 현상 제거.
[F12-3] _obs_score 주석의 승수 예시 수정(DA 60% → ×1.19).

v3 후속 수정 (3차 검증 반영)
----------------------------------
[F12-2] 승수 기준선 정렬(3차 검증): VERIFIED는 항상 ×1.0 이상
       (edge = 2·DA−1 기반), NO_EDGE ×0.85, 미검증 ×1.0.
       검증 통과 모델(≈×0.76)이 NO_EDGE(×0.85)/미검증(×1.0)보다
       낮아지던 승수 역전을 수정.
[F4-5] 평가 갱신 영속화(3차 검증): save()가 신규 레코드(_t=record)와
       평가 갱신 이벤트(_t=update)를 모두 append. load()는 같은 키의
       마지막 상태를 적용하므로, 실시간 "기록(PENDING) → 실제값
       부착(EVALUATED)" 순환이 재적재 후에도 유지된다.
[F4-4] 중복 키에 symbol과 source 추가(3차 검증):
       (timestamp, model, horizon, symbol, source). 같은 시각에 다른
       종목/공급원의 예측이 조용히 버려지지 않는다.
       PredictionRecord에 symbol 필드 추가(구형 원장 파일 호환).

v3 후속 수정 (2차 검증 반영)
----------------------------------
[F4-1] 원장 직렬화 크래시 수정: numpy.bool_ 등을 처리하는
       _json_default + evaluate()에서 순수 bool 캐스팅.
[F4-2] 중복 기록 차단: (timestamp, model, horizon) 키로 add()가
       중복을 무시한다. 재적재 후 재리플레이/반복 호출로 표본이
       두 배가 되는 일은 없다.
[F4-3] save()는 전체 덮어쓰기가 아니라 신규 레코드만 append한다.
       주석의 "append-only" 표현과 동작을 일치시킴.
[F5-2] run_demo()가 hub.fetch_orderbook()을 실제 호출해
       evaluate_current()에 전달한다. demo에선 호가가 없으므로
       Friction이 ORDERBOOK_UNAVAILABLE로 정직하게 표시됨.
[F7-2] TIR import 실패가 조용히 넘어가지 않고 실패 사유가 기록되고
       터미널에 표시된다. TIR_v2 주석은 원본 정의와의 일치를
       '검증되지 않은 재구현 규칙'으로 정직하게 고쳤다.
[F9-2] 변동성 척도를 절대 clip(0, 1%)에서 '자기 이력 대비 분위수'로
       변경. 포화로 인해 BREAKOUT_TRANSITION이 trend 하나로
       결정되던 문제를 해소. 이력 120봉 미만은 중립치.
[F12] NO_EDGE를 미검증과 구분하고 스코어에 ×0.85 페널티.
       통계적으로 우위가 없다고 판정된 모델이 '미검증' 문구로
       Priority 1위가 되는 모순을 제거.

v2 대비 변경점 (FIXED / CHANGED 마커 참조)
------------------------------------------
[F1] Breakout 방향적중률 버그 수정:
     summarize()가 direction_correct(object: bool/None 혼합)를 잘못 평균내던
     문제를 pd.to_numeric 기반으로 수정.
[F2] Breakout n/Brier/PF/Sharpe 왜곡 수정:
     NO_BREAKOUT(중립, p_up=0.5) 예측은 OOS 원장에 기록하지 않음.
     direction 예측은 actionable 신호만 ledger에 들어감.
[F3] 겹치는 horizon 표본 수정:
     walk-forward 리플레이에서 stride=horizon으로 비중첩 표본만 평가.
     VERIFIED 판정에 Wilson 95% 신뢰구간 하한 > 50% 조건 추가.
[F4] Ledger 고정 기록화:
     - JSONL save/load 지원.
     - evaluate_current()의 현재 예측도 PENDING으로 원장에 기록되어
       실시간에서도 "예측 기록 → 실제값 부착" 순환이 동작함.
[F5] FrictionSensor 연결:
     evaluate_current()가 orderbook을 받으면 Friction 센서가 sensors에 포함되고
     대시보드에도 표시됨. orderbook이 없으면 ORDERBOOK_UNAVAILABLE로 명시.
[F6] 순위 계산식 통일:
     Priority, 터미널 표, 대시보드 표가 모두 동일한 _obs_score()를 사용.
[F7] TIR frozen baseline 보존:
     tir_reflection_backtest_v1 모듈이 있으면 그것을 import해 사용하고,
     없을 때만 내부 폴백 구현을 쓴다(헤더 주석에 분리 명시).
     [F7-3] 원본 실물 확인(2026-09-26) 후 클래스가 아닌 함수 기반
     (run_backtest_v1) import로 수정 — 이제 원본이 있으면 실제로
     frozen baseline이 쓰인다.
     [F7-4] TIR_v2 상태를 원본 classify_v2_states의 4분류
     (TRAPPED/LEAK_WARNING/일반(NORMAL)/BREAKOUT_후보)에 일치시킴.
     BREAKOUT_후보는 'TIR 미충족 + Fast'에서만 등장(원본 정의).
[F8] 타임존 방어:
     normalize_bars()가 tz-aware 타임스탬프를 Asia/Seoul naive로 통일.
     Ledger evaluate가 TypeError로 죽지 않음.
[F9] Regime 임계값의 봉 주기 종속성 완화:
     RegimeEngine(bar_minutes)이 변동성 임계값을 일간 환산으로 정규화.
[F10] ProviderHub 개선:
     폴백 성공 후에도 다음 호출은 항상 primary부터 시도(자동 복귀).
     latency_ms는 측정되어 quality에 기록, stale 플래그 사용.
     대시보드 QUALITY 칸은 상태에 따라 색이 변함.
[F11] REGIME_FIT 가중치는 사람이 정한 heuristic prior임을 UI에 명시.

주의 (v2 원칙 유지)
-------------------
- demo는 synthetic replay이며 실제 KOSPI 성능을 의미하지 않는다.
- 실제 API 키가 없으면 LIVE로 표시하지 않는다.
- 주문을 실행하지 않는다.
- horizon은 '봇 개수' 기준이다. 장 마감/점심/결측 구간을 넘는 예측의
  실제 시간 간격은 달라질 수 있다(세션 경계 보정은 실데이터 연결 시 과제).

실행
----
python kospi_model_arena_observatory_v4.py --demo
python kospi_model_arena_observatory_v4.py --dashboard
python kospi_model_arena_observatory_v4.py --dashboard --port 8765

파일 배치/명명 (명명 규칙 v5 기준)
----------------------------------
- 정식 파일명: kospi_model_arena_observatory_v4.py (스네이크 케이스).
  '수정본', '(2)' 같은 복사 접미사나 하이픈·한글 파일명을 쓰지 않는다.
- 폴더: 02_engine/ (엔진·관측 도구). 리플레이는 내부 검증 수단이므로
  03_backtest 전용으로 두지 않는다.
- 버전: 파일명의 vN은 기능 단위 변경 시 올린다(v3 → v4).

보안 (보안 규칙 v1 기준 조치)
-----------------------------
- SEC-204/205: API 키는 환경변수에서만 읽고, 키/토큰을 출력하지 않는다.
- SEC-001/002: 대시보드 서버는 127.0.0.1에만 바인딩한다.
  Codespaces에서는 해당 포트의 Visibility를 Private로 유지한다.
  포트를 Public으로 바꾸면 SEC-201~203(인증 없는 대시보드) 위반이다.
- SEC-206: LS 실연동 시 예외에 URL·응답 본문이 섞이지 않도록
  _sanitize_error()로 감싼다(아래 LSAdapter 참조).
- SEC-402/403: --ledger로 생성되는 *.jsonl 원장은 Git에 커밋하지 않는다.
  *.jsonl 전체 무시는 프로젝트의 다른 .jsonl까지 치우므로,
  원장을 전용 폴더(예: observatory_ledger/)에만 쓰고 그 폴더만
  .gitignore에 추가한다:

      # prediction ledgers / 수집일지 (SEC-402)
      observatory_ledger/
      ledger*.jsonl
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import threading
import time
import webbrowser
from dataclasses import dataclass, field, asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple
from urllib.parse import urlparse

import numpy as np
import pandas as pd

# [F7-3] TIR v1 frozen baseline: 원본 파일이 있으면 import해서 쓴다.
# 실패 시 조용히 넘어가지 않고 경고를 남긴다(폴백이 쓰이는지 항상 알 수 있게).
# [검증 반영] 원본 tir_reflection_backtest_v1.py에는 TIRReflectionV1 '클래스'가
# 없고 run_backtest_v1/compute_tir_proxies '함수'가 있다(2026-09-26 실물 확인).
# 따라서 클래스 import가 아니라 모듈 import + 함수 인터페이스 검증으로 바꾼다
# (kospi_cockpit_sensor_hub_v1.1.py의 TIRSensor와 동일한 패턴).
TIR_V1_IMPORT_ERROR: Optional[str] = None
try:  # pragma: no cover - 환경 의존
    import tir_reflection_backtest_v1 as _tir_v1_module  # type: ignore
    if not callable(getattr(_tir_v1_module, "run_backtest_v1", None)):
        raise AttributeError("run_backtest_v1 함수 없음")
    TIR_V1_MODULE_AVAILABLE = True
except Exception as _exc:  # noqa: BLE001 - 원본 부재/시그니처 불일치 모두 폴백
    _tir_v1_module = None  # type: ignore
    TIR_V1_MODULE_AVAILABLE = False
    TIR_V1_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"


def tir_v1_baseline_status() -> str:
    if TIR_V1_MODULE_AVAILABLE:
        return "frozen(import tir_reflection_backtest_v1.run_backtest_v1)"
    return f"internal fallback (import failed: {TIR_V1_IMPORT_ERROR})"


# =============================================================================
# 1. COMMON DATA CONTRACT
# =============================================================================

REQUIRED_BAR_COLUMNS = {
    "timestamp", "symbol", "open", "high", "low", "close", "volume", "trade_amount"
}

# [F8] 모든 내부 타임스탬프는 이 타임존의 naive datetime으로 통일한다.
LOCAL_TZ = "Asia/Seoul"


@dataclass
class DataQuality:
    status: str
    source: str
    message: str = ""
    latency_ms: Optional[float] = None
    stale: bool = False
    missing_fields: Tuple[str, ...] = ()


@dataclass
class MarketSnapshot:
    timestamp: pd.Timestamp
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    trade_amount: float
    source: str
    quality: str
    source_timestamp: Optional[pd.Timestamp] = None
    spot_close: Optional[float] = None
    futures_close: Optional[float] = None
    basis: Optional[float] = None
    bid_prices: Tuple[float, ...] = ()
    ask_prices: Tuple[float, ...] = ()
    bid_volumes: Tuple[float, ...] = ()
    ask_volumes: Tuple[float, ...] = ()


def normalize_bars(df: pd.DataFrame, source: str) -> pd.DataFrame:
    x = df.copy()
    rename = {
        "date": "timestamp", "datetime": "timestamp", "time": "timestamp",
        "price": "close", "amount": "trade_amount", "turnover": "trade_amount",
    }
    for a, b in rename.items():
        if a in x.columns and b not in x.columns:
            x = x.rename(columns={a: b})

    missing = REQUIRED_BAR_COLUMNS - set(x.columns)
    if missing:
        raise ValueError(f"{source}: required columns missing: {sorted(missing)}")

    # [F8] tz-aware → LOCAL_TZ naive 로 통일. naive는 그대로 둔다.
    ts = pd.to_datetime(x["timestamp"])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert(LOCAL_TZ).dt.tz_localize(None)
    x["timestamp"] = ts

    x["symbol"] = x["symbol"].astype(str)
    for c in ["open", "high", "low", "close", "volume", "trade_amount"]:
        x[c] = pd.to_numeric(x[c], errors="coerce")

    # [FIX] 컬럼 부재 시 스칼라 fillna로 크래시하던 v2 버그 수정.
    if "source" in x.columns:
        x["source"] = x["source"].fillna(source)
    else:
        x["source"] = source
    if "quality" in x.columns:
        x["quality"] = x["quality"].fillna("GOOD")
    else:
        x["quality"] = "GOOD"
    return x.sort_values("timestamp").reset_index(drop=True)


# =============================================================================
# 2. DATA SOURCE CATALOG
# =============================================================================

@dataclass(frozen=True)
class ProviderSpec:
    key: str
    category: str
    name: str
    realtime: bool
    historical: bool
    orderbook: bool
    role: str = "OPTIONAL"
    note: str = ""


PROVIDER_CATALOG: Tuple[ProviderSpec, ...] = (
    ProviderSpec("krx", "exchange", "KRX", True, True, True,
                 note="공식 거래소 기준 데이터; 실제 수집 방식은 계정/서비스별 Adapter"),
    ProviderSpec("nxt", "exchange", "NXT", True, True, True,
                 note="NXT 데이터 접근 계약은 별도 Adapter"),
    ProviderSpec("ls", "broker", "LS증권", True, True, True,
                 note="REST/OAuth + WebSocket 실시간 구조"),
    ProviderSpec("kiwoom", "broker", "키움증권", True, True, True, note="향후 Adapter"),
    ProviderSpec("kis", "broker", "한국투자증권", True, True, True, note="향후 Adapter"),
    ProviderSpec("kb", "broker", "KB증권", True, True, True, note="향후 Adapter"),
    ProviderSpec("daishin", "broker", "대신증권", True, True, True, note="향후 Adapter"),
    ProviderSpec("mirae", "broker", "미래에셋증권", True, True, True, note="향후 Adapter"),
    ProviderSpec("nh", "broker", "NH투자증권", True, True, True, note="향후 Adapter"),
    ProviderSpec("samsung", "broker", "삼성증권", True, True, True, note="향후 Adapter"),
    ProviderSpec("shinhan", "broker", "신한투자증권", True, True, True, note="향후 Adapter"),
    ProviderSpec("hana", "broker", "하나증권", True, True, True, note="향후 Adapter"),
    ProviderSpec("naver", "public", "Naver Finance", False, True, False,
                 note="보조/개발용. 실시간 체결 원천으로 간주하지 않음"),
    ProviderSpec("yahoo", "public", "Yahoo Finance", False, True, False, note="개발/보조용"),
    ProviderSpec("investing", "public", "Investing.com", False, True, False,
                 note="라이선스/접근정책 확인 후 사용"),
    ProviderSpec("dart", "fundamental", "DART", False, True, False, note="기업 공시/재무"),
    ProviderSpec("ecos", "macro", "한국은행 ECOS", False, True, False, note="거시/금리/경제"),
    ProviderSpec("kosis", "macro", "KOSIS", False, True, False, note="통계/거시"),
    ProviderSpec("file", "storage", "CSV/Parquet", False, True, False, note="재현 가능한 로컬 데이터"),
    ProviderSpec("database", "storage", "SQL/Time-series DB", True, True, True, note="저장/재생 계층"),
)


class ProviderAdapter(Protocol):
    name: str

    def health(self) -> DataQuality: ...
    def fetch_bars(self, symbol: str, start: Any = None, end: Any = None) -> pd.DataFrame: ...
    def fetch_orderbook(self, symbol: str) -> Mapping[str, Any]: ...


class BaseAdapter:
    name = "base"

    def health(self) -> DataQuality:
        return DataQuality("UNIMPLEMENTED", self.name, "adapter slot exists")

    def fetch_bars(self, symbol: str, start: Any = None, end: Any = None) -> pd.DataFrame:
        raise NotImplementedError

    def fetch_orderbook(self, symbol: str) -> Mapping[str, Any]:
        raise NotImplementedError


class ReplayAdapter(BaseAdapter):
    def __init__(self, data: pd.DataFrame, name: str = "demo_replay"):
        self.name = name
        self.data = normalize_bars(data, name)

    def health(self) -> DataQuality:
        return DataQuality("GOOD", self.name, "synthetic/local replay")

    def fetch_bars(self, symbol: str, start: Any = None, end: Any = None) -> pd.DataFrame:
        x = self.data[self.data["symbol"].astype(str) == str(symbol)].copy()
        if start is not None:
            x = x[x["timestamp"] >= pd.Timestamp(start)]
        if end is not None:
            x = x[x["timestamp"] <= pd.Timestamp(end)]
        return x.reset_index(drop=True)

    def fetch_orderbook(self, symbol: str) -> Mapping[str, Any]:
        return {}


class CSVParquetAdapter(BaseAdapter):
    def __init__(self, path: str):
        self.path = Path(path)
        self.name = "file"

    def health(self) -> DataQuality:
        if not self.path.exists():
            return DataQuality("MISSING", self.name, str(self.path))
        return DataQuality("READY", self.name, str(self.path))

    def fetch_bars(self, symbol: str, start: Any = None, end: Any = None) -> pd.DataFrame:
        if self.path.suffix.lower() == ".csv":
            x = pd.read_csv(self.path)
        elif self.path.suffix.lower() in {".parquet", ".pq"}:
            x = pd.read_parquet(self.path)
        else:
            raise ValueError("file adapter supports CSV/Parquet")
        x = normalize_bars(x, self.name)
        x = x[x["symbol"].astype(str) == str(symbol)]
        if start is not None:
            x = x[x["timestamp"] >= pd.Timestamp(start)]
        if end is not None:
            x = x[x["timestamp"] <= pd.Timestamp(end)]
        return x.reset_index(drop=True)

    def fetch_orderbook(self, symbol: str) -> Mapping[str, Any]:
        return {}


def _sanitize_error(exc: Exception, context: str) -> str:
    """
    [SEC-206] 내부 오류 세부(URL, 응답 본문, 인증 헤더)를 로그/메시지에
    노출하지 않고 유형+컨텍스트만 남긴다. 실연동 시 LSAdapter가 이
    함수로 예외를 감싼다.
    """
    return f"{context} 실패 ({type(exc).__name__})"


class LSAdapter(BaseAdapter):
    """
    LS증권 공식 OPEN API의 인증/연결 지점.

    실제 TR 필드 매핑은 계정에서 사용 가능한 API 명세에 맞춰 구현한다.
    이 클래스는 인증키를 코드에 저장하지 않는다.

    현재 공식 문서 기준:
    - OAuth token endpoint: https://openapi.ls-sec.co.kr:8080/oauth2/token
    - WebSocket: wss://openapi.ls-sec.co.kr:9443/websocket
    - 모의: wss://openapi.ls-sec.co.kr:29443
    """

    name = "ls"

    def __init__(self):
        self.app_key = os.getenv("LS_APP_KEY")
        self.app_secret = os.getenv("LS_APP_SECRET")
        self.base_url = os.getenv("LS_BASE_URL", "https://openapi.ls-sec.co.kr:8080")
        self.token = None
        self.token_expiry = 0.0
        self._last_latency_ms: Optional[float] = None

    def health(self) -> DataQuality:
        if not self.app_key or not self.app_secret:
            return DataQuality("SLOT_READY", self.name,
                               "LS_APP_KEY / LS_APP_SECRET 미설정; LIVE 아님")
        return DataQuality("AUTH_CONFIGURED", self.name,
                           "환경변수 기반 인증정보 준비됨; 실제 TR/WebSocket 연결 전",
                           latency_ms=self._last_latency_ms)

    def fetch_token(self) -> str:
        if not self.app_key or not self.app_secret:
            raise RuntimeError("LS_APP_KEY / LS_APP_SECRET are required")
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError("LS live adapter requires requests") from exc

        url = self.base_url.rstrip("/") + "/oauth2/token"
        t0 = time.perf_counter()
        try:
            response = requests.post(
                url,
                headers={"content-type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "client_credentials",
                    "appkey": self.app_key,
                    "appsecretkey": self.app_secret,
                    "scope": "oob",
                },
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            # [SEC-206] URL/응답 본문/인증 정보가 메시지에 섞이지 않게 유형만 전파
            self._last_latency_ms = (time.perf_counter() - t0) * 1000
            raise RuntimeError(_sanitize_error(exc, "LS OAuth token 발급")) from None
        self._last_latency_ms = (time.perf_counter() - t0) * 1000
        self.token = payload["access_token"]
        self.token_expiry = time.time() + float(payload.get("expires_in", 86400)) - 60
        return self.token

    def get_token(self) -> str:
        if self.token and time.time() < self.token_expiry:
            return self.token
        return self.fetch_token()

    def fetch_bars(self, symbol: str, start: Any = None, end: Any = None) -> pd.DataFrame:
        raise NotImplementedError(
            "LS REST TR별 요청/응답 필드는 계정 API 명세에 맞춰 연결해야 합니다. "
            "인증은 fetch_token()/get_token()으로 준비되어 있습니다."
        )

    def fetch_orderbook(self, symbol: str) -> Mapping[str, Any]:
        raise NotImplementedError(
            "LS WebSocket 실시간 호가 TR을 연결하는 자리입니다. "
            "가짜 orderbook을 생성하지 않습니다."
        )


class SlotAdapter(BaseAdapter):
    def __init__(self, key: str):
        self.name = key

    def health(self) -> DataQuality:
        spec = next((x for x in PROVIDER_CATALOG if x.key == self.name), None)
        label = spec.name if spec else self.name
        return DataQuality("SLOT_READY", self.name, f"{label} Adapter slot ready")

    def fetch_bars(self, symbol: str, start: Any = None, end: Any = None) -> pd.DataFrame:
        raise NotImplementedError(f"{self.name} adapter slot is not connected")

    def fetch_orderbook(self, symbol: str) -> Mapping[str, Any]:
        raise NotImplementedError(f"{self.name} orderbook slot is not connected")


class ProviderHub:
    """
    [F10] 폴백 정책 변경:
    항상 primary를 먼저 시도하고, 실패 시에만 백업을 쓴다.
    백업 성공 후에도 다음 호출은 다시 primary부터 시도한다(자동 복귀).
    """

    def __init__(self, adapters: Sequence[BaseAdapter], primary: Optional[str] = None):
        self.adapters = {x.name: x for x in adapters}
        if not self.adapters:
            raise ValueError("ProviderHub needs at least one adapter")
        self.primary = primary or next(iter(self.adapters))
        if self.primary not in self.adapters:
            raise ValueError(f"Unknown primary provider: {self.primary}")

    @property
    def active(self) -> str:
        return self.primary

    def health_table(self) -> pd.DataFrame:
        rows = []
        for key, adapter in self.adapters.items():
            q = adapter.health()
            rows.append({
                "provider": key,
                "role": "PRIMARY" if key == self.primary else "BACKUP",
                "status": q.status,
                "message": q.message,
                "latency_ms": q.latency_ms,
            })
        return pd.DataFrame(rows)

    def _order(self) -> List[str]:
        return [self.primary] + [x for x in self.adapters if x != self.primary]

    def fetch_bars(self, symbol: str, **kwargs: Any) -> Tuple[pd.DataFrame, DataQuality]:
        errors = []
        for key in self._order():
            adapter = self.adapters[key]
            try:
                t0 = time.perf_counter()
                df = adapter.fetch_bars(symbol, **kwargs)
                if df is not None and not df.empty:
                    latency = (time.perf_counter() - t0) * 1000
                    q = adapter.health()
                    q.latency_ms = latency
                    # [F10] primary가 아니면 백업 사용임을 명시
                    if key != self.primary:
                        q.message = f"[BACKUP of {self.primary}] " + q.message
                    return normalize_bars(df, key), q
            except Exception as exc:
                errors.append(f"{key}: {exc}")
        raise RuntimeError("No usable market-data provider. " + " | ".join(errors))

    def fetch_orderbook(self, symbol: str) -> Tuple[Mapping[str, Any], DataQuality]:
        errors = []
        for key in self._order():
            adapter = self.adapters[key]
            try:
                book = adapter.fetch_orderbook(symbol)
                if book:
                    return book, adapter.health()
            except Exception as exc:
                errors.append(f"{key}: {exc}")
        return {}, DataQuality("ORDERBOOK_UNAVAILABLE", self.primary, " | ".join(errors))


# =============================================================================
# 3. MODELS / SENSORS
# =============================================================================

def sigmoid(x: float) -> float:
    x = float(np.clip(x, -30, 30))
    return 1.0 / (1.0 + math.exp(-x))


def wilson_lower_bound(k: int, n: int, z: float = 1.96) -> Optional[float]:
    """[F3] 방향적중률의 Wilson 95% 신뢰구간 하한."""
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / denom


def _json_default(obj: Any) -> Any:
    """[F4-1] numpy bool_/int64/float64 등을 JSON 직렬화 가능 값으로 변환."""
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (pd.Timestamp,)):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class BaseModel:
    name = "Base"
    task = "direction"

    def predict(self, df: pd.DataFrame) -> Dict[str, Any]:
        raise NotImplementedError


class MomentumModel(BaseModel):
    name, task = "Momentum", "direction"

    def predict(self, df):
        r = float(df["close"].pct_change(5).iloc[-1])
        p = sigmoid(r * 120) if np.isfinite(r) else 0.5
        return {"model": self.name, "task": self.task, "direction": "UP" if p >= .5 else "DOWN",
                "p_up": p, "predicted_return": r, "strength": abs(p-.5)*2, "actionable": True}


class MeanReversionModel(BaseModel):
    name, task = "Hook_OU", "direction"

    def predict(self, df):
        ma = float(df["close"].rolling(20).mean().iloc[-1])
        px = float(df["close"].iloc[-1])
        z = (px/ma - 1) if ma else 0
        p = sigmoid(-z * 80)
        return {"model": self.name, "task": self.task, "direction": "UP" if p >= .5 else "DOWN",
                "p_up": p, "predicted_return": -z, "strength": abs(p-.5)*2, "actionable": True}


class ThresholdModel(BaseModel):
    name, task = "Threshold", "direction"

    def predict(self, df):
        r = df["close"].pct_change().rolling(10).mean().iloc[-1]
        v = df["close"].pct_change().rolling(20).std().iloc[-1]
        score = float(r/v) if pd.notna(r) and pd.notna(v) and v > 0 else 0
        p = sigmoid(score)
        return {"model": self.name, "task": self.task, "direction": "UP" if p >= .5 else "DOWN",
                "p_up": p, "predicted_return": float(r) if pd.notna(r) else 0,
                "strength": min(1, abs(score)/3), "actionable": True}


class BreakoutModel(BaseModel):
    name, task = "Breakout", "breakout"

    def predict(self, df):
        hh = df["high"].rolling(20).max().iloc[-2]
        ll = df["low"].rolling(20).min().iloc[-2]
        px = df["close"].iloc[-1]
        if pd.isna(hh) or pd.isna(ll):
            return {"model": self.name, "task": self.task, "signal": "UNKNOWN",
                    "predicted_return": 0, "strength": 0, "actionable": False}
        if px > hh:
            ret = float(px/hh - 1)
            return {"model": self.name, "task": self.task, "signal": "UP_BREAKOUT",
                    "direction": "UP", "p_up": .5 + min(.49, ret*100),
                    "predicted_return": ret, "strength": min(1, ret*100),
                    "actionable": True}
        if px < ll:
            ret = float(ll/px - 1)
            return {"model": self.name, "task": self.task, "signal": "DOWN_BREAKOUT",
                    "direction": "DOWN", "p_up": .5 - min(.49, ret*100),
                    "predicted_return": -ret, "strength": min(1, ret*100),
                    "actionable": True}
        # [F2] NO_BREAKOUT은 중립 신호: 원장에서 제외(actionable=False).
        return {"model": self.name, "task": self.task, "signal": "NO_BREAKOUT",
                "direction": "UP" if px >= df["close"].rolling(20).mean().iloc[-1] else "DOWN",
                "p_up": .5, "predicted_return": 0, "strength": 0, "actionable": False}


class TIRV1External:
    """
    [F7-3] 원본 tir_reflection_backtest_v1.py의 함수 기반 frozen baseline 래퍼.

    원본 run_backtest_v1(df)는 다음 컬럼을 요구한다:
      spot_close, futures_close, high, low, close, trade_amount
    없으면 close로 보조한다(futures_close가 없으면 basis=0, theta_proxy=0).
    반환 df에 tir_score/tir_signal/kappa_proxy/theta_proxy가 생기며,
    이 래퍼는 그 '마지막 행'을 센서 신호로 변환한다.

    주의: 원본은 일봉(rolling 60일) 기준이다. 분봉에 적용하면 창의 의미가
    달라진다(60봉). bar 단위는 호출자가 문서화한다.
    """

    name, task = "TIR_v1", "sensor"
    frozen = True  # 원본 import 시

    def compute(self, df):
        x = df.copy()
        if "spot_close" not in x.columns:
            x["spot_close"] = x["close"]
        if "futures_close" not in x.columns:
            x["futures_close"] = x["close"]
        # 원본은 내부에서 print(시그널 통계)를 출력한다 - 그대로 둔다.
        return _tir_v1_module.run_backtest_v1(x)

    def predict(self, df):
        x = self.compute(df)
        s = x["tir_score"].iloc[-1]
        active = bool(x["tir_signal"].iloc[-1]) if pd.notna(x["tir_signal"].iloc[-1]) else False
        return {"model": self.name, "task": self.task,
                "signal": "TIR_ACTIVE" if active else "NORMAL",
                "strength": float(s/4) if pd.notna(s) else 0,
                "frozen_baseline": self.frozen}


class TIRV1Fallback:
    """
    [F7] TIR v1 폴백 구현.

    주의: 이 클래스는 frozen baseline의 '복제'이다. 원본
    tir_reflection_backtest_v1.py가 import 가능하면 그것이 우선한다.
    또한 원본이 일봉(rolling 60일) 기준이라면, 분봉에 적용하면
    창의 의미가 달라진다(60분). bar_minutes로 의미를 문서화한다.
    """

    name, task = "TIR_v1", "sensor"
    frozen = False  # 폴백이면 False, 원본 import면 True

    def compute(self, df):
        x = df.copy()
        spot = x.get("spot_close", x["close"])
        if "spot_close" not in x.columns:
            x["spot_close"] = spot
        fut = x.get("futures_close", x["close"])
        if "futures_close" not in x.columns:
            x["futures_close"] = fut
        x["basis"] = x["futures_close"] - x["spot_close"]
        x["theta_proxy"] = x["basis"].diff()
        range_pct = (x["high"] - x["low"]) / x["close"]
        m = x["trade_amount"].rolling(20).mean()
        s = x["trade_amount"].rolling(20).std()
        z = np.clip((x["trade_amount"]-m)/(s+1e-9), 0, None)
        x["kappa_proxy"] = z/(range_pct+1e-3)
        high60 = x["close"].rolling(60).max()
        box = (x["close"] >= high60*.95).astype(int)*2
        kt = x["kappa_proxy"].expanding(60).quantile(.65).shift(1)
        tt = x["theta_proxy"].expanding(60).quantile(.35).shift(1)
        # [F7-3] 원본 run_backtest_v1과 동일한 컬럼명(tir_score/tir_signal) 사용
        x["tir_score"] = box + (x["kappa_proxy"] >= kt).astype(int) + (x["theta_proxy"] <= tt).astype(int)
        x["tir_signal"] = x["tir_score"] >= 3
        return x

    def predict(self, df):
        x = self.compute(df)
        s = x["tir_score"].iloc[-1]
        active = bool(s >= 3) if pd.notna(s) else False
        return {"model": self.name, "task": self.task,
                "signal": "TIR_ACTIVE" if active else "NORMAL",
                "strength": float(s/4) if pd.notna(s) else 0,
                "frozen_baseline": self.frozen}


def get_tir_v1():
    """[F7-3] 원본 frozen baseline 우선, 없으면 폴백."""
    if TIR_V1_MODULE_AVAILABLE and _tir_v1_module is not None:
        return TIRV1External()
    return TIRV1Fallback()


class TIRV2:
    """
    [F7-4] 원본 4분류 정의에 일치시킴 (2026-09-26 원본 실물 확보 후 검증).

    원본 tir_reflection_backtest_v1.py의 classify_v2_states 규칙:
      - v_proxy = EMA(ROC_5), v_thresh = |v_proxy|의 expanding
        quantile(0.70) + shift(1) → look-ahead 없음
      - is_fast = |v_proxy| >= v_thresh
      - TIR 충족 + Slow   → TRAPPED
      - TIR 충족 + Fast   → LEAK_WARNING
      - TIR 미충족 + Slow → 일반(이 파일 표기: NORMAL)
      - TIR 미충족 + Fast → BREAKOUT_후보(확정 아님, 후보)
    즉 BREAKOUT_후보는 'TIR 미충족' 상태에서만 등장한다
    (이전 구현인 'TIR 활성 + 빠름 = BREAKOUT_CANDIDATE'와는 다른, 원본 정의).
    """

    name, task = "TIR_v2", "sensor"

    def predict(self, df):
        tir1 = get_tir_v1()
        x = tir1.compute(df)
        roc = x["close"].pct_change(5)
        v = roc.ewm(alpha=.2, adjust=False).mean()
        # 원본과 동일: |v_proxy| 기준 expanding quantile + shift(1)
        th = v.abs().expanding(60).quantile(.70).shift(1)
        active = bool(x["tir_score"].iloc[-1] >= 3) if pd.notna(x["tir_score"].iloc[-1]) else False
        vv = v.iloc[-1]
        tt = th.iloc[-1]
        if pd.isna(tt) or pd.isna(vv):
            state = "TIR_ACTIVE" if active else "NORMAL"
            strength = .5
        else:
            is_fast = bool(abs(vv) >= tt)
            if active and not is_fast:
                state = "TRAPPED"
            elif active and is_fast:
                state = "LEAK_WARNING"
            elif not active and not is_fast:
                state = "NORMAL"  # 원본 표기 '일반'
            else:
                state = "BREAKOUT_후보"  # 원본 표기 그대로 사용
            strength = float(min(1, abs(vv)/(tt+1e-9)))
        return {"model": self.name, "task": self.task, "signal": state,
                "strength": strength,
                "tir_v1_frozen_baseline": getattr(tir1, "frozen", False)}


class StateSpaceSensor:
    name, task = "StateSpace", "sensor"

    def predict(self, df):
        ma = df["close"].rolling(20).mean()
        atr = (df["high"]-df["low"]).rolling(14).mean().replace(0, np.nan)
        pos = (df["close"]-ma)/atr
        vel = pos.diff()
        acc = vel.diff()
        x = float(pos.iloc[-1]) if pd.notna(pos.iloc[-1]) else 0
        v = float(vel.iloc[-1]) if pd.notna(vel.iloc[-1]) else 0
        a = float(acc.iloc[-1]) if pd.notna(acc.iloc[-1]) else 0
        if x > 1 and v > 0: state = "UP_ACCELERATION"
        elif x < -1 and v < 0: state = "DOWN_ACCELERATION"
        elif abs(x) < .5: state = "CENTERED"
        else: state = "TRANSITION"
        return {"model": self.name, "task": self.task, "signal": state,
                "strength": min(1, abs(x)/3), "x": x, "v": v, "a": a}


class FrictionSensor:
    name, task = "Friction", "sensor"

    def predict(self, orderbook: Mapping[str, Any]):
        if not orderbook:
            return {"model": self.name, "task": self.task, "signal": "ORDERBOOK_UNAVAILABLE",
                    "strength": 0, "status": "DEGRADED"}
        try:
            bid = np.array(orderbook["bid_volumes"], dtype=float)
            ask = np.array(orderbook["ask_volumes"], dtype=float)
            spread = float(orderbook["spread"])
            depth = float(bid.sum()+ask.sum())
            oib = float((bid.sum()-ask.sum())/(bid.sum()+ask.sum()+1e-9))
            ratio = spread * (1 + .4*abs(oib)) / max(depth, 1e-9)
            return {"model": self.name, "task": self.task,
                    "signal": "STRESS" if ratio > .001 else "NORMAL",
                    "strength": min(1, ratio*1000), "status": "GOOD",
                    "friction_ratio": ratio, "oib": oib}
        except Exception as exc:
            return {"model": self.name, "task": self.task, "signal": "DEGRADED",
                    "strength": 0, "status": "ERROR", "error": str(exc)}


# =============================================================================
# 4. REGIME
# =============================================================================

class RegimeEngine:
    """
    [F9 v2] 변동성 척도 변경: 절대 clip 대신 자기 이력 분위수.

    v1의 clip(0, .01)은 demo와 실제 일봉 KOSPI 모두에서 포화되어
    BREAKOUT_TRANSITION 판정이 사실상 trend 하나로 결정되는 문제가 있었다.
    이제 일간 환산 변동성을 '과거 자기 이력 대비 상위 분위수'로 바꿔서
    봉 주기와 변동성 수준 모두에 robust하게 만든다.
    - volatility = 최근 일간환산 변동성이 자기 이력에서 차지하는 분위수(0~1).
      최소 120봉 이력이 쌓이기 전에는 확정 판정을 하지 않는다(TRANSITION).

    bar_minutes: 한 봉의 길이(분). 일봉이면 390.
    """

    MIN_HISTORY = 120

    def __init__(self, bar_minutes: float = 1.0):
        self.bar_minutes = float(bar_minutes)

    def infer(self, df: pd.DataFrame) -> Tuple[str, Dict[str, float]]:
        ret = df["close"].pct_change()
        mom = ret.rolling(10).mean().iloc[-1]
        vol = ret.rolling(20).std().iloc[-1]
        ma = df["close"].rolling(20).mean().iloc[-1]
        px = df["close"].iloc[-1]
        dist = (px/ma-1) if pd.notna(ma) and ma else 0
        trend = float(np.clip(abs(dist)*40, 0, 1))
        momentum = float(np.clip(abs(float(mom) if pd.notna(mom) else 0)*200, 0, 1))

        # 봉당 변동성 → 일간 환산 (sqrt of bars per day)
        bars_per_day = max(1.0, 390.0 / max(self.bar_minutes, 1e-9))
        vol_series = (ret.rolling(20).std() * math.sqrt(bars_per_day)).dropna()
        vol_daily = float(vol_series.iloc[-1]) if len(vol_series) else 0.0
        if len(vol_series) >= self.MIN_HISTORY:
            hist = vol_series.iloc[:-1]
            # 자기 이력 대비 현재 변동성의 분위수(0~1)
            volatility = float(np.mean(hist.values <= vol_daily)) if len(hist) else 0.5
        else:
            # 이력 부족: 이력이 쌓일 때까지 이력 기반 판정 불가 → 중립치 사용
            volatility = 0.5

        if trend > .75 and momentum > .6:
            regime = "TREND"
        elif volatility > .75 and trend > .5:
            regime = "BREAKOUT_TRANSITION"
        elif trend < .25 and momentum < .35:
            regime = "MEAN_REVERSION"
        else:
            regime = "TRANSITION"
        return regime, {"trend": trend, "momentum": momentum, "volatility": volatility,
                        "distance_ma": float(dist), "bar_minutes": self.bar_minutes}


# =============================================================================
# 5. PREDICTION LEDGER / OOS EVALUATOR
# =============================================================================

@dataclass
class PredictionRecord:
    timestamp: str
    model: str
    task: str
    horizon: int
    regime: str
    prediction: str
    p_up: Optional[float]
    predicted_return: Optional[float]
    price_at_prediction: float
    target_timestamp: Optional[str] = None
    actual_return: Optional[float] = None
    actual_direction: Optional[str] = None
    direction_correct: Optional[bool] = None
    absolute_error: Optional[float] = None
    status: str = "PENDING"
    source: str = "UNKNOWN"
    # [F4-4] 중복 키에 symbol 포함(지수/선물 등 종목 병행 대비).
    # 기존 원장 파일(필드 없음)도 기본값으로 무리 없이 적재된다.
    symbol: str = "UNKNOWN"


class PredictionLedger:
    """
    [F4] 예측 고정 기록(append-only ledger).

    - [F4-4] (timestamp, model, horizon, symbol, source) 키로 중복 기록을
      차단한다. 같은 시각에 다른 종목/공급원의 예측은 별도 레코드로
      공존한다(예: KOSPI 지수와 KOSPI200 선물).
    - [F4-2] 재적재 후 리플레이를 다시 돌려도 같은 예측이 두 배로
      쌓이지 않고, 실시간에서 evaluate_current()를 반복 호출해도
      한 시점·모델·종목당 1건만 남는다.
    - [F4-6] 구형 원장(symbol 필드 없음 → UNKNOWN) 호환: load()에
      legacy_symbol을 지정하면 UNKNOWN 심볼을 해당 심볼로 승격해서
      새 리플레이(symbol="KOSPI")와 키가 달라 중복 방지가 작동하지
      않는 일을 막는다. [F4-8] 승격을 빠뜨려도 통계는 지켜진다:
      OOSAnalyzer가 symbol/source와 무관한 내용 지문(timestamp,
      model, horizon, price_at_prediction, p_up)으로 중복을 검사하고
      UNKNOWN은 wildcard 취급한다. 중복이 있으면 VERIFIED 대신
      DUPLICATED_SAMPLE — 원장 형식과 무관한 통계 방어선.
    - [F4-5] save()는 신규 예측 레코드와 '평가 갱신 이벤트'(_t=update)
      줄을 append한다. PENDING으로 저장된 예측이 나중에 EVALUATED로
      바뀌면 갱신 줄이 추가되고, load()는 같은 키의 마지막 상태를
      우선 적용한다 — append-only와 양립하면서 실시간
      "기록 → 실제값 부착" 순환이 재적재 후에도 유지된다.
      [F4-7] 신규 레코드를 쓸 때 현재 상태를 _saved_status에 함께
      기록해, 이미 EVALUATED인 레코드에 불필요한 갱신 줄이 붙지 않는다.
    - evaluate()는 PENDING 레코드에만 실제값을 부착한다(재평가 안 함).
    """

    def __init__(self):
        self.records: List[PredictionRecord] = []
        self._seen: Dict[Tuple[str, str, int, str, str], PredictionRecord] = {}
        self._saved_count = 0  # 이미 디스크에 append된 신규 레코드 수
        self._saved_status: Dict[Tuple[str, str, int, str, str], str] = {}

    def _key(self, rec: PredictionRecord) -> Tuple[str, str, int, str, str]:
        # [F4-4] symbol과 source를 포함한 복합 키
        return (rec.timestamp, rec.model, int(rec.horizon),
                str(rec.symbol), str(rec.source))

    def add(self, rec: PredictionRecord) -> bool:
        """중복이면 기록하지 않고 False를 반환한다."""
        k = self._key(rec)
        if k in self._seen:
            return False
        self._seen[k] = rec
        self.records.append(rec)
        return True

    def save(self, path: str):
        """
        [F4-3] 전체 덮어쓰기가 아니라 append.
        [F4-5] 신규 레코드 줄(_t=record) 다음에, 마지막 저장 이후
        상태가 변한 레코드의 평가 갱신 줄(_t=update)을 추가한다.
        [F4-7] 신규 레코드를 쓸 때 _saved_status를 함께 기록해서,
        이미 EVALUATED로 저장된 레코드에 불필요한 갱신 줄이
        하나씩 더 붙지 않는다(리플레이에서 2배 파일 방지).
        """
        p = Path(path)
        with p.open("a", encoding="utf-8") as f:
            for rec in self.records[self._saved_count:]:
                row = asdict(rec)
                row["_t"] = "record"
                f.write(json.dumps(row, ensure_ascii=False,
                                   default=_json_default) + "\n")
                # [F4-7] 저장 시점의 상태를 기록
                self._saved_status[self._key(rec)] = rec.status
            self._saved_count = len(self.records)
            for rec in self.records:
                k = self._key(rec)
                last = self._saved_status.get(k, "PENDING")
                if rec.status != last:
                    f.write(json.dumps({
                        "_t": "update",
                        "key": list(k),
                        "status": rec.status,
                        "target_timestamp": rec.target_timestamp,
                        "actual_return": rec.actual_return,
                        "actual_direction": rec.actual_direction,
                        "direction_correct": rec.direction_correct,
                        "absolute_error": rec.absolute_error,
                    }, ensure_ascii=False, default=_json_default) + "\n")
                    self._saved_status[k] = rec.status

    def load(self, path: str, legacy_symbol: Optional[str] = None):
        """
        [F4-6] legacy_symbol: 구형 원장(symbol 필드 없음 → "UNKNOWN")의
        심볼을 이 값으로 승격한다(예: --legacy-symbol KOSPI).
        승격하지 않으면 새 리플레이(symbol="KOSPI")와 키가 달라
        중복 방지가 작동하지 않아 표본이 두 배가 될 수 있다.
        """
        p = Path(path)
        if not p.exists():
            return
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                kind = d.get("_t", "record")  # 구형 파일(필드 없음)은 레코드 줄
                if kind == "update":
                    # [F4-5] 같은 키의 마지막 상태를 적용(파일 순서대로 처리)
                    k = tuple(d["key"])
                    rec = self._seen.get(k)  # type: ignore[arg-type]
                    if rec is None:
                        continue
                    rec.status = d.get("status", rec.status)
                    rec.target_timestamp = d.get("target_timestamp")
                    rec.actual_return = d.get("actual_return")
                    rec.actual_direction = d.get("actual_direction")
                    rec.direction_correct = d.get("direction_correct")
                    rec.absolute_error = d.get("absolute_error")
                else:
                    d.pop("_t", None)
                    rec = PredictionRecord(**d)
                    # [F4-6] 구형 UNKNOWN 심볼 승격(중복 방지 키 통일)
                    if legacy_symbol and rec.symbol == "UNKNOWN":
                        rec.symbol = legacy_symbol
                    self.add(rec)
        self._saved_count = len(self.records)
        self._saved_status = {self._key(r): r.status for r in self.records}

    def evaluate(self, bars: pd.DataFrame):
        x = normalize_bars(bars, "ledger")
        ts = x["timestamp"].to_numpy()
        px = x["close"].to_numpy()

        for rec in self.records:
            if rec.status != "PENDING":
                continue
            t0 = pd.Timestamp(rec.timestamp)  # [F8] naive로 통일된 입력 전제
            future = np.where(ts > np.datetime64(t0))[0]
            if len(future) < rec.horizon:
                continue
            idx = future[rec.horizon-1]
            actual = float(px[idx]/rec.price_at_prediction - 1)
            rec.target_timestamp = str(pd.Timestamp(ts[idx]))
            rec.actual_return = actual
            rec.actual_direction = "UP" if actual > 0 else "DOWN" if actual < 0 else "FLAT"
            if rec.task == "direction" and rec.p_up is not None:
                pred_dir = "UP" if rec.p_up >= .5 else "DOWN"
                # [F4-1] numpy.bool_ 대신 순수 bool로 저장(JSON 직렬화 가능)
                rec.direction_correct = bool(pred_dir == rec.actual_direction)
            elif rec.predicted_return is not None:
                if actual != 0 and rec.predicted_return != 0:
                    # [F4-1] numpy.bool_ 대신 순수 bool로 저장(JSON 직렬화 가능)
                    rec.direction_correct = bool(np.sign(rec.predicted_return) == np.sign(actual))
                else:
                    rec.direction_correct = None
            if rec.predicted_return is not None:
                rec.absolute_error = abs(actual-rec.predicted_return)
            rec.status = "EVALUATED"

    def dataframe(self) -> pd.DataFrame:
        if not self.records:
            return pd.DataFrame()
        return pd.DataFrame([asdict(x) for x in self.records])


@dataclass
class Performance:
    model: str
    task: str
    n: int
    directional_accuracy: Optional[float]
    da_ci_low: Optional[float] = None
    brier: Optional[float] = None
    mae: Optional[float] = None
    profit_factor: Optional[float] = None
    sharpe: Optional[float] = None
    mdd: Optional[float] = None
    status: str = "UNVERIFIED"


class OOSAnalyzer:
    """
    [F1][F3] 수정된 스코어카드.

    - direction_correct는 bool/None이 섞인 object 열이므로
      pd.to_numeric(errors='coerce') 후 dropna().mean() 한다.
    - VERIFIED 조건: n >= 30 (비중첩) AND Wilson 95% CI 하한 > 50%.
      CI 하한이 50% 이하면 DA가 우연일 가능성을 배제하지 못하므로
      'NO_EDGE'로 표기한다.
    """

    MIN_VERIFIED_N = 30

    @staticmethod
    def _has_duplicate_samples(g: pd.DataFrame) -> bool:
        """
        [F4-8] 중복 표본 방어선 — 심볼·소스와 무관한 '내용 지문' 기반.

        원장 키(timestamp, model, horizon, symbol, source)와 달리,
        통계 검사는 symbol/source를 신뢰하지 않는다:
        - 구형 원장의 symbol="UNKNOWN"은 어떤 심볼과도 같은 것으로
          취급한다(wildcard). --legacy-symbol 승격을 빠뜨려도
          UNKNOWN+KOSPI 중복이 VERIFIED로 통과하지 않는다.
        - 검사 키: (timestamp, model, horizon, price_at_prediction, p_up).
          이 값들이 같으면 같은 시장 시점에 대한 같은 예측으로 본다.
        - source가 달라도(예: demo_replay vs live) 같은 시각·모델·가격의
          예측은 같은 시장 시점을 두 번 세는 것이므로 중복이다.

        정책 요약(두 계층의 역할 분담):
        - 원장(add/load)은 source까지 포함해 기록 보존을 위해 중복을
          허용하지 않는다(기록 계층).
        - OOS 통계(summarize)는 시장 시점 기준으로 유일성을 강제하고,
          위반이 있으면 VERIFIED를 주지 않는다(통계 계층).

        [F4-11] 성능: 지문 키로 그룹화한 뒤 그룹 안에서만 심볼을
        비교한다(O(n) 근사). 전체 이중 루프는 피한다.
        """
        key_cols = ["timestamp", "model", "horizon",
                    "price_at_prediction", "p_up"]
        for c in key_cols:
            if c not in g.columns:
                return False
        gg = g.dropna(subset=["timestamp"])
        if gg.empty:
            return False

        # [F4-11] (timestamp, model, horizon, price, p_up) 그룹화 → O(n).
        # 가격·확률이 다르면(KOSPI 지수 vs K200 선물 등) 다른 그룹이
        # 되므로 오탐하지 않는다. 같은 지문이 2건 이상인 그룹만 중복.
        grouped = gg.groupby(
            ["timestamp", "model", "horizon", "price_at_prediction", "p_up"],
            dropna=False)
        for _, grp in grouped:
            if len(grp) < 2:
                continue
            symbols = {str(r.get("symbol", "UNKNOWN"))
                       for r in grp.to_dict("records")}
            if "UNKNOWN" in symbols or len(symbols) == 1:
                # UNKNOWN wildcard 포함, 또는 심볼까지 같음 → 같은 시장
                # 시점을 두 번 센 것(source만 다른 경우 포함)
                return True
            # 심볼이 서로 다르면 다른 종목의 우연한 동일 지문(가격·p_up까지
            # 같음)이다. 희박한 경우로, 중복이 아니므로 통과시킨다.
        return False

    def summarize(self, ledger: PredictionLedger) -> pd.DataFrame:
        df = ledger.dataframe()
        if df.empty:
            return pd.DataFrame()
        out = []
        for (model, task), g in df.groupby(["model", "task"]):
            g = g[g["status"] == "EVALUATED"].copy()
            n = len(g)
            if n == 0:
                out.append(asdict(Performance(model, task, 0, None, status="UNVERIFIED")))
                continue

            # [F1] bool/None 혼합 object 열의 안전한 수치화
            dc = pd.to_numeric(g["direction_correct"], errors="coerce")
            acc = None
            ci_low = None
            if dc.notna().any():
                k = int(dc.dropna().sum())
                n_eff = int(dc.notna().sum())
                acc = float(k / n_eff)
                ci_low = wilson_lower_bound(k, n_eff)

            brier = None
            if "p_up" in g.columns and g["p_up"].notna().any() and g["actual_direction"].notna().any():
                gg = g[g["p_up"].notna() & g["actual_direction"].notna()].copy()
                y = (gg["actual_direction"] == "UP").astype(float)
                brier = float(np.mean((gg["p_up"].astype(float)-y)**2))

            mae = float(g["absolute_error"].dropna().mean()) if g["absolute_error"].notna().any() else None

            pnl = []
            for _, r in g.iterrows():
                if r["predicted_return"] is None or pd.isna(r["predicted_return"]):
                    continue
                pnl.append(float(np.sign(r["predicted_return"]) * r["actual_return"]))
            pf = None
            sharpe = None
            mdd = None
            if pnl:
                arr = np.asarray(pnl, dtype=float)
                gains = arr[arr > 0].sum()
                losses = -arr[arr < 0].sum()
                pf = float(gains/losses) if losses > 0 else float("inf")
                sharpe = float(arr.mean()/(arr.std(ddof=1)+1e-12)*np.sqrt(len(arr))) if len(arr) > 1 else None
                curve = np.cumsum(arr)
                peak = np.maximum.accumulate(curve)
                mdd = float(np.min(curve-peak))

            # [F3] VERIFIED 판정 강화 + [F4-6] 중복 표본 방어선
            if self._has_duplicate_samples(g):
                status = "DUPLICATED_SAMPLE"
            elif acc is None or n < self.MIN_VERIFIED_N:
                status = "INSUFFICIENT_SAMPLE"
            elif ci_low is not None and ci_low > 0.5:
                status = "VERIFIED"
            else:
                status = "NO_EDGE"
            out.append(asdict(Performance(model, task, n, acc, ci_low, brier,
                                          mae, pf, sharpe, mdd, status)))
        return pd.DataFrame(out)


# =============================================================================
# 6. ARENA
# =============================================================================

REGIME_FIT = {
    # [F11] 사람이 정한 heuristic prior. Priority는 신호강도 × 이 사전값 ×(검증 시) OOS 승수다.
    "Hook_OU": {"MEAN_REVERSION": 1.0, "TRANSITION": .7, "TREND": .35, "BREAKOUT_TRANSITION": .3},
    "Momentum": {"TREND": 1.0, "BREAKOUT_TRANSITION": .9, "TRANSITION": .65, "MEAN_REVERSION": .3},
    "Breakout": {"BREAKOUT_TRANSITION": 1.0, "TREND": .8, "TRANSITION": .6, "MEAN_REVERSION": .3},
    "Threshold": {"TRANSITION": .8, "MEAN_REVERSION": .75, "TREND": .5, "BREAKOUT_TRANSITION": .4},
    "TIR_v2": {"BREAKOUT_TRANSITION": 1.0, "TREND": .8, "TRANSITION": .6, "MEAN_REVERSION": .3},
}


def _oos_row(oos: pd.DataFrame, name: str) -> pd.DataFrame:
    if oos.empty or "model" not in oos.columns:
        return pd.DataFrame()
    return oos[oos["model"] == name]


def _obs_score(name: str, strength: float, regime: str, oos: pd.DataFrame) -> Tuple[float, str, bool]:
    """
    [F6] Priority/터미널/대시보드가 공유하는 단일 관찰 점수.
    [F12-2] 승수 기준선 정렬: VERIFIED는 항상 ×1.0 이상, 나머지는
      ×1.0 이하가 되도록 설계한다:
      - VERIFIED            : ×(1.0 + edge × stability_factor).
        edge = 2·DA − 1 (DA>50% 보장됨 → 항상 양수)이고
        stability_factor = 0.5 + 0.5·안정성이므로 승수는 항상 ≥1.0.
        예: DA 60%, 안정성 0.9 → edge=0.2, factor=0.95 → ×1.19. DA 70% → ×1.38.
      - NO_EDGE             : ×0.85 (우위 미확정 페널티)
      - 미검증·표본부족      : ×1.0 (중립)
      v3-1의 (0.5+0.5·DA)(≈0.76) 승수 역전 버그(검증된 모델이
      NO_EDGE·미검증보다 낮아지던 문제)를 수정했다.

    returns: (score, evidence, validated)
    """
    fit = REGIME_FIT.get(name, {}).get(regime, .5)
    base = float(np.clip(strength, 0, 1)) * fit
    row = _oos_row(oos, name)
    if row.empty:
        return base, "OOS 미검증(표본 없음)", False
    status = str(row["status"].iloc[0])
    if status == "VERIFIED":
        acc = float(row["directional_accuracy"].iloc[0])
        mdd = row["mdd"].iloc[0]
        stability = 1 - min(1, abs(float(mdd))) if pd.notna(mdd) else .5
        edge = 2.0 * acc - 1.0  # VERIFIED는 CI_low>50%이므로 항상 >0
        multiplier = 1.0 + edge * (0.5 + 0.5 * stability)
        evidence = f"OOS VERIFIED: DA={acc:.1%}, CI_low={float(row['da_ci_low'].iloc[0]):.1%}, n={int(row['n'].iloc[0])} (승수 ×{multiplier:.2f})"
        return base * multiplier, evidence, True
    if status in {"NO_EDGE", "DUPLICATED_SAMPLE"}:
        # [F4-6] 중복 표본도 통계 신뢰 불가 → NO_EDGE와 동일 페널티
        acc = float(row["directional_accuracy"].iloc[0]) if pd.notna(row["directional_accuracy"].iloc[0]) else 0.0
        ci = float(row["da_ci_low"].iloc[0]) if pd.notna(row["da_ci_low"].iloc[0]) else 0.0
        label = "OOS NO_EDGE" if status == "NO_EDGE" else "OOS DUPLICATED_SAMPLE(중복 표본)"
        evidence = (f"{label}: DA={acc:.1%}, CI_low={ci:.1%}, n={int(row['n'].iloc[0])} "
                    f"— 통계적 우위 미확정(스코어 ×0.85)")
        return base * 0.85, evidence, False
    return base, f"OOS 미검증({status}, n={int(row['n'].iloc[0])})", False


@dataclass
class ArenaResult:
    timestamp: pd.Timestamp
    regime: str
    market_state: Dict[str, float]
    predictions: List[Dict[str, Any]]
    sensors: List[Dict[str, Any]]
    oos: pd.DataFrame
    current_priority: Optional[str]
    current_reason: str
    oos_leader: Optional[str]
    provider: str
    quality: str


class Arena:
    def __init__(self, ledger_path: Optional[str] = None, bar_minutes: float = 1.0,
                 legacy_symbol: Optional[str] = None):
        self.models = [
            MomentumModel(), MeanReversionModel(), ThresholdModel(), BreakoutModel()
        ]
        self.tir2 = TIRV2()
        self.state = StateSpaceSensor()
        self.friction = FrictionSensor()
        self.regime = RegimeEngine(bar_minutes=bar_minutes)
        self.ledger = PredictionLedger()
        self.oos = OOSAnalyzer()
        self.ledger_path = ledger_path
        if ledger_path and Path(ledger_path).exists():
            # [F4-6] 구형 원장의 UNKNOWN 심볼을 승격해 키 중복 방지
            self.ledger.load(ledger_path, legacy_symbol=legacy_symbol)

    # -------------------------------------------------- ledger persistence
    def _flush_ledger(self):
        if self.ledger_path:
            self.ledger.save(self.ledger_path)

    def _record(self, hist: pd.DataFrame, reg: str, p: Dict[str, Any], horizon: int):
        """[F2] actionable 신호만 원장에 고정 기록한다."""
        if not p.get("actionable", False):
            return
        if "direction" not in p and "p_up" not in p:
            return
        self.ledger.add(PredictionRecord(
            timestamp=str(hist["timestamp"].iloc[-1]),
            model=p["model"], task=p.get("task", "direction"),
            horizon=horizon, regime=reg,
            prediction=p.get("direction", p.get("signal", "UNKNOWN")),
            p_up=float(p["p_up"]) if "p_up" in p else None,
            predicted_return=float(p.get("predicted_return", 0)),
            price_at_prediction=float(hist["close"].iloc[-1]),
            source=str(hist["source"].iloc[-1]),
            symbol=str(hist["symbol"].iloc[-1]),  # [F4-4]
        ))

    def run_backtest_replay(self, bars: pd.DataFrame, horizon: int = 5) -> ArenaResult:
        """
        [F3] stride=horizon 비중첩 워크포워드.
        매 horizon 봉마다 한 번만 예측하므로 평가 표본이 서로 겹치지 않는다.
        여전히 예측 시점에는 미래 데이터가 들어가지 않는다(hist = x.iloc[:i+1]).
        """
        x = normalize_bars(bars, "replay")
        start = 70
        for i in range(start, len(x)-horizon, horizon):
            hist = x.iloc[:i+1].copy()
            reg, _ = self.regime.infer(hist)
            for model in self.models:
                p = model.predict(hist)
                self._record(hist, reg, p, horizon)
        self.ledger.evaluate(x)
        self._flush_ledger()
        return self.evaluate_current(x, "replay", "GOOD", record=False)

    def evaluate_current(self, bars: pd.DataFrame, provider: str, quality: str,
                         orderbook: Optional[Mapping[str, Any]] = None,
                         horizon: int = 5, record: Optional[bool] = None) -> ArenaResult:
        """
        현재 스냅샷 관찰 + [F4] 현재 예측을 PENDING으로 원장에 고정 기록.
        이후 실제 봉이 들어오면 ledger.evaluate()가 실제값을 부착한다.
        [F5] orderbook이 제공되면 Friction 센서가 활성화된다.
        """
        if record is None:
            record = True
        x = normalize_bars(bars, provider)
        reg, state = self.regime.infer(x)

        predictions = [m.predict(x) for m in self.models]

        if record:
            for p in predictions:
                self._record(x, reg, p, horizon)
            self._flush_ledger()

        sensors = [get_tir_v1().predict(x), self.tir2.predict(x), self.state.predict(x)]
        sensors.append(self.friction.predict(orderbook or {}))  # [F5]

        oos = self.oos.summarize(self.ledger)
        current_priority, reason = self._priority(predictions, reg, oos)
        oos_leader = self._oos_leader(oos)
        return ArenaResult(pd.Timestamp(x["timestamp"].iloc[-1]), reg, state,
                           predictions, sensors, oos, current_priority, reason,
                           oos_leader, provider, quality)

    def _priority(self, predictions, regime, oos):
        candidates = []
        for p in predictions:
            strength = float(np.clip(p.get("strength", 0), 0, 1))
            # [F2] 중립(NO_BREAKOUT) 신호는 Priority 후보에서 제외
            if not p.get("actionable", True):
                continue
            score, evidence, validated = _obs_score(p["model"], strength, regime, oos)
            candidates.append((score, p["model"], strength,
                               REGIME_FIT.get(p["model"], {}).get(regime, .5),
                               validated, evidence))

        if not candidates:
            return None, "지금은 actionable 예측이 없습니다(모두 중립 신호)."

        candidates.sort(reverse=True)
        _, name, strength, fit, validated, evidence = candidates[0]
        if validated:
            reason = (f"{name}: 현재 신호강도 {strength:.2f} × Regime 적합도 {fit:.2f} "
                      f"+ 검증된 OOS 증거({evidence}). "
                      f"단, Regime 적합도는 heuristic prior다.")
        else:
            reason = (f"{name}: 현재 신호강도 {strength:.2f} × Regime 적합도 {fit:.2f}. "
                      f"{evidence}; 따라서 잠정 Priority.")
        return name, reason

    @staticmethod
    def _oos_leader(oos):
        if oos.empty:
            return None
        v = oos[(oos["task"] == "direction") & (oos["status"] == "VERIFIED")].copy()
        if v.empty:
            return None
        # [F3] DA가 같으면 CI 하한이 높은 쪽, 그다음 표본이 많은 쪽
        v = v.sort_values(["directional_accuracy", "da_ci_low", "n"], ascending=False)
        return str(v.iloc[0]["model"])


# =============================================================================
# 7. DEMO DATA
# =============================================================================

def generate_demo_data(n=720, seed=42):
    rng = np.random.default_rng(seed)
    parts = [
        rng.normal(0.0000, .0030, n//3),
        rng.normal(0.0007, .0045, n//3),
        rng.normal(-0.0004, .0050, n - 2*(n//3)),
    ]
    ret = np.concatenate(parts)
    close = 100 * np.exp(np.cumsum(ret))
    intrabar = rng.uniform(.0005, .003, n)
    high = close*(1+intrabar)
    low = close*(1-intrabar)
    open_ = np.r_[close[0], close[:-1]]
    volume = rng.lognormal(10, .4, n)
    amount = volume*close
    ts = pd.date_range("2026-01-02 09:00", periods=n, freq="min")
    return pd.DataFrame({
        "timestamp": ts, "symbol": "KOSPI", "open": open_, "high": high,
        "low": low, "close": close, "volume": volume, "trade_amount": amount,
        "spot_close": close,
        "futures_close": close + rng.normal(0, .12, n),
        "source": "demo_replay", "quality": "GOOD",
    })


# =============================================================================
# 8. OBSERVATORY DASHBOARD
# =============================================================================

CSS = r"""
:root{--bg:#07111f;--panel:#0d1b2a;--panel2:#10263a;--line:#20384f;--text:#e9f1f7;--muted:#8fa7ba;--good:#42d392;--warn:#f4c95d;--bad:#ff6b6b;--blue:#55a7ff}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(135deg,#06101c,#0b1b2b 55%,#07111f);color:var(--text);font-family:Inter,Arial,sans-serif}
.wrap{max-width:1500px;margin:auto;padding:24px}.title{font-size:30px;font-weight:800}.sub{color:var(--muted);margin-top:5px}
.grid{display:grid;gap:14px}.top{grid-template-columns:repeat(5,1fr);margin:20px 0}.two{grid-template-columns:1.2fr .8fr}.three{grid-template-columns:1fr 1fr 1fr}
.card{background:rgba(13,27,42,.94);border:1px solid var(--line);border-radius:14px;padding:17px;box-shadow:0 10px 30px #0003}.label{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}.value{font-size:22px;font-weight:750;margin-top:7px}.big{font-size:34px}.good{color:var(--good)}.warn{color:var(--warn)}.bad{color:var(--bad)}
table{width:100%;border-collapse:collapse}th,td{padding:10px 8px;border-bottom:1px solid var(--line);text-align:left;font-size:13px}th{color:var(--muted);font-weight:600}.rank{font-weight:800}.bar{height:8px;background:#142c42;border-radius:10px;overflow:hidden}.fill{height:100%;background:var(--blue);border-radius:10px}.reason{font-size:14px;line-height:1.6;color:#cfe0ec}.pill{display:inline-block;padding:4px 8px;border-radius:999px;background:#16324a;margin:2px;font-size:11px}
svg{width:100%;height:260px;background:#091827;border-radius:10px}.footer{color:#7890a4;font-size:11px;margin-top:18px}
@media(max-width:1000px){.top,.two,.three{grid-template-columns:1fr 1fr}}@media(max-width:650px){.top,.two,.three{grid-template-columns:1fr}.wrap{padding:12px}}
"""


def metric(v, pct=False):
    if v is None or (isinstance(v, float) and not np.isfinite(v)) or pd.isna(v):
        return "N/A"
    return f"{v:.1%}" if pct else f"{v:.3f}"


def quality_class(status: str) -> str:
    """[F10] QUALITY 칸 색상을 상태에 따라 변경."""
    if status in {"GOOD", "AUTH_CONFIGURED", "READY"}:
        return "good"
    if status in {"BAD", "MISSING", "ORDERBOOK_UNAVAILABLE"}:
        return "bad"
    return "warn"


def chart_svg(bars: pd.DataFrame) -> str:
    x = bars["close"].tail(180).to_numpy(dtype=float)
    if len(x) < 2:
        return "<svg viewBox='0 0 900 260'><text x='20' y='40' fill='#aaa'>차트 데이터 부족</text></svg>"
    w, h = 900, 260
    lo, hi = float(np.min(x)), float(np.max(x))
    pts = []
    for i, v in enumerate(x):
        xx = 10 + i*(w-20)/(len(x)-1)
        yy = h-15-(v-lo)/(hi-lo+1e-12)*(h-30)
        pts.append(f"{xx:.1f},{yy:.1f}")
    return (f"<svg viewBox='0 0 {w} {h}' preserveAspectRatio='none'>"
            f"<polyline points='{' '.join(pts)}' fill='none' stroke='#55a7ff' stroke-width='2.2'/>"
            f"<text x='15' y='24' fill='#8fa7ba'>KOSPI / replay close</text>"
            f"<text x='15' y='246' fill='#8fa7ba'>{lo:.2f}</text>"
            f"<text x='830' y='24' fill='#8fa7ba'>{hi:.2f}</text></svg>")


def dashboard_html(result: ArenaResult, bars: pd.DataFrame, health: pd.DataFrame) -> str:
    preds = result.predictions
    oos = result.oos.copy()

    ranked = []
    for p in preds:
        name = p["model"]
        strength = float(np.clip(p.get("strength", 0), 0, 1))
        # [F6] Priority와 동일한 공식
        obs, evidence, validated = _obs_score(name, strength, result.regime, oos)
        row = _oos_row(oos, name)
        da = float(row["directional_accuracy"].iloc[0]) if not row.empty and pd.notna(row["directional_accuracy"].iloc[0]) else None
        n = int(row["n"].iloc[0]) if not row.empty else 0
        status = str(row["status"].iloc[0]) if not row.empty else "UNVERIFIED"
        ranked.append((obs, name, strength, da, n, status, evidence, p))
    ranked.sort(reverse=True)

    pred_rows = []
    for rank, (obs, name, strength, da, n, status, evidence, p) in enumerate(ranked, 1):
        sig = p.get("direction", p.get("signal", "UNKNOWN"))
        neutral = not p.get("actionable", True)
        pred_rows.append(
            f"<tr><td class='rank'>#{rank}</td><td><b>{html.escape(name)}</b></td>"
            f"<td>{html.escape(str(sig))}{' (중립)' if neutral else ''}</td><td>{strength:.2f}</td>"
            f"<td>{metric(da, True)}</td><td>{n}</td>"
            f"<td><span class='pill'>{html.escape(status)}</span></td>"
            f"<td class='sub' style='font-size:11px;color:#8fa7ba'>{html.escape(evidence)}</td>"
            f"<td><div class='bar'><div class='fill' style='width:{obs*100:.0f}%'></div></div></td></tr>"
        )

    oos_rows = []
    if not oos.empty:
        for _, r in oos.iterrows():
            oos_rows.append(
                f"<tr><td><b>{html.escape(str(r['model']))}</b></td><td>{int(r['n'])}</td>"
                f"<td>{metric(r['directional_accuracy'], True)}</td>"
                f"<td>{metric(r.get('da_ci_low'), True)}</td>"
                f"<td>{metric(r.get('brier'))}</td>"
                f"<td>{metric(r.get('mae'))}</td><td>{metric(r.get('profit_factor'))}</td>"
                f"<td>{metric(r.get('sharpe'))}</td><td>{metric(r.get('mdd'))}</td>"
                f"<td><span class='pill'>{html.escape(str(r['status']))}</span></td></tr>"
            )

    health_rows = []
    for _, r in health.iterrows():
        cls = quality_class(str(r["status"]))
        health_rows.append(
            f"<tr><td>{html.escape(str(r['provider']))}</td><td>{html.escape(str(r['role']))}</td>"
            f"<td class='{cls}'>{html.escape(str(r['status']))}</td><td>{html.escape(str(r['message']))}</td></tr>"
        )

    sensor_html = ""
    for s in result.sensors:
        sig = str(s.get("signal", ""))
        cls = "good" if sig in {"NORMAL", "CENTERED", "GOOD", "TIR_ACTIVE", "BREAKOUT_후보"} else "warn"
        sensor_html += (f"<div class='card'><div class='label'>{html.escape(s['model'])}</div>"
                        f"<div class='value {cls}'>{html.escape(sig)}</div>"
                        f"<div class='sub'>strength {float(s.get('strength',0) or 0):.2f}</div></div>")

    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>KOSPI Model Arena Observatory v4</title><style>{CSS}</style></head>
<body><div class='wrap'>
<div class='title'>🏟 KOSPI MODEL ARENA — OBSERVATORY v4</div>
<div class='sub'>예측 → 실제값 → OOS 검증(비중첩 + Wilson CI) → 현재 Priority를 한 화면에서 관찰합니다.</div>

<div class='grid top'>
<div class='card'><div class='label'>REGIME</div><div class='value'>{html.escape(result.regime)}</div></div>
<div class='card'><div class='label'>CURRENT PRIORITY</div><div class='value big good'>{html.escape(result.current_priority or 'NONE')}</div></div>
<div class='card'><div class='label'>OOS LEADER</div><div class='value'>{html.escape(result.oos_leader or 'UNVERIFIED')}</div></div>
<div class='card'><div class='label'>DATA SOURCE</div><div class='value'>{html.escape(result.provider)}</div></div>
<div class='card'><div class='label'>QUALITY</div><div class='value {quality_class(result.quality)}'>{html.escape(result.quality)}</div></div>
</div>

<div class='grid two'>
<div class='card'><div class='label'>WHY IS THIS MODEL PRIORITY?</div><div class='reason'>{html.escape(result.current_reason)}</div></div>
<div class='card'><div class='label'>MARKET STATE</div>
<div class='reason'>Trend <b>{result.market_state['trend']:.2f}</b> · Momentum <b>{result.market_state['momentum']:.2f}</b> · Volatility(일간 환산) <b>{result.market_state['volatility']:.2f}</b> · MA distance <b>{result.market_state['distance_ma']:.3%}</b></div></div>
</div>

<div class='card' style='margin-top:14px'><div class='label'>KOSPI MARKET TRACE</div>{chart_svg(bars)}</div>

<div class='card' style='margin-top:14px'><div class='label'>MODEL COMPETITION — CURRENT OBSERVATION (Priority와 동일 공식)</div>
<table><thead><tr><th>Rank</th><th>Model</th><th>Signal</th><th>Strength</th><th>OOS DA</th><th>N</th><th>Status</th><th>Evidence</th><th>Obs</th></tr></thead>
<tbody>{''.join(pred_rows)}</tbody></table></div>

<div class='grid three' style='margin-top:14px'>{sensor_html}</div>

<div class='card' style='margin-top:14px'><div class='label'>OOS VALIDATION LAYER — NON-OVERLAPPING WALK-FORWARD REPLAY</div>
<table><thead><tr><th>Model</th><th>N</th><th>Directional Accuracy</th><th>Wilson CI Low</th><th>Brier</th><th>MAE</th><th>Profit Factor</th><th>Sharpe*</th><th>MDD*</th><th>Status</th></tr></thead>
<tbody>{''.join(oos_rows) or "<tr><td colspan='10'>아직 평가된 OOS 예측이 없습니다.</td></tr>"}</tbody></table>
<div class='footer'>VERIFIED = n≥30(비중첩)이고 Wilson 95% CI 하한 &gt; 50%. NO_EDGE = DA는 50% 이상일 수 있으나 통계적 우연을 배제 불가. * 거래비용/슬리피지 미반영 파이프라인 검증용 값입니다. demo 수치는 실제 KOSPI 성능이 아닙니다.</div></div>

<div class='card' style='margin-top:14px'><div class='label'>DATA PROVIDER HUB</div>
<table><thead><tr><th>Provider</th><th>Role</th><th>Status</th><th>Message</th></tr></thead>
<tbody>{''.join(health_rows)}</tbody></table></div>

<div class='footer'>Timestamp: {html.escape(str(result.timestamp))} · source={html.escape(result.provider)} · v4 single-file Observatory · REGIME_FIT 가중치는 heuristic prior입니다.</div>
</div></body></html>"""


# =============================================================================
# 9. LOCAL SERVER
# =============================================================================

class DashboardHandler(BaseHTTPRequestHandler):
    page = ""

    def do_GET(self):
        if urlparse(self.path).path in {"/", "/index.html"}:
            body = self.page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        return


def serve_dashboard(page: str, port: int = 8765, open_browser: bool = True):
    DashboardHandler.page = page
    server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    url = f"http://127.0.0.1:{port}/"
    print("\nKOSPI Model Arena Observatory v4")
    print(f"Dashboard: {url}")
    print("종료: Ctrl+C\n")
    if open_browser:
        threading.Timer(.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


# =============================================================================
# 10. DEMO / MAIN
# =============================================================================

def build_demo_hub(df):
    adapters: List[BaseAdapter] = [ReplayAdapter(df, "demo_replay"), LSAdapter()]
    for key in [
        "krx", "nxt", "kiwoom", "kis", "kb", "daishin", "mirae",
        "nh", "samsung", "shinhan", "hana", "naver", "yahoo",
        "investing", "dart", "ecos", "kosis", "database"
    ]:
        adapters.append(SlotAdapter(key))
    return ProviderHub(adapters, primary="demo_replay")


def run_demo(dashboard=False, port=8765, ledger_path=None, legacy_symbol=None):
    bars = generate_demo_data()
    hub = build_demo_hub(bars)
    fetched, quality = hub.fetch_bars("KOSPI")

    arena = Arena(ledger_path=ledger_path, bar_minutes=1.0,
                 legacy_symbol=legacy_symbol)
    result = arena.run_backtest_replay(fetched, horizon=5)

    # [F5] Hub에서 호가(orderbook)를 실제로 가져와 Friction 센서에 전달한다.
    # demo의 ReplayAdapter는 orderbook을 반환하지 않으므로
    # ORDERBOOK_UNAVAILABLE 상태가 정직하게 표시된다.
    orderbook, ob_quality = hub.fetch_orderbook("KOSPI")
    result = arena.evaluate_current(fetched, quality.source, quality.status,
                                     orderbook=orderbook, record=False)

    print("\n" + "="*118)
    print(" KOSPI MODEL ARENA OBSERVATORY v4")
    print("="*118)
    print(f"REGIME          : {result.regime}")
    print(f"CURRENT PRIORITY: {result.current_priority or 'NONE'}")
    print(f"OOS LEADER      : {result.oos_leader or 'UNVERIFIED'}")
    print(f"DATA            : {result.provider} / {result.quality}")
    print(f"TIR V1 BASELINE : {tir_v1_baseline_status()}")
    print(f"REASON          : {result.current_reason}")
    print("-"*118)

    # [F6] Priority와 동일한 공식으로 표를 정렬
    ranked = []
    for p in result.predictions:
        name = p["model"]
        strength = float(np.clip(p.get("strength", 0), 0, 1))
        obs, evidence, validated = _obs_score(name, strength, result.regime, result.oos)
        row = _oos_row(result.oos, name)
        da = float(row["directional_accuracy"].iloc[0]) if not row.empty and pd.notna(row["directional_accuracy"].iloc[0]) else None
        ci = float(row["da_ci_low"].iloc[0]) if not row.empty and pd.notna(row["da_ci_low"].iloc[0]) else None
        n = int(row["n"].iloc[0]) if not row.empty else 0
        status = str(row["status"].iloc[0]) if not row.empty else "UNVERIFIED"
        ranked.append((obs, name, p, da, ci, n, status, evidence))
    ranked.sort(reverse=True)
    print(f"{'RANK':<6}{'MODEL':<16}{'SIGNAL':<24}{'STR':>7}{'OOS_DA':>10}{'CI_LOW':>9}{'N':>6}  {'STATUS':<20}{'OBS':>6}")
    for i, (obs, name, p, da, ci, n, status, evidence) in enumerate(ranked, 1):
        sig = p.get("direction", p.get("signal", "UNKNOWN"))
        print(f"{i:<6}{name:<16}{str(sig):<24}{p.get('strength',0):>7.2f}"
              f"{('N/A' if da is None else f'{da:.1%}'):>10}"
              f"{('N/A' if ci is None else f'{ci:.1%}'):>9}{n:>6}  {status:<20}{obs:>6.3f}")
    print("-"*118)
    print("※ demo_replay는 synthetic pipeline test입니다. 실제 KOSPI 투자 성능을 의미하지 않습니다.")
    print("※ OOS N은 비중첩 표본(stride=horizon)이며, VERIFIED는 Wilson 95% CI 하한>50%를 요구합니다.")
    print("="*118)

    if dashboard:
        page = dashboard_html(result, fetched, hub.health_table())
        serve_dashboard(page, port=port)


def main():
    parser = argparse.ArgumentParser(description="KOSPI Model Arena Observatory v4")
    parser.add_argument("--demo", action="store_true", help="synthetic walk-forward + terminal observatory")
    parser.add_argument("--dashboard", action="store_true", help="open single-file local dashboard")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--ledger", type=str, default=None,
                        help="[F4] Prediction Ledger JSONL 경로 (지정 시 저장/적재)")
    parser.add_argument("--legacy-symbol", type=str, default=None,
                        help="[F4-6] 구형 원장(symbol 필드 없음)의 UNKNOWN 심볼을 "
                             "이 값으로 승격 (예: --legacy-symbol KOSPI)")
    args = parser.parse_args()

    if args.demo or args.dashboard:
        run_demo(dashboard=args.dashboard, port=args.port, ledger_path=args.ledger,
                 legacy_symbol=args.legacy_symbol)
    else:
        print("KOSPI Model Arena Observatory v4")
        print("사용:")
        print("  python kospi_model_arena_observatory_v4.py --demo")
        print("  python kospi_model_arena_observatory_v4.py --dashboard")
        print("  python kospi_model_arena_observatory_v4.py --demo --ledger ledger.jsonl")
        print("\nAPI 키는 코드에 넣지 말고 환경변수로 설정하세요.")


if __name__ == "__main__":
    main()