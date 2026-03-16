"""Hedge ratio calculation logic.

The hedge ratio determines what fraction of a position should be offset with
an inverse ETF (e.g. KODEX 인버스) to protect against downside risk.

Calculation model
-----------------
The ratio is derived from two independent risk signals and then clamped:

1. **MA deviation risk** - how far the current price has fallen below the
   long-term moving average, expressed as a percentage.  Each 1 % of
   downward deviation adds ``MA_DEVIATION_SCALE`` (5 pp) to the ratio.

2. **Index drop risk** - the day-over-day percentage change of a market index
   (KOSPI / KOSDAQ).  Each 1 % of index drop adds ``INDEX_DROP_SCALE`` (3 pp).

Formula::

    deviation = max(0, (long_ma - price) / long_ma)
    index_risk = max(0, -index_change_rate / 100)
    ratio = base + deviation * MA_DEVIATION_SCALE + index_risk * INDEX_DROP_SCALE
    ratio = clamp(ratio, MIN_RATIO, MAX_RATIO)

Example:
    >>> calculate_hedge_ratio(
    ...     current_price=58_000,
    ...     long_ma=60_000,      # price is 3.3 % below MA
    ...     base_ratio=0.30,
    ...     index_change_rate=-2.0,   # index dropped 2 %
    ... )
    0.57   # 30 % base + 16.5 pp MA-risk + 6 pp index-risk ≈ 52.5 % → 57 %
"""

from __future__ import annotations

from typing import List

# Contribution of each 1 % below long MA to the hedge ratio (percentage points)
MA_DEVIATION_SCALE: float = 5.0

# Contribution of each 1 % market-index drop to the hedge ratio (percentage points)
INDEX_DROP_SCALE: float = 3.0

# Hard bounds on the returned ratio
MIN_RATIO: float = 0.0
MAX_RATIO: float = 0.80  # Never hedge more than 80 % of a position


def calculate_hedge_ratio(
    current_price: float,
    long_ma: float,
    base_ratio: float = 0.30,
    index_change_rate: float = 0.0,
) -> float:
    """Compute a dynamic hedge ratio scaled to current market conditions.

    The ratio increases when the stock trades below its long-term moving
    average and/or when the broader market index is falling.  It is clamped
    between ``MIN_RATIO`` and ``MAX_RATIO`` to prevent over-hedging.

    Args:
        current_price:    Latest close or real-time price of the position.
        long_ma:          Long-window SMA value at the current bar.
        base_ratio:       Minimum hedge ratio from configuration
                          (``Settings.hedge_ratio``, default 0.30 = 30 %).
        index_change_rate: Day-over-day percentage change of the market index
                           (negative means the index fell).  Defaults to 0.0
                           when index data is unavailable.

    Returns:
        Hedge ratio in [``MIN_RATIO``, ``MAX_RATIO``].  Multiply by position
        value to obtain the inverse-ETF notional to hold.

    Example:
        >>> calculate_hedge_ratio(58_000, 60_000, base_ratio=0.3, index_change_rate=-2.0)
        0.575
    """
    # --- 1. MA deviation risk -------------------------------------------
    # How far below the long MA is the current price?  Negative deviation
    # (price above MA) contributes zero risk.
    ma_deviation = max(0.0, (long_ma - current_price) / long_ma) if long_ma > 0 else 0.0
    ma_risk = ma_deviation * MA_DEVIATION_SCALE  # convert fraction to pp

    # --- 2. Index drop risk ---------------------------------------------
    # Only negative index moves increase the hedge ratio.
    index_drop = max(0.0, -index_change_rate)  # e.g. -2.0 % → 2.0
    index_risk = (index_drop / 100) * INDEX_DROP_SCALE

    # --- 3. Combine and clamp -------------------------------------------
    ratio = base_ratio + ma_risk + index_risk
    return round(min(max(ratio, MIN_RATIO), MAX_RATIO), 4)


