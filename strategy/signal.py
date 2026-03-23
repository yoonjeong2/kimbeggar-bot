"""퀀텀 점프 — 공격적 시그널 탐지 엔진 (하이리스크 하이리턴).

비대칭 페이오프를 극대화하기 위해 과매도 즉시 진입 + 과매수/추세반전 즉시 익절
전략을 구현합니다.

Signal priority (highest → lowest)
-----------------------------------
1. STOP_LOSS — 진입가 대비 설정 비율 이상 손실 시 즉시 손절
2. SELL      — RSI 과매수(≥70) 도달  OR  데드크로스 발생 (둘 중 하나)
3. BUY       — RSI 과매도(≤30) 도달 (MA 추세 확인 없이 즉시 진입)
4. HOLD      — 위 조건 미충족

Index-level HEDGE signals are evaluated separately in ``main.py`` so that a
single market check covers all monitored symbols at once.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import pandas as pd

from config.settings import Settings
from strategy.indicators import (
    calculate_moving_average,
    calculate_rsi,
    detect_dead_cross,
    detect_golden_cross,
)

# Day-over-day index change rate (%) that triggers a HEDGE signal
_HEDGE_TRIGGER_RATE: float = -1.5


def is_market_open(now: Optional[datetime] = None) -> bool:
    """한국장 거래 시간(평일 09:00~15:30) 여부를 반환한다."""
    if now is None:
        now = datetime.now()
    # 주말 체크 (5=토, 6=일)
    if now.weekday() >= 5:
        return False
    # 시간 체크
    market_open = now.replace(hour=9, minute=0, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


class SignalType(Enum):
    """Trading signal categories."""

    BUY = "BUY"
    SELL = "SELL"
    STOP_LOSS = "STOP_LOSS"
    HEDGE = "HEDGE"
    HOLD = "HOLD"


@dataclass
class Signal:
    """Container for a single trading signal.

    Attributes:
        symbol:      KRX 6-digit stock code.
        signal_type: Category of the signal.
        price:       Close price at signal generation time.
        reason:      Human-readable explanation of the trigger condition.
        rsi:         RSI value at signal time (``None`` if unavailable).
        ma_short:    Short-window SMA at signal time (``None`` if unavailable).
        ma_long:     Long-window SMA at signal time (``None`` if unavailable).
    """

    symbol: str
    signal_type: SignalType
    price: float
    reason: str
    rsi: Optional[float] = None
    ma_short: Optional[float] = None
    ma_long: Optional[float] = None


class SignalEngine:
    """Evaluate OHLCV candle data and return the highest-priority signal.

    Args:
        settings: Application ``Settings`` instance providing RSI period,
            oversold/overbought thresholds, MA windows, and stop-loss rate.
    """

    # Minimum number of daily candles needed for reliable indicator output
    _MIN_CANDLES: int = 30

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        symbol: str,
        ohlcv_data: List[Dict[str, Any]],
        entry_price: Optional[float] = None,
    ) -> Signal:
        """Evaluate a symbol and return the highest-priority signal.

        Converts the raw KIS OHLCV list into a pandas Series, computes RSI
        and dual SMA, then checks conditions in priority order.

        Args:
            symbol:      KRX stock code (e.g. ``"005930"``).
            ohlcv_data:  Daily OHLCV records from
                         :meth:`~data_agent.kis_api.KISClient.get_ohlcv_daily`.
                         Each dict must contain the ``stck_clpr`` key.
            entry_price: Price at which the position was opened; used only
                         for stop-loss detection.  Pass ``None`` to skip.

        Returns:
            A :class:`Signal` with the highest-priority condition met, or
            ``SignalType.HOLD`` when no condition triggers.
        """
        if not ohlcv_data:
            return Signal(
                symbol=symbol,
                signal_type=SignalType.HOLD,
                price=0.0,
                reason="No OHLCV data available.",
            )

        # Build a clean close-price Series (oldest → newest)
        close: pd.Series = (
            pd.DataFrame(ohlcv_data)["stck_clpr"]
            .apply(pd.to_numeric, errors="coerce")
            .dropna()
            .reset_index(drop=True)
        )

        if len(close) < self._MIN_CANDLES:
            self._logger.warning(
                "%s: only %d candles available (need %d) — returning HOLD.",
                symbol,
                len(close),
                self._MIN_CANDLES,
            )
            return Signal(
                symbol=symbol,
                signal_type=SignalType.HOLD,
                price=float(close.iloc[-1]) if not close.empty else 0.0,
                reason=f"Insufficient data ({len(close)} < {self._MIN_CANDLES} candles).",
            )

        # --- Compute indicators -----------------------------------------
        rsi_series = calculate_rsi(close, self._settings.rsi_period)
        short_ma = calculate_moving_average(close, self._settings.ma_short)
        long_ma = calculate_moving_average(close, self._settings.ma_long)

        current_price = float(close.iloc[-1])
        current_rsi = (
            float(rsi_series.iloc[-1]) if not rsi_series.isna().all() else None
        )
        current_short_ma = (
            float(short_ma.iloc[-1]) if not short_ma.isna().all() else None
        )
        current_long_ma = float(long_ma.iloc[-1]) if not long_ma.isna().all() else None

        self._logger.debug(
            "%s | price=%.0f  RSI=%.1f  MA%d=%.0f  MA%d=%.0f",
            symbol,
            current_price,
            current_rsi or 0,
            self._settings.ma_short,
            current_short_ma or 0,
            self._settings.ma_long,
            current_long_ma or 0,
        )

        # --- Signal priority checks -------------------------------------

        # 1. Stop-loss (highest priority — capital preservation)
        if entry_price is not None and self.check_stop_loss(current_price, entry_price):
            loss_pct = (current_price - entry_price) / entry_price * 100
            return Signal(
                symbol=symbol,
                signal_type=SignalType.STOP_LOSS,
                price=current_price,
                reason=(
                    f"Stop-loss triggered: entry {entry_price:,.0f} → "
                    f"current {current_price:,.0f} ({loss_pct:+.1f}%)"
                ),
                rsi=current_rsi,
                ma_short=current_short_ma,
                ma_long=current_long_ma,
            )

        # 2. Sell signal — RSI overbought OR dead cross (퀀텀점프: 둘 중 하나라도 → 즉시 익절)
        if current_rsi is not None:
            sell_trigger = self.check_sell_signal(close, rsi_series, short_ma, long_ma)
            if sell_trigger:
                rsi_hit = float(rsi_series.iloc[-1]) >= self._settings.rsi_overbought
                dead = bool(detect_dead_cross(short_ma, long_ma).iloc[-1])
                if rsi_hit and dead:
                    sell_reason = (
                        f"Sell: RSI={current_rsi:.1f} (≥{self._settings.rsi_overbought})"
                        f" + dead cross (MA{self._settings.ma_short}<MA{self._settings.ma_long})"
                    )
                elif rsi_hit:
                    sell_reason = (
                        f"Sell: RSI={current_rsi:.1f} 과매수 도달"
                        f" (≥{self._settings.rsi_overbought})"
                    )
                else:
                    sell_reason = (
                        f"Sell: dead cross (MA{self._settings.ma_short}"
                        f"<MA{self._settings.ma_long}), RSI={current_rsi:.1f}"
                    )
                return Signal(
                    symbol=symbol,
                    signal_type=SignalType.SELL,
                    price=current_price,
                    reason=sell_reason,
                    rsi=current_rsi,
                    ma_short=current_short_ma,
                    ma_long=current_long_ma,
                )

        # 3. Buy signal — RSI oversold 단독 진입 (퀀텀점프: 과매도 즉시 진입, 추세 확인 불필요)
        if current_rsi is not None and self.check_buy_signal(
            close, rsi_series, short_ma, long_ma
        ):
            return Signal(
                symbol=symbol,
                signal_type=SignalType.BUY,
                price=current_price,
                reason=(
                    f"Buy: RSI={current_rsi:.1f} 과매도 진입"
                    f" (≤{self._settings.rsi_oversold}) — 퀀텀점프 공격적 진입"
                ),
                rsi=current_rsi,
                ma_short=current_short_ma,
                ma_long=current_long_ma,
            )

        # 4. Hold — no condition met
        return Signal(
            symbol=symbol,
            signal_type=SignalType.HOLD,
            price=current_price,
            reason="No signal condition met.",
            rsi=current_rsi,
            ma_short=current_short_ma,
            ma_long=current_long_ma,
        )

    def check_buy_signal(
        self,
        prices: pd.Series,
        rsi: pd.Series,
        short_ma: pd.Series,
        long_ma: pd.Series,
    ) -> bool:
        """퀀텀점프 BUY: RSI 과매도 단독 진입 (추세 확인 불필요).

        Condition::

            RSI[-1] <= rsi_oversold

        MA 필터를 제거해 과매도 구간 즉시 진입 — 하이리스크 하이리턴.

        Args:
            prices:   Close-price series (unused directly, kept for API symmetry).
            rsi:      RSI series aligned with ``prices``.
            short_ma: Short-window SMA series (unused, kept for API symmetry).
            long_ma:  Long-window SMA series (unused, kept for API symmetry).

        Returns:
            ``True`` when RSI is at or below the oversold threshold.
        """
        if rsi.isna().iloc[-1]:
            return False

        return float(rsi.iloc[-1]) <= self._settings.rsi_oversold

    def check_sell_signal(
        self,
        prices: pd.Series,
        rsi: pd.Series,
        short_ma: pd.Series,
        long_ma: pd.Series,
    ) -> bool:
        """퀀텀점프 SELL: RSI 과매수 도달 OR 데드크로스 발생 시 즉시 익절.

        Condition::

            RSI[-1] >= rsi_overbought  OR  dead_cross[-1] is True

        둘 중 하나라도 충족되면 포지션 청산 — 빠른 수익 확정.

        Args:
            prices:   Close-price series (unused directly, kept for API symmetry).
            rsi:      RSI series aligned with ``prices``.
            short_ma: Short-window SMA series.
            long_ma:  Long-window SMA series.

        Returns:
            ``True`` if RSI is overbought OR a dead cross just occurred.
        """
        if rsi.isna().iloc[-1] or short_ma.isna().iloc[-1] or long_ma.isna().iloc[-1]:
            return False

        rsi_overbought = float(rsi.iloc[-1]) >= self._settings.rsi_overbought
        dead_cross_now = bool(detect_dead_cross(short_ma, long_ma).iloc[-1])
        return rsi_overbought or dead_cross_now

    def check_stop_loss(self, current_price: float, entry_price: float) -> bool:
        """Return ``True`` when the position has fallen below the stop-loss floor.

        Condition::

            current_price <= entry_price * (1 - stop_loss_rate)

        Args:
            current_price: Latest price of the holding.
            entry_price:   Price at which the position was opened.

        Returns:
            ``True`` if the drawdown exceeds the configured ``stop_loss_rate``.
        """
        stop_floor = entry_price * (1.0 - self._settings.stop_loss_rate)
        return current_price <= stop_floor

    def check_hedge_signal(self, index_data: Dict[str, Any]) -> bool:
        """Return ``True`` when the market index has fallen past the hedge trigger.

        Uses the ``bstp_nmix_prdy_ctrt`` field from the KIS index response
        (day-over-day change rate as a percentage string, e.g. ``"-1.97"``).

        Condition::

            index_change_rate <= _HEDGE_TRIGGER_RATE  (default -1.5 %)

        Args:
            index_data: Dictionary returned by
                :meth:`~data_agent.kis_api.KISClient.get_index_data`.

        Returns:
            ``True`` if the index drop equals or exceeds the trigger threshold.
        """
        try:
            change_rate = float(index_data.get("bstp_nmix_prdy_ctrt", "0"))
        except (ValueError, TypeError):
            self._logger.warning("Could not parse index change rate: %s", index_data)
            return False

        triggered = change_rate <= _HEDGE_TRIGGER_RATE
        if triggered:
            self._logger.info(
                "Hedge signal triggered: index change rate %.2f%% ≤ %.1f%%",
                change_rate,
                _HEDGE_TRIGGER_RATE,
            )
        return triggered
