"""합성 VKOSPI(변동성 지수) 추정기.

KIS API가 VKOSPI 데이터를 직접 제공하지 않으므로 실현변동성(Realized Volatility)
기반으로 내재변동성을 근사합니다.

추정 공식
---------
1. 20일 롤링 표준편차 연율화 (기본 변동성)
2. × 1.2 (공포 프리미엄 — VIX는 실현변동성보다 약 20% 높음)
3. + 드로다운 추가분 (최근 최대 낙폭이 심할수록 공포 프리미엄 가산)

기존 ``strategy.indicators.calculate_volatility()``를 내부적으로 재사용합니다.
"""

from __future__ import annotations

import math
from typing import List, Union

import numpy as np
import pandas as pd

from strategy.indicators import calculate_volatility

# VIX vs 실현변동성 평균 프리미엄 계수 (경험적 값)
_FEAR_PREMIUM_FACTOR: float = 1.2

# 드로다운 → VKOSPI 가산 스케일 (MDD 1% 당 VKOSPI 0.5% 포인트 추가)
_DRAWDOWN_SCALE: float = 0.005


def estimate_vkospi(
    close_prices: Union[pd.Series, List[float]],
    window: int = 20,
) -> float:
    """종가 시계열에서 합성 VKOSPI를 추정합니다.

    Args:
        close_prices: 일봉 종가 시계열 (오래된 순 → 최신 순).
            ``pd.Series`` 또는 ``list[float]`` 모두 허용.
        window: 롤링 변동성 계산 윈도우 (기본 20 거래일).

    Returns:
        추정 VKOSPI 값 (0~100 스케일, 연율화). 데이터 부족 시 20.0 반환.

    Examples:
        >>> prices = [300.0 + i * 0.5 for i in range(30)]
        >>> v = estimate_vkospi(prices)
        >>> 0 < v < 100
        True
    """
    if isinstance(close_prices, list):
        series = pd.Series(close_prices, dtype=float)
    else:
        series = close_prices.reset_index(drop=True).astype(float)

    if len(series) < window + 1:
        return 20.0  # 데이터 부족 시 중립값 반환

    # 1. 롤링 표준편차 (가격 단위) → 일별 수익률 기반으로 변환
    returns = series.pct_change().dropna()
    if len(returns) < window:
        return 20.0

    rolling_vol = calculate_volatility(returns, period=window)
    latest_daily_vol = rolling_vol.iloc[-1]

    if math.isnan(latest_daily_vol) or latest_daily_vol <= 0:
        return 20.0

    # 2. 연율화 × 공포 프리미엄
    annualized_vol = latest_daily_vol * math.sqrt(252) * _FEAR_PREMIUM_FACTOR

    # 3. 드로다운 추가분
    recent = series.iloc[-window:]
    peak = recent.max()
    trough = recent.min()
    drawdown_pct = (peak - trough) / peak * 100.0 if peak > 0 else 0.0
    drawdown_addon = drawdown_pct * _DRAWDOWN_SCALE

    vkospi = annualized_vol * 100.0 + drawdown_addon
    return float(min(max(vkospi, 0.0), 100.0))
