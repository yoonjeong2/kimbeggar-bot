"""Unit tests for data_agent.paper_trade_store.PaperTradeStore.

Uses pytest's ``tmp_path`` fixture for an isolated SQLite database per test
so tests are hermetic and leave no residual files.
"""

from __future__ import annotations

import pytest

from data_agent.paper_trade_store import PaperTradeStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path):
    ps = PaperTradeStore(str(tmp_path / "paper_test.db"))
    yield ps
    ps.close()


# ---------------------------------------------------------------------------
# record() — write path
# ---------------------------------------------------------------------------


class TestRecord:
    def test_returns_dict(self, store):
        result = store.record("005930", "BUY", 70_000.0)
        assert isinstance(result, dict)

    def test_symbol_round_trips(self, store):
        result = store.record("000660", "SELL", 120_000.0)
        assert result["symbol"] == "000660"

    def test_signal_type_round_trips(self, store):
        result = store.record("005930", "STOP_LOSS", 65_000.0)
        assert result["signal_type"] == "STOP_LOSS"

    def test_price_round_trips(self, store):
        result = store.record("005930", "BUY", 73_500.0)
        assert result["price"] == pytest.approx(73_500.0)

    def test_default_quantity_is_one(self, store):
        result = store.record("005930", "BUY", 70_000.0)
        assert result["quantity"] == 1

    def test_custom_quantity(self, store):
        result = store.record("005930", "BUY", 70_000.0, quantity=5)
        assert result["quantity"] == 5

    def test_total_krw_equals_price_times_quantity(self, store):
        result = store.record("005930", "BUY", 70_000.0, quantity=3)
        assert result["total_krw"] == pytest.approx(210_000.0)


# ---------------------------------------------------------------------------
# get_all() — read all
# ---------------------------------------------------------------------------


class TestGetAll:
    def test_empty_on_fresh_store(self, store):
        assert store.get_all() == []

    def test_returns_inserted_row(self, store):
        store.record("005930", "BUY", 70_000.0)
        rows = store.get_all()
        assert len(rows) == 1
        assert rows[0]["symbol"] == "005930"

    def test_newest_first(self, store):
        store.record("005930", "BUY", 70_000.0)
        store.record("000660", "SELL", 120_000.0)
        rows = store.get_all()
        assert rows[0]["symbol"] == "000660"
        assert rows[1]["symbol"] == "005930"

    def test_multiple_signals_all_returned(self, store):
        for sig in ("BUY", "SELL", "STOP_LOSS"):
            store.record("005930", sig, 70_000.0)
        assert len(store.get_all()) == 3

    def test_row_has_traded_at_field(self, store):
        store.record("005930", "BUY", 70_000.0)
        row = store.get_all()[0]
        assert "traded_at" in row
        assert row["traded_at"]  # non-empty string


# ---------------------------------------------------------------------------
# get_by_symbol()
# ---------------------------------------------------------------------------


class TestGetBySymbol:
    def test_filters_by_symbol(self, store):
        store.record("005930", "BUY", 70_000.0)
        store.record("000660", "BUY", 120_000.0)
        rows = store.get_by_symbol("005930")
        assert len(rows) == 1
        assert rows[0]["symbol"] == "005930"

    def test_empty_for_unknown_symbol(self, store):
        store.record("005930", "BUY", 70_000.0)
        assert store.get_by_symbol("999999") == []

    def test_returns_all_trades_for_symbol(self, store):
        store.record("005930", "BUY", 70_000.0)
        store.record("005930", "STOP_LOSS", 66_000.0)
        rows = store.get_by_symbol("005930")
        assert len(rows) == 2


# ---------------------------------------------------------------------------
# get_summary() — P&L
# ---------------------------------------------------------------------------


class TestGetSummary:
    def test_empty_on_fresh_store(self, store):
        assert store.get_summary() == {}

    def test_buy_only_shows_negative_pnl(self, store):
        store.record("005930", "BUY", 70_000.0, quantity=10)
        summary = store.get_summary()
        assert "005930" in summary
        assert summary["005930"]["bought_krw"] == pytest.approx(700_000.0)
        assert summary["005930"]["sold_krw"] == pytest.approx(0.0)
        assert summary["005930"]["pnl_krw"] == pytest.approx(-700_000.0)

    def test_buy_then_sell_positive_pnl(self, store):
        store.record("005930", "BUY", 70_000.0, quantity=10)
        store.record("005930", "SELL", 80_000.0, quantity=10)
        summary = store.get_summary()
        assert summary["005930"]["pnl_krw"] == pytest.approx(100_000.0)

    def test_stop_loss_counted_as_sold(self, store):
        store.record("005930", "BUY", 70_000.0, quantity=10)
        store.record("005930", "STOP_LOSS", 66_000.0, quantity=10)
        summary = store.get_summary()
        assert summary["005930"]["sold_krw"] == pytest.approx(660_000.0)

    def test_trades_count(self, store):
        store.record("005930", "BUY", 70_000.0)
        store.record("005930", "SELL", 75_000.0)
        assert store.get_summary()["005930"]["trades"] == 2

    def test_multiple_symbols_independent(self, store):
        store.record("005930", "BUY", 70_000.0)
        store.record("000660", "BUY", 120_000.0)
        summary = store.get_summary()
        assert len(summary) == 2
        assert "005930" in summary
        assert "000660" in summary


# ---------------------------------------------------------------------------
# clear()
# ---------------------------------------------------------------------------


class TestClear:
    def test_clear_empties_all_records(self, store):
        store.record("005930", "BUY", 70_000.0)
        store.record("000660", "SELL", 120_000.0)
        store.clear()
        assert store.get_all() == []

    def test_clear_then_re_insert(self, store):
        store.record("005930", "BUY", 70_000.0)
        store.clear()
        store.record("005930", "BUY", 75_000.0)
        rows = store.get_all()
        assert len(rows) == 1
        assert rows[0]["price"] == pytest.approx(75_000.0)


# ---------------------------------------------------------------------------
# persistence across re-open
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_records_survive_reconnect(self, tmp_path):
        db = str(tmp_path / "persist.db")
        s1 = PaperTradeStore(db)
        s1.record("005930", "BUY", 70_000.0)
        s1.close()

        s2 = PaperTradeStore(db)
        rows = s2.get_all()
        s2.close()
        assert len(rows) == 1
        assert rows[0]["symbol"] == "005930"
