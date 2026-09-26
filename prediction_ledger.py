# -*- coding: utf-8 -*-
"""
prediction_ledger.py
=======================================================================
예측 영구 기록(Append-only Ledger) + 신뢰도 검증(OOS 판정) 공용 모듈
=======================================================================

[출처] 2026-09-26, kospi-model-arena-observatory-v4(F4 시리즈 수정)의
PredictionLedger / OOSAnalyzer / Performance / wilson_lower_bound를 그대로
추출함. add()/save()/load() 중복 차단·append 저장·구형 원장 승격 로직과
OOSAnalyzer의 판정 기준(VERIFIED 조건: n>=30 AND Wilson 95% CI 하한>50%,
중복 표본 방어선 포함)은 원본과 동일하다.

evaluate()만 일반화했다: Arena 전용 normalize_bars/MarketSnapshot(요구 컬럼
open/symbol/volume 등)에 의존하지 않고, "타임스탬프로 색인된 종가 pd.Series"
하나만 받도록 바꿨다. 콕핏처럼 open/symbol 컬럼이 없는 더 단순한 분봉에도
그대로 쓸 수 있게 하기 위함이며, 통계·판정 로직 자체는 손대지 않았다.

[2026-09-26 통합] prediction_ledger_shared.py의 내용을 prediction_ledger.py
파일명으로 확정했다. TIR(tir_reflection_backtest_v1_connected.py)과 콕핏
(kospi_cockpit_sensor_hub_v1.1)이 `import prediction_ledger as _pl`로
참조하는 파일명과 일치시키기 위함이며, 이전 버전(prediction_ledger.py 구버전,
evaluate_binary_events 없음)에 있던 AttributeError 크래시를 제거한다.
prediction_ledger_shared.py는 이 파일로 흡수되었으므로 더 이상 별도로
유지하지 않는다(99_archive 이동 또는 삭제 권장).

이 모듈이 담당하는 3단계 (요구사항):
  1) add()      — 예측을 append-only로 영구 기록 ((timestamp, model, horizon,
                  symbol, source) 키로 중복 차단)
  2) evaluate()  — 나중에 들어온 실제 가격으로 PENDING 예측에 실제값을 붙여
                  EVALUATED로 갱신 ("업데이트 후 그 전 값과 비교")
  3) OOSAnalyzer.summarize() — 방향적중률 + Wilson 95% CI 하한 + Brier/MAE/
                  Profit Factor/Sharpe/MDD 계산, 4단계 신뢰도 판정
                  (VERIFIED / NO_EDGE / INSUFFICIENT_SAMPLE / DUPLICATED_SAMPLE)

저장 위치 규칙 (SEC-402/403):
    ledger*.jsonl은 04_data/local/ 아래에 두고 Git에 커밋하지 않는다.
    (.gitignore에 04_data/local/ 패턴 추가 권장 — 본 모듈은 파일 저장 여부와
    무관하게 동작하며, save()/load()를 호출하지 않으면 메모리에서만 쓰인다.)
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# =============================================================================
# 신뢰도 계산 유틸 (원본과 동일)
# =============================================================================

def wilson_lower_bound(k: int, n: int, z: float = 1.96) -> Optional[float]:
    """방향적중률의 Wilson 95% 신뢰구간 하한."""
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / denom


def _json_default(obj: Any) -> Any:
    """numpy bool_/int64/float64 등을 JSON 직렬화 가능 값으로 변환."""
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (pd.Timestamp,)):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


# =============================================================================
# 예측 레코드 / 원장 (add/save/load는 원본과 동일, evaluate만 일반화)
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
    # Binary-event extension; existing direction/return fields remain unchanged.
    actual_event: Optional[bool] = None
    event_correct: Optional[bool] = None
    status: str = "PENDING"
    source: str = "UNKNOWN"
    symbol: str = "UNKNOWN"


class PredictionLedger:
    """예측 고정 기록(append-only ledger).

    - (timestamp, model, horizon, symbol, source) 키로 중복 기록을 차단한다.
    - save()는 전체 덮어쓰기가 아니라 append. 신규 레코드 줄(_t=record) +
      상태가 바뀐 레코드의 갱신 줄(_t=update)만 추가한다.
    - load()는 같은 키의 마지막 상태를 우선 적용한다.
    - legacy_symbol: 구형 원장(symbol 필드 없음 → "UNKNOWN")의 심볼을 지정한
      값으로 승격해서, 새 기록과 키가 달라 중복 방지가 깨지는 것을 막는다.
    """

    def __init__(self) -> None:
        self.records: List[PredictionRecord] = []
        self._seen: Dict[Tuple[str, str, int, str, str], PredictionRecord] = {}
        self._saved_count = 0
        self._saved_status: Dict[Tuple[str, str, int, str, str], str] = {}

    def _key(self, rec: PredictionRecord) -> Tuple[str, str, int, str, str]:
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

    def save(self, path: str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            for rec in self.records[self._saved_count:]:
                row = asdict(rec)
                row["_t"] = "record"
                f.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")
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
                        "actual_event": rec.actual_event,
                        "event_correct": rec.event_correct,
                    }, ensure_ascii=False, default=_json_default) + "\n")
                    self._saved_status[k] = rec.status

    def load(self, path: str, legacy_symbol: Optional[str] = None) -> None:
        p = Path(path)
        if not p.exists():
            return
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                kind = d.get("_t", "record")
                if kind == "update":
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
                    rec.actual_event = d.get("actual_event")
                    rec.event_correct = d.get("event_correct")
                else:
                    d.pop("_t", None)
                    rec = PredictionRecord(**d)
                    if legacy_symbol and rec.symbol == "UNKNOWN":
                        rec.symbol = legacy_symbol
                    self.add(rec)
        self._saved_count = len(self.records)
        self._saved_status = {self._key(r): r.status for r in self.records}

    def evaluate(self, prices: pd.Series) -> None:
        """[일반화 지점] prices: 타임스탬프로 변환 가능한 인덱스 + 종가 값을
        담은 pd.Series. Arena의 normalize_bars 없이도, 어떤 분봉/일봉이든
        이 형태로만 맞추면 그대로 평가할 수 있다. PENDING 레코드에만 실제값을
        붙인다(재평가하지 않음)."""
        idx = pd.to_datetime(prices.index)
        order = np.argsort(idx.to_numpy())
        ts = idx.to_numpy()[order]
        px = prices.to_numpy(dtype=float)[order]

        for rec in self.records:
            if rec.status != "PENDING":
                continue
            t0 = pd.Timestamp(rec.timestamp)
            future = np.where(ts > np.datetime64(t0))[0]
            if len(future) < rec.horizon:
                continue
            i = future[rec.horizon - 1]
            actual = float(px[i] / rec.price_at_prediction - 1)
            rec.target_timestamp = str(pd.Timestamp(ts[i]))
            rec.actual_return = actual
            rec.actual_direction = "UP" if actual > 0 else "DOWN" if actual < 0 else "FLAT"
            if rec.task == "direction" and rec.p_up is not None:
                pred_dir = "UP" if rec.p_up >= .5 else "DOWN"
                rec.direction_correct = bool(pred_dir == rec.actual_direction)
            elif rec.predicted_return is not None:
                if actual != 0 and rec.predicted_return != 0:
                    rec.direction_correct = bool(np.sign(rec.predicted_return) == np.sign(actual))
                else:
                    rec.direction_correct = None
            if rec.predicted_return is not None:
                rec.absolute_error = abs(actual - rec.predicted_return)
            rec.status = "EVALUATED"

    def evaluate_binary_events(self, outcomes: pd.Series,
                               at_prediction_timestamp: bool = False) -> None:
        """Evaluate binary-event records against a timestamp-indexed bool Series.

        ``at_prediction_timestamp=True`` is intended for events such as TIR
        ``bounded_success`` where the row at t already contains the forward
        outcome over t+1..t+horizon. In that mode the outcome is attached to
        the same prediction timestamp; no second horizon shift is applied.
        """
        idx = pd.to_datetime(outcomes.index)
        order = np.argsort(idx.to_numpy())
        ts = idx.to_numpy()[order]
        vals = outcomes.to_numpy()[order]

        for rec in self.records:
            if rec.status != "PENDING" or rec.task != "binary_event":
                continue
            t0 = pd.Timestamp(rec.timestamp)

            if at_prediction_timestamp:
                matches = np.where(ts == np.datetime64(t0))[0]
                if len(matches) == 0:
                    continue
                i = matches[0]
            else:
                future = np.where(ts > np.datetime64(t0))[0]
                if len(future) < rec.horizon:
                    continue
                i = future[rec.horizon - 1]

            value = vals[i]
            if pd.isna(value):
                continue
            actual = bool(value)
            rec.target_timestamp = str(pd.Timestamp(ts[i]))
            rec.actual_event = actual
            pred = str(rec.prediction).upper()
            rec.event_correct = bool(pred == ("TRUE" if actual else "FALSE"))
            rec.status = "EVALUATED"

    def dataframe(self) -> pd.DataFrame:
        if not self.records:
            return pd.DataFrame()
        return pd.DataFrame([asdict(x) for x in self.records])


# =============================================================================
# 신뢰도 판정 (원본과 완전 동일)
# =============================================================================

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
    """VERIFIED 조건: n >= 30(비중첩) AND Wilson 95% CI 하한 > 50%.
    CI 하한이 50% 이하면 DA가 우연일 가능성을 배제하지 못하므로 'NO_EDGE'."""

    MIN_VERIFIED_N = 30

    @staticmethod
    def _has_duplicate_samples(g: pd.DataFrame) -> bool:
        """중복 표본 방어선 — (timestamp, model, horizon, price_at_prediction,
        p_up) 지문이 같으면 같은 시장 시점을 두 번 센 것으로 본다. symbol이
        "UNKNOWN"이거나 서로 같으면 중복, symbol이 서로 다르면 다른 종목의
        우연한 동일 지문으로 보고 통과시킨다."""
        key_cols = ["timestamp", "model", "horizon", "price_at_prediction", "p_up"]
        for c in key_cols:
            if c not in g.columns:
                return False
        gg = g.dropna(subset=["timestamp"])
        if gg.empty:
            return False
        grouped = gg.groupby(
            ["timestamp", "model", "horizon", "price_at_prediction", "p_up"], dropna=False)
        for _, grp in grouped:
            if len(grp) < 2:
                continue
            symbols = {str(r.get("symbol", "UNKNOWN")) for r in grp.to_dict("records")}
            if "UNKNOWN" in symbols or len(symbols) == 1:
                return True
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
                brier = float(np.mean((gg["p_up"].astype(float) - y) ** 2))

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
                pf = float(gains / losses) if losses > 0 else float("inf")
                sharpe = float(arr.mean() / (arr.std(ddof=1) + 1e-12) * np.sqrt(len(arr))) if len(arr) > 1 else None
                curve = np.cumsum(arr)
                peak = np.maximum.accumulate(curve)
                mdd = float(np.min(curve - peak))

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

    def summarize_binary_events(self, ledger: PredictionLedger) -> pd.DataFrame:
        """Summarize task='binary_event' separately from directional OOS metrics."""
        df = ledger.dataframe()
        if df.empty or "task" not in df.columns:
            return pd.DataFrame()
        gdf = df[(df["task"] == "binary_event") & (df["status"] == "EVALUATED")].copy()
        if gdf.empty:
            return pd.DataFrame()
        rows = []
        for model, g in gdf.groupby("model"):
            ok = pd.to_numeric(g["event_correct"], errors="coerce").dropna()
            n = int(len(ok))
            k = int(ok.sum())
            acc = float(k / n) if n else None
            ci = wilson_lower_bound(k, n) if n else None
            if self._has_duplicate_samples(g):
                status = "DUPLICATED_SAMPLE"
            elif n < self.MIN_VERIFIED_N:
                status = "INSUFFICIENT_SAMPLE"
            elif ci is not None and ci > 0.5:
                status = "VERIFIED"
            else:
                status = "NO_EDGE"
            rows.append({
                "model": model, "task": "binary_event", "n": n,
                "event_accuracy": acc, "event_ci_low": ci, "status": status,
            })
        return pd.DataFrame(rows)