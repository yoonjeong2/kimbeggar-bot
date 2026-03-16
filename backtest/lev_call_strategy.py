"""레버리지 ETF + 콜 옵션 복합 전략 - backtrader 전략 클래스.

``LevCallStrategy``는 backtrader의 ``bt.Strategy``를 상속하며,
ETF 포지션은 브로커를 통해 실행하고 옵션은 가상 포지션으로 인스턴스 변수로
추적합니다 (backtrader 브로커 외부).

마진 레버리지
-------------
- ETF 매수 시 ``cash * margin_leverage / price``로 수량 계산
- 브로커 잔고와 별도로 실제 노출(Exposure)을 추적

옵션 가격
---------
- 매 봉마다 Black-Scholes로 시가평가
- ETF 수익률로 코스피 수준을 역산 (2X 레버리지 관계)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import backtrader as bt

from strategy.option_pricing import black_scholes_call, estimate_premium_per_contract
from strategy.vkospi_estimator import estimate_vkospi
from strategy.lev_call_signal import LevCallSignalEngine, LevCallSignalType
from strategy.portfolio_tracker import LevCallPortfolio


@dataclass
class LevCallEvent:
    """전략 이벤트 레코드."""

    date: str
    event_type: str
    etf_price: float
    kospi_level: float
    portfolio_value: float
    detail: str


class LevCallStrategy(bt.Strategy):
    """레버리지 ETF + 콜 옵션 backtrader 전략.

    params
    ------
    initial_cash         : 초기 투자금 (KRW, 기본 10,000,000)
    etf_alloc            : ETF 배분 비율 (기본 0.70)
    option_alloc         : 옵션 배분 비율 (기본 0.30)
    call_strike          : 콜 옵션 행사가 (포인트, 기본 5500.0)
    call_expiry_months   : 만기 월수 (기본 2)
    entry_kospi_level    : 진입 코스피 수준 (기본 5400.0)
    exit_kospi_level     : 청산 코스피 수준 (기본 6000.0)
    take_profit_pct      : 익절 기준 (기본 0.20)
    take_profit_sell_ratio: 익절 매도 비율 (기본 0.50)
    margin_leverage      : 마진 레버리지 (기본 3.0)
    vkospi_threshold     : VKOSPI 추가 옵션 매수 기준 (기본 30.0)
    rsi_period           : RSI 기간 (기본 14)
    rsi_oversold         : RSI 과매도 기준 (기본 30.0)
    ma_short             : 단기 MA 기간 (기본 5)
    ma_long              : 장기 MA 기간 (기본 20)
    kospi_start          : 시뮬레이션 시작 코스피 수준 (기본 5600.0)
    option_sigma         : 옵션 기초변동성 초기값 (기본 0.20)
    """

    params = (
        ("initial_cash", 10_000_000.0),
        ("etf_alloc", 0.70),
        ("option_alloc", 0.30),
        ("call_strike", 5500.0),
        ("call_expiry_months", 2),
        ("entry_kospi_level", 5400.0),
        ("exit_kospi_level", 6000.0),
        ("take_profit_pct", 0.20),
        ("take_profit_sell_ratio", 0.50),
        ("margin_leverage", 3.0),
        ("vkospi_threshold", 30.0),
        ("rsi_period", 14),
        ("rsi_oversold", 30.0),
        ("ma_short", 5),
        ("ma_long", 20),
        ("kospi_start", 5600.0),
        ("option_sigma", 0.20),
    )

    def __init__(self) -> None:
        self.rsi = bt.indicators.RSI(
            self.data.close,
            period=self.p.rsi_period,
            safediv=True,
        )
        self.sma_short = bt.indicators.SMA(self.data.close, period=self.p.ma_short)
        self.sma_long = bt.indicators.SMA(self.data.close, period=self.p.ma_long)
        self.crossover = bt.indicators.CrossOver(self.sma_short, self.sma_long)

        # 가상 포트폴리오 (브로커 외부)
        self._portfolio = LevCallPortfolio(
            initial_cash=self.p.initial_cash,
            etf_alloc=self.p.etf_alloc,
            option_alloc=self.p.option_alloc,
            margin_leverage=self.p.margin_leverage,
        )

        # 상태 추적
        self._order: Optional[bt.Order] = None
        self._entry_etf_price: float = 0.0
        self._kospi_level: float = self.p.kospi_start
        self._close_history: List[float] = []
        self._etf_start_price: Optional[float] = None
        self.events: List[LevCallEvent] = []
        self._partial_exit_done: bool = False

    def prenext(self) -> None:
        """웜업 기간 동안 최초 ETF 시작가를 캡처합니다."""
        if self._etf_start_price is None:
            self._etf_start_price = float(self.data.close[0])

    def notify_order(self, order: bt.Order) -> None:
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed:
            if order.isbuy():
                self._entry_etf_price = float(order.executed.price)
            else:
                self._entry_etf_price = 0.0
        self._order = None

    def _estimate_kospi(self, etf_price: float) -> float:
        """ETF 가격으로 코스피 수준을 역산합니다.

        KODEX 200 레버리지는 KOSPI200의 일별 수익률 2배를 추적합니다.
        ETF 가격 변화로 코스피 수준을 근사합니다.

        Args:
            etf_price: 현재 ETF 가격.

        Returns:
            추정 코스피 포인트.
        """
        if self._etf_start_price is None or self._etf_start_price <= 0:
            return self._kospi_level

        etf_return = etf_price / self._etf_start_price - 1.0
        kospi_return = etf_return / 2.0  # 2X 레버리지 역산
        return self.p.kospi_start * (1.0 + kospi_return)

    def _calc_option_price(self, etf_price: float, vkospi: float) -> float:
        """현재 시장 조건으로 옵션 계약당 KRW 프리미엄을 계산합니다.

        Args:
            etf_price: 현재 ETF 가격 (코스피 추정에 사용).
            vkospi:    합성 VKOSPI 추정값.

        Returns:
            계약당 KRW 프리미엄.
        """
        kospi = self._estimate_kospi(etf_price)
        T = self.p.call_expiry_months / 12.0
        sigma = max(vkospi / 100.0, self.p.option_sigma)
        return estimate_premium_per_contract(
            S=kospi,
            K=self.p.call_strike,
            T=T,
            sigma=sigma,
        )

    def next(self) -> None:
        current_price = float(self.data.close[0])
        date_str = self.data.datetime.date(0).strftime("%Y-%m-%d")

        self._close_history.append(current_price)
        if self._etf_start_price is None:
            self._etf_start_price = current_price  # fallback only

        # 코스피 수준 추정
        self._kospi_level = self._estimate_kospi(current_price)

        # VKOSPI 추정
        import pandas as pd
        if len(self._close_history) >= 21:
            vkospi = estimate_vkospi(self._close_history, window=20)
        else:
            vkospi = 20.0

        # 옵션 현재 프리미엄 (KRW)
        option_premium = self._calc_option_price(current_price, vkospi)

        # 포트폴리오 시가평가
        mtm = self._portfolio.mark_to_market(current_price, option_premium)
        pnl_pct = mtm.get("pnl_pct", 0.0)

        if self._order is not None:
            return

        if not self._portfolio.is_active:
            # ── 진입 조건 ────────────────────────────────────────────────
            should_entry = False
            reason = ""

            if self._kospi_level <= self.p.entry_kospi_level:
                should_entry = True
                reason = (
                    f"코스피 저점 ({self._kospi_level:.0f} <= "
                    f"{self.p.entry_kospi_level:.0f})"
                )
            elif (
                self.rsi[0] <= self.p.rsi_oversold
                and self.crossover[0] > 0
            ):
                should_entry = True
                reason = f"RSI 과매도+골든크로스 (RSI={self.rsi[0]:.1f})"

            if should_entry:
                # 브로커: ETF 배분 현금으로 매수 (마진은 가상 포트폴리오로 추적)
                available = self.broker.getcash()
                etf_cash = available * self.p.etf_alloc
                size = int(etf_cash / current_price)
                if size > 0:
                    self._order = self.buy(size=size)
                    # 가상 포트폴리오도 동기화
                    self._portfolio.allocate_initial(current_price, option_premium)
                    self.events.append(
                        LevCallEvent(
                            date=date_str,
                            event_type="ENTRY",
                            etf_price=current_price,
                            kospi_level=self._kospi_level,
                            portfolio_value=self.p.initial_cash,
                            detail=reason,
                        )
                    )
        else:
            # ── 청산 조건 ────────────────────────────────────────────────
            should_exit = False
            exit_reason = ""

            if self._kospi_level >= self.p.exit_kospi_level:
                should_exit = True
                exit_reason = (
                    f"코스피 목표 ({self._kospi_level:.0f} >= "
                    f"{self.p.exit_kospi_level:.0f})"
                )
            elif self.crossover[0] < 0:
                should_exit = True
                exit_reason = "ETF 데드크로스"

            if should_exit:
                result = self._portfolio.full_exit(current_price, option_premium)
                self._order = self.close()
                self.events.append(
                    LevCallEvent(
                        date=date_str,
                        event_type="EXIT",
                        etf_price=current_price,
                        kospi_level=self._kospi_level,
                        portfolio_value=result.get("final_value", 0.0),
                        detail=exit_reason,
                    )
                )
                self._partial_exit_done = False
                return

            # ── 익절 부분 청산 (1회만) ───────────────────────────────────
            if (
                not self._partial_exit_done
                and pnl_pct >= self.p.take_profit_pct
            ):
                result = self._portfolio.partial_exit(
                    current_price,
                    option_premium,
                    sell_ratio=self.p.take_profit_sell_ratio,
                )
                # 브로커 포지션도 절반 청산
                half_size = int(self.position.size * self.p.take_profit_sell_ratio)
                if half_size > 0:
                    self._order = self.sell(size=half_size)
                self._partial_exit_done = True
                self.events.append(
                    LevCallEvent(
                        date=date_str,
                        event_type="PARTIAL_EXIT",
                        etf_price=current_price,
                        kospi_level=self._kospi_level,
                        portfolio_value=mtm.get("total_value", 0.0),
                        detail=(
                            f"익절 +{pnl_pct:.1%} - "
                            f"{self.p.take_profit_sell_ratio:.0%} 청산"
                        ),
                    )
                )

            # ── VKOSPI 옵션 추가 매수 ────────────────────────────────────
            if vkospi > self.p.vkospi_threshold:
                add_cash = self.broker.getcash() * 0.05  # 여유 현금 5%
                if add_cash > option_premium:
                    self._portfolio.add_options(add_cash, option_premium)
                    self.events.append(
                        LevCallEvent(
                            date=date_str,
                            event_type="ADD_OPTIONS",
                            etf_price=current_price,
                            kospi_level=self._kospi_level,
                            portfolio_value=mtm.get("total_value", 0.0),
                            detail=f"VKOSPI={vkospi:.1f} > {self.p.vkospi_threshold:.0f}",
                        )
                    )
