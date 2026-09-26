"""
tir_reflection_backtest_v1.py
=======================================================================
TIR(전반사 비유) 기반 KOSPI 박스권 갇힘 가설 백테스트

[통합 메모] 2026-09-25: 여러 차례 업로드된 tir_reflection_backtest_v1 계열 파일
(초기 단순판, "(1)" 완전 중복본, "(2)" v1+v2 결합본)을 이 파일 하나로 정리함.
Part A/B의 로직 자체는 한 글자도 수정하지 않았고("v1 기준선은 절대 수정 안 함"
원칙 유지), 파일 중복만 제거한 것임. 튜닝된 임계값(box 0.98 / kappa 0.80 /
theta 0.20)은 이 파일이 아니라 별도 mock_market_data.py 하네스에서 오버라이드
해 검증하는 것으로 이미 합의되어 있으므로, 아래 기본값(0.95/0.65/0.35)은
그대로 둠.

구성:
  Part A. v1 (기준선, baseline) — 절대 수정하지 않음
    - kappa_proxy: 거래대금 폭증 대비 변동폭 축소 (하한 0으로 클리핑)
    - theta_proxy: 베이시스(선물-현물) 급변동
    - score = box(2) + kappa(1) + theta(1), score>=3 → tir_signal
    - 모든 임계값은 expanding quantile + shift(1)로 look-ahead 방지
    - 성공 판정: t+1~t+5 forward window 최고가 < 진입일 종가*1.015

  Part B. v2 (v1 위에 얹는 후처리 레이어, v1 결과는 변경하지 않음)
    - v_proxy = EMA(ROC_5) : "가격 변화율 프록시" (물리적 군속도 아님, 명칭 주의)
    - v_proxy도 expanding quantile + shift(1)로 Slow/Fast 판정 (동일 시간축 규칙)
    - TIR 충족/미충족 x Slow/Fast → TRAPPED / LEAK_WARNING / 일반 / BREAKOUT_후보 4분류
    - BREAKOUT_후보는 확정이 아니라 후보이며, 실제 돌파는 별도 forward 관측으로 판정
    - 반드시 baseline(TIR 비충족 전체)과 비교 + 표본수/신뢰구간 계산

주의: n1/n2(시가총액·채권금리 기반 임계각) 정밀 계산은 2차로 연기.
      1차는 is_upper_box(60일 고가 95%)로 대체.
=======================================================================
"""
import numpy as np
import pandas as pd


# =======================================================================
# [0] 데이터 로드 (기존 KRX 파이프라인 연동 지점 — 아직 미구현)
# =======================================================================
def load_market_data(start_date="2024-01-01", end_date="2026-01-01"):
    # TODO: 기존 KRX Open API 클라이언트로 코스피 지수/선물/거래대금/고저가 수집
    # 반환 df 필수 컬럼: ['date', 'spot_close', 'futures_close', 'high', 'low', 'close', 'trade_amount']
    # date는 오름차순 정렬, 인덱스는 RangeIndex 또는 date 기준 정렬된 인덱스여야
    # 아래 함수들의 shift/rolling 방향이 의도대로 동작함
    pass


# =======================================================================
# Part A. v1 — 기준선 (baseline, 고정)
# =======================================================================
def compute_tir_proxies(df: pd.DataFrame) -> pd.DataFrame:
    """theta_proxy, kappa_proxy 계산. kappa는 하한 0으로 클리핑."""
    df = df.copy()

    # theta_proxy: 베이시스(선물-현물) 변화율의 충격량
    df['basis'] = df['futures_close'] - df['spot_close']
    df['theta_proxy'] = df['basis'].diff()

    # kappa_proxy: 거래대금 폭증(Z-score, 하한 0) 대비 변동폭(Range %) 비율
    range_pct = (df['high'] - df['low']) / df['close']
    vol_mean = df['trade_amount'].rolling(20).mean()
    vol_std = df['trade_amount'].rolling(20).std()
    vol_z = (df['trade_amount'] - vol_mean) / (vol_std + 1e-9)
    vol_z = np.clip(vol_z, 0, None)  # 음수 "흡수도"는 정의상 불가 -> 0으로 클리핑
    df['kappa_proxy'] = vol_z / (range_pct + 1e-3)

    return df


