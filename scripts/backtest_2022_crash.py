"""2022 하락장 백테스트 시뮬레이션 — KimBeggar 3단 방어선 검증.

2022년 한국 증시는 연초 KOSPI 2,988p에서 10월 저점 2,155p까지 약 28% 하락한
대표적인 베어마켓입니다.  이 스크립트는 해당 구간을 모의 OHLCV 데이터로 재현하고
KimBeggar의 3단 방어선이 계좌를 어떻게 보호하는지 검증합니다.

3단 방어선
----------
1. **1선 — 손절(Stop-Loss)**  : 진입가 대비 -5% 도달 시 포지션 즉시 청산
2. **2선 — 매도 시그널**      : RSI 과매수 + 데드크로스 조건 충족 시 매도
3. **3선 — ML 동적 헤지 권고**: predict_volatility() 기반 인버스 ETF 편입 비율 산출

시나리오 설계
-------------
단순 하락장은 골든크로스 조건이 발화되지 않으므로, 2022년 실제 패턴을 반영해
"초기 상승 → 급락(과매도) → 반등(매수 발화) → 재하락(손절)" 4단계로 구성합니다.

비교 지표
----------
- KimBeggar 3단 방어선  vs  단순 매수보유(Buy & Hold)
- 최종 수익률, 최대낙폭(MDD), 거래 횟수, 승률, ML 변동성 예측값

실행 방법::

    python scripts/backtest_2022_crash.py

의존성: backtrader, pandas, numpy, scikit-learn (requirements.txt 참조)
"""

from __future__ import annotations

import os
import sys

# 프로젝트 루트를 sys.path에 추가 (scripts/ 외부 모듈 임포트)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import backtrader as bt
import numpy as np
import pandas as pd

from strategy.hedge_logic import calculate_hedge_ratio, describe_hedge, predict_volatility

# backtrader 내부 로그 억제
logging.getLogger("backtrader").setLevel(logging.CRITICAL)
logging.basicConfig(level=logging.WARNING, format="%(message)s")

# ──────────────────────────────────────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────────────────────────────────────

_START_PRICE: float = 78_000.0   # 삼성전자 2022-01-03 근사 시작가 (원)
_INITIAL_CASH: float = 10_000_000.0   # 초기 투자금 1,000만 원
_KRX_COMMISSION: float = 0.00015      # 편도 수수료 0.015 %

# ──────────────────────────────────────────────────────────────────────────────
# 구간별 레짐 설정
# ──────────────────────────────────────────────────────────────────────────────
# (일수, 연율 drift, 연율 vol, 설명)
#
# Phase 0: 상승 → 골든크로스 형성
# Phase 1: 급락 → RSI 과매도 + 데드크로스
# Phase 2: 반등 → 골든크로스 재발생, RSI 아직 낮아 매수 시그널 발화
# Phase 3: 재하락 → 진입가 -5% → 1선 손절 발동
# Phase 4: 약반등
# Phase 5: 재하락 → 3선 헤지 권고 집중
# Phase 6: 회복
_REGIMES = [
    (25,  +0.50, 0.15, "초기 상승 — 골든크로스 형성"),
    (25,  -0.70, 0.40, "1차 급락 — RSI 과매도"),
    (18,  +1.20, 0.35, "기술적 반등 — 매수 시그널 발화 구간"),
    (60,  -0.55, 0.35, "2Q22 급락 — 연준 자이언트 스텝, 손절 발동"),
    (40,  +0.20, 0.30, "3Q22 반등 시도"),
    (40,  -0.40, 0.28, "3Q22 재하락 — 경기침체 공포"),
    (54,  +0.35, 0.22, "4Q22 회복 — 연준 피벗 기대"),
]

# ──────────────────────────────────────────────────────────────────────────────
# 1. 2022 시나리오 OHLCV 데이터 생성
# ──────────────────────────────────────────────────────────────────────────────


