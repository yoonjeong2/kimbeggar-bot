"""Unit tests for the strategy layer.

Coverage
--------
- ``strategy.indicators``  : RSI, SMA, EMA, crossovers, volatility
- ``strategy.hedge_logic`` : dynamic hedge-ratio calculation and descriptions
- ``strategy.signal``      : SignalEngine — all signal types and edge cases

Design choices
--------------
* ``Settings`` is mocked so tests never read ``.env`` or hit external APIs.
* Synthetic price series are constructed to guarantee deterministic indicator
  values and cross events at known positions.
* Each test asserts one logical concern (single-responsibility).
"""

from __future__ import annotations

import pytest
import pandas as pd

from strategy.indicators import (
    calculate_rsi,
    calculate_moving_average,
    calculate_ema,
    detect_golden_cross,
    detect_dead_cross,
    calculate_volatility,
)
from strategy.hedge_logic import (
    MAX_RATIO,
    MIN_RATIO,
    calculate_hedge_ratio,
    describe_hedge,
)
from strategy.signal import SignalEngine, SignalType


# ===========================================================================
# strategy.indicators
# ===========================================================================

class TestCalculateRsi:
    """Tests for ``calculate_rsi``."""

    def test_returns_series(self, ascending_prices):
        result = calculate_rsi(ascending_prices, period=14)
        assert isinstance(result, pd.Series)

    def test_length_matches_input(self, ascending_prices):
        result = calculate_rsi(ascending_prices, period=14)
        assert len(result) == len(ascending_prices)

    def test_first_period_values_are_nan(self, ascending_prices):
        result = calculate_rsi(ascending_prices, period=14)
        # ta library (Wilder smoothing) needs exactly period data points for the
        # first value, so the first (period - 1) = 13 entries are NaN.
        assert result.iloc[:13].isna().all()
        assert not pd.isna(result.iloc[13])

    def test_rsi_range_0_to_100(self, ascending_prices):
        result = calculate_rsi(ascending_prices, period=14).dropna()
        assert (result >= 0).all() and (result <= 100).all()

    def test_ascending_prices_yield_high_rsi(self, ascending_prices):
        """Monotonically rising prices → RSI close to 100."""
        result = calculate_rsi(ascending_prices, period=14).dropna()
        assert result.iloc[-1] > 70

    def test_descending_prices_yield_low_rsi(self, descending_prices):
        """Monotonically falling prices → RSI close to 0."""
        result = calculate_rsi(descending_prices, period=14).dropna()
        assert result.iloc[-1] < 30


class TestCalculateMovingAverage:
    """Tests for ``calculate_moving_average`` (SMA)."""

    def test_returns_series(self, ascending_prices):
        result = calculate_moving_average(ascending_prices, period=5)
        assert isinstance(result, pd.Series)

    def test_warm_up_window_is_nan(self, ascending_prices):
        result = calculate_moving_average(ascending_prices, period=5)
        assert result.iloc[:4].isna().all()

    def test_sma_is_arithmetic_mean(self):
        prices = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
        result = calculate_moving_average(prices, period=5)
        assert result.iloc[-1] == pytest.approx(30.0)

    def test_sma5_lags_less_than_sma20(self, ascending_prices):
        """For ascending prices, short SMA is always above long SMA."""
        sma5 = calculate_moving_average(ascending_prices, period=5)
        sma20 = calculate_moving_average(ascending_prices, period=20)
        valid = sma5.dropna().index.intersection(sma20.dropna().index)
        assert (sma5[valid] > sma20[valid]).all()


class TestCalculateEma:
    """Tests for ``calculate_ema`` (EMA)."""

    def test_returns_series(self, ascending_prices):
        result = calculate_ema(ascending_prices, period=10)
        assert isinstance(result, pd.Series)

    def test_ema_reacts_faster_than_sma(self):
        """After a price spike EMA should be closer to spike than SMA."""
        base = [100.0] * 30
        spike = base + [200.0] * 5
        prices = pd.Series(spike)
        sma = calculate_moving_average(prices, period=10).iloc[-1]
        ema = calculate_ema(prices, period=10).iloc[-1]
        # EMA gives more weight to the recent spike → higher value
        assert ema > sma


