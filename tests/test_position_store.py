"""Unit tests for data_agent.position_store.PositionStore."""

from __future__ import annotations

import pytest

from data_agent.position_store import PositionStore


@pytest.fixture()
def store(tmp_path):
    """Fresh PositionStore backed by a temporary database file."""
    db = PositionStore(str(tmp_path / "test_bot_state.db"))
    yield db
    db.close()


class TestPositionStoreGet:
    def test_returns_none_when_symbol_absent(self, store):
        assert store.get("005930") is None

    def test_returns_float_after_set(self, store):
        store.set("005930", 70_000.0)
        assert store.get("005930") == pytest.approx(70_000.0)


class TestPositionStoreSet:
    def test_set_stores_value(self, store):
        store.set("000660", 120_000.0)
        assert store.get("000660") == pytest.approx(120_000.0)

    def test_upsert_overwrites_previous_price(self, store):
        store.set("005930", 70_000.0)
        store.set("005930", 75_000.0)
        assert store.get("005930") == pytest.approx(75_000.0)

    def test_multiple_symbols_stored_independently(self, store):
        store.set("005930", 70_000.0)
        store.set("000660", 120_000.0)
        assert store.get("005930") == pytest.approx(70_000.0)
        assert store.get("000660") == pytest.approx(120_000.0)


class TestPositionStoreDelete:
    def test_delete_removes_symbol(self, store):
        store.set("005930", 70_000.0)
        store.delete("005930")
        assert store.get("005930") is None

    def test_delete_is_noop_for_absent_symbol(self, store):
        # Must not raise
        store.delete("999999")

    def test_delete_does_not_affect_other_symbols(self, store):
        store.set("005930", 70_000.0)
        store.set("000660", 120_000.0)
        store.delete("005930")
        assert store.get("000660") == pytest.approx(120_000.0)


class TestPositionStoreGetAll:
    def test_empty_store_returns_empty_dict(self, store):
        assert store.get_all() == {}

    def test_returns_all_stored_symbols(self, store):
        store.set("005930", 70_000.0)
        store.set("000660", 120_000.0)
        result = store.get_all()
        assert result == pytest.approx({"005930": 70_000.0, "000660": 120_000.0})

    def test_get_all_reflects_deletions(self, store):
        store.set("005930", 70_000.0)
        store.set("000660", 120_000.0)
        store.delete("005930")
        assert "005930" not in store.get_all()
        assert "000660" in store.get_all()
