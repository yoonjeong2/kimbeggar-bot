"""End-to-end tests for the FastAPI web dashboard (api/app.py).

Uses FastAPI's built-in ``TestClient`` (backed by ``httpx``) so no real server
process is needed.  The ``PositionStore`` is wired to a temporary SQLite file
so each test starts with a clean state.
"""

from __future__ import annotations

from collections import deque

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from data_agent.position_store import PositionStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path):
    ps = PositionStore(str(tmp_path / "e2e_test.db"))
    yield ps
    ps.close()


@pytest.fixture()
def signal_log():
    return deque(maxlen=50)


@pytest.fixture()
def client(store, signal_log):
    app = create_app(store, signal_log)
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET / — HTML dashboard
# ---------------------------------------------------------------------------


class TestDashboardHTML:
    def test_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_content_type_is_html(self, client):
        resp = client.get("/")
        assert "text/html" in resp.headers["content-type"]

    def test_contains_title(self, client):
        resp = client.get("/")
        assert "KimBeggar" in resp.text

    def test_shows_no_position_message_when_empty(self, client):
        resp = client.get("/")
        assert "보유 포지션 없음" in resp.text

    def test_shows_no_signal_message_when_empty(self, client):
        resp = client.get("/")
        assert "아직 기록된 시그널 없음" in resp.text

    def test_shows_position_symbol_when_present(self, client, store):
        store.set("005930", 70_000.0)
        resp = client.get("/")
        assert "005930" in resp.text

    def test_shows_signal_when_present(self, client, signal_log):
        signal_log.appendleft(
            {
                "time": "2024-01-02 10:00:00",
                "symbol": "000660",
                "signal_type": "BUY",
                "price": 120_000.0,
                "rsi": 28.5,
                "reason": "RSI oversold + golden cross",
            }
        )
        resp = client.get("/")
        assert "000660" in resp.text
        assert "BUY" in resp.text


# ---------------------------------------------------------------------------
# GET /api/status
# ---------------------------------------------------------------------------


class TestApiStatus:
    def test_returns_200(self, client):
        assert client.get("/api/status").status_code == 200

    def test_status_field_is_running(self, client):
        data = client.get("/api/status").json()
        assert data["status"] == "running"

    def test_uptime_seconds_is_non_negative(self, client):
        data = client.get("/api/status").json()
        assert data["uptime_seconds"] >= 0

    def test_open_positions_reflects_store(self, client, store):
        store.set("005930", 70_000.0)
        data = client.get("/api/status").json()
        assert data["open_positions"] == 1

    def test_recent_signals_reflects_log(self, client, signal_log):
        signal_log.appendleft({"symbol": "005930", "signal_type": "SELL"})
        data = client.get("/api/status").json()
        assert data["recent_signals"] == 1


# ---------------------------------------------------------------------------
# GET /api/positions
# ---------------------------------------------------------------------------


class TestApiPositions:
    def test_returns_200(self, client):
        assert client.get("/api/positions").status_code == 200

    def test_empty_when_no_positions(self, client):
        assert client.get("/api/positions").json() == {}

    def test_contains_inserted_position(self, client, store):
        store.set("005930", 70_000.0)
        data = client.get("/api/positions").json()
        assert "005930" in data
        assert data["005930"] == pytest.approx(70_000.0)

    def test_multiple_positions(self, client, store):
        store.set("005930", 70_000.0)
        store.set("000660", 120_000.0)
        data = client.get("/api/positions").json()
        assert len(data) == 2

    def test_deleted_position_not_returned(self, client, store):
        store.set("005930", 70_000.0)
        store.delete("005930")
        assert client.get("/api/positions").json() == {}


# ---------------------------------------------------------------------------
# GET /api/signals
# ---------------------------------------------------------------------------


class TestApiSignals:
    def test_returns_200(self, client):
        assert client.get("/api/signals").status_code == 200

    def test_empty_list_when_no_signals(self, client):
        assert client.get("/api/signals").json() == []

    def test_returns_appended_signal(self, client, signal_log):
        signal_log.appendleft(
            {
                "time": "2024-01-02 10:00:00",
                "symbol": "005930",
                "signal_type": "BUY",
                "price": 71_000.0,
                "rsi": 27.3,
                "reason": "test",
            }
        )
        data = client.get("/api/signals").json()
        assert len(data) == 1
        assert data[0]["symbol"] == "005930"
        assert data[0]["signal_type"] == "BUY"

    def test_signals_ordered_newest_first(self, client, signal_log):
        signal_log.appendleft({"symbol": "A", "signal_type": "BUY"})
        signal_log.appendleft({"symbol": "B", "signal_type": "SELL"})
        data = client.get("/api/signals").json()
        # appendleft means B is index 0 (newest)
        assert data[0]["symbol"] == "B"
        assert data[1]["symbol"] == "A"

    def test_respects_maxlen(self, signal_log, store):
        tiny_log: deque = deque(maxlen=3)
        app = create_app(store, tiny_log)
        tc = TestClient(app)
        for i in range(5):
            tiny_log.appendleft({"symbol": str(i), "signal_type": "BUY"})
        data = tc.get("/api/signals").json()
        assert len(data) == 3