class TestDetectGoldenCross:
    """Tests for ``detect_golden_cross``."""

    def test_returns_boolean_series(self):
        short_ma = pd.Series([1.0, 2.0, 3.0, 4.0])
        long_ma = pd.Series([4.0, 3.0, 3.0, 3.5])
        result = detect_golden_cross(short_ma, long_ma)
        assert result.dtype == bool

    def test_golden_cross_detected_at_correct_bar(self):
        """short crosses above long at index 3."""
        short_ma = pd.Series([1.0, 2.0, 3.0, 5.0, 5.5])
        long_ma = pd.Series([5.0, 4.0, 4.0, 4.0, 3.0])
        # index 2: short=3 < long=4  →  index 3: short=5 > long=4
        result = detect_golden_cross(short_ma, long_ma)
        assert result.iloc[3] is True or result.iloc[3] == True
        assert not result.iloc[2]

    def test_no_false_positives_when_already_above(self):
        """short was already above long — no cross should fire."""
        short_ma = pd.Series([5.0, 6.0, 7.0, 8.0])
        long_ma = pd.Series([1.0, 2.0, 3.0, 4.0])
        result = detect_golden_cross(short_ma, long_ma)
        # No new crossings after the first bar
        assert not result.iloc[1:].any()

    def test_ascending_series_triggers_cross(self):
        """V-shaped series: sharp fall then recovery → SMA5 crosses above SMA20."""
        fall = pd.Series(range(100, 50, -1), dtype=float)   # 50 bars down
        rise = pd.Series(range(50, 110), dtype=float)        # 60 bars up
        prices = pd.concat([fall, rise], ignore_index=True)
        sma5 = calculate_moving_average(prices, period=5)
        sma20 = calculate_moving_average(prices, period=20)
        crosses = detect_golden_cross(sma5, sma20)
        assert crosses.sum() >= 1


class TestDetectDeadCross:
    """Tests for ``detect_dead_cross``."""

    def test_dead_cross_detected_at_correct_bar(self):
        """short crosses below long at index 3."""
        short_ma = pd.Series([8.0, 7.0, 5.0, 2.0, 1.0])
        long_ma = pd.Series([1.0, 2.0, 3.0, 3.0, 4.0])
        # index 2: short=5 > long=3  →  index 3: short=2 < long=3
        result = detect_dead_cross(short_ma, long_ma)
        assert result.iloc[3] is True or result.iloc[3] == True
        assert not result.iloc[2]

    def test_descending_series_triggers_dead_cross(self):
        """A-shaped series: rise then sharp fall → SMA5 crosses below SMA20."""
        rise = pd.Series(range(50, 110), dtype=float)        # 60 bars up
        fall = pd.Series(range(110, 50, -1), dtype=float)    # 60 bars down
        prices = pd.concat([rise, fall], ignore_index=True)
        sma5 = calculate_moving_average(prices, period=5)
        sma20 = calculate_moving_average(prices, period=20)
        crosses = detect_dead_cross(sma5, sma20)
        assert crosses.sum() >= 1

    def test_golden_and_dead_cross_are_mutually_exclusive_per_bar(self):
        """At any single bar, both golden and dead cross cannot both be True."""
        prices = pd.Series(
            [float(x) for x in range(50, 80)] + [float(x) for x in range(79, 49, -1)]
        )
        sma5 = calculate_moving_average(prices, period=5)
        sma20 = calculate_moving_average(prices, period=20)
        gc = detect_golden_cross(sma5, sma20)
        dc = detect_dead_cross(sma5, sma20)
        assert not (gc & dc).any()


class TestCalculateVolatility:
    """Tests for ``calculate_volatility``."""

    def test_returns_series(self, ascending_prices):
        result = calculate_volatility(ascending_prices, period=20)
        assert isinstance(result, pd.Series)

    def test_constant_prices_have_zero_volatility(self):
        prices = pd.Series([100.0] * 30)
        result = calculate_volatility(prices, period=20).dropna()
        # All values must be effectively zero (floating-point safe comparison)
        assert result.abs().max() < 1e-10

    def test_volatile_series_has_higher_vol_than_stable(self):
        stable = pd.Series([100.0] * 30)
        volatile = pd.Series([100.0 + (i % 2) * 20 for i in range(30)], dtype=float)
        vol_stable = calculate_volatility(stable, 20).dropna().iloc[-1]
        vol_volatile = calculate_volatility(volatile, 20).dropna().iloc[-1]
        assert vol_volatile > vol_stable


