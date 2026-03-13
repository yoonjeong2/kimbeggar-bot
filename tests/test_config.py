"""Unit tests for config modules.

Coverage
--------
- ``config.ssl.ssl_verify``  : DEV_MODE flag handling
"""

from __future__ import annotations

import os
from unittest.mock import patch

from config.ssl import ssl_verify


class TestSslVerify:
    """Tests for the centralised SSL verification helper."""

    def test_returns_false_when_dev_mode_true(self):
        with patch.dict(os.environ, {"DEV_MODE": "true"}):
            assert ssl_verify() is False

    def test_returns_false_when_dev_mode_true_uppercase(self):
        with patch.dict(os.environ, {"DEV_MODE": "TRUE"}):
            assert ssl_verify() is False

    def test_returns_true_when_dev_mode_false(self):
        with patch.dict(os.environ, {"DEV_MODE": "false"}):
            assert ssl_verify() is True

    def test_returns_true_when_dev_mode_not_set(self):
        env = {k: v for k, v in os.environ.items() if k != "DEV_MODE"}
        with patch.dict(os.environ, env, clear=True):
            assert ssl_verify() is True

    def test_returns_true_when_dev_mode_empty_string(self):
        with patch.dict(os.environ, {"DEV_MODE": ""}):
            assert ssl_verify() is True
