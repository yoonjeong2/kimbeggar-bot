"""Technical indicator calculation module.

All indicators are computed with pure ``pandas`` / ``numpy`` — no third-party
TA library required.  Each function accepts and returns a ``pd.Series`` so
results can be composed and passed directly into signal-detection logic.

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


def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """Compute RSI using Wilder's smoothing (EMA with alpha = 1 / period).

    Formula::

        delta    = prices.diff()
        gain     = max(delta, 0)
        loss     = max(-delta, 0)
        avg_gain = EWM(alpha=1/period) of gain
        avg_loss = EWM(alpha=1/period) of loss
        RS       = avg_gain / avg_loss
        RSI      = 100 - (100 / (1 + RS))

    The first ``period - 1`` entries are ``NaN`` (Wilder warm-up).

    Args:
        prices: Close-price time series (chronological order, oldest first).
        period: Look-back window (default 14).

    Returns:
        RSI values in the range [0, 100].  The first ``period - 1`` entries
        are ``NaN``.
    """
    delta = prices.diff()

    # Separate price moves into gains and losses
    gain = delta.clip(lower=0)   # negative deltas → 0
    loss = -delta.clip(upper=0)  # positive deltas → 0

    # Wilder's smoothing = EMA with alpha = 1/period.
    # min_periods=period-1 ensures the first (period-1) values stay NaN,
    # matching the conventional RSI warm-up convention.
    alpha = 1.0 / period
    avg_gain = gain.ewm(alpha=alpha, min_periods=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, min_periods=period - 1, adjust=False).mean()

    # RS = inf when avg_loss == 0 (all gains) → RSI = 100
    # RS = 0   when avg_gain == 0 (all losses) → RSI = 0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calculate_moving_average(prices: pd.Series, period: int) -> pd.Series:
    """Compute a Simple Moving Average (SMA).

    Args:
        prices: Close-price time series.
        period: Rolling window size.

    Returns:
        SMA series; the first ``period - 1`` entries are ``NaN``.
    """
    return prices.rolling(window=period).mean()


def calculate_ema(prices: pd.Series, period: int) -> pd.Series:
    """Compute an Exponential Moving Average (EMA).

    Uses ``span = period`` which gives ``alpha = 2 / (period + 1)``.

    Args:
        prices: Close-price time series.
        period: Span for the exponential decay factor.

    Returns:
        EMA series.
    """
    return prices.ewm(span=period, adjust=False).mean()


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
    """Compute rolling volatility (standard-deviation based).

    Args:
        prices: Close-price time series.
        period: Rolling window size (default 20 trading days).

    Returns:
        Rolling standard deviation series.  The first ``period - 1`` entries
        are ``NaN``.
    """
    return prices.rolling(window=period).std()