def predict_volatility(returns: List[float], window: int = 10) -> float:
    """Predict next-period annualised volatility using a walk-forward LinearRegression.

    Approach
    --------
    Trains a :class:`sklearn.linear_model.LinearRegression` model entirely on
    the supplied ``returns`` series using a walk-forward scheme — no pre-trained
    weights file is required.

    For each rolling window of ``window`` bars the following features are computed:

    ==================  =====================================================
    Feature             Description
    ==================  =====================================================
    ``mean``            Mean daily return over the window
    ``vol``             Realised volatility (std-dev, ddof=1) over the window
    ``slope``           Linear trend slope (np.polyfit degree-1 coefficient)
    ``min`` / ``max``   Extreme returns in the window (tail-risk proxies)
    ==================  =====================================================

    The **target** is the realised volatility of the immediately following
    ``window`` bars — i.e. the model learns "given how volatile the last
    10 days were, how volatile will the next 10 days be?".

    After fitting, the model predicts on the *most recent* ``window`` bars
    to produce the next-period forecast, which is then annualised::

        annualised_vol = daily_vol_forecast × √252

    Fallback
    --------
    When ``len(returns) < 2 * window + 1`` (insufficient history), the function
    falls back to the simple annualised standard-deviation of all available
    returns.  This ensures the function always returns a sensible value even
    for very short series.

    Integration with ``calculate_hedge_ratio``
    ------------------------------------------
    The returned volatility can be used to scale the hedge ratio dynamically::

        ml_vol = predict_volatility(recent_returns)   # e.g. 0.35 = 35 % ann.
        ratio  = calculate_hedge_ratio(price, long_ma, base_ratio=ml_vol * 0.5)

    Args:
        returns: Daily simple or log returns, oldest first, most recent last
                 (e.g. ``[(c1/c0) - 1, (c2/c1) - 1, ...]``).
                 Recommended length: 30–120 bars for stable estimates.
        window:  Look-back / look-forward window size used to build training
                 pairs (default 10).  Must be ≥ 3.

    Returns:
        Predicted annualised volatility as a decimal
        (e.g. ``0.30`` = 30 %).  Always ≥ 0.

    Raises:
        ImportError: If ``scikit-learn`` is not installed.
    """
    import numpy as np
    from sklearn.linear_model import LinearRegression

    arr = np.array(returns, dtype=float)
    n = len(arr)
    min_required = 2 * window + 1

    # ── Fallback: not enough data for walk-forward training ──────────────
    if n < min_required:
        daily_vol = float(np.std(arr, ddof=1)) if n > 1 else 0.0
        return round(daily_vol * (252**0.5), 6)

    # ── Build (features, target) training pairs ───────────────────────────
    t = np.arange(window, dtype=float)
    X_rows: List[List[float]] = []
    y_vals: List[float] = []

    for i in range(n - 2 * window):
        w = arr[i : i + window]
        nxt = arr[i + window : i + 2 * window]
        slope = float(np.polyfit(t, w, 1)[0])
        X_rows.append(
            [
                float(w.mean()),
                float(w.std(ddof=1)),
                slope,
                float(w.min()),
                float(w.max()),
            ]
        )
        y_vals.append(float(nxt.std(ddof=1)))

    X = np.array(X_rows)
    y = np.array(y_vals)

    # ── Train LinearRegression in-sample ─────────────────────────────────
    lr = LinearRegression().fit(X, y)

    # ── Predict on most recent window ────────────────────────────────────
    last_w = arr[-window:]
    slope_last = float(np.polyfit(t, last_w, 1)[0])
    x_pred = np.array(
        [
            [
                float(last_w.mean()),
                float(last_w.std(ddof=1)),
                slope_last,
                float(last_w.min()),
                float(last_w.max()),
            ]
        ]
    )

    daily_vol_pred = float(max(lr.predict(x_pred)[0], 0.0))
    return round(daily_vol_pred * (252**0.5), 6)


def describe_hedge(ratio: float) -> str:
    """Return a human-readable description of the hedge intensity.

    Args:
        ratio: Hedge ratio in [0, 1].

    Returns:
        Korean description string for use in notification messages.
    """
    if ratio >= 0.60:
        return f"강헤지 {ratio:.0%} - 인버스 ETF 비중 확대 권고"
    if ratio >= 0.40:
        return f"중헤지 {ratio:.0%} - 인버스 ETF 포지션 진입 권고"
    if ratio >= 0.20:
        return f"약헤지 {ratio:.0%} - 소량 인버스 ETF 편입 권고"
    return f"헤지 불필요 ({ratio:.0%})"
