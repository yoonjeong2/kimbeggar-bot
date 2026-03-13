"""Unit tests for notifier.kakao_token_manager.KakaoTokenManager."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
import requests

from notifier.kakao_token_manager import KakaoTokenManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _manager(token_file: str = "data/kakao_token.json") -> KakaoTokenManager:
    return KakaoTokenManager(token_file=token_file, rest_api_key="rest_key")


def _future_iso(hours: int = 6) -> str:
    return (datetime.now() + timedelta(hours=hours)).isoformat()


def _past_iso(hours: int = 1) -> str:
    return (datetime.now() - timedelta(hours=hours)).isoformat()


# ---------------------------------------------------------------------------
# load / save
# ---------------------------------------------------------------------------


class TestLoad:
    def test_returns_false_when_file_missing(self):
        mgr = _manager("/nonexistent/path/token.json")
        assert mgr.load() is False

    def test_returns_true_and_populates_data(self, tmp_path):
        token_file = str(tmp_path / "token.json")
        data = {"access_token": "at", "refresh_token": "rt"}
        with open(token_file, "w") as fh:
            json.dump(data, fh)

        mgr = _manager(token_file)
        assert mgr.load() is True
        assert mgr._token_data["access_token"] == "at"

    def test_returns_false_on_invalid_json(self, tmp_path):
        token_file = str(tmp_path / "bad.json")
        with open(token_file, "w") as fh:
            fh.write("not json")

        mgr = _manager(token_file)
        assert mgr.load() is False


class TestSave:
    def test_persists_data_to_file(self, tmp_path):
        token_file = str(tmp_path / "token.json")
        mgr = _manager(token_file)
        mgr.save({"access_token": "new_tok"})

        with open(token_file) as fh:
            saved = json.load(fh)
        assert saved["access_token"] == "new_tok"

    def test_updates_in_memory_data(self, tmp_path):
        token_file = str(tmp_path / "token.json")
        mgr = _manager(token_file)
        mgr.save({"access_token": "mem_tok"})
        assert mgr._token_data["access_token"] == "mem_tok"

    def test_creates_parent_directory(self, tmp_path):
        nested = str(tmp_path / "sub" / "dir" / "token.json")
        mgr = _manager(nested)
        mgr.save({"x": 1})
        assert os.path.exists(nested)


# ---------------------------------------------------------------------------
# get_valid_access_token
# ---------------------------------------------------------------------------


class TestGetValidAccessToken:
    def test_returns_none_when_no_token_data(self):
        mgr = _manager("/nonexistent/token.json")
        result = mgr.get_valid_access_token()
        assert result is None

    def test_returns_token_when_fresh(self):
        mgr = _manager()
        mgr._token_data = {
            "access_token": "fresh_tok",
            "access_token_expires_at": _future_iso(2),
            "refresh_token": "rt",
            "refresh_token_expires_at": _future_iso(24 * 30),
        }
        result = mgr.get_valid_access_token()
        assert result == "fresh_tok"

    def test_triggers_refresh_when_expiring(self):
        mgr = _manager()
        mgr._token_data = {
            "access_token": "expiring_tok",
            "access_token_expires_at": _past_iso(1),  # already expired
            "refresh_token": "rt",
        }
        with patch.object(mgr, "refresh", return_value=True) as mock_refresh:
            mgr._token_data["access_token"] = "refreshed_tok"
            mgr.get_valid_access_token()
        mock_refresh.assert_called_once()

    def test_returns_none_when_refresh_fails(self):
        mgr = _manager()
        mgr._token_data = {
            "access_token": "expiring",
            "access_token_expires_at": _past_iso(1),
            "refresh_token": "rt",
        }
        with patch.object(mgr, "refresh", return_value=False):
            result = mgr.get_valid_access_token()
        assert result is None


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------


class TestRefresh:
    def test_returns_false_when_no_refresh_token(self):
        mgr = _manager()
        mgr._token_data = {"access_token": "at"}
        assert mgr.refresh() is False

    def test_returns_false_when_refresh_token_expired(self):
        mgr = _manager()
        mgr._token_data = {
            "refresh_token": "rt",
            "refresh_token_expires_at": _past_iso(24 * 10),
        }
        assert mgr.refresh() is False

    def test_returns_true_and_saves_on_success(self, tmp_path):
        token_file = str(tmp_path / "token.json")
        mgr = _manager(token_file)
        mgr._token_data = {
            "access_token": "old",
            "refresh_token": "rt",
            "refresh_token_expires_at": _future_iso(24 * 60),
        }
        response = {"access_token": "new_at", "expires_in": 21600}
        with patch.object(mgr, "_post_token_with_retry", return_value=response):
            result = mgr.refresh()
        assert result is True
        assert mgr._token_data["access_token"] == "new_at"

    def test_returns_false_on_api_error_key(self):
        mgr = _manager()
        mgr._token_data = {
            "refresh_token": "rt",
            "refresh_token_expires_at": _future_iso(24 * 60),
        }
        response = {"error": "invalid_grant", "error_description": "token expired"}
        with patch.object(mgr, "_post_token_with_retry", return_value=response):
            result = mgr.refresh()
        assert result is False

    def test_returns_false_on_request_exception(self):
        mgr = _manager()
        mgr._token_data = {
            "refresh_token": "rt",
            "refresh_token_expires_at": _future_iso(24 * 60),
        }
        with patch.object(
            mgr, "_post_token_with_retry", side_effect=requests.RequestException("fail")
        ):
            result = mgr.refresh()
        assert result is False

    def test_also_renews_refresh_token_when_present_in_response(self, tmp_path):
        token_file = str(tmp_path / "token.json")
        mgr = _manager(token_file)
        mgr._token_data = {
            "refresh_token": "old_rt",
            "refresh_token_expires_at": _future_iso(24 * 60),
        }
        response = {
            "access_token": "new_at",
            "expires_in": 21600,
            "refresh_token": "new_rt",
            "refresh_token_expires_in": 5184000,
        }
        with patch.object(mgr, "_post_token_with_retry", return_value=response):
            mgr.refresh()
        assert mgr._token_data["refresh_token"] == "new_rt"


# ---------------------------------------------------------------------------
# Expiry helpers
# ---------------------------------------------------------------------------


class TestIsAccessTokenExpiring:
    def test_returns_true_when_no_expiry_field(self):
        mgr = _manager()
        mgr._token_data = {}
        assert mgr._is_access_token_expiring() is True

    def test_returns_true_when_expired(self):
        mgr = _manager()
        mgr._token_data = {"access_token_expires_at": _past_iso(1)}
        assert mgr._is_access_token_expiring() is True

    def test_returns_false_when_fresh(self):
        mgr = _manager()
        mgr._token_data = {"access_token_expires_at": _future_iso(2)}
        assert mgr._is_access_token_expiring() is False

    def test_returns_true_on_invalid_iso_string(self):
        mgr = _manager()
        mgr._token_data = {"access_token_expires_at": "not-a-date"}
        assert mgr._is_access_token_expiring() is True


class TestIsRefreshTokenExpired:
    def test_returns_false_when_no_expiry_field(self):
        mgr = _manager()
        mgr._token_data = {}
        assert mgr._is_refresh_token_expired() is False

    def test_returns_true_when_expired(self):
        mgr = _manager()
        mgr._token_data = {"refresh_token_expires_at": _past_iso(24)}
        assert mgr._is_refresh_token_expired() is True

    def test_returns_false_when_fresh(self):
        mgr = _manager()
        mgr._token_data = {"refresh_token_expires_at": _future_iso(24 * 30)}
        assert mgr._is_refresh_token_expired() is False
