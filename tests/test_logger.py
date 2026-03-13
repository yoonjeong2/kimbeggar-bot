"""Unit tests for logger.log_setup."""

from __future__ import annotations

import logging

from logger.log_setup import setup_logger


class TestSetupLogger:
    def test_adds_handlers_to_root_logger(self, tmp_path, monkeypatch):
        # Point LOG_DIR to a temp directory so no real files are created
        import logger.log_setup as ls

        monkeypatch.setattr(ls, "LOG_DIR", tmp_path)
        monkeypatch.setattr(ls, "LOG_FILE", tmp_path / "bot.log")

        root = logging.getLogger()
        original_handlers = root.handlers[:]
        try:
            setup_logger(level=logging.DEBUG)
            assert len(root.handlers) > len(original_handlers)
        finally:
            # Restore original state so other tests are not affected
            for h in root.handlers[:]:
                if h not in original_handlers:
                    h.close()
                    root.removeHandler(h)

    def test_sets_requested_log_level(self, tmp_path, monkeypatch):
        import logger.log_setup as ls

        monkeypatch.setattr(ls, "LOG_DIR", tmp_path)
        monkeypatch.setattr(ls, "LOG_FILE", tmp_path / "bot.log")

        root = logging.getLogger()
        original_level = root.level
        original_handlers = root.handlers[:]
        try:
            setup_logger(level=logging.WARNING)
            assert root.level == logging.WARNING
        finally:
            root.setLevel(original_level)
            for h in root.handlers[:]:
                if h not in original_handlers:
                    h.close()
                    root.removeHandler(h)

    def test_creates_log_directory(self, tmp_path, monkeypatch):
        import logger.log_setup as ls

        log_dir = tmp_path / "new_logs"
        monkeypatch.setattr(ls, "LOG_DIR", log_dir)
        monkeypatch.setattr(ls, "LOG_FILE", log_dir / "bot.log")

        root = logging.getLogger()
        original_handlers = root.handlers[:]
        try:
            setup_logger()
            assert log_dir.exists()
        finally:
            for h in root.handlers[:]:
                if h not in original_handlers:
                    h.close()
                    root.removeHandler(h)
