"""합성 VKOSPI 추정기 테스트."""

from __future__ import annotations

import pytest

from strategy.vkospi_estimator import estimate_vkospi


class TestEstimateVkospi:
    """estimate_vkospi() 함수 테스트."""

    def _make_stable_prices(self, n: int = 30, start: float = 300.0) -> list:
        """안정적인 가격 시계열 (소폭 상승)."""
        return [start + i * 0.1 for i in range(n)]

    def _make_volatile_prices(self, n: int = 30, start: float = 300.0) -> list:
        """고변동성 가격 시계열 (±10% 왕복)."""
        prices = [start]
        for i in range(1, n):
            factor = 1.10 if i % 2 == 0 else 0.90
            prices.append(prices[-1] * factor)
        return prices

    def _make_crash_prices(self, n: int = 30, start: float = 300.0) -> list:
        """급락 후 소폭 반등 시계열."""
        prices = [start - i * 3 for i in range(n)]
        return [max(p, 1.0) for p in prices]

    def test_insufficient_data_returns_default(self):
        """데이터 부족 시 기본값 20.0을 반환해야 합니다."""
        prices = [100.0, 101.0, 102.0]  # window=20보다 짧음
        result = estimate_vkospi(prices)
        assert result == 20.0

    def test_stable_regime_low_vkospi(self):
        """안정적인 시장에서 VKOSPI가 낮아야 합니다."""
        prices = self._make_stable_prices(40)
        result = estimate_vkospi(prices, window=20)
        assert 0 < result < 30  # 안정적 시장: 30 미만

    def test_volatile_regime_high_vkospi(self):
        """고변동성 시장에서 VKOSPI가 높아야 합니다."""
        prices = self._make_volatile_prices(40)
        result = estimate_vkospi(prices, window=20)
        assert result > 30  # 고변동성: 30 초과

    def test_stable_less_than_volatile(self):
        """안정적 시장 < 고변동성 시장 VKOSPI."""
        stable = estimate_vkospi(self._make_stable_prices(40))
        volatile = estimate_vkospi(self._make_volatile_prices(40))
        assert stable < volatile

    def test_output_range(self):
        """출력값이 0~100 범위 내여야 합니다."""
        for prices in [
            self._make_stable_prices(40),
            self._make_volatile_prices(40),
            self._make_crash_prices(40),
        ]:
            result = estimate_vkospi(prices)
            assert 0.0 <= result <= 100.0

    def test_accepts_list_and_series(self):
        """list와 pd.Series 모두 동일한 결과를 반환해야 합니다."""
        import pandas as pd

        prices_list = self._make_stable_prices(40)
        prices_series = pd.Series(prices_list)
        result_list = estimate_vkospi(prices_list)
        result_series = estimate_vkospi(prices_series)
        assert abs(result_list - result_series) < 1e-6

    def test_custom_window(self):
        """윈도우 크기 파라미터가 동작해야 합니다."""
        prices = self._make_stable_prices(50)
        result_10 = estimate_vkospi(prices, window=10)
        result_30 = estimate_vkospi(prices, window=30)
        # 두 값 모두 유효한 범위
        assert 0 < result_10 <= 100
        assert 0 < result_30 <= 100

    def test_threshold_30_detection(self):
        """VKOSPI > 30 옵션 추가 매수 기준값을 올바르게 감지해야 합니다."""
        # 안정적 시장은 30 미만
        stable_vkospi = estimate_vkospi(self._make_stable_prices(40))
        assert stable_vkospi < 30

        # 고변동성 시장은 30 초과
        volatile_vkospi = estimate_vkospi(self._make_volatile_prices(40))
        assert volatile_vkospi > 30
