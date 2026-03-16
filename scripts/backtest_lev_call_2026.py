"""2026년 3월 반등장 백테스트 시뮬레이션 - 레버리지+콜 옵션 전략 검증.

2026년 3월 코스피 -12% 급락 이후 반등 시나리오를 GBM으로 생성하고
레버리지 ETF(122630) + 콜 옵션 복합 전략의 성과를 검증합니다.

시나리오 (6 Phase)
------------------
| Phase | 일수 | Drift | Vol  | 설명                          |
|-------|------|-------|------|-------------------------------|
|   1   |  10  |  0%   |  15% | 코스피 5,600 횡보               |
|   2   |   8  | -70%  |  40% | 5,400 조정 (진입 트리거)         |
|   3   |   5  | +120% |  35% | 바닥 형성, RSI<30 골든크로스     |
|   4   |  15  | +50%  |  25% | 5,800 회복 랠리               |
|   5   |   5  | -20%  |  30% | 중간 조정                     |
|   6   |  10  | +60%  |  20% | 6,000 돌파 (청산)              |

비교 지표
---------
- 레버리지+콜 전략  vs  ETF Buy & Hold  vs  코스피 Buy & Hold
- 포트폴리오 분해 (ETF P&L + 옵션 P&L)
- 마진 효과, 이벤트 로그

실행::

    python scripts/backtest_lev_call_2026.py

의존성: backtrader, pandas, numpy (requirements.txt 참조)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import logging
import math
from typing import List, Tuple

import numpy as np
import pandas as pd

logging.getLogger("backtrader").setLevel(logging.CRITICAL)
logging.basicConfig(level=logging.WARNING, format="%(message)s")

# ──────────────────────────────────────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────────────────────────────────────

# KODEX 200 레버리지(122630) 2026-03 근사 시작가 (원)
# KOSPI200 약 280pt 기준 레버리지 ETF ~ 15,000원
_ETF_START_PRICE: float = 15_000.0
_INITIAL_CASH: float = 10_000_000.0
_KRX_COMMISSION: float = 0.00015

# 코스피 시뮬레이션 파라미터
_KOSPI_START: float = 5_600.0
_CALL_STRIKE: float = 5_500.0
_ENTRY_KOSPI: float = 5_400.0
_EXIT_KOSPI: float = 6_000.0

# ──────────────────────────────────────────────────────────────────────────────
# 6 Phase 레짐 정의
# ──────────────────────────────────────────────────────────────────────────────
# (일수, 연율 drift, 연율 vol, 설명)
_REGIMES = [
    (10,  0.00, 0.15, "Phase 1: 코스피 5,600 횡보"),
    (8,  -0.70, 0.40, "Phase 2: 5,400 조정 (진입 트리거)"),
    (5,  +1.20, 0.35, "Phase 3: 바닥 형성, 골든크로스"),
    (15, +0.50, 0.25, "Phase 4: 5,800 회복 랠리"),
    (5,  -0.20, 0.30, "Phase 5: 중간 조정"),
    (10, +0.60, 0.20, "Phase 6: 6,000 돌파 (청산)"),
]

_W = 72
_SEP = "=" * _W
_SEP2 = "-" * _W


# ──────────────────────────────────────────────────────────────────────────────
# 1. OHLCV 데이터 생성
# ──────────────────────────────────────────────────────────────────────────────


def _generate_etf_ohlcv(seed: int = 2026) -> Tuple[pd.DataFrame, List[float]]:
    """2026년 3월 반등 시나리오 ETF 일봉 OHLCV를 생성합니다.

    레버리지 ETF(2X) 특성: 코스피200 일별 수익률의 2배를 추적하므로
    코스피 시뮬레이션 수익률에 2를 곱합니다.

    Args:
        seed: 재현성을 위한 난수 시드.

    Returns:
        (OHLCV DataFrame, 일별 ETF 수익률 리스트) 튜플.
    """
    rng = np.random.default_rng(seed)
    total_bars = sum(r[0] for r in _REGIMES)
    dates = pd.bdate_range(start="2026-03-02", periods=total_bars)

    close_prices: List[float] = []
    daily_returns: List[float] = []
    prev = _ETF_START_PRICE

    for n_days, annual_drift, annual_vol, _ in _REGIMES:
        dt = 1.0 / 252
        # 레버리지 ETF: drift × 2, vol × 2 (2X 레버리지)
        lev_drift = annual_drift * 2.0
        lev_vol = annual_vol * 2.0
        mu = (lev_drift - 0.5 * lev_vol**2) * dt
        sigma = lev_vol * dt**0.5
        for _ in range(n_days):
            shock = float(rng.standard_normal())
            log_ret = mu + sigma * shock
            new_price = prev * math.exp(log_ret)
            simple_ret = new_price / prev - 1.0
            daily_returns.append(simple_ret)
            close_prices.append(new_price)
            prev = new_price

    opens, highs, lows, volumes = [], [], [], []
    for i, (close, ret) in enumerate(zip(close_prices, daily_returns)):
        prev_close = close_prices[i - 1] if i > 0 else _ETF_START_PRICE
        gap = float(rng.uniform(-0.006, 0.006))
        open_p = prev_close * (1.0 + gap)
        intraday = abs(ret) * float(rng.uniform(0.5, 2.0))
        high_p = max(open_p, close) * (1.0 + intraday * 0.35)
        low_p = min(open_p, close) * (1.0 - intraday * 0.35)
        opens.append(max(round(open_p), 1))
        highs.append(max(round(high_p), 1))
        lows.append(max(round(low_p), 1))
        volumes.append(int(rng.integers(1_000_000, 8_000_000)))

    df = pd.DataFrame(
        {
            "open": [float(v) for v in opens],
            "high": [float(v) for v in highs],
            "low": [float(v) for v in lows],
            "close": [float(round(c, 0)) for c in close_prices],
            "volume": [float(v) for v in volumes],
        },
        index=dates[:total_bars],
    )
    df.index.name = "date"
    return df, daily_returns


# ──────────────────────────────────────────────────────────────────────────────
# 2. Buy & Hold 계산
# ──────────────────────────────────────────────────────────────────────────────


def _calc_etf_buy_and_hold(df: pd.DataFrame, initial_cash: float) -> Tuple[float, float, float]:
    """ETF 단순 매수보유 성과를 계산합니다."""
    first_close = df["close"].iloc[0]
    shares = int(initial_cash // first_close)
    cash_remaining = initial_cash - shares * first_close
    final_value = shares * df["close"].iloc[-1] + cash_remaining

    portfolio_values = shares * df["close"].values + cash_remaining
    peak = np.maximum.accumulate(portfolio_values)
    drawdowns = (portfolio_values - peak) / peak
    mdd = float(drawdowns.min()) * 100

    return final_value, final_value - initial_cash, mdd


def _calc_kospi_buy_and_hold(initial_cash: float, etf_df: pd.DataFrame) -> Tuple[float, float]:
    """코스피 지수 Buy & Hold를 ETF 수익률 역산으로 근사합니다."""
    etf_return = etf_df["close"].iloc[-1] / etf_df["close"].iloc[0] - 1.0
    # 2X 레버리지 역산으로 코스피 수익률 근사
    kospi_return = etf_return / 2.0
    final_value = initial_cash * (1.0 + kospi_return)
    return final_value, final_value - initial_cash


# ──────────────────────────────────────────────────────────────────────────────
# 3. 레버리지+콜 전략 실행
# ──────────────────────────────────────────────────────────────────────────────


def _run_lev_call(df: pd.DataFrame, initial_cash: float):
    """레버리지+콜 백테스트를 실행합니다."""
    from config.settings import Settings
    from backtest.runner import run_lev_call_backtest

    settings = Settings.__new__(Settings)
    # 수동으로 필드 설정 (load_dotenv 없이)
    object.__setattr__(settings, "lev_call_enabled", True)
    object.__setattr__(settings, "lev_etf_symbol", "122630")
    object.__setattr__(settings, "lev_etf_alloc", 0.70)
    object.__setattr__(settings, "call_option_alloc", 0.30)
    object.__setattr__(settings, "call_strike", _CALL_STRIKE)
    object.__setattr__(settings, "call_expiry_months", 2)
    object.__setattr__(settings, "entry_kospi_level", _ENTRY_KOSPI)
    object.__setattr__(settings, "exit_kospi_level", _EXIT_KOSPI)
    object.__setattr__(settings, "take_profit_pct", 0.20)
    object.__setattr__(settings, "take_profit_sell_ratio", 0.50)
    object.__setattr__(settings, "margin_leverage", 3.0)
    object.__setattr__(settings, "vkospi_option_add_threshold", 30.0)
    object.__setattr__(settings, "rsi_period", 14)
    object.__setattr__(settings, "rsi_oversold", 30.0)
    object.__setattr__(settings, "rsi_overbought", 70.0)
    object.__setattr__(settings, "ma_short", 5)
    object.__setattr__(settings, "ma_long", 20)

    return run_lev_call_backtest(df, settings, initial_cash)


# ──────────────────────────────────────────────────────────────────────────────
# 4. 출력 헬퍼
# ──────────────────────────────────────────────────────────────────────────────


def _pct_str(value: float, base: float) -> str:
    return f"{(value / base - 1) * 100:+.2f}%"


def _section(title: str) -> None:
    print(f"\n{_SEP}\n  {title}\n{_SEP}")


# ──────────────────────────────────────────────────────────────────────────────
# 5. 메인
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    print(_SEP)
    print("  KimBeggar -- 2026년 3월 반등장 레버리지+콜 옵션 전략 시뮬레이션")
    print(_SEP)

    # ── 1. 데이터 생성 ──────────────────────────────────────────────────────
    print("\n[1/4] 2026년 3월 시나리오 ETF OHLCV 데이터 생성...")
    df, daily_returns = _generate_etf_ohlcv(seed=2026)

    start_price = df["close"].iloc[0]
    end_price = df["close"].iloc[-1]
    etf_total_return = end_price / start_price - 1.0
    kospi_approx_return = etf_total_return / 2.0

    print(f"  기간     : {df.index[0].date()} ~ {df.index[-1].date()}  ({len(df)} 거래일)")
    print(f"  ETF 시작가: {start_price:>10,.0f} 원")
    print(f"  ETF 종료가: {end_price:>10,.0f} 원  ({etf_total_return:+.2%})")
    print(f"  코스피 추정 수익률: {kospi_approx_return:+.2%}")
    print()
    print(f"  {'Phase':<7}  {'기간':<25}  {'설명'}")
    print(f"  {_SEP2[2:]}")
    idx = 0
    for i, (n, drift, vol, desc) in enumerate(_REGIMES, 1):
        s = df.index[idx].strftime("%Y-%m-%d")
        e = df.index[min(idx + n - 1, len(df) - 1)].strftime("%Y-%m-%d")
        print(f"  Phase {i}  {s} ~ {e}  {desc}")
        idx += n

    # ── 2. Buy & Hold 계산 ─────────────────────────────────────────────────
    print("\n[2/4] 베이스라인 계산...")
    etf_bh_final, etf_bh_pnl, etf_bh_mdd = _calc_etf_buy_and_hold(df, _INITIAL_CASH)
    kospi_bh_final, kospi_bh_pnl = _calc_kospi_buy_and_hold(_INITIAL_CASH, df)
    print(f"  ETF Buy & Hold  : {etf_bh_final:>12,.0f} 원  ({_pct_str(etf_bh_final, _INITIAL_CASH)})  MDD={etf_bh_mdd:.2f}%")
    print(f"  코스피 Buy & Hold: {kospi_bh_final:>12,.0f} 원  ({_pct_str(kospi_bh_final, _INITIAL_CASH)})")

    # ── 3. 레버리지+콜 전략 실행 ─────────────────────────────────────────────
    print("\n[3/4] 레버리지 ETF + 콜 옵션 전략 실행...")
    result = _run_lev_call(df, _INITIAL_CASH)
    print(f"  최종 평가액: {result.final_value:>12,.0f} 원  ({result.pnl_pct:+.2f}%)")

    # ── 4. 결과 비교표 ─────────────────────────────────────────────────────
    _section("백테스트 결과 비교")
    W1, W2, W3, W4 = 22, 15, 15, 18
    print(
        f"\n  {'항목':<{W1}}  {'코스피 B&H':>{W2}}  {'ETF B&H':>{W3}}  {'레버리지+콜':>{W4}}"
    )
    print(f"  {_SEP2[2:]}")

    def row(label: str, v1: str, v2: str, v3: str) -> None:
        print(f"  {label:<{W1}}  {v1:>{W2}}  {v2:>{W3}}  {v3:>{W4}}")

    row("초기 투자금 (원)",
        f"{_INITIAL_CASH:,.0f}",
        f"{_INITIAL_CASH:,.0f}",
        f"{_INITIAL_CASH:,.0f}")
    row("최종 평가액 (원)",
        f"{kospi_bh_final:,.0f}",
        f"{etf_bh_final:,.0f}",
        f"{result.final_value:,.0f}")
    row("손익 (원)",
        f"{kospi_bh_pnl:+,.0f}",
        f"{etf_bh_pnl:+,.0f}",
        f"{result.pnl:+,.0f}")
    row("수익률",
        _pct_str(kospi_bh_final, _INITIAL_CASH),
        _pct_str(etf_bh_final, _INITIAL_CASH),
        f"{result.pnl_pct:+.2f}%")
    row("최대낙폭 (MDD)",
        "N/A",
        f"{etf_bh_mdd:.2f}%",
        f"{result.max_drawdown_pct:.2f}%")
    row("거래 횟수",
        "1회 (보유)",
        "1회 (보유)",
        f"{result.total_trades}회")
    row("승률",
        "N/A",
        "N/A",
        f"{result.win_rate:.1%}" if result.win_rate is not None else "N/A")
    row("실효 레버리지",
        "1.0x",
        "2.0x (ETF)",
        f"{result.effective_leverage:.1f}x")
    row("부분 청산 횟수",
        "0",
        "0",
        f"{result.partial_exits}")
    row("옵션 추가 매수",
        "0",
        "0",
        f"{result.option_adds}")

    # ── 포트폴리오 분해 ──────────────────────────────────────────────────────
    _section("포트폴리오 손익 분해")
    print()
    print(f"  ETF 레그 손익  : {result.etf_pnl:>+12,.0f} 원")
    print(f"  옵션 레그 손익 : {result.option_pnl:>+12,.0f} 원")
    print(f"  합계           : {result.pnl:>+12,.0f} 원")

    # ── 마진 효과 분석 ──────────────────────────────────────────────────────
    no_margin_return = (etf_bh_final - _INITIAL_CASH) / _INITIAL_CASH
    margin_addon = result.pnl_pct / 100.0 - no_margin_return if no_margin_return != 0 else 0.0
    print()
    print(f"  마진 없는 경우 (ETF B&H): {no_margin_return:+.2%}")
    print(f"  마진 3x 효과             : {margin_addon:+.2%} 추가")
    print(f"  최종 전략 수익률         : {result.pnl_pct / 100.0:+.2%}")

    # ── 이벤트 로그 ─────────────────────────────────────────────────────────
    _section("전략 이벤트 로그")
    if result.events:
        print()
        print(f"  {'날짜':<12}  {'이벤트':<14}  {'ETF가':>8}  {'코스피':>8}  {'포트폴리오':>12}  {'상세'}")
        print(f"  {_SEP2[2:]}")
        for ev in result.events:
            print(
                f"  {ev.date:<12}  [{ev.event_type:<12}]"
                f"  {ev.etf_price:>8,.0f}"
                f"  {ev.kospi_level:>8,.0f}"
                f"  {ev.portfolio_value:>12,.0f}"
                f"  {ev.detail}"
            )
    else:
        print("\n  ※ 이벤트 없음 - 진입 조건 미충족 (데이터 부족 가능성)")

    # ── 시뮬레이션 예상치 검증 ──────────────────────────────────────────────
    _section("이론적 예상 수익률 vs 실제 결과")
    print()
    print("  [이론 추정 (1,000만원 기준)]")
    print("  코스피 +7.1% 반등 가정 (5,600 → 6,000):")
    kospi_return_theory = (_EXIT_KOSPI - _KOSPI_START) / _KOSPI_START
    etf_return_theory = kospi_return_theory * 2.0
    strategy_theory = (
        etf_return_theory * 0.70 * 3.0  # ETF (70% × 마진3X)
        + 0.20 * 0.30  # 옵션 +20% (보수적 추정) × 30%
    )
    print(f"    ETF (2X) 수익률       : {etf_return_theory:+.2%}")
    print(f"    ETF × 70% × 마진3X   : {etf_return_theory * 0.70 * 3.0:+.2%}")
    print(f"    옵션 +20% × 30%       : {0.20 * 0.30:+.2%}")
    print(f"    이론 합계             : {strategy_theory:+.2%}  (~1,000만 → {_INITIAL_CASH * (1 + strategy_theory):,.0f} 원)")
    print()
    print(f"  [실제 백테스트 결과]")
    print(f"    최종 수익률          : {result.pnl_pct:+.2f}%")
    print(f"    최종 평가액          : {result.final_value:,.0f} 원")

    # ── 결론 ────────────────────────────────────────────────────────────────
    _section("시뮬레이션 결론")
    print()
    etf_outperform = result.final_value - etf_bh_final
    if result.pnl > 0:
        print(
            f"  [수익 달성]  레버리지+콜 전략이 초기 대비 "
            f"{result.pnl:+,.0f} 원 ({result.pnl_pct:+.2f}%) 수익을 냈습니다."
        )
    else:
        print(
            f"  [손실]  이 시나리오에서 전략이 "
            f"{result.pnl:,.0f} 원 ({result.pnl_pct:.2f}%) 손실을 냈습니다."
        )

    if etf_outperform > 0:
        print(
            f"  [초과 성과]  ETF B&H 대비 {etf_outperform:+,.0f} 원 더 수익을 냈습니다."
        )
    else:
        print(
            f"  [열위]  ETF B&H 대비 {-etf_outperform:,.0f} 원 낮았습니다."
        )

    print()
    print("  [주의사항]")
    print("  - 옵션 가격은 Black-Scholes 모델로 합성된 가상값입니다.")
    print("  - 마진 레버리지는 이자비용/마진콜 리스크를 반영하지 않습니다.")
    print("  - 실제 KODEX 200 레버리지 ETF는 일별 복리 효과로 장기 보유 시 괴리가 발생합니다.")
    print("  - 이 시뮬레이션은 교육/연구 목적이며 실제 투자 권유가 아닙니다.")
    print(f"\n{_SEP}\n")


if __name__ == "__main__":
    main()