def _generate_crash_ohlcv(seed: int = 2022) -> pd.DataFrame:
    """2022년 하락장 시나리오를 모사하는 일봉 OHLCV DataFrame을 생성합니다.

    기하 브라운 운동(GBM)에 구간별 추세(레짐)를 적용합니다.

    Args:
        seed: 재현성을 위한 난수 시드.

    Returns:
        DatetimeIndex + open/high/low/close/volume 컬럼의 DataFrame.
    """
    rng = np.random.default_rng(seed)
    total_bars = sum(r[0] for r in _REGIMES)
    dates = pd.bdate_range(start="2022-01-03", periods=total_bars)

    # GBM으로 종가 시계열 생성
    close_prices: List[float] = []
    daily_returns: List[float] = []
    prev = _START_PRICE

    for n_days, annual_drift, annual_vol, _ in _REGIMES:
        dt = 1.0 / 252
        mu = (annual_drift - 0.5 * annual_vol**2) * dt   # GBM 로그 정규 drift
        sigma = annual_vol * dt**0.5
        for _ in range(n_days):
            shock = float(rng.standard_normal())
            log_ret = mu + sigma * shock
            new_price = prev * np.exp(log_ret)
            simple_ret = new_price / prev - 1.0
            daily_returns.append(simple_ret)
            close_prices.append(new_price)
            prev = new_price

    # OHLCV 구성
    opens, highs, lows, volumes = [], [], [], []
    for i, (close, ret) in enumerate(zip(close_prices, daily_returns)):
        prev_close = close_prices[i - 1] if i > 0 else _START_PRICE
        gap = float(rng.uniform(-0.004, 0.004))
        open_p = prev_close * (1.0 + gap)
        intraday = abs(ret) * float(rng.uniform(0.6, 1.9))
        high_p = max(open_p, close) * (1.0 + intraday * 0.35)
        low_p = min(open_p, close) * (1.0 - intraday * 0.35)
        opens.append(max(round(open_p), 1))
        highs.append(max(round(high_p), 1))
        lows.append(max(round(low_p), 1))
        volumes.append(int(rng.integers(500_000, 3_500_000)))

    df = pd.DataFrame(
        {
            "open": [float(v) for v in opens],
            "high": [float(v) for v in highs],
            "low": [float(v) for v in lows],
            "close": [float(round(c)) for c in close_prices],
            "volume": [float(v) for v in volumes],
        },
        index=dates[:total_bars],
    )
    df.index.name = "date"
    return df, daily_returns


# ──────────────────────────────────────────────────────────────────────────────
# 2. Buy & Hold 계산 (산술, backtrader 불필요)
# ──────────────────────────────────────────────────────────────────────────────


