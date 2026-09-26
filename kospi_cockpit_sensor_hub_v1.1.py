# -*- coding: utf-8 -*-
"""
kospi_cockpit_sensor_hub_v1.1.py

KOSPI 장중감시 콕핏 - 3센서 통합 허브 (v1.1)

v1.1 변경사항 (v1.0 대비):
  - TIRSensor를 실제 tir_reflection_backtest_v1.py의 v1 로직(compute_tir_proxies,
    run_backtest_v1)으로 교체. v1 로직 자체는 수정하지 않고 그대로 import해서 사용.
  - TIR은 일봉(daily), State-Space/Friction은 분봉(intraday)이라는 주기 차이를
    명시적으로 분리. Hub.run()이 df_intraday, df_daily 두 입력을 받도록 변경.
  - 일봉 TIR 신호를 분봉 타임스탬프에 전파할 때 pd.merge_asof(direction="backward")
    사용 - 각 분봉 시점 "이전 또는 같은" 가장 최근 일봉 값만 붙어서 미래 데이터가
    새어들 수 없음(look-ahead 방지).
  - friction_engine.py는 아직 미연동 (폴백 proxy 유지, v1.0과 동일)

설계 원칙 (프로젝트 메모 기준):
  1) TIR / Friction / State-Space는 "경쟁 모델"이 아니라 서로 다른 것을 측정하는
     독립 센서다. 세 값을 w1*TIR + w2*mu + w3*eps 식으로 선형결합하지 않는다.
  2) 세 센서는 같은 원천 바(bar) 데이터에서 "병렬"로 계산한다.
     TIR -> Friction -> State-Space 순서로 계산이 의존하지 않는다.
     (설계 다이어그램의 순서는 "해석 순서"이지 "계산 순서"가 아니다.)
  3) State-Space의 x_t, v_t, a_t는 반드시 causal(과거 데이터만 사용)하게 계산한다.
     중심차분(centered difference) 금지.
  4) r_t, theta_t, omega_t, alpha_t는 (x_t, v_t)의 좌표변환일 뿐 독립 feature가 아니다.
     lambda_scale=1.0 고정, x*, v*는 각자 rolling volatility로 정규화한다.
  5) Trajectory Residual epsilon_{t+h} 계산에서 미래값(x_{t+h})은 "평가 대상"으로만
     쓰고, t 시점의 예측치(x_hat)는 절대 미래 정보를 참조하지 않는다.
  6) Friction 센서는 자체 공식을 새로 만들지 않고 기존 friction_engine.py
     (compute_refined_friction, FrictionState)를 그대로 재사용한다.
     이 파일이 없는 환경에서는 안전한 폴백(proxy)으로 대체하고 경고를 남긴다.
  7) 세 센서 결과는 마지막에 CockpitGate에서 "조건부 cascade"로만 해석한다.

이 파일은 인터페이스 + 더미(mock) 데이터 동작 테스트까지 포함한 v1.0 초안이다.
실제 KRX/증권사 API 데이터 연결, friction_engine.py 실제 파일 연동,
TIR의 실제 kappa/theta_c 계산식은 후속 버전에서 채워 넣어야 한다.
(코드 내 "# TODO(실データ연동)" 표시 참고)
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

import numpy as np
import pandas as pd

# [통합 메모] 2026-09-26: kospi-model-arena-observatory-v4의 PredictionLedger/
# OOSAnalyzer를 02_engine/prediction_ledger.py로 추출해, 콕핏의 cascade 경보를
# "예측"으로 영구 기록하고 나중에 실제 가격과 비교해 신뢰도(방향적중률 + Wilson
# 95% CI)를 계산할 수 있게 연결한다. TIR v1과 동일하게 import로만 재사용하며,
# 모듈이 없는 환경에서는 원장 관련 기능만 비활성화되고 나머지 콕핏 동작에는
# 영향이 없다.
try:
    import prediction_ledger as _pl  # TODO(배포시): 같은 폴더(02_engine)에 배치 확인
    _LEDGER_AVAILABLE = True
except ImportError:
    _LEDGER_AVAILABLE = False
    warnings.warn(
        "prediction_ledger.py를 찾지 못해 예측 원장/신뢰도 검증 기능이 "
        "비활성화됩니다(콕핏 센서 계산 자체는 정상 동작).",
        RuntimeWarning,
    )


# =====================================================================
# 0. 설정값 (하이퍼파라미터) - 절대 하드코딩하지 않고 여기서만 관리
# =====================================================================

@dataclass
class CockpitConfig:
    # --- State-Space: x_t, v_t, a_t 정규화 윈도우 ---
    ma_window: int = 20          # W_MA: 기준 가격 이동평균 윈도우
    atr_window: int = 14         # W_ATR: ATR 윈도우
    sigma_x_window: int = 60     # x_t 정규화용 rolling std 윈도우
    sigma_v_window: int = 60     # v_t 정규화용 rolling std 윈도우

    # --- Phase Coordinates ---
    lambda_scale: float = 1.0    # 반드시 1.0 고정 (물리 상수 아님, 좌표변환용)

    # --- Impact (Q_t, D_t): 거래량/거래대금 표준화 윈도우 ---
    volume_z_window: int = 50    # W_Q
    turnover_z_window: int = 50  # W_D

    # --- Trajectory Residual horizon (분 단위, 바 간격 기준) ---
    horizons: List[int] = field(default_factory=lambda: [1, 5, 10, 20])

    # --- 상태 이벤트 임계값 ---
    q_shock_sigma: float = 2.0        # 상태 C: |Q_t| > q_shock_sigma * sigma
    epsilon_dev_sigma: float = 2.0    # 상태 D: |epsilon| >> sigma_epsilon 기준 배수

    # --- Friction 게이트 임계값 ---
    friction_spike_quantile: float = 0.95   # 최근 N바 대비 상위 분위
    friction_lookback: int = 100

    # --- TIR (임계돌파) 프록시 파라미터 (1차 proxy, 실 데이터 연결 전) ---
    tir_kappa_window: int = 20   # kappa proxy: 거래대금 증가 대비 변동폭 축소 비율 계산 윈도우
    tir_theta_i_sigma: float = 2.0  # theta_i proxy 트리거 (베이시스 급변동 sigma)


# =====================================================================
# 1. State-Space 센서: X_t=(x,v,a) + Phase Coordinates + Residual
# =====================================================================

class StateSpaceSensor:
    """
    독립 축 X_t=(x_t, v_t, a_t)를 causal하게 계산하고,
    r_t/theta_t/omega_t/alpha_t는 좌표변환으로만 파생시킨다.
    Trajectory Residual epsilon_{t+h}도 함께 계산한다.
    """

    def __init__(self, config: CockpitConfig):
        self.cfg = config

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        df 필수 컬럼: close, high, low, volume, turnover(거래대금)
        인덱스는 시간순 정렬된 DatetimeIndex 가정.
        """
        cfg = self.cfg
        out = df.copy()

        # --- 기준 가격(MA), 변동성(ATR): 전부 과거 데이터만 사용(shift 없이도
        #     rolling().mean()은 t시점까지의 값만 쓰므로 causal함) ---
        out["MA"] = out["close"].rolling(cfg.ma_window, min_periods=cfg.ma_window).mean()

        prev_close = out["close"].shift(1)
        tr = pd.concat(
            [
                out["high"] - out["low"],
                (out["high"] - prev_close).abs(),
                (out["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        out["ATR"] = tr.rolling(cfg.atr_window, min_periods=cfg.atr_window).mean()

        # --- x_t, v_t, a_t: causal(backward-looking) diff만 사용 ---
        out["x_t"] = (out["close"] - out["MA"]) / out["ATR"]
        out["v_t"] = out["x_t"].diff()          # x_t - x_{t-1}
        out["a_t"] = out["v_t"].diff()           # v_t - v_{t-1}

        # --- Phase Coordinates: x*, v*를 각자 rolling volatility로 정규화 후 좌표변환 ---
        sigma_x = out["x_t"].rolling(cfg.sigma_x_window, min_periods=cfg.sigma_x_window).std()
        sigma_v = out["v_t"].rolling(cfg.sigma_v_window, min_periods=cfg.sigma_v_window).std()
        x_star = out["x_t"] / sigma_x.replace(0, np.nan)
        v_star = out["v_t"] / sigma_v.replace(0, np.nan)
        v_scaled = cfg.lambda_scale * v_star

        out["r_t"] = np.sqrt(x_star**2 + v_scaled**2)
        out["theta_t"] = np.arctan2(v_scaled, x_star)
        out["omega_t"] = out["theta_t"].diff()
        out["alpha_t"] = out["omega_t"].diff()

        # --- Impact: Q_t(거래량 z-score), D_t(거래대금 z-score) ---
        vol_mean = out["volume"].rolling(cfg.volume_z_window, min_periods=cfg.volume_z_window).mean()
        vol_std = out["volume"].rolling(cfg.volume_z_window, min_periods=cfg.volume_z_window).std()
        out["Q_t"] = (out["volume"] - vol_mean) / vol_std.replace(0, np.nan)

        if "turnover" in out.columns:
            to_mean = out["turnover"].rolling(cfg.turnover_z_window, min_periods=cfg.turnover_z_window).mean()
            to_std = out["turnover"].rolling(cfg.turnover_z_window, min_periods=cfg.turnover_z_window).std()
            out["D_t"] = (out["turnover"] - to_mean) / to_std.replace(0, np.nan)
        else:
            out["D_t"] = np.nan

        # --- Trajectory Residual: t 시점까지 정보로 x_hat 예측 -> 미래 실제값과 비교 ---
        for h in cfg.horizons:
            x_hat = out["x_t"] + out["v_t"] * h + 0.5 * out["a_t"] * (h**2)  # t시점 정보만 사용
            x_actual_future = out["x_t"].shift(-h)  # "평가용" 미래값(feature 아님)
            out[f"epsilon_h{h}"] = x_actual_future - x_hat

        return out

    def classify_state_events(self, row: pd.Series) -> Dict[str, bool]:
        """상태 A/B/C/D 이벤트 판정 (조합 가능, 배타적 아님)"""
        cfg = self.cfg
        v, a, q = row.get("v_t"), row.get("a_t"), row.get("Q_t")
        eps = row.get(f"epsilon_h{cfg.horizons[0]}")

        def safe(x):
            return (x is not None) and (not pd.isna(x))

        state_a = safe(v) and safe(a) and safe(q) and (v > 0 and a > 0 and q > 0)
        state_b = safe(v) and safe(a) and safe(q) and (v > 0 and a < 0 and q > 0)
        state_c = safe(q) and (abs(q) > cfg.q_shock_sigma)
        state_d = safe(eps) and (abs(eps) > cfg.epsilon_dev_sigma)  # sigma_epsilon 대신 표준화된 epsilon 가정

        return {"state_A_추진": state_a, "state_B_감속": state_b,
                "state_C_충격": state_c, "state_D_궤적이탈": state_d}


# =====================================================================
# 2. Friction 센서: 기존 friction_engine.py 재사용 (폴백 포함)
# =====================================================================

class FrictionAdapter:
    """
    기존에 완성해둔 friction_engine.py의 compute_refined_friction() /
    FrictionState를 그대로 호출하는 어댑터.

    friction_engine.py를 아직 이 환경에 올리지 않았으므로, import가 실패하면
    "명시적으로 표시되는" 폴백 프록시로 대체한다. 실제 프로젝트에 통합할 때는
    반드시 friction_engine.py를 이 모듈과 같은 경로에 두고 폴백이 아닌
    실제 엔진이 쓰이는지 확인해야 한다 (아래 self.using_real_engine 참고).
    """

    def __init__(self, config: CockpitConfig):
        self.cfg = config
        self.using_real_engine = False
        self._real_module = None
        try:
            import friction_engine as _fe  # TODO(실데이터연동): 실제 friction_engine.py를 같은 폴더에 배치
            self._real_module = _fe
            self.using_real_engine = True
        except ImportError:
            warnings.warn(
                "friction_engine.py를 찾지 못해 폴백 프록시로 마찰지수를 계산합니다. "
                "실제 프로젝트 파일을 연결하면 이 경고는 사라집니다.",
                RuntimeWarning,
            )

    def compute(self, df: pd.DataFrame) -> pd.Series:
        if self.using_real_engine:
            # 실제 friction_engine.py의 인터페이스에 맞춰 호출부를 채워야 함.
            # TODO(실데이터연동): compute_refined_friction(...) / FrictionState 실제 연동
            raise NotImplementedError(
                "friction_engine.py가 감지되었지만 실제 호출부는 파일 스키마 확인 후 연결 필요"
            )

        # --- 폴백 프록시: 절대 실제 마찰지수 공식(Sₜ 산식)을 대체하지 않음. 임시용. ---
        price_change_abs = df["close"].diff().abs()
        vol_ma = df["volume"].rolling(20, min_periods=20).mean()
        friction_proxy = price_change_abs / (df["volume"] / vol_ma.replace(0, np.nan) + 1e-6)
        return friction_proxy.rename("friction_score_PROXY")


# =====================================================================
# 3. TIR 센서 (1차 proxy, 실제 n1/n2/theta_c/kappa/E(x) 연결 전)
# =====================================================================

class TIRSensor:
    """
    광학 전반사(TIR) 비유 기반 임계돌파 센서.

    v1.1: tir_reflection_backtest_v1.py의 v1 로직(compute_tir_proxies,
    run_backtest_v1)을 그대로 import해서 재사용한다. v1 로직 자체는 절대
    수정하지 않는다(그 파일의 "기준선, 절대 수정하지 않음" 원칙 유지).

    이 TIR은 일봉(daily) 기준으로 설계되어 있어(rolling 60일, t+1~t+5
    거래일 forward), 분봉 기준인 State-Space/Friction과 입력 데이터프레임
    자체가 다르다. 일봉 tir_signal을 분봉 타임스탬프에 전파하는 것은
    CockpitGate에서 merge_asof(backward)로 처리한다(미래 데이터 참조 없음).
    """

    def __init__(self, config: CockpitConfig):
        self.cfg = config
        self.using_real_module = False
        try:
            import tir_reflection_backtest_v1 as _tir  # TODO(배포시): 같은 폴더에 배치 확인
            self._tir_module = _tir
            self.using_real_module = True
        except ImportError:
            warnings.warn(
                "tir_reflection_backtest_v1.py를 찾지 못해 TIR 센서를 폴백 proxy로 대체합니다. "
                "실제 파일을 이 모듈과 같은 폴더에 두면 이 경고는 사라집니다.",
                RuntimeWarning,
            )
            self._tir_module = None

    def compute(self, df_daily: pd.DataFrame) -> pd.DataFrame:
        """
        df_daily 필수 컬럼(tir_reflection_backtest_v1.py 기준):
          spot_close, futures_close, high, low, close, trade_amount
        인덱스는 날짜 오름차순 정렬.
        """
        if self.using_real_module:
            result = self._tir_module.run_backtest_v1(df_daily.copy())
            out = result[["tir_score", "tir_signal", "kappa_proxy", "theta_proxy"]].copy()
            out = out.rename(columns={"tir_signal": "tir_event"})
            out["threshold"] = 3  # run_backtest_v1의 score>=3 고정 컷오프
            return out

        # --- 폴백 proxy: 실제 v1 로직을 대체하지 않는 임시용 ---
        out = pd.DataFrame(index=df_daily.index)
        price_range = (df_daily["high"] - df_daily["low"]) / df_daily["close"]
        range_ma = price_range.rolling(cfg_window := self.cfg.tir_kappa_window, min_periods=cfg_window).mean()
        out["kappa_proxy"] = 1.0 / (price_range / range_ma.replace(0, np.nan)).replace(0, np.nan)
        out["tir_event"] = False
        out["threshold"] = np.nan
        out["tir_score"] = np.nan
        return out


# =====================================================================
# 4. Cockpit Gate: 세 센서 결과를 "조건부 cascade"로만 결합
# =====================================================================

class CockpitGate:
    def __init__(self, config: CockpitConfig):
        self.cfg = config

    def fuse(self, state_df: pd.DataFrame, tir_df: pd.DataFrame,
             friction_series: pd.Series) -> pd.DataFrame:
        cfg = self.cfg
        unified = state_df.copy()

        # --- 시간 동기화: 일봉 TIR -> 분봉으로 전파 ---
        # merge_asof(direction="backward")는 각 분봉 시점보다 "이전이거나 같은" 가장
        # 최근 일봉 값만 붙인다. 미래의 일봉 데이터가 새어들 수 없다(look-ahead 방지).
        left = unified.reset_index().rename(columns={"index": "_ts"})
        right = tir_df.reset_index().rename(columns={"index": "_ts"}).sort_values("_ts")
        left = left.sort_values("_ts")
        merged = pd.merge_asof(
            left, right[["_ts", "tir_event", "threshold"]],
            on="_ts", direction="backward",
        )
        merged = merged.set_index("_ts")
        merged.index.name = unified.index.name

        unified["tir_event"] = merged["tir_event"].fillna(False)
        unified["threshold"] = merged.get("threshold", np.nan)
        # Q_z는 분봉 자체의 거래량 충격(State-Space의 Q_t)을 그대로 노출한다.
        # (일봉 TIR에는 분봉 단위 Q_z 개념이 없으므로 혼동 방지 위해 분리)
        unified["Q_z"] = unified["Q_t"]

        # 시간 동기화: friction은 같은(분봉) 빈도라 가정(다른 빈도라면 ffill로 낮은 주파수 전파,
        # 단 미래 데이터가 새어들지 않도록 반드시 ffill만 사용)
        unified["friction_score"] = friction_series.reindex(unified.index, method="ffill")
        friction_thresh = unified["friction_score"].rolling(
            cfg.friction_lookback, min_periods=cfg.friction_lookback
        ).quantile(cfg.friction_spike_quantile)
        unified["friction_spike"] = unified["friction_score"] > friction_thresh

        # --- 조건부 cascade 판정 (선형결합 아님) ---
        def cascade_label(row) -> str:
            if not row.get("tir_event", False):
                return "NORMAL"
            if not row.get("friction_spike", False):
                return "TIR_발생_저항낮음"
            # TIR + friction spike -> State-Space 이탈 여부 확인
            eps0 = row.get(f"epsilon_h{cfg.horizons[0]}")
            if pd.notna(eps0) and abs(eps0) > cfg.epsilon_dev_sigma:
                return "TIR_발생_저항붕괴_상태전이"
            return "TIR_발생_저항큼_대기"

        unified["cascade_label"] = unified.apply(cascade_label, axis=1)
        unified["regime_alert"] = unified["cascade_label"] == "TIR_발생_저항붕괴_상태전이"

        return unified


# =====================================================================
# 5. 통합 허브: 병렬 계산 -> 게이트 결합 -> 최종 레코드 스키마
# =====================================================================

class KospiCockpitSensorHub:
    FINAL_COLUMNS = [
        # TIR
        "tir_event", "Q_z", "threshold",
        # Friction
        "friction_score", "friction_spike",
        # State-Space
        "x_t", "v_t", "a_t", "r_t", "theta_t", "omega_t", "alpha_t",
        # Cascade
        "cascade_label", "regime_alert",
    ]

    def __init__(self, config: Optional[CockpitConfig] = None):
        self.cfg = config or CockpitConfig()
        self.state_sensor = StateSpaceSensor(self.cfg)
        self.friction_adapter = FrictionAdapter(self.cfg)
        self.tir_sensor = TIRSensor(self.cfg)
        self.gate = CockpitGate(self.cfg)

    def run(self, df_intraday: pd.DataFrame, df_daily: pd.DataFrame) -> pd.DataFrame:
        """
        df_intraday 필수 컬럼: close, high, low, volume, turnover (분봉, State-Space/Friction용)
        df_daily 필수 컬럼: spot_close, futures_close, high, low, close, trade_amount (일봉, TIR용)
        세 센서를 "병렬"로 각각 계산한 뒤 게이트에서만 결합한다.
        TIR은 일봉이므로 게이트에서 merge_asof(backward)로 분봉에 안전하게 전파한다.
        """
        state_df = self.state_sensor.compute(df_intraday)          # 센서 1 (독립, 분봉)
        friction_series = self.friction_adapter.compute(df_intraday)  # 센서 2 (독립, 분봉)
        tir_df = self.tir_sensor.compute(df_daily)                  # 센서 3 (독립, 일봉)

        fused = self.gate.fuse(state_df, tir_df, friction_series)

        eps_cols = [c for c in fused.columns if c.startswith("epsilon_h")]
        final_cols = self.FINAL_COLUMNS + eps_cols
        return fused[[c for c in final_cols if c in fused.columns]]


# =====================================================================
# 6. 더미(mock) 데이터 생성 + 동작 테스트
# =====================================================================

def generate_mock_intraday_bars(n_bars: int = 500, seed: int = 42,
                                 start: str = "2026-09-23 09:00") -> pd.DataFrame:
    """
    실제 KRX/증권사 데이터 없이 파이프라인 동작을 확인하기 위한 1분봉 mock 데이터.
    가격은 random walk + 간헐적 거래량 충격을 섞어 생성한다.
    """
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n_bars, freq="1min")

    returns = rng.normal(0, 0.0008, n_bars)
    # 몇 개 지점에 인위적 충격(거래량 급증 + 큰 가격변동)을 심어 이벤트 발생 확인
    shock_points = rng.choice(np.arange(50, n_bars - 20), size=max(3, n_bars // 100), replace=False)
    for sp in shock_points:
        returns[sp] += rng.choice([-1, 1]) * rng.uniform(0.004, 0.01)

    close = 2500 * np.exp(np.cumsum(returns))
    high = close * (1 + rng.uniform(0.0005, 0.002, n_bars))
    low = close * (1 - rng.uniform(0.0005, 0.002, n_bars))

    base_volume = rng.normal(10000, 1500, n_bars).clip(min=100)
    volume = base_volume.copy()
    for sp in shock_points:
        volume[sp] *= rng.uniform(3, 6)

    turnover = close * volume

    df = pd.DataFrame(
        {"close": close, "high": high, "low": low, "volume": volume, "turnover": turnover},
        index=idx,
    )
    return df


def generate_mock_daily_bars(n_days: int = 250, seed: int = 7) -> pd.DataFrame:
    """
    tir_reflection_backtest_v1.py(일봉 기준) 테스트용 mock 데이터.
    필수 컬럼: spot_close, futures_close, high, low, close, trade_amount
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-01-02", periods=n_days)

    returns = rng.normal(0, 0.008, n_days)
    spot_close = 2500 * np.exp(np.cumsum(returns))
    basis_noise = rng.normal(0, 1.5, n_days)  # 선물-현물 베이시스 노이즈
    futures_close = spot_close + basis_noise

    high = spot_close * (1 + rng.uniform(0.002, 0.01, n_days))
    low = spot_close * (1 - rng.uniform(0.002, 0.01, n_days))
    trade_amount = rng.normal(8_000_000, 1_000_000, n_days).clip(min=100_000)

    df = pd.DataFrame(
        {
            "spot_close": spot_close, "futures_close": futures_close,
            "high": high, "low": low, "close": spot_close,
            "trade_amount": trade_amount,
        },
        index=idx,
    )
    return df


# =====================================================================
# 7. 예측 원장 연결 (regime_alert 발생 시점만 "예측"으로 기록)
# =====================================================================

def record_cascade_predictions(fused: pd.DataFrame, df_intraday: pd.DataFrame,
                                ledger: "_pl.PredictionLedger", horizon: int = 30,
                                symbol: str = "KOSPI", source: str = "cockpit_cascade") -> int:
    """
    regime_alert(=TIR_발생_저항붕괴_상태전이)가 뜬 시점만 "예측"으로 원장에 남긴다.
    나머지 두 cascade(TIR_발생_저항낮음 / TIR_발생_저항큼_대기)는 방향을 걸지
    않는 "대기" 상태라 예측 원장에는 기록하지 않는다 — 실제로 방향을 건 신호만
    나중에 맞았는지 틀렸는지 검증 대상이 되어야 하기 때문이다.

    방향 판정: 경보 시점의 상태공간 속도 v_t 부호 (v_t>0 -> UP, 그 외 DOWN).
    price_at_prediction/평가용 가격은 fused의 x_t(상태공간 추정치)가 아니라
    df_intraday의 실제 종가(close)를 쓴다 — 나중에 evaluate()도 반드시 실제
    체결가 시계열로 검증해야 "예측 대 실제"가 왜곡되지 않는다.
    horizon: 몇 개 분봉 뒤 종가로 검증할지(기본 30분봉).
    """
    if not _LEDGER_AVAILABLE:
        raise RuntimeError("prediction_ledger 모듈을 찾을 수 없어 예측을 기록할 수 없습니다.")
    added = 0
    alerts = fused[fused["regime_alert"] == True]  # noqa: E712
    for ts, row in alerts.iterrows():
        if ts not in df_intraday.index:
            continue
        price = float(df_intraday.loc[ts, "close"])
        direction = "UP" if row.get("v_t", 0) > 0 else "DOWN"
        rec = _pl.PredictionRecord(
            timestamp=str(pd.Timestamp(ts)),
            model="cockpit_cascade",
            task="direction",
            horizon=horizon,
            regime=str(row.get("cascade_label", "UNKNOWN")),
            prediction=direction,
            p_up=1.0 if direction == "UP" else 0.0,
            predicted_return=None,
            price_at_prediction=price,
            source=source,
            symbol=symbol,
        )
        if ledger.add(rec):
            added += 1
    return added


def run_demo():
    print("=" * 70)
    print("KOSPI Cockpit Sensor Hub v1.1 - 더미 데이터 동작 테스트 (실제 TIR v1 연동)")
    print("=" * 70)

    df_daily = generate_mock_daily_bars(n_days=250)
    print(f"[mock 일봉] {len(df_daily)}개 ({df_daily.index[0].date()} ~ {df_daily.index[-1].date()})")

    hub = KospiCockpitSensorHub()
    print(f"[TIR 센서] 실제 tir_reflection_backtest_v1.py 모듈 사용 여부: "
          f"{hub.tir_sensor.using_real_module}")

    # TIR 신호가 실제로 발생한 날짜를 찾아, 그 날짜에 맞춰 분봉을 생성한다
    # (일봉/분봉 날짜 범위가 겹치지 않으면 merge_asof가 항상 과거의 값 하나만
    #  붙게 되어 cascade 데모 의미가 없어짐 - 실전 KRX 데이터에서는 당연히
    #  날짜가 연속되므로 이 문제가 없다).
    tir_daily = hub.tir_sensor.compute(df_daily)
    event_days = tir_daily.index[tir_daily["tir_event"].fillna(False)]
    if len(event_days) > 0:
        demo_date = event_days[-1]
        print(f"[demo] TIR 신호 발생일 {demo_date.date()}로 분봉을 생성해 cascade 확인")
    else:
        demo_date = df_daily.index[-1]
        print(f"[demo] TIR 신호 발생일이 없어 마지막 일봉({demo_date.date()})으로 분봉 생성")

    df_intraday = generate_mock_intraday_bars(n_bars=500, start=f"{demo_date.date()} 09:00")
    print(f"[mock 분봉] {len(df_intraday)}개 ({df_intraday.index[0]} ~ {df_intraday.index[-1]})")

    result = hub.run(df_intraday, df_daily)

    print(f"\n[결과 스키마] {list(result.columns)}")
    print(f"[전체 레코드 수] {len(result)}건 (앞부분 NaN은 rolling window 워밍업 구간)")

    alerts = result[result["regime_alert"] == True]  # noqa: E712
    print(f"\n[cascade_label 분포]")
    print(result["cascade_label"].value_counts())

    print(f"\n[TIR_발생_저항붕괴_상태전이 이벤트: {len(alerts)}건]")
    if len(alerts) > 0:
        cols_to_show = ["tir_event", "Q_z", "friction_score", "friction_spike",
                         "x_t", "v_t", "a_t", "cascade_label"]
        print(alerts[cols_to_show].head(10).to_string())
    else:
        print("(더미 데이터 특성상 이번 시드에서는 0건일 수 있음 - 정상)")

    # -------------------------------------------------------------
    # 예측 원장 연결 데모: 경보 -> 기록 -> (나중에 들어온 실제값과) 평가 -> 신뢰도 판정
    # -------------------------------------------------------------
    if _LEDGER_AVAILABLE:
        print("\n" + "=" * 70)
        print("[예측 원장] regime_alert 경보를 예측으로 기록 -> 평가 -> 신뢰도 판정")
        print("=" * 70)

        ledger = _pl.PredictionLedger()
        added = record_cascade_predictions(result, df_intraday, ledger, horizon=30)
        print(f"[기록] 신규 예측 {added}건 (전체 원장 {len(ledger.records)}건)")

        if added > 0:
            # 데모에서는 "나중에 들어온 실제값"을 같은 df_intraday의 close 시계열로
            # 대체 재현한다(합성 데이터라 미래 구간이 이미 존재하기 때문).
            # 실전에서는 다음 실행 시점에 새로 들어온 분봉으로 evaluate()를 호출하면 된다.
            ledger.evaluate(df_intraday["close"])
            evaluated = sum(1 for r in ledger.records if r.status == "EVALUATED")
            print(f"[평가] horizon(30분봉) 도달로 실제값이 붙은 예측: {evaluated}건 "
                  f"(나머지는 데이터 끝에 도달해 아직 PENDING)")

            summary = _pl.OOSAnalyzer().summarize(ledger)
            if not summary.empty:
                print("\n[신뢰도 판정] (VERIFIED 조건: n>=30 & Wilson 95% CI 하한>50%)")
                print(summary.to_string(index=False))
            else:
                print("(평가된 예측이 없어 신뢰도 판정 불가)")
        else:
            print("(이번 시드에서는 regime_alert가 없어 기록할 예측이 없음 - 정상)")

        print("\n※ 실전 운영: ledger.save('04_data/local/cockpit_ledger.jsonl')로 저장하고,\n"
              "   다음 실행에서 ledger.load(같은 경로, legacy_symbol='KOSPI')로 이어받으면\n"
              "   예측이 실행할 때마다 계속 누적·검증된다. 이 파일은 Git에 커밋하지 않는다\n"
              "   (SEC-402/403 — .gitignore에 04_data/local/ 패턴 추가 권장).")
    else:
        print("\n(prediction_ledger.py가 없어 예측 원장/신뢰도 검증 데모는 생략됨)")


if __name__ == "__main__":
    run_demo()