def run_backtest_v1(df: pd.DataFrame, min_history: int = 60) -> pd.DataFrame:
    """v1 기준선: score>=3 고정 컷오프, t+1~t+5 forward 검증."""
    df = compute_tir_proxies(df)

    rolling_60h = df['close'].rolling(min_history).max()

    # 1. 박스권 상단 (가중치 2점) — n1/n2/θc 정밀 계산의 1차 대체 프록시
    c_box = (df['close'] >= rolling_60h * 0.95).astype(int) * 2

    # 2. kappa/theta 임계값: 과거 데이터만 사용 (expanding + shift(1))
    k_thresh = df['kappa_proxy'].expanding(min_periods=min_history).quantile(0.65).shift(1)
    t_thresh = df['theta_proxy'].expanding(min_periods=min_history).quantile(0.35).shift(1)

    c_kappa = (df['kappa_proxy'] >= k_thresh).astype(int)
    c_theta = (df['theta_proxy'] <= t_thresh).astype(int)

    df['tir_score'] = c_box + c_kappa + c_theta
    df['tir_signal'] = df['tir_score'] >= 3  # 고정 컷오프

    # 3. 미래 5거래일(t+1~t+5) 최고가 — concat+shift 방식 (인덱스 방향 오류 없음)
    fwd_max_high = pd.concat([df['high'].shift(-i) for i in range(1, 6)], axis=1).max(axis=1)
    df['fwd_max_high_5d'] = fwd_max_high
    df['bounded_success'] = fwd_max_high < df['close'] * 1.015

    valid_sig = df['tir_signal'] & df['bounded_success'].notna()
    sig_cnt = int(valid_sig.sum())
    win_rate = df.loc[valid_sig, 'bounded_success'].mean() if sig_cnt > 0 else float('nan')
    print(f"[v1] 시그널 발생: {sig_cnt}회 | 갇힘(TRAPPED) 성공률: "
          f"{win_rate:.2%}" if sig_cnt > 0 else f"[v1] 시그널 발생: {sig_cnt}회 | 성공률: N/A")

    return df



# -----------------------------------------------------------------------
# Shared Prediction Ledger 연결 계층 (Part A/B frozen baseline과 분리)
# -----------------------------------------------------------------------
try:
    import prediction_ledger as _pl
    _LEDGER_AVAILABLE = True
except ImportError:
    _LEDGER_AVAILABLE = False


def record_tir_predictions(df: pd.DataFrame, ledger, horizon: int = 5,
                           symbol: str = "KOSPI", source: str = "tir_v1") -> int:
    """tir_signal -> bounded_success 사건을 공용 PredictionLedger에 기록한다.

    TIR은 UP/DOWN 방향 예측이 아니므로 task='binary_event'를 사용한다.
    run_backtest_v1()의 계산 결과만 읽으며, baseline 계산부는 수정하지 않는다.
    """
    if not _LEDGER_AVAILABLE:
        raise RuntimeError("prediction_ledger 모듈을 찾을 수 없어 TIR 예측을 기록할 수 없습니다.")
    required = {"tir_signal", "bounded_success", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"TIR ledger adapter required columns missing: {sorted(missing)}")

    added = 0
    valid = df["tir_signal"].fillna(False).astype(bool) & df["bounded_success"].notna()
    for ts, row in df.loc[valid].iterrows():
        rec = _pl.PredictionRecord(
            timestamp=str(pd.Timestamp(ts)),
            model="tir_v1",
            task="binary_event",
            horizon=horizon,
            regime="TIR_SIGNAL",
            prediction="TRUE",
            p_up=None,
            predicted_return=None,
            price_at_prediction=float(row["close"]),
            source=source,
            symbol=symbol,
        )
        if ledger.add(rec):
            added += 1
    return added


def evaluate_tir_predictions(df: pd.DataFrame, ledger) -> None:
    """이미 계산된 bounded_success를 TIR ledger outcome으로 연결한다."""
    if not _LEDGER_AVAILABLE:
        raise RuntimeError("prediction_ledger 모듈을 찾을 수 없어 TIR 예측을 평가할 수 없습니다.")
    if "bounded_success" not in df.columns:
        raise ValueError("run_backtest_v1() 결과에 bounded_success가 없습니다.")
    ledger.evaluate_binary_events(df["bounded_success"], at_prediction_timestamp=True)


def summarize_tir_predictions(ledger) -> pd.DataFrame:
    """TIR binary-event OOS 요약을 반환한다."""
    if not _LEDGER_AVAILABLE:
        raise RuntimeError("prediction_ledger 모듈을 찾을 수 없습니다.")
    return _pl.OOSAnalyzer().summarize_binary_events(ledger)