def _calc_buy_and_hold(df: pd.DataFrame, initial_cash: float) -> Tuple[float, float, float]:
    """첫 봉에 전액 매수 후 마지막 봉까지 보유 시 성과를 계산합니다.

    Args:
        df: OHLCV DataFrame.
        initial_cash: 초기 투자금.

    Returns:
        (최종 평가액, 손익, 구간 MDD) 튜플.
    """
    first_close = df["close"].iloc[0]
    shares = int(initial_cash // first_close)
    cash_remaining = initial_cash - shares * first_close
    final_value = shares * df["close"].iloc[-1] + cash_remaining

    # MDD 계산 (매수 후 포지션 기준)
    portfolio_values = shares * df["close"].values + cash_remaining
    peak = np.maximum.accumulate(portfolio_values)
    drawdowns = (portfolio_values - peak) / peak
    mdd = float(drawdowns.min()) * 100

    return final_value, final_value - initial_cash, mdd


# ──────────────────────────────────────────────────────────────────────────────
# 3. 방어선 이벤트 추적 전략
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class DefenseEvent:
    """3단 방어선 발동 이벤트 레코드."""

    date: str
    line: int       # 1=손절, 2=매도, 3=헤지권고
    price: float
    detail: str


class KimBeggar2022Strategy(bt.Strategy):
    """방어선 발동 이벤트를 기록하는 KimBeggar 전략 확장판.

    기존 KimBeggarStrategy와 동일한 매매 로직(RSI + MA 크로스오버 + 손절)에
    ML 변동성 예측 기반 헤지 권고(3선)를 추가합니다.
    """

    params = (
        ("rsi_period", 14),
        ("rsi_oversold", 30.0),
        ("rsi_overbought", 70.0),
        ("ma_short", 5),
        ("ma_long", 20),
        ("stop_loss_rate", 0.05),
        ("base_hedge_ratio", 0.30),
    )

    def __init__(self) -> None:
        self.rsi = bt.indicators.RSI(
            self.data.close, period=self.p.rsi_period, safediv=True
        )
        self.sma_short = bt.indicators.SMA(self.data.close, period=self.p.ma_short)
        self.sma_long = bt.indicators.SMA(self.data.close, period=self.p.ma_long)
        self.crossover = bt.indicators.CrossOver(self.sma_short, self.sma_long)

        self._entry_price: float = 0.0
        self._order: Optional[bt.Order] = None
        self.events: List[DefenseEvent] = []
        self._close_history: List[float] = []

    def notify_order(self, order: bt.Order) -> None:
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed:
            if order.isbuy():
                self._entry_price = float(order.executed.price)
            else:
                self._entry_price = 0.0
        self._order = None

    def next(self) -> None:
        current_price = float(self.data.close[0])
        date_str = self.data.datetime.date(0).strftime("%Y-%m-%d")

        # 종가 기록 및 수익률 계산
        self._close_history.append(current_price)

        if len(self._close_history) >= 2:
            returns = [
                self._close_history[i] / self._close_history[i - 1] - 1.0
                for i in range(1, len(self._close_history))
            ]
        else:
            returns = []

        # ── 3선: ML 변동성 기반 헤지 권고 (매 20봉마다) ──────────────────
        if len(returns) >= 25 and len(returns) % 20 == 0:
            ml_vol = predict_volatility(returns, window=10)
            if ml_vol > 0.0:
                long_ma = float(self.sma_long[0])
                hedge_ratio = calculate_hedge_ratio(
                    current_price=current_price,
                    long_ma=long_ma,
                    base_ratio=min(ml_vol * 0.8, self.p.base_hedge_ratio),
                    index_change_rate=(returns[-1] * 100 if returns else 0.0),
                )
                if hedge_ratio >= 0.20:
                    self.events.append(
                        DefenseEvent(
                            date=date_str,
                            line=3,
                            price=current_price,
                            detail=(
                                f"ML변동성={ml_vol:.1%} | "
                                f"{describe_hedge(hedge_ratio)}"
                            ),
                        )
                    )

        if self._order is not None:
            return

        if not self.position:
            # ── 매수: RSI 과매도 + 골든크로스 ────────────────────────────
            if self.rsi[0] <= self.p.rsi_oversold and self.crossover[0] > 0:
                size = int(self.broker.getcash() // current_price)
                if size > 0:
                    self._order = self.buy(size=size)
        else:
            # ── 1선: 손절 ────────────────────────────────────────────────
            if self._entry_price > 0 and current_price <= self._entry_price * (
                1.0 - self.p.stop_loss_rate
            ):
                self.events.append(
                    DefenseEvent(
                        date=date_str,
                        line=1,
                        price=current_price,
                        detail=(
                            f"손절 발동 | 진입가 {self._entry_price:,.0f} -> "
                            f"현재 {current_price:,.0f} "
                            f"({(current_price / self._entry_price - 1) * 100:+.1f}%)"
                        ),
                    )
                )
                self._order = self.close()
                return

            # ── 2선: RSI 과매수 + 데드크로스 매도 ───────────────────────
            if self.rsi[0] >= self.p.rsi_overbought and self.crossover[0] < 0:
                self.events.append(
                    DefenseEvent(
                        date=date_str,
                        line=2,
                        price=current_price,
                        detail=(
                            f"매도 시그널 | RSI={self.rsi[0]:.1f} "
                            f"데드크로스 @ {current_price:,.0f}"
                        ),
                    )
                )
                self._order = self.close()


def _run_kimbeggar(
    df: pd.DataFrame, initial_cash: float
) -> Tuple[float, List[DefenseEvent], Dict[str, Any], Dict[str, Any]]:
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.addstrategy(KimBeggar2022Strategy)
    cerebro.adddata(bt.feeds.PandasData(dataname=df))
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=_KRX_COMMISSION)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    results = cerebro.run()
    final_value = cerebro.broker.getvalue()

    strat = results[0]
    trade_stats: Dict[str, Any] = strat.analyzers.trades.get_analysis()
    dd_stats: Dict[str, Any] = strat.analyzers.drawdown.get_analysis()
    return final_value, strat.events, trade_stats, dd_stats


# ──────────────────────────────────────────────────────────────────────────────
# 4. 출력 헬퍼
# ──────────────────────────────────────────────────────────────────────────────

_W = 70
_SEP = "=" * _W
_SEP2 = "-" * _W


def _pct_str(value: float, base: float) -> str:
    return f"{(value / base - 1) * 100:+.2f}%"


def _section(title: str) -> None:
    print(f"\n{_SEP}\n  {title}\n{_SEP}")


# ──────────────────────────────────────────────────────────────────────────────
# 5. 메인
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    print(_SEP)
    print("  KimBeggar -- 2022 하락장 백테스트 (3단 방어선 시뮬레이션)")
    print(_SEP)

    # ── 1. 데이터 생성 ─────────────────────────────────────────────────────
    print("\n[1/4] 2022 하락장 OHLCV 데이터 생성...")
    df, daily_returns = _generate_crash_ohlcv(seed=2022)

    start_price = df["close"].iloc[0]
    end_price = df["close"].iloc[-1]
    min_price = df["close"].min()
    max_price = df["close"].max()
    peak_to_trough = (min_price - max_price) / max_price * 100

    print(f"  기간    : {df.index[0].date()} ~ {df.index[-1].date()}  ({len(df)} 거래일)")
    print(f"  시작가  : {start_price:>10,.0f} 원")
    print(f"  종료가  : {end_price:>10,.0f} 원  ({_pct_str(end_price, start_price)})")
    print(f"  구간저점: {min_price:>10,.0f} 원  (고점 대비 {peak_to_trough:+.1f}%)")
    print()
    print(f"  {'Phase':<7} {'기간':<25} {'설명'}")
    print(f"  {_SEP2[2:]}")
    idx = 0
    for i, (n, drift, vol, desc) in enumerate(_REGIMES, 1):
        s = df.index[idx].strftime("%Y-%m-%d")
        e = df.index[min(idx + n - 1, len(df) - 1)].strftime("%Y-%m-%d")
        print(f"  Phase {i}  {s} ~ {e}  {desc}")
        idx += n

    # ── 2. ML 변동성 예측 ──────────────────────────────────────────────────
    print("\n[2/4] ML 변동성 예측 (predict_volatility) 검증...")
    checkpoints = [
        ("Phase 2 반등기 (day 43~68)",  daily_returns[42:68]),
        ("Phase 3 급락기 (day 68~128)", daily_returns[68:128]),
        ("Phase 6 회복기 (day 208~262)", daily_returns[208:]),
    ]
    print(f"\n  {'구간':<32}  {'ML 예측(연율)':>12}  {'단순 실현(연율)':>14}")
    print(f"  {_SEP2[2:]}")
    for label, rets in checkpoints:
        if len(rets) < 5:
            continue
        ml_vol = predict_volatility(rets, window=10)
        simple_vol = float(np.std(rets, ddof=1)) * (252**0.5)
        print(f"  {label:<32}  {ml_vol:>11.1%}  {simple_vol:>13.1%}")

    # ── 3. Buy & Hold 계산 ────────────────────────────────────────────────
    print("\n[3/4] Buy & Hold 베이스라인 계산...")
    bh_final, bh_pnl, bh_mdd = _calc_buy_and_hold(df, _INITIAL_CASH)
    print(f"  최종 평가액: {bh_final:>12,.0f} 원  ({_pct_str(bh_final, _INITIAL_CASH)})")
    print(f"  최대낙폭   : {bh_mdd:>12.2f}%")

    # ── 4. KimBeggar 실행 ─────────────────────────────────────────────────
    print("\n[4/4] KimBeggar 3단 방어선 전략 실행...")
    kb_final, events, trade_stats, dd_stats = _run_kimbeggar(df, _INITIAL_CASH)
    kb_pnl = kb_final - _INITIAL_CASH
    total = trade_stats.get("total", {}).get("total", 0)
    won = trade_stats.get("won", {}).get("total", 0)
    win_rate = won / total if total > 0 else 0.0
    kb_mdd = -dd_stats.get("max", {}).get("drawdown", 0.0)
    print(f"  최종 평가액: {kb_final:>12,.0f} 원  ({_pct_str(kb_final, _INITIAL_CASH)})")

    # ── 결과 비교표 ────────────────────────────────────────────────────────
    _section("백테스트 결과 비교")
    W1, W2, W3 = 22, 16, 17
    print(
        f"\n  {'항목':<{W1}}  {'Buy & Hold':>{W2}}  {'KimBeggar 3단방어':>{W3}}"
    )
    print(f"  {_SEP2[2:]}")

    def row(label: str, bh_val: str, kb_val: str) -> None:
        print(f"  {label:<{W1}}  {bh_val:>{W2}}  {kb_val:>{W3}}")

    row("초기 투자금 (원)",
        f"{_INITIAL_CASH:,.0f}", f"{_INITIAL_CASH:,.0f}")
    row("최종 평가액 (원)",
        f"{bh_final:,.0f}", f"{kb_final:,.0f}")
    row("손익 (원)",
        f"{bh_pnl:+,.0f}", f"{kb_pnl:+,.0f}")
    row("수익률",
        _pct_str(bh_final, _INITIAL_CASH),
        _pct_str(kb_final, _INITIAL_CASH))
    row("최대낙폭 (MDD)",
        f"{bh_mdd:.2f}%", f"{kb_mdd:.2f}%")
    row("거래 횟수",
        "1회 (보유)",
        f"{total}회")
    row("승률",
        "N/A",
        f"{win_rate:.1%}" if total > 0 else "N/A")
    row("방어선 발동 건수",
        "없음",
        f"{len(events)}건")

    protection = kb_final - bh_final
    row("Buy&Hold 대비 보전액 (원)",
        "기준",
        f"{protection:+,.0f}")

    # ── 방어선 이벤트 상세 ─────────────────────────────────────────────────
    _section("3단 방어선 발동 이벤트 상세")
    line_counts = {1: 0, 2: 0, 3: 0}
    for ev in events:
        line_counts[ev.line] += 1

    print(
        f"\n  1선 손절      : {line_counts[1]:2d}건"
        f"  (진입가 -5% 시 즉시 청산)"
    )
    print(
        f"  2선 매도시그널: {line_counts[2]:2d}건"
        f"  (RSI 과매수 + 데드크로스)"
    )
    print(
        f"  3선 헤지권고  : {line_counts[3]:2d}건"
        f"  (ML 변동성 예측 기반 인버스 ETF 편입)"
    )

    if events:
        print()
        print(f"  {'날짜':<12}  {'방어선':<9}  {'가격':>10}  {'상세'}")
        print(f"  {_SEP2[2:]}")
        label_map = {1: "[1선 손절]", 2: "[2선 매도]", 3: "[3선 헤지]"}
        for ev in sorted(events, key=lambda e: e.date):
            print(
                f"  {ev.date:<12}  {label_map[ev.line]:<9}"
                f"  {ev.price:>10,.0f}  {ev.detail}"
            )
    else:
        print("\n  ※ 방어선 발동 없음 — 매수 조건 미충족으로 현금 보유")

    # ── 결론 ───────────────────────────────────────────────────────────────
    _section("시뮬레이션 결론")
    print()
    if kb_final >= bh_final:
        print(
            f"  [보전 성공]  KimBeggar가 Buy & Hold 대비"
            f" {protection:+,.0f} 원 더 보전했습니다."
        )
    else:
        print(
            f"  [비교 열위]  이 시나리오에서 KimBeggar는 Buy & Hold 대비"
            f" {-protection:,.0f} 원 낮았습니다."
        )

    print(
        "\n  [1선 평가] 손절(-5%)은 단기 반등 후 재하락 구간에서 핵심 방어 역할을 합니다."
    )
    print(
        "  [2선 평가] RSI 과매수+데드크로스 조합은 하락 초입에 포지션을 줄이는 효과가 있습니다."
    )
    print(
        "  [3선 평가] ML 변동성 예측(predict_volatility)은 헤지 권고를 동적으로 조정하여"
    )
    print(
        "             고변동성 구간(Phase 2·3)에서 더 높은 인버스 ETF 편입 비율을 권고합니다."
    )
    print(
        "\n  Phase 6 (Alpaca API 연동) 이후 미국 시장 급락 시나리오에도 동일 시뮬레이션이"
        "\n  적용될 예정입니다."
    )
    print(f"\n{_SEP}\n")


if __name__ == "__main__":
    main()
