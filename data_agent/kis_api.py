"""KIS (Korea Investment & Securities) Open API client.

Handles OAuth token issuance / auto-renewal and market-data retrieval for
domestic equities and indices.

API base URLs:
    - Production : ``https://openapi.koreainvestment.com:9443``
    - Sandbox    : ``https://openapivts.koreainvestment.com:29443``
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

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

_logger = logging.getLogger(__name__)

_TOKEN_PATH = "/oauth2/tokenP"
_PRICE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-price"
_CHART_5MIN_PATH = "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
_CHART_DAILY_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
_INDEX_PATH = "/uapi/domestic-stock/v1/quotations/inquire-index-price"


class KISClient:
    """KIS Open API client with automatic token management and retry logic.

    Features:
        - OAuth ``access_token`` issuance and 5-minute-margin auto-renewal.
        - 5-minute and daily OHLCV candle retrieval.
        - KOSPI / KOSDAQ index price retrieval.
        - All HTTP calls retry up to 3 times on transient network errors
          (powered by *tenacity*, exponential back-off).

    Args:
        settings: Application-wide ``Settings`` instance.  Provides API
            credentials and the base URL (production vs. sandbox).
    """

    _TOKEN_EXPIRY_MARGIN: timedelta = timedelta(minutes=5)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._logger = logging.getLogger(__name__)
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def get_access_token(self) -> str:
        """Return a valid OAuth access token, re-issuing it if necessary.

        Returns:
            A non-empty access token string.

        Raises:
            RuntimeError: If token issuance fails.
        """
        if self._is_token_valid():
            return self._access_token  # type: ignore[return-value]
        return self._issue_token()

    def _issue_token(self) -> str:
        """Issue a new OAuth access token from the KIS token endpoint.

        Sends a ``client_credentials`` grant POST to ``/oauth2/tokenP``
        and caches the resulting token and its expiry time.

        Returns:
            Newly issued access token string.

        Raises:
            RuntimeError: If the API returns an error response.
            requests.RequestException: Re-raised after all retry attempts are
                exhausted.
        """
        body: Dict[str, str] = {
            "grant_type": "client_credentials",
            "appkey": self._settings.kis_app_key,
            "appsecret": self._settings.kis_app_secret,
        }
        data = self._post_with_retry(
            path=_TOKEN_PATH,
            json_body=body,
            headers={"content-type": "application/json; charset=utf-8"},
        )

        token = data.get("access_token")
        expires_in = int(data.get("expires_in", 86400))
        if not token:
            raise RuntimeError(f"KIS token issuance failed: {data}")

        self._access_token = token
        self._token_expires_at = datetime.now() + timedelta(seconds=expires_in)
        self._logger.info("KIS access token issued; expires in %d seconds.", expires_in)
        return self._access_token

    def _is_token_valid(self) -> bool:
        """Check whether the cached token exists and is not about to expire.

        Returns:
            ``True`` if the token is present and at least 5 minutes from
            expiry, ``False`` otherwise.
        """
        if not self._access_token or not self._token_expires_at:
            return False
        return datetime.now() < self._token_expires_at - self._TOKEN_EXPIRY_MARGIN

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def get_current_price(self, symbol: str) -> Dict[str, Any]:
        """Retrieve the real-time (or last) price for a domestic stock.

        Args:
            symbol: 6-digit KRX stock code (e.g. ``"005930"`` for Samsung).

        Returns:
            Dictionary containing at minimum:
                - ``stck_prpr``: current price (str)
                - ``stck_sdpr``: previous close (str)
                - ``prdy_ctrt``: day-over-day change rate (str, %)
                - ``acml_vol``:  accumulated volume (str)

        Raises:
            KeyError: If the response does not contain the ``output`` field.
        """
        data = self._request(
            method="GET",
            path=_PRICE_PATH,
            tr_id="FHKST01010100",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": symbol,
            },
        )
        if "output" not in data:
            raise KeyError(
                f"KIS response for symbol {symbol!r} is missing 'output' key: {data}"
            )
        return data["output"]

    def get_ohlcv_5min(self, symbol: str) -> List[Dict[str, Any]]:
        """Retrieve intraday 5-minute OHLCV candles for a domestic stock.

        Returns up to 30 candles ending at the current time.

        Args:
            symbol: 6-digit KRX stock code.

        Returns:
            List of candle dictionaries, each containing ``stck_bsop_date``,
            ``stck_cntg_hour``, ``stck_oprc``, ``stck_hgpr``, ``stck_lwpr``,
            ``stck_prpr``, and ``cntg_vol``.
        """
        now_str = datetime.now().strftime("%H%M%S")
        data = self._request(
            method="GET",
            path=_CHART_5MIN_PATH,
            tr_id="FHKST03010200",
            params={
                "FID_ETC_CLS_CODE": "",
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": symbol,
                "FID_INPUT_HOUR_1": now_str,
                "FID_PW_DATA_INCU_YN": "N",
            },
        )
        if "output2" not in data:
            raise KeyError(
                f"KIS 5-min OHLCV response for {symbol!r} is missing 'output2' key: {data}"
            )
        return data["output2"]

    def get_ohlcv_daily(self, symbol: str, period: int = 60) -> List[Dict[str, Any]]:
        """Retrieve daily OHLCV candles for a domestic stock.

        Args:
            symbol: 6-digit KRX stock code.
            period: Number of calendar days to look back (default: 60).

        Returns:
            List of daily candle dictionaries, each containing
            ``stck_bsop_date``, ``stck_oprc``, ``stck_hgpr``, ``stck_lwpr``,
            ``stck_clpr``, and ``acml_vol``.
        """
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=period)).strftime("%Y%m%d")
        data = self._request(
            method="GET",
            path=_CHART_DAILY_PATH,
            tr_id="FHKST03010100",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": symbol,
                "FID_INPUT_DATE_1": start_date,
                "FID_INPUT_DATE_2": end_date,
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "1",
            },
        )
        if "output2" not in data:
            raise KeyError(
                f"KIS daily OHLCV response for {symbol!r} is missing 'output2' key: {data}"
            )
        return data["output2"]

    def get_index_data(self, index_code: str) -> Dict[str, Any]:
        """Retrieve current price data for a domestic market index.

        Args:
            index_code: KRX index code — ``"0001"`` for KOSPI,
                ``"1001"`` for KOSDAQ.

        Returns:
            Dictionary containing ``bstp_nmix_prpr`` (current index level),
            ``bstp_nmix_prdy_ctrt`` (day-over-day change rate), and related
            fields.
        """
        data = self._request(
            method="GET",
            path=_INDEX_PATH,
            tr_id="FHPUP02100000",
            params={
                "FID_COND_MRKT_DIV_CODE": "U",
                "FID_INPUT_ISCD": index_code,
            },
        )
        if "output" not in data:
            raise KeyError(
                f"KIS index response for code {index_code!r} is missing 'output' key: {data}"
            )
        return data["output"]

    def simulate_trade(
        self,
        symbol: str,
        signal_type: str,
        price: float,
        quantity: int = 1,
    ) -> Dict[str, Any]:
        """Simulate a trade order for demo / DEV_MODE purposes.

        When ``Settings.dev_mode`` is ``True`` this method logs the intended
        order and returns a mock response **without** sending any real order to
        KIS.  It is intended for local testing and CI pipelines where live API
        credentials are not available.

        Args:
            symbol:      6-digit KRX stock code (e.g. ``"005930"``).
            signal_type: Signal that triggered the trade (e.g. ``"BUY"``,
                         ``"SELL"``, ``"STOP_LOSS"``).
            price:       Execution price in KRW.
            quantity:    Number of shares (default: 1).

        Returns:
            Mock order response dictionary with keys ``symbol``, ``signal_type``,
            ``price``, ``quantity``, ``total_krw``, and ``simulated``.

        Raises:
            RuntimeError: If called when ``dev_mode`` is ``False``.
        """
        if not self._settings.dev_mode:
            raise RuntimeError(
                "simulate_trade() is only available when DEV_MODE=true. "
                "Use the real KIS order API for live trading."
            )

        total_krw: float = price * quantity
        self._logger.info(
            "[DEV_MODE] SIMULATED %s | symbol=%s | price=%.0f | qty=%d | total=%.0f KRW",
            signal_type,
            symbol,
            price,
            quantity,
            total_krw,
        )
        return {
            "symbol": symbol,
            "signal_type": signal_type,
            "price": price,
            "quantity": quantity,
            "total_krw": total_krw,
            "simulated": True,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        tr_id: str,
        params: Optional[Dict[str, str]] = None,
        json_body: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Execute an authenticated KIS API request.

        Injects the required KIS authentication headers (``appkey``,
        ``appsecret``, ``authorization``, ``tr_id``) automatically and
        validates the ``rt_cd`` field in the response.

        Args:
            method: HTTP method (``"GET"`` or ``"POST"``).
            path: API path starting with ``/`` (appended to the base URL).
            tr_id: KIS transaction ID for the target endpoint.
            params: URL query parameters (for GET requests).
            json_body: JSON request body (for POST requests).

        Returns:
            Full parsed JSON response dictionary.

        Raises:
            RuntimeError: If ``rt_cd != "0"`` in the response.
            requests.RequestException: Re-raised after all retry attempts.
        """
        headers: Dict[str, str] = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.get_access_token()}",
            "appkey": self._settings.kis_app_key,
            "appsecret": self._settings.kis_app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }

        if method.upper() == "GET":
            data = self._get_with_retry(path, headers, params or {})
        else:
            data = self._post_with_retry(
                path, headers=headers, json_body=json_body or {}
            )

        rt_cd = data.get("rt_cd")
        if rt_cd is not None and rt_cd != "0":
            msg_cd = data.get("msg_cd", "")
            msg1 = data.get("msg1", "")
            self._logger.error(
                "KIS API error on %s | rt_cd=%s | msg_cd=%s | msg=%s",
                path,
                rt_cd,
                msg_cd,
                msg1,
            )
            # EGW00123: access token invalid or expired — force re-issue on
            # the next call by clearing the cached token.
            if msg_cd in ("EGW00123",):
                self._logger.warning(
                    "KIS token appears invalid (msg_cd=%s); clearing cached token.",
                    msg_cd,
                )
                self._access_token = None
                self._token_expires_at = None
            raise RuntimeError(
                f"KIS API error on {path} " f"(rt_cd={rt_cd}, msg_cd={msg_cd}): {msg1}"
            )
        return data

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        before_sleep=before_sleep_log(_logger, logging.WARNING),
        reraise=True,
    )
    def _get_with_retry(
        self,
        path: str,
        headers: Dict[str, str],
        params: Dict[str, str],
    ) -> Dict[str, Any]:
        """HTTP GET with automatic retry on transient network errors.

        Args:
            path: API path (appended to the configured base URL).
            headers: Request headers including auth tokens.
            params: URL query parameters.

        Returns:
            Parsed JSON response dictionary.

        Raises:
            requests.RequestException: Re-raised after all retry attempts.
        """
        url = f"{self._settings.kis_base_url}{path}"
        resp = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=10,
            verify=ssl_verify(),  # False in DEV_MODE, True in production
        )
        resp.raise_for_status()
        return resp.json()

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        before_sleep=before_sleep_log(_logger, logging.WARNING),
        reraise=True,
    )
    def _post_with_retry(
        self,
        path: str,
        json_body: Dict[str, str],
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """HTTP POST with automatic retry on transient network errors.

        Args:
            path: API path (appended to the configured base URL).
            json_body: JSON-serialisable request body.
            headers: Optional request headers.

        Returns:
            Parsed JSON response dictionary.

        Raises:
            requests.RequestException: Re-raised after all retry attempts.
        """
        url = f"{self._settings.kis_base_url}{path}"
        resp = requests.post(
            url,
            json=json_body,
            headers=headers or {},
            timeout=10,
            verify=ssl_verify(),  # False in DEV_MODE, True in production
        )
        resp.raise_for_status()
        return resp.json()
