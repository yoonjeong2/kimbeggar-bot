"""Technical indicator calculation module.

Each public function accepts and returns a ``pd.Series`` so results can be
composed and passed directly into signal-detection logic.

Backend selection
-----------------
When the ``TA-Lib`` C-extension library is importable, every indicator
delegates to the corresponding ``talib.*`` function for maximum performance.
If TA-Lib is **not** installed the module falls back transparently to the
original pure ``pandas`` / ``numpy`` implementation — no caller changes needed.

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

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Optional TA-Lib backend
# ---------------------------------------------------------------------------

try:
    import talib as _talib  # type: ignore[import]

    _TALIB_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _TALIB_AVAILABLE = False


# ---------------------------------------------------------------------------
# Public indicators
# ---------------------------------------------------------------------------


def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """Compute RSI using Wilder's smoothing method.

    Delegates to ``talib.RSI`` when TA-Lib is installed; otherwise uses the
    pure pandas/numpy Wilder-EWM implementation.

    TA-Lib lookback is ``period`` (first valid value at index ``period``).
    The pandas fallback uses ``min_periods = period - 1`` (first valid value
    at index ``period - 1``).  Both variants return values in ``[0, 100]``.

    Args:
        prices: Close-price time series (chronological order, oldest first).
        period: Look-back window (default 14).

    Returns:
        RSI values in the range [0, 100] with leading ``NaN`` during warm-up.
    """
    if _TALIB_AVAILABLE:
        raw: np.ndarray = _talib.RSI(prices.values.astype(float), timeperiod=period)
        return pd.Series(raw, index=prices.index)

    # ── pandas/numpy fallback ────────────────────────────────────────────────
    # Uncomment the lines below to inspect the reference implementation.
    #
    # delta    = prices.diff()
    # gain     = delta.clip(lower=0)          # negative deltas → 0
    # loss     = -delta.clip(upper=0)         # positive deltas → 0
    # alpha    = 1.0 / period
    # avg_gain = gain.ewm(alpha=alpha, min_periods=period - 1, adjust=False).mean()
    # avg_loss = loss.ewm(alpha=alpha, min_periods=period - 1, adjust=False).mean()
    # rs       = avg_gain / avg_loss
    # return   100.0 - (100.0 / (1.0 + rs))
    # ─────────────────────────────────────────────────────────────────────────
    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    alpha = 1.0 / period
    avg_gain = gain.ewm(alpha=alpha, min_periods=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, min_periods=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calculate_moving_average(prices: pd.Series, period: int) -> pd.Series:
    """Compute a Simple Moving Average (SMA).

    Delegates to ``talib.SMA`` when TA-Lib is installed; otherwise uses
    ``pd.Series.rolling``.  Both produce identical values; the first
    ``period - 1`` entries are ``NaN``.

    Args:
        prices: Close-price time series.
        period: Rolling window size.

    Returns:
        SMA series; the first ``period - 1`` entries are ``NaN``.
    """
    if _TALIB_AVAILABLE:
        raw: np.ndarray = _talib.SMA(prices.values.astype(float), timeperiod=period)
        return pd.Series(raw, index=prices.index)

    # ── pandas fallback ──────────────────────────────────────────────────────
    # return prices.rolling(window=period).mean()
    # ─────────────────────────────────────────────────────────────────────────
    return prices.rolling(window=period).mean()


def calculate_ema(prices: pd.Series, period: int) -> pd.Series:
    """Compute an Exponential Moving Average (EMA).

    Delegates to ``talib.EMA`` when TA-Lib is installed (initialised from
    SMA of first ``period`` bars, lookback = ``period - 1``).  The pandas
    fallback uses ``span = period`` (``alpha = 2 / (period + 1)``), which
    produces values from bar 0 with no leading ``NaN``.

    Args:
        prices: Close-price time series.
        period: Span / time-period for the exponential decay factor.

    Returns:
        EMA series.
    """
    if _TALIB_AVAILABLE:
        raw: np.ndarray = _talib.EMA(prices.values.astype(float), timeperiod=period)
        return pd.Series(raw, index=prices.index)

    # ── pandas fallback ──────────────────────────────────────────────────────
    # return prices.ewm(span=period, adjust=False).mean()
    # ─────────────────────────────────────────────────────────────────────────
    return prices.ewm(span=period, adjust=False).mean()


def detect_golden_cross(short_ma: pd.Series, long_ma: pd.Series) -> pd.Series:
    """Detect golden-cross events (short MA crosses *above* long MA).

    A golden cross is identified at bar *t* when:
        short_ma[t-1] < long_ma[t-1]  AND  short_ma[t] >= long_ma[t]

    TA-Lib does not expose a direct crossover primitive, so this function
    always uses the pandas shift-comparison approach regardless of whether
    TA-Lib is installed.

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

    TA-Lib does not expose a direct crossover primitive, so this function
    always uses the pandas shift-comparison approach regardless of whether
    TA-Lib is installed.

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

    TA-Lib provides ``STDDEV`` but the pandas rolling std is equivalent and
    avoids an extra dependency call for a simple statistic.  This function
    always uses the pandas implementation.

    Args:
        prices: Close-price time series.
        period: Rolling window size (default 20 trading days).

    Returns:
        Rolling standard deviation series.  The first ``period - 1`` entries
        are ``NaN``.
    """
    return prices.rolling(window=period).std()
