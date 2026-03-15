"""Persistent position store backed by SQLite.

Replaces the in-memory ``entry_prices`` dict so that entry prices survive
bot restarts.  Uses only the Python standard-library ``sqlite3`` module —
no extra dependencies required.
"""

from __future__ import annotations

import sqlite3
from typing import Dict, Optional

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS positions (
    symbol      TEXT PRIMARY KEY,
    entry_price REAL NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""


class PositionStore:
    """SQLite-backed store for open position entry prices.

    Args:
        db_path: Path to the SQLite database file.  The parent directory
                 must already exist.  Defaults to ``"data/bot_state.db"``.
    """

    def __init__(self, db_path: str = "data/bot_state.db") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, symbol: str) -> Optional[float]:
        """Return the stored entry price for *symbol*, or ``None``."""
        row = self._conn.execute(
            "SELECT entry_price FROM positions WHERE symbol = ?", (symbol,)
        ).fetchone()
        return float(row[0]) if row else None

    def set(self, symbol: str, price: float) -> None:
        """Insert or replace the entry price for *symbol*."""
        self._conn.execute(
            """
            INSERT OR REPLACE INTO positions (symbol, entry_price, updated_at)
            VALUES (?, ?, datetime('now', 'localtime'))
            """,
            (symbol, price),
        )
        self._conn.commit()

    def delete(self, symbol: str) -> None:
        """Remove the entry for *symbol* (no-op if not present)."""
        self._conn.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))
        self._conn.commit()

    def get_all(self) -> Dict[str, float]:
        """Return all stored positions as ``{symbol: entry_price}``."""
        rows = self._conn.execute(
            "SELECT symbol, entry_price FROM positions"
        ).fetchall()
        return {row[0]: float(row[1]) for row in rows}

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