# ===========================================================================
# strategy.hedge_logic
# ===========================================================================

class TestCalculateHedgeRatio:
    """Tests for ``calculate_hedge_ratio``."""

    def test_price_above_ma_no_index_drop_returns_base(self):
        """Price above long MA and flat index → pure base ratio."""
        ratio = calculate_hedge_ratio(
            current_price=62_000,
            long_ma=60_000,
            base_ratio=0.30,
            index_change_rate=0.0,
        )
        assert ratio == pytest.approx(0.30, abs=1e-4)

    def test_price_below_ma_increases_ratio(self):
        """Price below MA should push ratio above base."""
        ratio = calculate_hedge_ratio(
            current_price=57_000,
            long_ma=60_000,
            base_ratio=0.30,
            index_change_rate=0.0,
        )
        assert ratio > 0.30

    def test_index_drop_increases_ratio(self):
        ratio = calculate_hedge_ratio(
            current_price=60_000,
            long_ma=60_000,
            base_ratio=0.30,
            index_change_rate=-3.0,
        )
        assert ratio > 0.30

    def test_combined_risk_factors_sum_correctly(self):
        """Verify the formula: base + MA_risk + index_risk."""
        price, long_ma = 58_000.0, 60_000.0
        base = 0.30
        idx_rate = -2.0

        ma_dev = (long_ma - price) / long_ma          # ≈ 0.0333
        from strategy.hedge_logic import MA_DEVIATION_SCALE, INDEX_DROP_SCALE
        expected = base + ma_dev * MA_DEVIATION_SCALE + (2.0 / 100) * INDEX_DROP_SCALE
        result = calculate_hedge_ratio(price, long_ma, base, idx_rate)
        assert result == pytest.approx(expected, abs=1e-4)

    def test_ratio_clamped_at_max(self):
        """Extreme inputs must not exceed MAX_RATIO."""
        ratio = calculate_hedge_ratio(
            current_price=10_000,
            long_ma=100_000,
            base_ratio=0.50,
            index_change_rate=-20.0,
        )
        assert ratio == pytest.approx(MAX_RATIO, abs=1e-4)

    def test_ratio_never_below_min(self):
        ratio = calculate_hedge_ratio(
            current_price=100_000,
            long_ma=50_000,
            base_ratio=0.0,
            index_change_rate=5.0,
        )
        assert ratio >= MIN_RATIO

    def test_positive_index_change_does_not_increase_ratio(self):
        """A rising market should not inflate the hedge ratio."""
        ratio_flat = calculate_hedge_ratio(60_000, 60_000, 0.30, 0.0)
        ratio_bull = calculate_hedge_ratio(60_000, 60_000, 0.30, 3.0)
        assert ratio_bull == pytest.approx(ratio_flat, abs=1e-4)


class TestDescribeHedge:
    """Tests for ``describe_hedge`` threshold descriptions."""

    def test_strong_hedge_label(self):
        desc = describe_hedge(0.65)
        assert "강헤지" in desc

    def test_medium_hedge_label(self):
        desc = describe_hedge(0.45)
        assert "중헤지" in desc

    def test_weak_hedge_label(self):
        desc = describe_hedge(0.25)
        assert "약헤지" in desc

    def test_no_hedge_label(self):
        desc = describe_hedge(0.10)
        assert "불필요" in desc

    def test_ratio_appears_in_description(self):
        desc = describe_hedge(0.50)
        assert "50%" in desc


# ===========================================================================
# strategy.signal — SignalEngine
# ===========================================================================

class TestCheckStopLoss:
    """Tests for ``SignalEngine.check_stop_loss``."""

    def test_triggered_below_floor(self, mock_settings):
        engine = SignalEngine(mock_settings)
        # floor = 1000 * (1 - 0.05) = 950; price 900 is below floor
        assert engine.check_stop_loss(900.0, 1000.0) is True

    def test_triggered_exactly_at_floor(self, mock_settings):
        engine = SignalEngine(mock_settings)
        assert engine.check_stop_loss(950.0, 1000.0) is True

    def test_not_triggered_above_floor(self, mock_settings):
        engine = SignalEngine(mock_settings)
        assert engine.check_stop_loss(960.0, 1000.0) is False

    def test_not_triggered_when_price_equals_entry(self, mock_settings):
        engine = SignalEngine(mock_settings)
        assert engine.check_stop_loss(1000.0, 1000.0) is False


