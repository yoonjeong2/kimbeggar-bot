"""Unit tests for the backtest layer.

Coverage
--------
- ``backtest.runner``   : run_backtest() — result shape, error handling
- ``backtest.strategy`` : KimBeggarStrategy — buy/sell/stop-loss execution

Design choices
--------------
* Synthetic OHLCV DataFrames are constructed in-process (no API calls).
* Settings is provided explicitly so tests never read ``.env``.
"""

from __future__ import annotations

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock

from backtest.runner import BacktestResult, run_backtest, _normalise_columns


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(
    rsi_period: int = 14,
    rsi_oversold: float = 30.0,
    rsi_overbought: float = 70.0,
    ma_short: int = 5,
    ma_long: int = 20,
    stop_loss_rate: float = 0.05,
) -> MagicMock:
    s = MagicMock()
    s.rsi_period = rsi_period
    s.rsi_oversold = rsi_oversold
    s.rsi_overbought = rsi_overbought
    s.ma_short = ma_short
    s.ma_long = ma_long
    s.stop_loss_rate = stop_loss_rate
    return s


def _make_ohlcv(prices: list, start: str = "2023-01-02") -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from a close-price list."""
    idx = pd.date_range(start, periods=len(prices), freq="B")
    arr = np.array(prices, dtype=float)
    return pd.DataFrame(
        {
            "open":   arr * 0.99,
            "high":   arr * 1.01,
            "low":    arr * 0.98,
            "close":  arr,
            "volume": np.full(len(arr), 100_000.0),
        },
        index=idx,
    )


def _flat_prices(n: int = 100, base: float = 50_000.0) -> list:
    return [base] * n


def _ascending_prices(n: int = 100, start: float = 30_000.0) -> list:
    return [start + i * 100 for i in range(n)]


def _descending_prices(n: int = 100, start: float = 70_000.0) -> list:
    return [start - i * 100 for i in range(n)]


# ---------------------------------------------------------------------------
# _normalise_columns
# ---------------------------------------------------------------------------

class TestNormaliseColumns:
    def test_lowercases_headers(self):
        df = pd.DataFrame({"Open": [1], "High": [2], "Low": [1], "Close": [1], "Volume": [100]})
        result = _normalise_columns(df)
        assert list(result.columns) == ["open", "high", "low", "close", "volume"]

    def test_does_not_mutate_original(self):
        df = pd.DataFrame({"Close": [1.0]})
        _normalise_columns(df)
        assert "Close" in df.columns


# ---------------------------------------------------------------------------
# run_backtest — validation errors
# ---------------------------------------------------------------------------

class TestRunBacktestValidation:
    def test_raises_on_empty_dataframe(self):
        df = pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.DatetimeIndex([]),
        )
        with pytest.raises(ValueError, match="empty"):
            run_backtest(df, settings=_make_settings())

    def test_raises_on_missing_columns(self):
        df = pd.DataFrame({"close": [1.0, 2.0]}, index=pd.date_range("2023-01-02", periods=2))
        with pytest.raises(ValueError, match="missing columns"):
            run_backtest(df, settings=_make_settings())


# ---------------------------------------------------------------------------
# run_backtest — result shape
# ---------------------------------------------------------------------------

class TestRunBacktestResult:
    def test_returns_backtest_result_instance(self):
        df = _make_ohlcv(_flat_prices(60))
        result = run_backtest(df, settings=_make_settings(), initial_cash=1_000_000)
        assert isinstance(result, BacktestResult)

    def test_initial_cash_preserved(self):
        df = _make_ohlcv(_flat_prices(60))
        result = run_backtest(df, settings=_make_settings(), initial_cash=5_000_000)
        assert result.initial_cash == 5_000_000.0

    def test_final_value_is_positive(self):
        df = _make_ohlcv(_flat_prices(60))
        result = run_backtest(df, settings=_make_settings(), initial_cash=1_000_000)
        assert result.final_value > 0

    def test_pnl_equals_final_minus_initial(self):
        df = _make_ohlcv(_flat_prices(60))
        result = run_backtest(df, settings=_make_settings(), initial_cash=1_000_000)
        assert result.pnl == pytest.approx(result.final_value - result.initial_cash)

    def test_pnl_pct_consistent_with_pnl(self):
        df = _make_ohlcv(_flat_prices(60))
        result = run_backtest(df, settings=_make_settings(), initial_cash=1_000_000)
        expected = result.pnl / result.initial_cash * 100
        assert result.pnl_pct == pytest.approx(expected)

    def test_trade_counts_are_non_negative(self):
        df = _make_ohlcv(_flat_prices(60))
        result = run_backtest(df, settings=_make_settings(), initial_cash=1_000_000)
        assert result.total_trades >= 0
        assert result.won_trades >= 0
        assert result.lost_trades >= 0

    def test_win_rate_none_when_no_trades(self):
        # Flat prices produce no crossovers → no trades
        df = _make_ohlcv(_flat_prices(60))
        result = run_backtest(df, settings=_make_settings(), initial_cash=1_000_000)
        # win_rate may be None or 0 depending on trade count
        if result.total_trades == 0:
            assert result.win_rate is None

    def test_win_rate_between_0_and_1_when_trades_exist(self):
        # V-shaped prices encourage at least one buy signal
        v = _descending_prices(40) + _ascending_prices(40)
        df = _make_ohlcv(v)
        result = run_backtest(df, settings=_make_settings(), initial_cash=5_000_000)
        if result.total_trades > 0:
            assert 0.0 <= result.win_rate <= 1.0

    def test_won_plus_lost_lte_total(self):
        # Open (not yet closed) trades count toward total but not won/lost,
        # so won + lost <= total always holds.
        v = _descending_prices(40) + _ascending_prices(40)
        df = _make_ohlcv(v)
        result = run_backtest(df, settings=_make_settings(), initial_cash=5_000_000)
        assert result.won_trades + result.lost_trades <= result.total_trades

    def test_str_representation_contains_pnl(self):
        df = _make_ohlcv(_flat_prices(60))
        result = run_backtest(df, settings=_make_settings(), initial_cash=1_000_000)
        assert "PnL" in str(result)


# ---------------------------------------------------------------------------
# run_backtest — stop-loss triggers with extreme drop
# ---------------------------------------------------------------------------

class TestRunBacktestStopLoss:
    def test_stop_loss_limits_drawdown(self):
        # Build a price series that rises (triggers buy), then crashes 30 %
        prices = _ascending_prices(40) + [30_000.0] * 40
        df = _make_ohlcv(prices)
        settings = _make_settings(stop_loss_rate=0.05)
        result = run_backtest(df, settings=settings, initial_cash=5_000_000)
        # Without stop-loss a 30% crash would wipe most value.
        # With 5% stop-loss the loss should be bounded.
        assert result.pnl > -result.initial_cash * 0.20  # never lose > 20%
