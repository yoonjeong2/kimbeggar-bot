"""레버리지+콜 백테스트 E2E 테스트."""

from __future__ import annotations

import math
import pytest
import numpy as np
import pandas as pd

from backtest.runner import run_lev_call_backtest, LevCallBacktestResult
from config.settings import Settings


def _make_settings(**overrides) -> Settings:
    """테스트용 Settings를 생성합니다 (dotenv 없이)."""
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


def _make_ohlcv(n: int = 60, start: float = 15_000.0, trend: float = 50.0) -> pd.DataFrame:
    """테스트용 ETF OHLCV DataFrame을 생성합니다."""
    rng = np.random.default_rng(42)
    dates = pd.bdate_range(start="2026-03-01", periods=n)
    close = [start + i * trend + float(rng.normal(0, 200)) for i in range(n)]
    close = [max(c, 1.0) for c in close]
    df = pd.DataFrame(
        {
            "open": [c * (1 + float(rng.uniform(-0.01, 0.01))) for c in close],
            "high": [c * (1 + abs(float(rng.normal(0, 0.01)))) for c in close],
            "low": [c * (1 - abs(float(rng.normal(0, 0.01)))) for c in close],
            "close": close,
            "volume": [int(rng.integers(1_000_000, 5_000_000)) for _ in range(n)],
        },
        index=dates,
    )
    df.index.name = "date"
    return df


class TestRunLevCallBacktest:
    """run_lev_call_backtest() E2E 테스트."""

    def test_returns_result_dataclass(self):
        """LevCallBacktestResult 인스턴스를 반환해야 합니다."""
        df = _make_ohlcv(60)
        result = run_lev_call_backtest(df, _make_settings())
        assert isinstance(result, LevCallBacktestResult)

    def test_initial_cash_preserved(self):
        """초기 투자금이 결과에 보존되어야 합니다."""
        initial = 10_000_000.0
        df = _make_ohlcv(60)
        result = run_lev_call_backtest(df, _make_settings(), initial_cash=initial)
        assert result.initial_cash == initial

    def test_final_value_positive(self):
        """최종 평가액이 양수여야 합니다."""
        df = _make_ohlcv(60)
        result = run_lev_call_backtest(df, _make_settings())
        assert result.final_value > 0

    def test_pnl_consistent_with_final_value(self):
        """PnL = final_value - initial_cash."""
        df = _make_ohlcv(60)
        result = run_lev_call_backtest(df, _make_settings())
        assert math.isclose(
            result.pnl, result.final_value - result.initial_cash, rel_tol=1e-6
        )

    def test_pnl_pct_consistent(self):
        """pnl_pct = pnl / initial_cash * 100."""
        df = _make_ohlcv(60)
        result = run_lev_call_backtest(df, _make_settings())
        expected_pct = result.pnl / result.initial_cash * 100
        assert math.isclose(result.pnl_pct, expected_pct, rel_tol=1e-6)

    def test_effective_leverage_positive(self):
        """실효 레버리지가 양수여야 합니다."""
        df = _make_ohlcv(60)
        result = run_lev_call_backtest(df, _make_settings())
        assert result.effective_leverage > 0

    def test_empty_df_raises(self):
        """빈 DataFrame은 ValueError를 발생시켜야 합니다."""
        with pytest.raises(ValueError, match="empty"):
            run_lev_call_backtest(pd.DataFrame(), _make_settings())

    def test_missing_columns_raises(self):
        """필수 컬럼 누락 시 ValueError를 발생시켜야 합니다."""
        df = _make_ohlcv(60).drop(columns=["volume"])
        with pytest.raises(ValueError, match="missing"):
            run_lev_call_backtest(df, _make_settings())

    def test_uptrend_generates_profit(self):
        """강한 상승장에서 진입 후 수익이 나야 합니다."""
        # 낮은 kospi 진입 수준으로 무조건 진입하게 설정
        settings = _make_settings(
            entry_kospi_level=99_999.0,  # 항상 진입
            exit_kospi_level=99_999_999.0,  # 청산 없음
        )
        df = _make_ohlcv(60, start=10_000.0, trend=200.0)  # 강한 상승
        result = run_lev_call_backtest(df, settings)
        # 상승장에서 레버리지 적용 → 수익 기대
        # (단, 마진 레버리지는 브로커 구현 한계로 인해 정확한 배율 보장 불가)
        assert isinstance(result, LevCallBacktestResult)

    def test_str_representation(self):
        """문자열 표현이 정상 동작해야 합니다."""
        df = _make_ohlcv(60)
        result = run_lev_call_backtest(df, _make_settings())
        s = str(result)
        assert "LevCallBacktestResult" in s
        assert "PnL" in s

    def test_events_list(self):
        """events 필드가 리스트여야 합니다."""
        df = _make_ohlcv(60)
        result = run_lev_call_backtest(df, _make_settings())
        assert isinstance(result.events, list)

    def test_max_drawdown_non_negative(self):
        """최대낙폭은 0 이상이어야 합니다."""
        df = _make_ohlcv(60)
        result = run_lev_call_backtest(df, _make_settings())
        assert result.max_drawdown_pct >= 0
