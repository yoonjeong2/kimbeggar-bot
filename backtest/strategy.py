"""KimBeggar backtrader Strategy.

Implements the same signal logic as ``strategy.signal.SignalEngine`` inside a
``backtrader`` Strategy so that it can be replayed against historical OHLCV
data without any live API calls.

Signal rules
------------
- BUY       : RSI <= rsi_oversold  AND  short SMA just crossed above long SMA
- SELL      : RSI >= rsi_overbought AND  short SMA just crossed below long SMA
- STOP_LOSS : current price <= entry price × (1 − stop_loss_rate)

One position at a time; size is computed as
    floor(available_cash / close_price)   (whole shares only).
"""

from __future__ import annotations

import logging

import backtrader as bt

_logger = logging.getLogger(__name__)


class KimBeggarStrategy(bt.Strategy):
    """RSI + MA-crossover hedge strategy for backtrader.

    Parameters
    ----------
    rsi_period : int
        Look-back window for RSI (default 14).
    rsi_oversold : float
        RSI level that marks an oversold condition (default 30).
    rsi_overbought : float
        RSI level that marks an overbought condition (default 70).
    ma_short : int
        Short-window SMA period (default 5).
    ma_long : int
        Long-window SMA period (default 20).
    stop_loss_rate : float
        Fractional drawdown from entry that triggers a stop-loss (default 0.05).
    """

    params = (
        ("rsi_period", 14),
        ("rsi_oversold", 30.0),
        ("rsi_overbought", 70.0),
        ("ma_short", 5),
        ("ma_long", 20),
        ("stop_loss_rate", 0.05),
    )

    def __init__(self) -> None:
        self.rsi = bt.indicators.RSI(
            self.data.close,
            period=self.p.rsi_period,
            safediv=True,
        )
        self.sma_short = bt.indicators.SMA(self.data.close, period=self.p.ma_short)
        self.sma_long = bt.indicators.SMA(self.data.close, period=self.p.ma_long)
        # +1 when short crosses above long (golden cross); -1 for dead cross
        self.crossover = bt.indicators.CrossOver(self.sma_short, self.sma_long)

        self._entry_price: float = 0.0
        self._order = None  # pending order reference

    # ------------------------------------------------------------------
    # backtrader callbacks
    # ------------------------------------------------------------------

    def notify_order(self, order: bt.Order) -> None:
        if order.status in (order.Submitted, order.Accepted):
            return

        if order.status == order.Completed:
            if order.isbuy():
                self._entry_price = order.executed.price
                _logger.debug(
                    "BUY executed @ %.2f  size=%d",
                    order.executed.price,
                    order.executed.size,
                )
            else:
                _logger.debug(
                    "SELL executed @ %.2f  size=%d  pnl=%.2f",
                    order.executed.price,
                    order.executed.size,
                    order.executed.pnl,
                )
                self._entry_price = 0.0
        elif order.status in (order.Canceled, order.Margin, order.Rejected):
            _logger.warning("Order rejected / canceled: %s", order.status)

        self._order = None

    def next(self) -> None:
        # Do not double-order while one is pending
        if self._order:
            return

        current_price: float = self.data.close[0]

        if not self.position:
            # --- BUY condition -----------------------------------------
            # RSI oversold AND golden cross (short SMA just crossed above long)
            if self.rsi[0] <= self.p.rsi_oversold and self.crossover[0] > 0:
                size = int(self.broker.getcash() // current_price)
                if size > 0:
                    _logger.debug(
                        "BUY signal @ %.2f  RSI=%.1f  size=%d",
                        current_price,
                        self.rsi[0],
                        size,
                    )
                    self._order = self.buy(size=size)
        else:
            # --- STOP-LOSS check (highest priority) --------------------
            if self._entry_price > 0 and current_price <= self._entry_price * (
                1.0 - self.p.stop_loss_rate
            ):
                _logger.debug(
                    "STOP-LOSS triggered @ %.2f  entry=%.2f",
                    current_price,
                    self._entry_price,
                )
                self._order = self.close()
                return

            # --- SELL condition ----------------------------------------
            # RSI overbought AND dead cross (short SMA just crossed below long)
            if self.rsi[0] >= self.p.rsi_overbought and self.crossover[0] < 0:
                _logger.debug(
                    "SELL signal @ %.2f  RSI=%.1f",
                    current_price,
                    self.rsi[0],
                )
                self._order = self.close()
