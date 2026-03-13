"""Unit tests for data_agent.kis_api.KISClient.

All HTTP calls are mocked; no live network access is required.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import requests

from data_agent.kis_api import KISClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.kis_app_key = "test_key"
    s.kis_app_secret = "test_secret"
    s.kis_base_url = "https://openapivts.koreainvestment.com:29443"
    return s


def _make_client() -> KISClient:
    return KISClient(_make_settings())


def _ok_response(body: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = body
    resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------


class TestIsTokenValid:
    def test_returns_false_when_no_token(self):
        client = _make_client()
        assert client._is_token_valid() is False

    def test_returns_false_when_no_expiry(self):
        client = _make_client()
        client._access_token = "tok"
        assert client._is_token_valid() is False

    def test_returns_true_when_token_fresh(self):
        client = _make_client()
        client._access_token = "tok"
        client._token_expires_at = datetime.now() + timedelta(hours=1)
        assert client._is_token_valid() is True

    def test_returns_false_when_token_expiring_soon(self):
        client = _make_client()
        client._access_token = "tok"
        # Within the 5-minute margin
        client._token_expires_at = datetime.now() + timedelta(minutes=3)
        assert client._is_token_valid() is False


class TestIssueToken:
    def test_caches_access_token_on_success(self):
        client = _make_client()
        resp_body = {"access_token": "new_tok", "expires_in": 86400}
        with patch.object(client, "_post_with_retry", return_value=resp_body):
            token = client._issue_token()
        assert token == "new_tok"
        assert client._access_token == "new_tok"
        assert client._token_expires_at is not None

    def test_raises_when_no_access_token_in_response(self):
        client = _make_client()
        with patch.object(client, "_post_with_retry", return_value={"error": "bad"}):
            with pytest.raises(RuntimeError, match="token issuance failed"):
                client._issue_token()

    def test_get_access_token_uses_cache(self):
        client = _make_client()
        client._access_token = "cached"
        client._token_expires_at = datetime.now() + timedelta(hours=1)
        with patch.object(client, "_issue_token") as mock_issue:
            result = client.get_access_token()
        mock_issue.assert_not_called()
        assert result == "cached"

    def test_get_access_token_reissues_when_stale(self):
        client = _make_client()
        # Expired token
        client._access_token = "old"
        client._token_expires_at = datetime.now() - timedelta(hours=1)
        with patch.object(client, "_issue_token", return_value="fresh") as mock_issue:
            result = client.get_access_token()
        mock_issue.assert_called_once()
        assert result == "fresh"


# ---------------------------------------------------------------------------
# Market data — output key guard
# ---------------------------------------------------------------------------


class TestGetCurrentPrice:
    def _mock_request(self, client: KISClient, body: dict) -> None:
        client._access_token = "tok"
        client._token_expires_at = datetime.now() + timedelta(hours=1)
        with patch.object(client, "_get_with_retry", return_value=body):
            return body

    def test_returns_output_on_success(self):
        client = _make_client()
        client._access_token = "tok"
        client._token_expires_at = datetime.now() + timedelta(hours=1)
        body = {"rt_cd": "0", "output": {"stck_prpr": "71500"}}
        with patch.object(client, "_get_with_retry", return_value=body):
            result = client.get_current_price("005930")
        assert result["stck_prpr"] == "71500"

    def test_raises_key_error_when_output_missing(self):
        client = _make_client()
        client._access_token = "tok"
        client._token_expires_at = datetime.now() + timedelta(hours=1)
        body = {"rt_cd": "0"}  # no "output" key
        with patch.object(client, "_get_with_retry", return_value=body):
            with pytest.raises(KeyError, match="output"):
                client.get_current_price("005930")


class TestGetOhlcvDaily:
    def test_returns_output2_on_success(self):
        client = _make_client()
        client._access_token = "tok"
        client._token_expires_at = datetime.now() + timedelta(hours=1)
        candles = [{"stck_clpr": "71500"}]
        body = {"rt_cd": "0", "output2": candles}
        with patch.object(client, "_get_with_retry", return_value=body):
            result = client.get_ohlcv_daily("005930")
        assert result == candles

    def test_raises_key_error_when_output2_missing(self):
        client = _make_client()
        client._access_token = "tok"
        client._token_expires_at = datetime.now() + timedelta(hours=1)
        body = {"rt_cd": "0"}
        with patch.object(client, "_get_with_retry", return_value=body):
            with pytest.raises(KeyError, match="output2"):
                client.get_ohlcv_daily("005930")


class TestGetOhlcv5Min:
    def test_returns_output2_on_success(self):
        client = _make_client()
        client._access_token = "tok"
        client._token_expires_at = datetime.now() + timedelta(hours=1)
        candles = [{"stck_prpr": "71500"}]
        body = {"rt_cd": "0", "output2": candles}
        with patch.object(client, "_get_with_retry", return_value=body):
            result = client.get_ohlcv_5min("005930")
        assert result == candles

    def test_raises_key_error_when_output2_missing(self):
        client = _make_client()
        client._access_token = "tok"
        client._token_expires_at = datetime.now() + timedelta(hours=1)
        body = {"rt_cd": "0"}
        with patch.object(client, "_get_with_retry", return_value=body):
            with pytest.raises(KeyError, match="output2"):
                client.get_ohlcv_5min("005930")


class TestGetIndexData:
    def test_returns_output_on_success(self):
        client = _make_client()
        client._access_token = "tok"
        client._token_expires_at = datetime.now() + timedelta(hours=1)
        body = {"rt_cd": "0", "output": {"bstp_nmix_prdy_ctrt": "-2.1"}}
        with patch.object(client, "_get_with_retry", return_value=body):
            result = client.get_index_data("0001")
        assert result["bstp_nmix_prdy_ctrt"] == "-2.1"

    def test_raises_key_error_when_output_missing(self):
        client = _make_client()
        client._access_token = "tok"
        client._token_expires_at = datetime.now() + timedelta(hours=1)
        body = {"rt_cd": "0"}
        with patch.object(client, "_get_with_retry", return_value=body):
            with pytest.raises(KeyError, match="output"):
                client.get_index_data("0001")


# ---------------------------------------------------------------------------
# _request — rt_cd error handling
# ---------------------------------------------------------------------------


class TestRequest:
    def _patch_token(self, client: KISClient) -> None:
        client._access_token = "tok"
        client._token_expires_at = datetime.now() + timedelta(hours=1)

    def test_raises_runtime_error_on_non_zero_rt_cd(self):
        client = _make_client()
        self._patch_token(client)
        body = {"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "bad param"}
        with patch.object(client, "_get_with_retry", return_value=body):
            with pytest.raises(RuntimeError, match="EGW00201"):
                client._request("GET", "/some/path", "FHKST01010100")

    def test_clears_token_on_egw00123(self):
        client = _make_client()
        self._patch_token(client)
        body = {"rt_cd": "1", "msg_cd": "EGW00123", "msg1": "token invalid"}
        with patch.object(client, "_get_with_retry", return_value=body):
            with pytest.raises(RuntimeError):
                client._request("GET", "/some/path", "FHKST01010100")
        assert client._access_token is None
        assert client._token_expires_at is None

    def test_passes_through_on_rt_cd_zero(self):
        client = _make_client()
        self._patch_token(client)
        body = {"rt_cd": "0", "output": {"x": 1}}
        with patch.object(client, "_get_with_retry", return_value=body):
            result = client._request("GET", "/path", "TR_ID")
        assert result["output"]["x"] == 1


# ---------------------------------------------------------------------------
# HTTP retry helpers
# ---------------------------------------------------------------------------


class TestGetWithRetry:
    def test_returns_parsed_json(self):
        client = _make_client()
        body = {"rt_cd": "0", "data": 42}
        with patch("requests.get", return_value=_ok_response(body)):
            result = client._get_with_retry("/path", {}, {})
        assert result["data"] == 42

    def test_raises_on_http_error(self):
        client = _make_client()
        resp = MagicMock()
        resp.raise_for_status.side_effect = requests.HTTPError("404")
        with patch("requests.get", return_value=resp):
            with pytest.raises(requests.HTTPError):
                client._get_with_retry("/path", {}, {})


class TestPostWithRetry:
    def test_returns_parsed_json(self):
        client = _make_client()
        body = {"access_token": "tok", "expires_in": 86400}
        with patch("requests.post", return_value=_ok_response(body)):
            result = client._post_with_retry("/oauth2/tokenP", {})
        assert result["access_token"] == "tok"
