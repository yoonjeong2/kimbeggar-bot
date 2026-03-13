"""Technical indicator calculation module.

All indicators are computed with the ``ta`` library (pandas-compatible).
Each function accepts and returns a ``pd.Series`` so results can be composed
and passed directly into signal-detection logic.

Indicator reference
-------------------
- RSI  : Wilder's Relative Strength Index (momentum oscillator, 0-100)
- SMA  : Simple Moving Average (trend baseline)
- EMA  : Exponential Moving Average (trend, more weight on recent prices)
- Golden cross : short SMA crosses *above* long SMA  → bullish signal
- Dead cross   : short SMA crosses *below* long SMA  → bearish signal
- Volatility   : rolling standard deviation of close prices
"""

from __future__ import annotations

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, SMAIndicator


def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """Compute RSI using Wilder's smoothing method via the ``ta`` library.

    Args:
        prices: Close-price time series (chronological order, oldest first).
        period: Look-back window (default 14).

    Returns:
        RSI values in the range [0, 100].  The first ``period`` entries will
        be ``NaN``.
    """
    return RSIIndicator(close=prices, window=period).rsi()


def calculate_moving_average(prices: pd.Series, period: int) -> pd.Series:
    """Compute a Simple Moving Average (SMA).

    Args:
        prices: Close-price time series.
        period: Rolling window size.

    Returns:
        SMA series; the first ``period - 1`` entries are ``NaN``.
    """
    return SMAIndicator(close=prices, window=period).sma_indicator()


def calculate_ema(prices: pd.Series, period: int) -> pd.Series:
    """Compute an Exponential Moving Average (EMA).

    Args:
        prices: Close-price time series.
        period: Span for the exponential decay factor.

    Returns:
        EMA series; the first ``period - 1`` entries are ``NaN``.
    """
    return EMAIndicator(close=prices, window=period).ema_indicator()


def detect_golden_cross(short_ma: pd.Series, long_ma: pd.Series) -> pd.Series:
    """Detect golden-cross events (short MA crosses *above* long MA).

    A golden cross is identified at bar *t* when:
        short_ma[t-1] < long_ma[t-1]  AND  short_ma[t] >= long_ma[t]

    Args:
        short_ma: Short-window SMA series.
        long_ma:  Long-window SMA series.

    Returns:
        Boolean series — ``True`` on the bar where a golden cross occurred.
    """
    prev_below = short_ma.shift(1) < long_ma.shift(1)
    curr_above = short_ma >= long_ma
    return (prev_below & curr_above).fillna(False)


def detect_dead_cross(short_ma: pd.Series, long_ma: pd.Series) -> pd.Series:
    """Detect dead-cross events (short MA crosses *below* long MA).

    A dead cross is identified at bar *t* when:
        short_ma[t-1] >= long_ma[t-1]  AND  short_ma[t] < long_ma[t]

    Args:
        short_ma: Short-window SMA series.
        long_ma:  Long-window SMA series.

    Returns:
        Boolean series — ``True`` on the bar where a dead cross occurred.
    """
    prev_above = short_ma.shift(1) >= long_ma.shift(1)
    curr_below = short_ma < long_ma
    return (prev_above & curr_below).fillna(False)


def calculate_volatility(prices: pd.Series, period: int = 20) -> pd.Series:
    """Compute annualised rolling volatility (standard-deviation based).

    Args:
        prices: Close-price time series.
        period: Rolling window size (default 20 trading days).

    Returns:
        Rolling standard deviation series scaled to the same price units.
        The first ``period - 1`` entries are ``NaN``.
    """
    return prices.rolling(window=period).std()
