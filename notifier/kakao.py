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

    SIGNAL_LABELS: Dict[SignalType, str] = {
        SignalType.BUY: "[매수]",
        SignalType.SELL: "[매도]",
        SignalType.STOP_LOSS: "[긴급:손절]",
        SignalType.HEDGE: "[헤지]",
    }

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
        """Format a trading signal into a human-readable Kakao message string.

        Args:
            signal: ``Signal`` object with type, symbol, and price.

        Returns:
            Multi-line string ready to be sent as a Kakao text template.
        """
        label = self.SIGNAL_LABELS.get(signal.signal_type, "[알림]")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"{label} {signal.symbol}",
            f"시각: {timestamp}",
            f"가격: {signal.price:,.0f}원",
        ]
        if signal.signal_type == SignalType.STOP_LOSS:
            lines.append("→ 즉시 손절 필요")
        elif signal.signal_type == SignalType.HEDGE:
            lines.append("→ 인버스 ETF 헤지 진입")
        return "\n".join(lines)
