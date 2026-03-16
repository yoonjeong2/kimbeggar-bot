"""Black-Scholes 옵션 가격 모델 테스트."""

from __future__ import annotations

import math
import pytest

from strategy.option_pricing import (
    black_scholes_call,
    call_option_pnl,
    estimate_premium_per_contract,
    _KOSPI200_MULTIPLIER,
)


class TestBlackScholesCall:
    """black_scholes_call() 함수 테스트."""

    def test_atm_option_positive(self):
        """ATM(등가격) 옵션은 양수여야 합니다."""
        price = black_scholes_call(S=300.0, K=300.0, T=0.5, r=0.035, sigma=0.20)
        assert price > 0

    def test_deep_itm_option_near_intrinsic(self):
        """Deep ITM 옵션은 내재가치에 근접해야 합니다."""
        S, K = 400.0, 300.0
        price = black_scholes_call(S=S, K=K, T=0.5, r=0.035, sigma=0.20)
        intrinsic = S - K
        # BS 가격 ≥ 내재가치
        assert price >= intrinsic * 0.95

    def test_deep_otm_option_small(self):
        """Deep OTM 옵션은 작은 값이어야 합니다."""
        price = black_scholes_call(S=200.0, K=400.0, T=0.1, r=0.035, sigma=0.20)
        assert price < 1.0  # 포인트 단위에서 매우 작아야 함

    def test_expired_option_returns_intrinsic(self):
        """만기(T=0) 옵션은 내재가치를 반환해야 합니다."""
        # ITM
        price_itm = black_scholes_call(S=320.0, K=300.0, T=0.0)
        assert math.isclose(price_itm, 20.0, rel_tol=1e-6)
        # OTM
        price_otm = black_scholes_call(S=280.0, K=300.0, T=0.0)
        assert price_otm == 0.0

    def test_longer_maturity_higher_price(self):
        """만기가 길수록 옵션 가격이 높아야 합니다 (시간가치)."""
        price_1m = black_scholes_call(S=300.0, K=300.0, T=1/12, sigma=0.20)
        price_3m = black_scholes_call(S=300.0, K=300.0, T=3/12, sigma=0.20)
        assert price_3m > price_1m

    def test_higher_vol_higher_price(self):
        """변동성이 높을수록 옵션 가격이 높아야 합니다."""
        price_low = black_scholes_call(S=300.0, K=300.0, T=0.5, sigma=0.15)
        price_high = black_scholes_call(S=300.0, K=300.0, T=0.5, sigma=0.40)
        assert price_high > price_low

    def test_invalid_inputs_raise(self):
        """유효하지 않은 입력은 ValueError를 발생시켜야 합니다."""
        with pytest.raises(ValueError):
            black_scholes_call(S=-100.0, K=300.0, T=0.5)
        with pytest.raises(ValueError):
            black_scholes_call(S=300.0, K=300.0, T=0.5, sigma=-0.1)

    def test_kospi_realistic_values(self):
        """KOSPI 200 실제 수준(5,400 행사가 5,500)에서 합리적인 결과."""
        price = black_scholes_call(
            S=5_400.0,
            K=5_500.0,
            T=2/12,
            r=0.035,
            sigma=0.20,
        )
        # 5,400 vs 5,500 OTM, 2개월 만기 → 포인트 단위 현실적 범위 (5~50pt)
        assert 1.0 < price < 200.0


class TestCallOptionPnl:
    """call_option_pnl() 함수 테스트."""

    def test_profit_when_premium_rises(self):
        """프리미엄이 오르면 이익이어야 합니다."""
        pnl = call_option_pnl(
            entry_premium=10.0,
            current_premium=15.0,
            num_contracts=1.0,
        )
        expected = (15.0 - 10.0) * _KOSPI200_MULTIPLIER
        assert math.isclose(pnl, expected, rel_tol=1e-9)

    def test_loss_when_premium_falls(self):
        """프리미엄이 하락하면 손실이어야 합니다."""
        pnl = call_option_pnl(
            entry_premium=10.0,
            current_premium=5.0,
            num_contracts=1.0,
        )
        assert pnl < 0

    def test_zero_pnl_at_entry(self):
        """진입 직후 P&L은 0이어야 합니다."""
        pnl = call_option_pnl(5.0, 5.0, 2.0)
        assert pnl == 0.0

    def test_scales_with_contracts(self):
        """계약 수에 비례하여 P&L이 증가해야 합니다."""
        pnl_1 = call_option_pnl(5.0, 10.0, 1.0)
        pnl_2 = call_option_pnl(5.0, 10.0, 2.0)
        assert math.isclose(pnl_2, pnl_1 * 2, rel_tol=1e-9)


class TestEstimatePremiumPerContract:
    """estimate_premium_per_contract() 함수 테스트."""

    def test_returns_krw_positive(self):
        """KRW 기준 프리미엄은 양수여야 합니다."""
        premium = estimate_premium_per_contract(
            S=5_400.0, K=5_500.0, T=2/12, sigma=0.20
        )
        assert premium > 0

    def test_multiplier_applied(self):
        """250,000원 거래승수가 적용되어야 합니다."""
        point_price = black_scholes_call(S=5_400.0, K=5_500.0, T=2/12, sigma=0.20)
        krw_premium = estimate_premium_per_contract(
            S=5_400.0, K=5_500.0, T=2/12, sigma=0.20
        )
        assert math.isclose(krw_premium, point_price * _KOSPI200_MULTIPLIER, rel_tol=1e-6)

    def test_realistic_range(self):
        """현실적인 범위의 프리미엄인지 확인합니다.

        KOSPI 200 옵션은 거래승수 250,000원/포인트이므로
        5,400pt 기초자산 기준 계약당 수백만~수억 원 수준입니다.
        """
        premium = estimate_premium_per_contract(
            S=5_400.0, K=5_500.0, T=2/12, sigma=0.20
        )
        # 5,400 vs 5,500 OTM, 2개월: 약 100~200포인트 × 250,000 = 2,500만~5,000만원
        assert 1_000_000 < premium < 500_000_000
