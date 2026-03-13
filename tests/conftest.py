"""Shared pytest fixtures for the KimBeggar test suite.

All fixtures that span multiple test modules live here so that pytest
discovers them automatically without any explicit imports.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest


@pytest.fixture
def mock_settings() -> MagicMock:
    """Return a MagicMock that mimics ``config.settings.Settings``.

    Using a mock avoids loading ``.env`` (which does not exist in CI) and
    keeps tests fully deterministic regardless of the local environment.
    """
    s = MagicMock()
    s.rsi_period = 14
    s.rsi_oversold = 30.0
    s.rsi_overbought = 70.0
    s.ma_short = 5
    s.ma_long = 20
    s.stop_loss_rate = 0.05
    s.hedge_ratio = 0.30
    return s


@pytest.fixture
def ascending_prices() -> pd.Series:
    """60-bar monotonically increasing close prices (50 → 109)."""
    return pd.Series(range(50, 110), dtype=float)


@pytest.fixture
def descending_prices() -> pd.Series:
    """60-bar monotonically decreasing close prices (109 → 50)."""
    return pd.Series(range(109, 49, -1), dtype=float)


@pytest.fixture
def ohlcv_ascending(ascending_prices) -> list:
    """OHLCV dict list built from ``ascending_prices`` (KIS format)."""
    return [{"stck_clpr": str(int(p))} for p in ascending_prices]


@pytest.fixture
def ohlcv_descending(descending_prices) -> list:
    """OHLCV dict list built from ``descending_prices`` (KIS format)."""
    return [{"stck_clpr": str(int(p))} for p in descending_prices]
