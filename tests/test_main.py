"""Unit tests for main.run_cycle.

All external dependencies (KIS API, SignalEngine, NotifierService, PositionStore)
are mocked so tests are fully deterministic and never hit live APIs or the filesystem.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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


def _make_position_store(entries: dict | None = None) -> MagicMock:
    """Return a MagicMock that behaves like a PositionStore."""
    store = MagicMock()
    data: dict = dict(entries or {})
    store.get.side_effect = lambda sym: data.get(sym)
    store.set.side_effect = lambda sym, price: data.__setitem__(sym, price)
    store.delete.side_effect = lambda sym: data.pop(sym, None)
    store._data = data  # expose internal dict for assertions
    return store


def _run(
    signal: Signal,
    position_store: MagicMock | None = None,
    index_change: str = "0.5",
    hedge_triggered: bool = False,
    market_open: bool = True,
) -> dict:
    settings = _make_settings()
    kis = MagicMock()
    kis.get_index_data.return_value = {"bstp_nmix_prdy_ctrt": index_change}
    kis.get_ohlcv_daily.return_value = [{"stck_clpr": "70000"}]
    kis.get_current_price.return_value = {"stck_prpr": str(int(signal.price))}

    engine = MagicMock()
    engine.check_hedge_signal.return_value = hedge_triggered
    engine.evaluate.return_value = signal

    notifier = MagicMock()
    ps = position_store if position_store is not None else _make_position_store()

    with patch("main.is_market_open", return_value=market_open):
        run_cycle(settings, kis, engine, notifier, ps)

    return {"engine": engine, "notifier": notifier, "position_store": ps}


# ---------------------------------------------------------------------------
# Market hours filter
# ---------------------------------------------------------------------------


class TestMarketHoursFilter:
    def test_skips_cycle_when_market_closed(self):
        ctx = _run(_make_signal(), market_open=False)
        ctx["engine"].evaluate.assert_not_called()

    def test_runs_cycle_when_market_open(self):
        ctx = _run(_make_signal(), market_open=True)
        ctx["engine"].evaluate.assert_called_once()


# ---------------------------------------------------------------------------
# HOLD signal
# ---------------------------------------------------------------------------


class TestRunCycleHold:
    def test_hold_does_not_call_send_signal(self):
        ctx = _run(_make_signal(signal_type=SignalType.HOLD))
        ctx["notifier"].send_signal.assert_not_called()

    def test_hold_does_not_record_entry_price(self):
        ps = _make_position_store()
        _run(_make_signal(signal_type=SignalType.HOLD), position_store=ps)
        ps.set.assert_not_called()


# ---------------------------------------------------------------------------
# BUY signal
# ---------------------------------------------------------------------------


class TestRunCycleBuy:
    def test_buy_calls_send_signal(self):
        ctx = _run(_make_signal(signal_type=SignalType.BUY, price=71_500.0))
        ctx["notifier"].send_signal.assert_called_once()

    def test_buy_records_entry_price(self):
        ps = _make_position_store()
        _run(
            _make_signal(symbol="005930", signal_type=SignalType.BUY, price=71_500.0),
            position_store=ps,
        )
        ps.set.assert_called_once_with("005930", pytest.approx(71_500.0))

    def test_buy_does_not_clear_existing_entry(self):
        ps = _make_position_store({"000660": 50_000.0})
        _run(
            _make_signal(symbol="005930", signal_type=SignalType.BUY, price=71_500.0),
            position_store=ps,
        )
        # The other symbol's entry must survive
        assert ps._data.get("000660") == pytest.approx(50_000.0)


# ---------------------------------------------------------------------------
# SELL signal
# ---------------------------------------------------------------------------


class TestRunCycleSell:
    def test_sell_calls_send_signal(self):
        ctx = _run(_make_signal(signal_type=SignalType.SELL))
        ctx["notifier"].send_signal.assert_called_once()

    def test_sell_clears_entry_price(self):
        ps = _make_position_store({"005930": 70_000.0})
        _run(
            _make_signal(symbol="005930", signal_type=SignalType.SELL),
            position_store=ps,
        )
        ps.delete.assert_called_once_with("005930")


# ---------------------------------------------------------------------------
# STOP_LOSS signal
# ---------------------------------------------------------------------------


class TestRunCycleStopLoss:
    def test_stop_loss_calls_send_signal(self):
        ctx = _run(_make_signal(signal_type=SignalType.STOP_LOSS))
        ctx["notifier"].send_signal.assert_called_once()

    def test_stop_loss_clears_entry_price(self):
        ps = _make_position_store({"005930": 70_000.0})
        _run(
            _make_signal(symbol="005930", signal_type=SignalType.STOP_LOSS),
            position_store=ps,
        )
        ps.delete.assert_called_once_with("005930")

    def test_stop_loss_sends_hedge_recommendation(self):
        ctx = _run(_make_signal(signal_type=SignalType.STOP_LOSS))
        ctx["notifier"].send_message.assert_called()


# ---------------------------------------------------------------------------
# HEDGE (index-level)
# ---------------------------------------------------------------------------


class TestRunCycleHedge:
    def test_hedge_signal_sends_message(self):
        settings = _make_settings()
        kis = MagicMock()
        kis.get_index_data.return_value = {"bstp_nmix_prdy_ctrt": "-2.1"}
        kis.get_ohlcv_daily.return_value = [{"stck_clpr": "70000"}]
        kis.get_current_price.return_value = {"stck_prpr": "70000"}

        engine = MagicMock()
        engine.check_hedge_signal.return_value = True
        engine.evaluate.return_value = _make_signal(signal_type=SignalType.HOLD)

        notifier = MagicMock()
        ps = _make_position_store()

        with patch("main.is_market_open", return_value=True):
            run_cycle(settings, kis, engine, notifier, ps)

        notifier.send_message.assert_called()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


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
        ps = _make_position_store()

        with patch("main.is_market_open", return_value=True):
            run_cycle(settings, kis, engine, notifier, ps)

    def test_symbol_api_error_does_not_crash(self):
        settings = _make_settings(watch_symbols=["005930"])
        kis = MagicMock()
        kis.get_index_data.return_value = {"bstp_nmix_prdy_ctrt": "0.1"}
        kis.get_ohlcv_daily.side_effect = RuntimeError("timeout")

        engine = MagicMock()
        engine.check_hedge_signal.return_value = False

        notifier = MagicMock()
        ps = _make_position_store()

        with patch("main.is_market_open", return_value=True):
            run_cycle(settings, kis, engine, notifier, ps)

    def test_empty_symbol_list_is_skipped_gracefully(self):
        settings = _make_settings(watch_symbols=["", "  "])
        kis = MagicMock()
        kis.get_index_data.return_value = {"bstp_nmix_prdy_ctrt": "0.0"}
        engine = MagicMock()
        engine.check_hedge_signal.return_value = False
        notifier = MagicMock()
        ps = _make_position_store()

        with patch("main.is_market_open", return_value=True):
            run_cycle(settings, kis, engine, notifier, ps)

        engine.evaluate.assert_not_called()