class TestCheckBuySignal:
    """Tests for ``SignalEngine.check_buy_signal``."""

    def _make_golden_cross_at_last(self):
        """Return (prices, rsi, short_ma, long_ma) with golden cross at [-1]."""
        n = 25
        prices = pd.Series([100.0] * n)
        rsi = pd.Series([50.0] * (n - 1) + [25.0])      # oversold last bar
        # short was below long, now crosses above
        short_ma = pd.Series([79.0] * (n - 1) + [81.0])
        long_ma = pd.Series([80.0] * n)
        return prices, rsi, short_ma, long_ma

    def test_buy_signal_when_oversold_and_golden_cross(self, mock_settings):
        engine = SignalEngine(mock_settings)
        prices, rsi, short_ma, long_ma = self._make_golden_cross_at_last()
        assert engine.check_buy_signal(prices, rsi, short_ma, long_ma) is True

    def test_no_buy_signal_when_only_oversold(self, mock_settings):
        """Golden cross is missing — signal must not fire."""
        engine = SignalEngine(mock_settings)
        n = 25
        prices = pd.Series([100.0] * n)
        rsi = pd.Series([25.0] * n)           # oversold
        short_ma = pd.Series([75.0] * n)      # short always below long → no cross
        long_ma = pd.Series([80.0] * n)
        assert engine.check_buy_signal(prices, rsi, short_ma, long_ma) is False

    def test_no_buy_signal_when_only_golden_cross(self, mock_settings):
        """RSI is neutral — signal must not fire even with golden cross."""
        engine = SignalEngine(mock_settings)
        n = 25
        prices = pd.Series([100.0] * n)
        rsi = pd.Series([50.0] * n)            # neutral RSI
        short_ma = pd.Series([79.0] * (n - 1) + [81.0])
        long_ma = pd.Series([80.0] * n)
        assert engine.check_buy_signal(prices, rsi, short_ma, long_ma) is False


class TestCheckSellSignal:
    """Tests for ``SignalEngine.check_sell_signal``."""

    def _make_dead_cross_at_last(self):
        n = 25
        prices = pd.Series([100.0] * n)
        rsi = pd.Series([50.0] * (n - 1) + [75.0])   # overbought last bar
        short_ma = pd.Series([81.0] * (n - 1) + [79.0])
        long_ma = pd.Series([80.0] * n)
        return prices, rsi, short_ma, long_ma

    def test_sell_signal_when_overbought_and_dead_cross(self, mock_settings):
        engine = SignalEngine(mock_settings)
        prices, rsi, short_ma, long_ma = self._make_dead_cross_at_last()
        assert engine.check_sell_signal(prices, rsi, short_ma, long_ma) is True

    def test_no_sell_signal_when_only_overbought(self, mock_settings):
        engine = SignalEngine(mock_settings)
        n = 25
        prices = pd.Series([100.0] * n)
        rsi = pd.Series([75.0] * n)
        short_ma = pd.Series([85.0] * n)    # short always above long → no cross
        long_ma = pd.Series([80.0] * n)
        assert engine.check_sell_signal(prices, rsi, short_ma, long_ma) is False

    def test_no_sell_signal_when_only_dead_cross(self, mock_settings):
        engine = SignalEngine(mock_settings)
        n = 25
        prices = pd.Series([100.0] * n)
        rsi = pd.Series([50.0] * n)          # neutral RSI
        short_ma = pd.Series([81.0] * (n - 1) + [79.0])
        long_ma = pd.Series([80.0] * n)
        assert engine.check_sell_signal(prices, rsi, short_ma, long_ma) is False