# =======================================================================
# Part B. v2 — 속도(v_proxy) 후처리 레이어 (v1 결과를 바꾸지 않음)
# =======================================================================
def compute_v_proxy(df: pd.DataFrame, roc_window: int = 5, ema_alpha: float = 0.2) -> pd.DataFrame:
    """v_proxy = EMA(ROC_n). 물리적 군속도가 아닌 가격 변화율 프록시."""
    df = df.copy()
    roc = df['close'].pct_change(roc_window)
    df['v_proxy'] = roc.ewm(alpha=ema_alpha, adjust=False).mean()
    return df


def classify_v2_states(df: pd.DataFrame, min_history: int = 60, v_quantile: float = 0.70) -> pd.DataFrame:
    """
    TIR(v1) 충족여부 x v_proxy Slow/Fast -> 4상태 분류.
    v_thresh도 동일하게 expanding quantile + shift(1)로 look-ahead 방지.
    """
    df = compute_v_proxy(df)

    v_thresh = df['v_proxy'].abs().expanding(min_periods=min_history).quantile(v_quantile).shift(1)
    is_fast = df['v_proxy'].abs() >= v_thresh

    def _state(row_tir, row_fast):
        if pd.isna(row_fast):
            return np.nan
        if row_tir and not row_fast:
            return 'TRAPPED'
        if row_tir and row_fast:
            return 'LEAK_WARNING'
        if not row_tir and not row_fast:
            return '일반'
        return 'BREAKOUT_후보'  # TIR 미충족 + Fast. 확정 아님, 후보일 뿐.

    df['v2_state'] = [
        _state(tir, fast) for tir, fast in zip(df['tir_signal'], is_fast)
    ]
    return df


def compute_breakout_forward(df: pd.DataFrame, n: int = 5, breakout_threshold: float = 0.015) -> pd.DataFrame:
    """실제 돌파 여부(BREAKOUT_후보의 검증용): 향후 n일 최고가 > 기준가*(1+threshold)."""
    df = df.copy()
    fwd_max_high_n = pd.concat([df['high'].shift(-i) for i in range(1, n + 1)], axis=1).max(axis=1)
    df[f'fwd_max_high_{n}d'] = fwd_max_high_n
    df['breakout_occurred'] = fwd_max_high_n > df['close'] * (1 + breakout_threshold)
    return df


def _wilson_ci(successes: int, n: int, z: float = 1.96):
    """Wilson score 신뢰구간 (표본 적을 때 정규근사보다 안정적)."""
    if n == 0:
        return (float('nan'), float('nan'))
    p = successes / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = (z * np.sqrt((p * (1 - p) + z**2 / (4 * n)) / n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def compare_with_baseline(df: pd.DataFrame, outcome_col: str = 'breakout_occurred') -> pd.DataFrame:
    """
    4개 그룹(A.TRAPPED, B.LEAK_WARNING, C.TIR미충족+Fast, D.TIR미충족 전체)의
    outcome_col 발생률 + 표본수 + 95% 신뢰구간(Wilson)을 비교.
    """
    groups = {
        'A.TRAPPED': df['v2_state'] == 'TRAPPED',
        'B.LEAK_WARNING': df['v2_state'] == 'LEAK_WARNING',
        'C.TIR미충족+Fast (BREAKOUT_후보)': df['v2_state'] == 'BREAKOUT_후보',
        'D.TIR미충족 전체 (baseline)': ~df['tir_signal'].astype(bool),
    }

    rows = []
    for name, mask in groups.items():
        sub = df.loc[mask & df[outcome_col].notna(), outcome_col]
        n = len(sub)
        successes = int(sub.sum())
        rate = successes / n if n > 0 else float('nan')
        ci_lo, ci_hi = _wilson_ci(successes, n)
        rows.append({
            'group': name, 'n': n, 'rate': rate,
            'ci_95_low': ci_lo, 'ci_95_high': ci_hi,
        })

    result = pd.DataFrame(rows)
    print("\n[v2] 그룹별 발생률 비교 (95% Wilson 신뢰구간)")
    print(result.to_string(index=False))
    print("\n※ 표본수(n)가 작으면 신뢰구간이 넓어짐 — B의 구간이 D와 겹치면 "
          "LEAK_WARNING이 baseline과 통계적으로 구별되지 않는다는 뜻")
    return result


# =======================================================================
# 실행 예시
# =======================================================================
if __name__ == "__main__":
    print("뼈대 로드 완료. load_market_data()에 실제 KRX 연동 구현 후 아래 순서로 실행하세요:")
    print("""
    df = load_market_data()
    df = run_backtest_v1(df)              # Part A: v1 기준선
    df = classify_v2_states(df)           # Part B: 4상태 분류
    df = compute_breakout_forward(df)     # Part B: 실제 돌파 여부 관측
    compare_with_baseline(df)             # Part B: baseline 대비 통계 비교
    """)
