"""Kakao OAuth token lifecycle manager.

Handles persistent storage, automatic refresh, and expiry detection for
Kakao OAuth ``access_token`` / ``refresh_token`` pairs.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta
from typing import Dict, Optional

import requests
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.ssl import ssl_verify

_logger = logging.getLogger(__name__)

TOKEN_URL: str = "https://kauth.kakao.com/oauth/token"


class KakaoTokenManager:
    """Kakao OAuth token storage and automatic-refresh manager.

    Token lifecycle rules:
        - ``access_token``: 6-hour lifetime; refreshed automatically when
          fewer than 5 minutes remain.
        - ``refresh_token``: ~2-month lifetime; renewed alongside the
          access token when fewer than 30 days remain.

    Persistence:
        Token data is persisted to a JSON file via an atomic
        write-then-rename strategy (``tempfile`` → ``os.replace``) to
        prevent partial writes.

    Args:
        token_file: Path to the JSON file used for token persistence.
        rest_api_key: Kakao REST API key (``client_id`` in OAuth terms).
    """

    ACCESS_TOKEN_REFRESH_MARGIN: timedelta = timedelta(minutes=5)
    REFRESH_TOKEN_RENEW_THRESHOLD: timedelta = timedelta(days=30)

    def __init__(self, token_file: str, rest_api_key: str) -> None:
        self._token_file = token_file
        self._rest_api_key = rest_api_key
        self._logger = logging.getLogger(__name__)
        self._token_data: Dict = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> bool:
        """Load token data from the JSON file.

        Returns:
            ``True`` if the file was read and parsed successfully,
            ``False`` if the file does not exist or cannot be parsed.
        """
        if not os.path.exists(self._token_file):
            return False
        try:
            with open(self._token_file, "r", encoding="utf-8") as fh:
                self._token_data = json.load(fh)
            return True
        except (json.JSONDecodeError, OSError) as exc:
            self._logger.error("Failed to load token file: %s", exc)
            return False

    def save(self, token_data: Dict) -> None:
        """Atomically persist token data to the JSON file.

        Uses a write-to-temp-then-rename pattern to avoid partial writes
        that would corrupt the stored token.

        Args:
            token_data: Dictionary containing token fields to persist.

        Raises:
            OSError: If the file cannot be written or renamed.
        """
        self._token_data = token_data
        dir_name = os.path.dirname(os.path.abspath(self._token_file))
        os.makedirs(dir_name, exist_ok=True)
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=dir_name,
                delete=False,
                suffix=".tmp",
            ) as tmp:
                json.dump(token_data, tmp, ensure_ascii=False, indent=2)
                tmp_path = tmp.name
            os.replace(tmp_path, self._token_file)
        except OSError as exc:
            self._logger.error("Failed to save token file: %s", exc)
            raise

    def get_valid_access_token(self) -> Optional[str]:
        """Return a valid ``access_token``, refreshing it if necessary.

        Loads persisted data on the first call if the in-memory store is
        empty.  Triggers a token refresh when the token is within 5 minutes
        of expiry.

        Returns:
            A valid ``access_token`` string, or ``None`` if one cannot be
            obtained (missing token file, refresh failure, etc.).
        """
        if not self._token_data:
            self.load()

        if not self._token_data:
            self._logger.error(
                "No token data found.  Run scripts/kakao_auth_setup.py to authenticate."
            )
            return None

        if self._is_access_token_expiring():
            self._logger.info("access_token is expiring soon — attempting refresh.")
            if not self.refresh():
                return None

        return self._token_data.get("access_token")

    def refresh(self) -> bool:
        """Refresh the ``access_token`` using the stored ``refresh_token``.

        Also renews ``refresh_token`` when fewer than 30 days remain on it.
        Persists updated token data on success.

        Returns:
            ``True`` if the refresh succeeded and new tokens were saved,
            ``False`` otherwise.
        """
        refresh_token = self._token_data.get("refresh_token")
        if not refresh_token:
            self._logger.error(
                "No refresh_token available.  Re-authentication required."
            )
            return False

        if self._is_refresh_token_expired():
            self._logger.error(
                "refresh_token has expired.  Run scripts/kakao_auth_setup.py to re-authenticate."
            )
            return False

        payload = {
            "grant_type": "refresh_token",
            "client_id": self._rest_api_key,
            "refresh_token": refresh_token,
        }

        try:
            data = self._post_token_with_retry(payload)
        except requests.RequestException as exc:
            self._logger.error("Token refresh request failed after retries: %s", exc)
            return False

        if "error" in data:
            self._logger.error(
                "Token refresh error: %s — %s",
                data.get("error"),
                data.get("error_description"),
            )
            return False

        now = datetime.now()
        self._token_data["access_token"] = data["access_token"]
        self._token_data["access_token_expires_at"] = (
            now + timedelta(seconds=data.get("expires_in", 21600))
        ).isoformat()

        if "refresh_token" in data:
            self._token_data["refresh_token"] = data["refresh_token"]
            self._token_data["refresh_token_expires_at"] = (
                now + timedelta(seconds=data.get("refresh_token_expires_in", 5184000))
            ).isoformat()
            self._logger.info("refresh_token was also renewed.")

        self.save(self._token_data)
        self._logger.info("access_token refreshed successfully.")
        return True

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
    def _post_token_with_retry(self, payload: Dict) -> Dict:
        """POST to the Kakao token endpoint with automatic retry.

        Decorated with *tenacity* to retry up to 3 times on transient
        ``requests.RequestException``, using exponential back-off.

        Args:
            payload: Form-encoded POST body for the token request.

        Returns:
            Parsed JSON response dictionary.

        Raises:
            requests.RequestException: Re-raised after all retry attempts are
                exhausted.
        """
        resp = requests.post(
            TOKEN_URL,
            data=payload,
            timeout=10,
            verify=ssl_verify(),  # False in DEV_MODE, True in production
        )
        resp.raise_for_status()
        return resp.json()

    def _is_access_token_expiring(self) -> bool:
        """Return ``True`` if the access token expires within the refresh margin.

        Returns:
            ``True`` if the token is missing, unparseable, or within 5 minutes
            of expiry; ``False`` otherwise.
        """
        expires_at_str: Optional[str] = self._token_data.get("access_token_expires_at")
        if not expires_at_str:
            return True
        try:
            expires_at = datetime.fromisoformat(expires_at_str)
            return datetime.now() >= expires_at - self.ACCESS_TOKEN_REFRESH_MARGIN
        except ValueError:
            return True

    def _is_refresh_token_expired(self) -> bool:
        """Return ``True`` if the refresh token has expired.

        Returns:
            ``True`` if the token expiry is known and has passed.  If the
            expiry is unknown, returns ``False`` so that a refresh is
            attempted optimistically.
        """
        expires_at_str: Optional[str] = self._token_data.get("refresh_token_expires_at")
        if not expires_at_str:
            return False  # Unknown expiry — attempt the refresh optimistically
        try:
            expires_at = datetime.fromisoformat(expires_at_str)
            return datetime.now() >= expires_at
        except ValueError:
            return False