class TestCheckHedgeSignal:
    """Tests for ``SignalEngine.check_hedge_signal``."""

    def test_triggered_when_index_drops_past_threshold(self, mock_settings):
        engine = SignalEngine(mock_settings)
        assert engine.check_hedge_signal({"bstp_nmix_prdy_ctrt": "-2.0"}) is True

    def test_triggered_exactly_at_threshold(self, mock_settings):
        engine = SignalEngine(mock_settings)
        assert engine.check_hedge_signal({"bstp_nmix_prdy_ctrt": "-1.5"}) is True

    def test_not_triggered_when_drop_is_small(self, mock_settings):
        engine = SignalEngine(mock_settings)
        assert engine.check_hedge_signal({"bstp_nmix_prdy_ctrt": "-1.0"}) is False

    def test_not_triggered_on_positive_change(self, mock_settings):
        engine = SignalEngine(mock_settings)
        assert engine.check_hedge_signal({"bstp_nmix_prdy_ctrt": "1.2"}) is False

    def test_returns_false_on_invalid_data(self, mock_settings):
        engine = SignalEngine(mock_settings)
        assert engine.check_hedge_signal({"bstp_nmix_prdy_ctrt": "N/A"}) is False
        assert engine.check_hedge_signal({}) is False


class TestSignalEngineEvaluate:
    """Integration-style tests for ``SignalEngine.evaluate``."""

    def test_returns_hold_on_empty_data(self, mock_settings):
        engine = SignalEngine(mock_settings)
        signal = engine.evaluate("TEST", [])
        assert signal.signal_type == SignalType.HOLD

    def test_returns_hold_when_insufficient_candles(self, mock_settings):
        engine = SignalEngine(mock_settings)
        ohlcv = [{"stck_clpr": str(i + 50)} for i in range(10)]  # only 10 bars
        signal = engine.evaluate("TEST", ohlcv)
        assert signal.signal_type == SignalType.HOLD

    def test_symbol_is_preserved_in_signal(self, mock_settings, ohlcv_ascending):
        engine = SignalEngine(mock_settings)
        signal = engine.evaluate("005930", ohlcv_ascending)
        assert signal.symbol == "005930"

    def test_price_is_last_close(self, mock_settings, ohlcv_ascending, ascending_prices):
        engine = SignalEngine(mock_settings)
        signal = engine.evaluate("TEST", ohlcv_ascending)
        assert signal.price == pytest.approx(float(ascending_prices.iloc[-1]))

    def test_rsi_is_populated(self, mock_settings, ohlcv_ascending):
        engine = SignalEngine(mock_settings)
        signal = engine.evaluate("TEST", ohlcv_ascending)
        assert signal.rsi is not None
        assert 0.0 <= signal.rsi <= 100.0

    def test_stop_loss_takes_priority_over_other_signals(
        self, mock_settings, ohlcv_ascending
    ):
        """Entry price well above current price → STOP_LOSS regardless of other indicators."""
        engine = SignalEngine(mock_settings)
        # ascending_prices ends at ~109; entry at 10_000 → 99 % drawdown
        signal = engine.evaluate("TEST", ohlcv_ascending, entry_price=10_000.0)
        assert signal.signal_type == SignalType.STOP_LOSS

    def test_hold_when_no_entry_price_and_conditions_not_met(
        self, mock_settings, ohlcv_ascending
    ):
        """Steady ascending trend: RSI high, no fresh golden cross → HOLD or SELL."""
        engine = SignalEngine(mock_settings)
        signal = engine.evaluate("TEST", ohlcv_ascending)
        # Monotonic ascent doesn't produce a new golden cross → HOLD (or SELL if RSI OB)
        assert signal.signal_type in (SignalType.HOLD, SignalType.SELL)

    def test_non_numeric_close_prices_are_handled(self, mock_settings):
        """Malformed price strings must not raise — engine should return HOLD."""
        engine = SignalEngine(mock_settings)
        bad_ohlcv = [{"stck_clpr": "N/A"}] * 35
        signal = engine.evaluate("TEST", bad_ohlcv)
        assert signal.signal_type == SignalType.HOLD

    def test_stop_loss_boundary_not_triggered(self, mock_settings, ohlcv_ascending):
        """Price just above stop-loss floor should NOT trigger STOP_LOSS."""
        engine = SignalEngine(mock_settings)
        # ascending_prices ends at 109; entry=110 → floor=104.5; price 109 > 104.5
        signal = engine.evaluate("TEST", ohlcv_ascending, entry_price=110.0)
        assert signal.signal_type != SignalType.STOP_LOSS
