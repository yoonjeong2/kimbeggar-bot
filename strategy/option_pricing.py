"""Black-Scholes 콜 옵션 가격 모델.

scipy 없이 ``math.erf``만 사용하여 표준 정규 분포 CDF를 구현합니다.
KOSPI 200 옵션 거래승수(250,000원/포인트) 기반의 KRW 계약당 프리미엄 추정을 포함합니다.

References
----------
- Black, F. & Scholes, M. (1973). "The Pricing of Options and Corporate Liabilities."
  Journal of Political Economy, 81(3), 637–654.
- KOSPI 200 옵션 거래승수: 250,000원/포인트 (한국거래소)
"""

from __future__ import annotations

import math

# KOSPI 200 옵션 거래승수: 1포인트당 250,000원
_KOSPI200_MULTIPLIER: int = 250_000

# 한국 10년 국채 기본 리스크프리 금리 (연율)
_DEFAULT_RISK_FREE_RATE: float = 0.035


def _norm_cdf(x: float) -> float:
    """표준 정규 분포 CDF — ``math.erf`` 기반 구현.

    scipy 없이 정확한 CDF를 계산합니다.

    Args:
        x: 입력값.

    Returns:
        Φ(x) — 표준 정규 분포의 누적 확률.
    """
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes_call(
    S: float,
    K: float,
    T: float,
    r: float = _DEFAULT_RISK_FREE_RATE,
    sigma: float = 0.20,
) -> float:
    """Black-Scholes 유럽형 콜 옵션 가격을 계산합니다.

    Args:
        S: 현재 기초자산 가격 (KOSPI 200 포인트).
        K: 행사가 (포인트).
        T: 잔존 만기 (연율, 예: 2개월 = 2/12).
        r: 무위험 이자율 (연율, 기본값 3.5%).
        sigma: 기초자산 변동성 (연율, 기본값 20%).

    Returns:
        콜 옵션 가격 (포인트 단위). T ≤ 0이면 내재가치 max(S-K, 0) 반환.

    Raises:
        ValueError: S, K, sigma가 양수가 아닐 경우.
    """
    if S <= 0 or K <= 0:
        raise ValueError(f"S and K must be positive: S={S}, K={K}")
    if sigma <= 0:
        raise ValueError(f"sigma must be positive: sigma={sigma}")

    if T <= 0:
        return max(S - K, 0.0)

    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    call_price = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return max(call_price, 0.0)


def call_option_pnl(
    entry_premium: float,
    current_premium: float,
    num_contracts: float,
) -> float:
    """콜 옵션 포지션의 미실현 손익을 계산합니다.

    Args:
        entry_premium: 진입 시 옵션 프리미엄 (포인트 단위).
        current_premium: 현재 옵션 프리미엄 (포인트 단위).
        num_contracts: 계약 수 (소수 허용 — 가상 포지션용).

    Returns:
        미실현 손익 (KRW). 양수 = 이익, 음수 = 손실.
    """
    price_change_per_contract = (current_premium - entry_premium) * _KOSPI200_MULTIPLIER
    return price_change_per_contract * num_contracts


def estimate_premium_per_contract(
    S: float,
    K: float,
    T: float,
    r: float = _DEFAULT_RISK_FREE_RATE,
    sigma: float = 0.20,
    multiplier: int = _KOSPI200_MULTIPLIER,
) -> float:
    """1계약당 KRW 기준 콜 옵션 프리미엄을 추정합니다.

    Args:
        S: 현재 KOSPI 200 포인트.
        K: 행사가 (포인트).
        T: 잔존 만기 (연율).
        r: 무위험 이자율 (연율).
        sigma: 기초자산 변동성 (연율).
        multiplier: 거래승수 (기본 250,000원/포인트).

    Returns:
        1계약당 KRW 프리미엄.
    """
    price_in_points = black_scholes_call(S, K, T, r, sigma)
    return price_in_points * multiplier
