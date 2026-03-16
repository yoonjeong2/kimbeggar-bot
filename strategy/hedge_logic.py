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


def predict_volatility(returns: List[float]) -> float:
    """Predict next-period volatility using a scikit-learn LinearRegression model.

    This function is a **TODO stub** for Phase 6 (ML 기반 동적 헤지).
    The intent is to replace the fixed ``MA_DEVIATION_SCALE`` / ``INDEX_DROP_SCALE``
    multipliers in :func:`calculate_hedge_ratio` with a data-driven volatility
    forecast that feeds directly into the hedge ratio.

    Planned implementation
    ----------------------
    1. Feature engineering — sliding-window statistics derived from ``returns``:
       - Mean return over the last N bars
       - Realised volatility (std-dev of returns) over the last N bars
       - Trend indicator (slope of a linear fit over the last N bars)

    2. Model — ``sklearn.linear_model.LinearRegression`` trained offline on
       historical data; the fitted model would be serialised with ``joblib``
       and loaded at startup.

    3. Output — annualised volatility forecast used as a scalar adjustment to
       the hedge ratio::

           ratio += predict_volatility(recent_returns) * VOLATILITY_SCALE

    Example (illustrative — model not yet trained):

    .. code-block:: python

        # TODO: replace stub with a fitted model loaded from disk
        # import joblib
        # _model = joblib.load("models/volatility_lr.pkl")

        import numpy as np
        from sklearn.linear_model import LinearRegression

        def predict_volatility(returns: List[float]) -> float:
            n = len(returns)
            X = np.arange(n).reshape(-1, 1)
            y = np.array(returns)
            lr = LinearRegression().fit(X, y)       # trend line
            residuals = y - lr.predict(X)
            realised_vol = float(np.std(residuals))  # annualise as needed
            return realised_vol * (252 ** 0.5)       # daily → annual

    Args:
        returns: List of daily log-returns (most recent last), e.g.
                 ``[(close_t / close_{t-1}) - 1 for ...]``.
                 Recommended length: 20–60 bars.

    Returns:
        Predicted annualised volatility as a decimal (e.g. ``0.25`` = 25 %).
        Returns ``0.0`` until a trained model is available.

    Note:
        ``scikit-learn`` must be installed (``pip install scikit-learn``).
        The dependency is listed in ``requirements.txt`` but the model weights
        file (``models/volatility_lr.pkl``) is not yet generated.
        See Phase 6 in ``PROGRESS.md`` for the implementation timeline.
    """
    # TODO (Phase 6): load a pre-trained model and return its prediction.
    #
    #   import numpy as np
    #   from sklearn.linear_model import LinearRegression
    #
    #   n = len(returns)
    #   if n < 5:
    #       return 0.0
    #   X = np.arange(n).reshape(-1, 1)
    #   y = np.array(returns, dtype=float)
    #   lr = LinearRegression().fit(X, y)
    #   residuals = y - lr.predict(X)
    #   daily_vol = float(np.std(residuals, ddof=1))
    #   return daily_vol * (252 ** 0.5)   # annualise

    _ = returns  # suppress "unused argument" linter warning until implemented
    return 0.0   # stub: no adjustment until model is trained


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
