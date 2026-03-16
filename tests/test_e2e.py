"""End-to-end tests for the FastAPI web dashboard (api/app.py) and
KIS API DEV_MODE simulation path.

Uses FastAPI's built-in ``TestClient`` (backed by ``httpx``) so no real server
process is needed.  The ``PositionStore`` is wired to a temporary SQLite file
so each test starts with a clean state.

KIS API tests use ``DEV_MODE=true`` to exercise ``simulate_trade()`` without
making any real network calls — the method returns a mock response when
``settings.dev_mode`` is True, bypassing authentication entirely.
"""

from __future__ import annotations

from collections import deque
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from data_agent.kis_api import KISClient
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


# ---------------------------------------------------------------------------
# WS /ws — WebSocket real-time push
# ---------------------------------------------------------------------------


class TestWebSocket:
    def test_connect_and_receive_message(self, client):
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert "positions" in data
            assert "signals" in data
            assert "uptime" in data

    def test_positions_empty_on_fresh_store(self, client):
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert data["positions"] == {}

    def test_signals_empty_on_fresh_log(self, client):
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert data["signals"] == []

    def test_positions_reflect_store(self, client, store):
        store.set("005930", 70_000.0)
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert "005930" in data["positions"]
            assert data["positions"]["005930"] == pytest.approx(70_000.0)

    def test_signals_reflect_log(self, client, signal_log):
        signal_log.appendleft(
            {
                "time": "2024-01-02 10:00:00",
                "symbol": "000660",
                "signal_type": "BUY",
                "price": 120_000.0,
                "rsi": 28.5,
                "reason": "golden cross",
            }
        )
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert len(data["signals"]) == 1
            assert data["signals"][0]["symbol"] == "000660"

    def test_uptime_is_string(self, client):
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert isinstance(data["uptime"], str)
            assert "h" in data["uptime"]

    def test_second_message_still_valid(self, client):
        """The push loop sends a second frame within the same connection."""
        with client.websocket_connect("/ws") as ws:
            first = ws.receive_json()
            second = ws.receive_json()
        assert set(first.keys()) == set(second.keys())
        assert isinstance(second["uptime"], str)

    def test_position_change_reflected_in_later_push(self, client, store):
        """A position added after the first frame appears in the second frame."""
        with client.websocket_connect("/ws") as ws:
            first = ws.receive_json()
            assert "005930" not in first["positions"]
            store.set("005930", 75_000.0)
            second = ws.receive_json()
        assert "005930" in second["positions"]

    def test_signal_change_reflected_in_later_push(self, client, signal_log):
        """A signal appended after the first frame appears in the second frame."""
        with client.websocket_connect("/ws") as ws:
            first = ws.receive_json()
            assert first["signals"] == []
            signal_log.appendleft({"symbol": "005930", "signal_type": "BUY", "price": 70_000.0})
            second = ws.receive_json()
        assert len(second["signals"]) == 1

    def test_multiple_clients_independent(self, store, signal_log):
        """Two simultaneous WebSocket clients each receive their own stream."""
        app = create_app(store, signal_log)
        c1 = TestClient(app)
        c2 = TestClient(app)
        with c1.websocket_connect("/ws") as ws1, c2.websocket_connect("/ws") as ws2:
            d1 = ws1.receive_json()
            d2 = ws2.receive_json()
        assert d1["positions"] == d2["positions"]


# ---------------------------------------------------------------------------
# KIS API — DEV_MODE=true simulation (no real network calls)
# ---------------------------------------------------------------------------


def _dev_client() -> KISClient:
    """Return a KISClient whose settings have dev_mode=True."""
    settings = MagicMock()
    settings.dev_mode = True
    return KISClient(settings)


def _prod_client() -> KISClient:
    """Return a KISClient whose settings have dev_mode=False."""
    settings = MagicMock()
    settings.dev_mode = False
    return KISClient(settings)


class TestSimulateTradeDEVMode:
    """simulate_trade() bypasses real KIS API when DEV_MODE=true.

    These tests represent the "모킹 우회" (mock bypass) E2E scenario:
    the bot can perform a full BUY/SELL/STOP_LOSS cycle using only
    log-level output, with zero network dependencies.
    """

    def test_raises_when_dev_mode_false(self):
        with pytest.raises(RuntimeError, match="DEV_MODE"):
            _prod_client().simulate_trade("005930", "BUY", 70_000.0)

    def test_returns_dict_in_dev_mode(self):
        result = _dev_client().simulate_trade("005930", "BUY", 70_000.0)
        assert isinstance(result, dict)

    def test_simulated_flag_is_true(self):
        result = _dev_client().simulate_trade("005930", "BUY", 70_000.0)
        assert result["simulated"] is True

    def test_symbol_round_trips(self):
        result = _dev_client().simulate_trade("000660", "SELL", 120_000.0)
        assert result["symbol"] == "000660"

    def test_signal_type_round_trips(self):
        for sig in ("BUY", "SELL", "STOP_LOSS"):
            result = _dev_client().simulate_trade("005930", sig, 70_000.0)
            assert result["signal_type"] == sig

    def test_price_round_trips(self):
        result = _dev_client().simulate_trade("005930", "BUY", 73_500.0)
        assert result["price"] == pytest.approx(73_500.0)

    def test_default_quantity_is_one(self):
        result = _dev_client().simulate_trade("005930", "BUY", 70_000.0)
        assert result["quantity"] == 1

    def test_custom_quantity(self):
        result = _dev_client().simulate_trade("005930", "BUY", 70_000.0, quantity=10)
        assert result["quantity"] == 10

    def test_total_krw_equals_price_times_quantity(self):
        result = _dev_client().simulate_trade("005930", "BUY", 70_000.0, quantity=5)
        assert result["total_krw"] == pytest.approx(350_000.0)

    def test_stop_loss_simulation(self):
        """Full stop-loss cycle: buy → price drops → simulate stop-loss order."""
        kis = _dev_client()
        buy = kis.simulate_trade("005930", "BUY", 70_000.0, quantity=10)
        stop = kis.simulate_trade("005930", "STOP_LOSS", 66_000.0, quantity=10)
        assert buy["simulated"] is True
        assert stop["signal_type"] == "STOP_LOSS"
        assert stop["total_krw"] == pytest.approx(660_000.0)

    def test_buy_sell_round_trip(self):
        """Full buy → sell simulation returns consistent payloads."""
        kis = _dev_client()
        buy = kis.simulate_trade("000660", "BUY", 120_000.0, quantity=3)
        sell = kis.simulate_trade("000660", "SELL", 130_000.0, quantity=3)
        assert buy["symbol"] == sell["symbol"]
        assert buy["quantity"] == sell["quantity"]
        assert sell["price"] > buy["price"]  # profitable trade
