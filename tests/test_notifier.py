"""Unit tests for the notification subsystem.

Coverage
--------
- ``notifier.kakao.KakaoNotifier._format_signal_message``  (all signal types)
- ``notifier.kakao.KakaoNotifier.send_message``            (success / failure paths)
- ``notifier.kakao.KakaoNotifier.send_error``              (timestamp included)
- ``notifier.base.NotifierService``                        (composite broadcast)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from notifier.base import BaseNotifier, NotifierService
from notifier.kakao import KakaoNotifier
from strategy.signal import Signal, SignalType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.kakao_rest_api_key = "test_key"
    s.kakao_token_file = "data/kakao_token.json"
    return s


def _make_signal(
    signal_type: SignalType = SignalType.BUY,
    symbol: str = "005930",
    price: float = 71_500.0,
    rsi: float | None = 28.3,
    ma_short: float | None = 70_800.0,
    ma_long: float | None = 69_500.0,
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


def _make_notifier() -> KakaoNotifier:
    """Return a KakaoNotifier with a mocked token manager."""
    settings = _make_settings()
    with patch("notifier.kakao.KakaoTokenManager") as mock_mgr_cls:
        mock_mgr = MagicMock()
        mock_mgr.get_valid_access_token.return_value = "fake_token"
        mock_mgr_cls.return_value = mock_mgr
        notifier = KakaoNotifier(settings)
        notifier._token_manager = mock_mgr
    return notifier


# ---------------------------------------------------------------------------
# KakaoNotifier._format_signal_message
# ---------------------------------------------------------------------------


class TestFormatSignalMessage:
    """Tests for the human-readable message formatter."""

    def test_buy_message_contains_rsi(self):
        notifier = _make_notifier()
        signal = _make_signal(SignalType.BUY, rsi=28.3)
        msg = notifier._format_signal_message(signal)
        assert "RSI 28.3" in msg

    def test_buy_message_contains_golden_cross(self):
        notifier = _make_notifier()
        signal = _make_signal(SignalType.BUY)
        msg = notifier._format_signal_message(signal)
        assert "골든크로스" in msg

    def test_sell_message_contains_dead_cross(self):
        notifier = _make_notifier()
        signal = _make_signal(SignalType.SELL, rsi=72.1, price=75_200.0)
        msg = notifier._format_signal_message(signal)
        assert "데드크로스" in msg

    def test_stop_loss_message_contains_emergency_text(self):
        notifier = _make_notifier()
        signal = _make_signal(SignalType.STOP_LOSS, price=67_900.0)
        msg = notifier._format_signal_message(signal)
        assert "청산" in msg

    def test_hedge_message_contains_inverse_etf_text(self):
        notifier = _make_notifier()
        signal = _make_signal(SignalType.HEDGE, rsi=None)
        msg = notifier._format_signal_message(signal)
        assert "인버스 ETF" in msg

    def test_message_contains_symbol(self):
        notifier = _make_notifier()
        signal = _make_signal(SignalType.BUY, symbol="000660")
        msg = notifier._format_signal_message(signal)
        assert "000660" in msg

    def test_message_contains_price(self):
        notifier = _make_notifier()
        signal = _make_signal(SignalType.BUY, price=71_500.0)
        msg = notifier._format_signal_message(signal)
        assert "71,500" in msg

    def test_message_within_200_chars(self):
        notifier = _make_notifier()
        for st in SignalType:
            signal = _make_signal(st)
            msg = notifier._format_signal_message(signal)
            assert len(msg) <= 200, f"{st} message exceeds 200 chars: {len(msg)}"

    def test_buy_message_shows_icon(self):
        notifier = _make_notifier()
        signal = _make_signal(SignalType.BUY)
        msg = notifier._format_signal_message(signal)
        assert "📈" in msg

    def test_sell_message_shows_icon(self):
        notifier = _make_notifier()
        signal = _make_signal(SignalType.SELL, rsi=72.0, price=75_000.0)
        msg = notifier._format_signal_message(signal)
        assert "📉" in msg

    def test_stop_loss_message_shows_icon(self):
        notifier = _make_notifier()
        signal = _make_signal(SignalType.STOP_LOSS)
        msg = notifier._format_signal_message(signal)
        assert "🚨" in msg


# ---------------------------------------------------------------------------
# KakaoNotifier.send_message
# ---------------------------------------------------------------------------


class TestSendMessage:
    """Tests for the Kakao Memo API POST path."""

    def test_returns_true_on_success(self):
        notifier = _make_notifier()
        with patch.object(
            notifier, "_post_with_retry", return_value={"result_code": 0}
        ):
            assert notifier.send_message("test") is True

    def test_returns_false_on_api_error_code(self):
        notifier = _make_notifier()
        with patch.object(
            notifier, "_post_with_retry", return_value={"result_code": -401}
        ):
            assert notifier.send_message("test") is False

    def test_returns_false_when_no_token(self):
        notifier = _make_notifier()
        notifier._token_manager.get_valid_access_token.return_value = None
        assert notifier.send_message("test") is False

    def test_returns_false_on_request_exception(self):
        import requests

        notifier = _make_notifier()
        with patch.object(
            notifier, "_post_with_retry", side_effect=requests.RequestException("fail")
        ):
            assert notifier.send_message("test") is False

    def test_long_message_is_truncated(self):
        notifier = _make_notifier()
        captured: list = []

        def fake_post(headers, data):
            import json

            obj = json.loads(data["template_object"])
            captured.append(obj["text"])
            return {"result_code": 0}

        with patch.object(notifier, "_post_with_retry", side_effect=fake_post):
            notifier.send_message("A" * 300)

        assert len(captured[0]) == 200


# ---------------------------------------------------------------------------
# KakaoNotifier.send_error
# ---------------------------------------------------------------------------


class TestSendError:
    def test_error_message_contains_timestamp(self):
        notifier = _make_notifier()
        sent: list = []

        with patch.object(
            notifier, "send_message", side_effect=lambda t: sent.append(t)
        ):
            notifier.send_error("Something broke")

        assert sent, "send_message was not called"
        assert "ERROR" in sent[0]
        assert "Something broke" in sent[0]

    def test_error_message_contains_error_text(self):
        notifier = _make_notifier()
        with patch.object(notifier, "send_message", return_value=True) as mock_send:
            notifier.send_error("DB connection lost")
        args, _ = mock_send.call_args
        assert "DB connection lost" in args[0]


# ---------------------------------------------------------------------------
# NotifierService (composite)
# ---------------------------------------------------------------------------


class _FakeNotifier(BaseNotifier):
    """Concrete notifier that records all calls for inspection."""

    def __init__(self, return_value: bool = True) -> None:
        self.messages: list = []
        self.signals: list = []
        self.errors: list = []
        self._rv = return_value

    def send_message(self, text: str) -> bool:
        self.messages.append(text)
        return self._rv

    def send_signal(self, signal: Signal) -> bool:
        self.signals.append(signal)
        return self._rv

    def send_error(self, error_msg: str) -> None:
        self.errors.append(error_msg)


class TestNotifierService:
    def test_broadcasts_message_to_all_channels(self):
        a, b = _FakeNotifier(), _FakeNotifier()
        service = NotifierService([a, b])
        service.send_message("hello")
        assert "hello" in a.messages
        assert "hello" in b.messages

    def test_broadcasts_signal_to_all_channels(self):
        a, b = _FakeNotifier(), _FakeNotifier()
        service = NotifierService([a, b])
        sig = _make_signal()
        service.send_signal(sig)
        assert sig in a.signals
        assert sig in b.signals

    def test_broadcasts_error_to_all_channels(self):
        a, b = _FakeNotifier(), _FakeNotifier()
        service = NotifierService([a, b])
        service.send_error("boom")
        assert "boom" in a.errors
        assert "boom" in b.errors

    def test_register_adds_new_channel(self):
        a = _FakeNotifier()
        service = NotifierService([a])
        b = _FakeNotifier()
        service.register(b)
        service.send_message("hi")
        assert "hi" in b.messages

    def test_returns_true_when_all_succeed(self):
        service = NotifierService([_FakeNotifier(True), _FakeNotifier(True)])
        assert service.send_message("x") is True

    def test_returns_false_when_any_channel_fails(self):
        service = NotifierService([_FakeNotifier(True), _FakeNotifier(False)])
        assert service.send_message("x") is False

    def test_empty_service_returns_true(self):
        assert NotifierService([]).send_message("x") is True
