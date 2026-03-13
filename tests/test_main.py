"""Unit tests for main.run_cycle.

All external dependencies (KIS API, SignalEngine, NotifierService) are mocked
so tests are fully deterministic and never hit live APIs.
"""

from __future__ import annotations

from typing import Dict, Optional
from unittest.mock import MagicMock, call, patch

import pytest

from main import run_cycle
from strategy.signal import Signal, SignalType

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_settings(
    watch_symbols=None,
    hedge_ratio: float = 0.30,
    monitor_interval: int = 5,
) -> MagicMock:
    s = MagicMock()
    s.watch_symbols = watch_symbols or ["005930"]
    s.hedge_ratio = hedge_ratio
    s.monitor_interval_minutes = monitor_interval
    return s


def _make_signal(
    symbol: str = "005930",
    signal_type: SignalType = SignalType.HOLD,
    price: float = 70_000.0,
    rsi: float = 50.0,
    ma_short: float = 70_000.0,
    ma_long: float = 69_000.0,
) -> Signal:
    return Signal(
        symbol=symbol,
        signal_type=signal_type,
        price=price,
        reason="test",
        rsi=rsi,
        ma_short=ma_short,
        ma_long=ma_long,
    )


def _run(
    signal: Signal,
    entry_prices: Optional[Dict] = None,
    index_change: str = "0.5",
    hedge_triggered: bool = False,
) -> Dict:
    settings = _make_settings()
    kis = MagicMock()
    kis.get_index_data.return_value = {"bstp_nmix_prdy_ctrt": index_change}
    kis.get_ohlcv_daily.return_value = [{"stck_clpr": "70000"}]
    kis.get_current_price.return_value = {"stck_prpr": str(int(signal.price))}

    engine = MagicMock()
    engine.check_hedge_signal.return_value = hedge_triggered
    engine.evaluate.return_value = signal

    notifier = MagicMock()
    ep = entry_prices if entry_prices is not None else {}

    run_cycle(settings, kis, engine, notifier, ep)
    return {"engine": engine, "notifier": notifier, "entry_prices": ep}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRunCycleHold:
    def test_hold_does_not_call_send_signal(self):
        ctx = _run(_make_signal(signal_type=SignalType.HOLD))
        ctx["notifier"].send_signal.assert_not_called()

    def test_hold_does_not_record_entry_price(self):
        ctx = _run(_make_signal(signal_type=SignalType.HOLD))
        assert ctx["entry_prices"] == {}


class TestRunCycleBuy:
    def test_buy_calls_send_signal(self):
        ctx = _run(_make_signal(signal_type=SignalType.BUY, price=71_500.0))
        ctx["notifier"].send_signal.assert_called_once()

    def test_buy_records_entry_price(self):
        ctx = _run(
            _make_signal(symbol="005930", signal_type=SignalType.BUY, price=71_500.0)
        )
        assert ctx["entry_prices"].get("005930") == pytest.approx(71_500.0)

    def test_buy_does_not_clear_existing_entry(self):
        existing = {"000660": 50_000.0}
        ctx = _run(
            _make_signal(symbol="005930", signal_type=SignalType.BUY, price=71_500.0),
            entry_prices=existing,
        )
        # The other symbol's entry must survive
        assert ctx["entry_prices"].get("000660") == pytest.approx(50_000.0)


class TestRunCycleSell:
    def test_sell_calls_send_signal(self):
        ctx = _run(_make_signal(signal_type=SignalType.SELL))
        ctx["notifier"].send_signal.assert_called_once()

    def test_sell_clears_entry_price(self):
        ctx = _run(
            _make_signal(symbol="005930", signal_type=SignalType.SELL),
            entry_prices={"005930": 70_000.0},
        )
        assert "005930" not in ctx["entry_prices"]


class TestRunCycleStopLoss:
    def test_stop_loss_calls_send_signal(self):
        ctx = _run(_make_signal(signal_type=SignalType.STOP_LOSS))
        ctx["notifier"].send_signal.assert_called_once()

    def test_stop_loss_clears_entry_price(self):
        ctx = _run(
            _make_signal(symbol="005930", signal_type=SignalType.STOP_LOSS),
            entry_prices={"005930": 70_000.0},
        )
        assert "005930" not in ctx["entry_prices"]

    def test_stop_loss_sends_hedge_recommendation(self):
        ctx = _run(_make_signal(signal_type=SignalType.STOP_LOSS))
        # send_message is called for the hedge recommendation
        ctx["notifier"].send_message.assert_called()


class TestRunCycleHedge:
    def test_hedge_signal_sends_message(self):
        settings = _make_settings()
        kis = MagicMock()
        kis.get_index_data.return_value = {"bstp_nmix_prdy_ctrt": "-2.1"}
        kis.get_ohlcv_daily.return_value = [{"stck_clpr": "70000"}]
        kis.get_current_price.return_value = {"stck_prpr": "70000"}

        engine = MagicMock()
        engine.check_hedge_signal.return_value = True  # trigger hedge
        engine.evaluate.return_value = _make_signal(signal_type=SignalType.HOLD)

        notifier = MagicMock()
        run_cycle(settings, kis, engine, notifier, {})

        notifier.send_message.assert_called()


class TestRunCycleErrorHandling:
    def test_index_api_error_does_not_crash(self):
        settings = _make_settings()
        kis = MagicMock()
        kis.get_index_data.side_effect = RuntimeError("network error")
        kis.get_ohlcv_daily.return_value = [{"stck_clpr": "70000"}]
        kis.get_current_price.return_value = {"stck_prpr": "70000"}

        engine = MagicMock()
        engine.check_hedge_signal.return_value = False
        engine.evaluate.return_value = _make_signal()

        notifier = MagicMock()
        # Should not raise
        run_cycle(settings, kis, engine, notifier, {})

    def test_symbol_api_error_does_not_crash(self):
        settings = _make_settings(watch_symbols=["005930"])
        kis = MagicMock()
        kis.get_index_data.return_value = {"bstp_nmix_prdy_ctrt": "0.1"}
        kis.get_ohlcv_daily.side_effect = RuntimeError("timeout")

        engine = MagicMock()
        engine.check_hedge_signal.return_value = False

        notifier = MagicMock()
        # Should not raise; error is caught per-symbol
        run_cycle(settings, kis, engine, notifier, {})

    def test_empty_symbol_list_is_skipped_gracefully(self):
        settings = _make_settings(watch_symbols=["", "  "])
        kis = MagicMock()
        kis.get_index_data.return_value = {"bstp_nmix_prdy_ctrt": "0.0"}
        engine = MagicMock()
        engine.check_hedge_signal.return_value = False
        notifier = MagicMock()

        run_cycle(settings, kis, engine, notifier, {})
        engine.evaluate.assert_not_called()
