"""레버리지+콜 전략 시그널 엔진 단위 테스트."""

from __future__ import annotations

import pytest
import pandas as pd
import numpy as np

from config.settings import Settings
from strategy.lev_call_signal import LevCallSignalEngine, LevCallSignalType


def _make_settings(**overrides) -> Settings:
    """테스트용 Settings 인스턴스를 생성합니다 (dotenv 없이)."""
    s = object.__new__(Settings)
    defaults = dict(
        lev_call_enabled=True,
        lev_etf_symbol="122630",
        lev_etf_alloc=0.70,
        call_option_alloc=0.30,
        call_strike=5500.0,
        call_expiry_months=2,
        entry_kospi_level=5400.0,
        exit_kospi_level=6000.0,
        take_profit_pct=0.20,
        take_profit_sell_ratio=0.50,
        margin_leverage=3.0,
        vkospi_option_add_threshold=30.0,
        rsi_period=14,
        rsi_oversold=30.0,
        rsi_overbought=70.0,
        ma_short=5,
        ma_long=20,
        stop_loss_rate=0.05,
        hedge_ratio=0.30,
    )
    defaults.update(overrides)
    for k, v in defaults.items():
        object.__setattr__(s, k, v)
    return s


def _make_flat_closes(n: int = 40, price: float = 15_000.0) -> pd.Series:
    """횡보 가격 시계열."""
    return pd.Series([price] * n, dtype=float)


def _make_uptrend_closes(n: int = 40, start: float = 13_000.0) -> pd.Series:
    """상승 추세 가격 시계열."""
    return pd.Series([start + i * 100 for i in range(n)], dtype=float)


def _make_downtrend_closes(n: int = 40, start: float = 17_000.0) -> pd.Series:
    """하락 추세 가격 시계열."""
    return pd.Series([start - i * 100 for i in range(n)], dtype=float)


def _make_oversold_then_golden(n: int = 40) -> pd.Series:
    """과매도 → 골든크로스 구간 시계열."""
    prices = (
        [15_000.0] * 5          # 초기 고점
        + [12_000.0] * 15       # 급락 → RSI 과매도
        + [12_500.0 + i * 200 for i in range(20)]  # 반등 → 골든크로스
    )
    return pd.Series(prices[:n], dtype=float)


class TestLevCallSignalEngine:
    """LevCallSignalEngine 테스트."""

    def test_insufficient_data_returns_hold(self):
        """데이터 부족 시 HOLD를 반환해야 합니다."""
        engine = LevCallSignalEngine(_make_settings())
        closes = pd.Series([15_000.0] * 10, dtype=float)
        signal = engine.evaluate(closes, kospi_level=5_600.0)
        assert signal.signal_type == LevCallSignalType.HOLD

    def test_entry_on_low_kospi(self):
        """코스피 ≤ entry_level 시 ENTRY 시그널을 반환해야 합니다."""
        engine = LevCallSignalEngine(_make_settings(entry_kospi_level=5400.0))
        closes = _make_flat_closes(40)
        signal = engine.evaluate(
            closes,
            kospi_level=5_350.0,  # < 5,400
            has_position=False,
        )
        assert signal.signal_type == LevCallSignalType.ENTRY
        assert "코스피 저점" in signal.reason

    def test_no_entry_when_kospi_above(self):
        """코스피 > entry_level이고 다른 조건 미충족 시 HOLD."""
        engine = LevCallSignalEngine(_make_settings())
        closes = _make_flat_closes(40)
        signal = engine.evaluate(
            closes,
            kospi_level=5_600.0,  # > 5,400
            has_position=False,
        )
        assert signal.signal_type == LevCallSignalType.HOLD

    def test_exit_on_high_kospi(self):
        """코스피 ≥ exit_level 시 EXIT 시그널을 반환해야 합니다."""
        engine = LevCallSignalEngine(_make_settings(exit_kospi_level=6000.0))
        closes = _make_flat_closes(40)
        signal = engine.evaluate(
            closes,
            kospi_level=6_050.0,  # ≥ 6,000
            has_position=True,
        )
        assert signal.signal_type == LevCallSignalType.EXIT
        assert "코스피 목표" in signal.reason

    def test_partial_exit_on_profit(self):
        """수익률 ≥ take_profit_pct 시 PARTIAL_EXIT 시그널."""
        engine = LevCallSignalEngine(_make_settings(take_profit_pct=0.20))
        closes = _make_flat_closes(40)
        signal = engine.evaluate(
            closes,
            kospi_level=5_600.0,  # EXIT 조건 미충족
            portfolio_pnl_pct=0.25,  # > 20%
            has_position=True,
        )
        assert signal.signal_type == LevCallSignalType.PARTIAL_EXIT

    def test_add_options_on_high_vkospi(self):
        """VKOSPI > threshold 시 ADD_OPTIONS 시그널."""
        engine = LevCallSignalEngine(_make_settings(vkospi_option_add_threshold=30.0))
        closes = _make_flat_closes(40)
        signal = engine.evaluate(
            closes,
            kospi_level=5_600.0,  # EXIT 조건 미충족
            vkospi=35.0,  # > 30
            portfolio_pnl_pct=0.05,  # 익절 미달
            has_position=True,
        )
        assert signal.signal_type == LevCallSignalType.ADD_OPTIONS

    def test_exit_priority_over_partial(self):
        """EXIT > PARTIAL_EXIT 우선순위 확인."""
        engine = LevCallSignalEngine(_make_settings())
        closes = _make_flat_closes(40)
        signal = engine.evaluate(
            closes,
            kospi_level=6_100.0,  # EXIT 조건
            portfolio_pnl_pct=0.30,  # PARTIAL_EXIT 조건도 충족
            has_position=True,
        )
        assert signal.signal_type == LevCallSignalType.EXIT

    def test_no_exit_without_position(self):
        """포지션 없으면 EXIT 조건이어도 ENTRY 또는 HOLD."""
        engine = LevCallSignalEngine(_make_settings())
        closes = _make_flat_closes(40)
        # 코스피 ≥ exit_level이지만 포지션 없음 → ENTRY/HOLD
        signal = engine.evaluate(
            closes,
            kospi_level=6_100.0,
            has_position=False,
        )
        # EXIT이 아닌 다른 시그널이어야 함
        assert signal.signal_type != LevCallSignalType.EXIT

    def test_signal_contains_rsi(self):
        """충분한 데이터가 있으면 RSI가 포함되어야 합니다."""
        engine = LevCallSignalEngine(_make_settings())
        closes = _make_flat_closes(40)
        signal = engine.evaluate(closes, kospi_level=5_600.0)
        assert signal.rsi is not None

    def test_vkospi_propagated(self):
        """VKOSPI 값이 시그널에 전달되어야 합니다."""
        engine = LevCallSignalEngine(_make_settings())
        closes = _make_flat_closes(40)
        signal = engine.evaluate(closes, kospi_level=5_600.0, vkospi=25.0)
        assert signal.vkospi == 25.0
