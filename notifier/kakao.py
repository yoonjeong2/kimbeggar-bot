"""Kakao Talk 'send-to-me' notification module.

Formats trading-signal messages and delivers them through the
Kakao Memo API (POST /v2/api/talk/memo/default/send).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Dict

import requests
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import Settings
from config.ssl import ssl_verify
from notifier.base import BaseNotifier
from notifier.kakao_token_manager import KakaoTokenManager
from strategy.signal import Signal, SignalType

_logger = logging.getLogger(__name__)

MEMO_API_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


class KakaoNotifier(BaseNotifier):
    """Kakao Talk 'send-to-me' notification channel.

    Implements :class:`~notifier.base.BaseNotifier` so it can be registered
    with :class:`~notifier.base.NotifierService` alongside other channels.

    Features:
        - Formats BUY / SELL / STOP_LOSS / HEDGE signal messages.
        - Sends messages via the Kakao Memo API.
        - Automatically refreshes the OAuth access token when it expires.
        - Retries transient network errors up to 3 times with exponential
          back-off (powered by *tenacity*).

    Args:
        settings: Application-wide ``Settings`` instance injected at
            construction time (Dependency-Inversion Principle).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._logger = logging.getLogger(__name__)
        self._token_manager = KakaoTokenManager(
            token_file=settings.kakao_token_file,
            rest_api_key=settings.kakao_rest_api_key,
        )
        self._token_manager.load()

    # ------------------------------------------------------------------
    # BaseNotifier interface
    # ------------------------------------------------------------------

    def send_signal(self, signal: Signal) -> bool:
        """Format and deliver a trading-signal notification via Kakao Talk.

        Args:
            signal: The ``Signal`` object containing symbol, price, and type.

        Returns:
            ``True`` if the message was delivered successfully, ``False``
            otherwise.
        """
        return self.send_message(self._format_signal_message(signal))

    def send_message(self, text: str) -> bool:
        """Send a plain-text message to 'Kakao Talk to me'.

        Acquires a valid access token, builds the text template payload, and
        calls the Kakao Memo API.  Retries up to 3 times on transient network
        errors before giving up.

        Args:
            text: Message content.  Truncated to 200 characters to comply with
                the Kakao text-template limit.

        Returns:
            ``True`` if ``result_code == 0`` was returned by the API,
            ``False`` otherwise.
        """
        access_token = self._token_manager.get_valid_access_token()
        if not access_token:
            self._logger.error("No valid access_token available; message not sent.")
            return False

        payload = {
            "template_object": json.dumps(
                {
                    "object_type": "text",
                    "text": text[:200],  # Kakao text-template 200-char limit
                    "link": {"web_url": "", "mobile_web_url": ""},
                },
                ensure_ascii=False,
            )
        }
        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            result = self._post_with_retry(headers, payload)
            if result.get("result_code") == 0:
                self._logger.info("Kakao message sent successfully.")
                return True
            self._logger.error("Kakao API returned an error: %s", result)
            return False
        except requests.RequestException as exc:
            self._logger.error("Kakao API request failed after retries: %s", exc)
            return False

    def send_error(self, error_msg: str) -> None:
        """Deliver an error alert via Kakao Talk.

        Args:
            error_msg: Human-readable description of the error condition.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.send_message(f"[ERROR] {timestamp}\n{error_msg}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        before_sleep=before_sleep_log(_logger, logging.WARNING),
        reraise=True,
    )
    def _post_with_retry(
        self,
        headers: Dict[str, str],
        data: Dict[str, str],
    ) -> Dict:
        """Execute the Kakao Memo API POST with automatic retry on failure.

        Decorated with *tenacity* to retry up to 3 times on any
        ``requests.RequestException``, using exponential back-off
        (1 s → 2 s → 4 s, capped at 8 s).

        Args:
            headers: HTTP request headers (must include ``Authorization``).
            data: Form-encoded POST body.

        Returns:
            Parsed JSON response dictionary.

        Raises:
            requests.RequestException: Re-raised after all retry attempts are
                exhausted.
        """
        resp = requests.post(
            MEMO_API_URL,
            headers=headers,
            data=data,
            timeout=10,
            verify=ssl_verify(),  # False in DEV_MODE, True in production
        )
        resp.raise_for_status()
        return resp.json()

    def _format_signal_message(self, signal: Signal) -> str:
        """Format a trading signal into a user-friendly Kakao message string.

        Message examples::

            📈 매수 시그널: 종목 005930
            RSI 28.3 (과매도) | 골든크로스 확인
            현재가: 71,500원
            2026-03-13 14:30

            🚨 긴급 손절: 종목 005930
            현재가: 67,800원 (-5.2%)
            → 즉시 포지션 청산 필요
            2026-03-13 14:30

        Args:
            signal: ``Signal`` object with type, symbol, price, and indicators.

        Returns:
            Multi-line string (≤ 200 chars) ready for the Kakao text template.
        """
        _ICONS = {
            SignalType.BUY: "📈",
            SignalType.SELL: "📉",
            SignalType.STOP_LOSS: "🚨",
            SignalType.HEDGE: "⚠️",
        }
        _LABELS = {
            SignalType.BUY: "매수 시그널",
            SignalType.SELL: "매도 시그널",
            SignalType.STOP_LOSS: "긴급 손절",
            SignalType.HEDGE: "헤지 경고",
        }

        icon = _ICONS.get(signal.signal_type, "🔔")
        label = _LABELS.get(signal.signal_type, "알림")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        lines = [f"{icon} {label}: 종목 {signal.symbol}"]

        # RSI + crossover detail for BUY / SELL signals
        if signal.rsi is not None and signal.signal_type in (
            SignalType.BUY,
            SignalType.SELL,
        ):
            rsi_tag = "과매도" if signal.signal_type == SignalType.BUY else "과매수"
            cross_tag = (
                "골든크로스 확인"
                if signal.signal_type == SignalType.BUY
                else "데드크로스 확인"
            )
            lines.append(f"RSI {signal.rsi:.1f} ({rsi_tag}) | {cross_tag}")

        lines.append(f"현재가: {signal.price:,.0f}원")

        if signal.signal_type == SignalType.STOP_LOSS:
            lines.append("→ 즉시 포지션 청산 필요")
        elif signal.signal_type == SignalType.HEDGE:
            lines.append("→ 인버스 ETF 포지션 진입 권고")

        lines.append(timestamp)
        return "\n".join(lines)
