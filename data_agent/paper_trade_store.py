"""Paper-trading ledger backed by SQLite.

When ``PAPER_TRADING=true`` the bot records every simulated fill to a
``paper_trades`` table in the same ``data/bot_state.db`` file used by
:class:`~data_agent.position_store.PositionStore`.  No real orders are
placed through the KIS API; the table acts as an auditable trade history
that can be inspected, replayed, or exported for analysis.

Table schema
------------
.. code-block:: sql

    CREATE TABLE IF NOT EXISTS paper_trades (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol      TEXT    NOT NULL,
        signal_type TEXT    NOT NULL,
        price       REAL    NOT NULL,
        quantity    INTEGER NOT NULL DEFAULT 1,
        total_krw   REAL    NOT NULL,
        traded_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
    );

P&L semantics
-------------
- ``BUY`` rows contribute to **cost** (bought_krw).
- ``SELL`` and ``STOP_LOSS`` rows contribute to **proceeds** (sold_krw).
- ``pnl_krw = sold_krw - bought_krw`` per symbol gives the realised P&L.
  Open positions (bought but not yet sold) show negative P&L until closed.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS paper_trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL,
    signal_type TEXT    NOT NULL,
    price       REAL    NOT NULL,
    quantity    INTEGER NOT NULL DEFAULT 1,
    total_krw   REAL    NOT NULL,
    traded_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""


class PaperTradeStore:
    """SQLite-backed virtual trade ledger for paper-trading mode.

    Shares the same database file as :class:`~data_agent.position_store.PositionStore`
    (``data/bot_state.db`` by default) so a single ``data/`` directory holds
    the complete bot state.

    Args:
        db_path: Path to the SQLite database file.  The parent directory is
                 created automatically if it does not exist.
                 Defaults to ``"data/bot_state.db"``.
    """

    def __init__(self, db_path: str = "data/bot_state.db") -> None:
        if dir_name := os.path.dirname(db_path):
            os.makedirs(dir_name, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(
        self,
        symbol: str,
        signal_type: str,
        price: float,
        quantity: int = 1,
    ) -> Dict[str, Any]:
        """Insert a simulated fill into the ``paper_trades`` table.

        Args:
            symbol:      KRX 6-digit stock code (e.g. ``"005930"``).
            signal_type: Signal that triggered the fill — one of
                         ``"BUY"``, ``"SELL"``, ``"STOP_LOSS"``, ``"HEDGE"``.
            price:       Execution price in KRW.
            quantity:    Number of shares (default 1).

        Returns:
            Dict with ``symbol``, ``signal_type``, ``price``, ``quantity``,
            and ``total_krw`` fields mirroring the inserted row.
        """
        total_krw = price * quantity
        self._conn.execute(
            """
            INSERT INTO paper_trades (symbol, signal_type, price, quantity, total_krw)
            VALUES (?, ?, ?, ?, ?)
            """,
            (symbol, signal_type, price, quantity, total_krw),
        )
        self._conn.commit()
        return {
            "symbol": symbol,
            "signal_type": signal_type,
            "price": price,
            "quantity": quantity,
            "total_krw": total_krw,
        }

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_all(self) -> List[Dict[str, Any]]:
        """Return all trades, newest first.

        Returns:
            List of dicts with keys ``id``, ``symbol``, ``signal_type``,
            ``price``, ``quantity``, ``total_krw``, ``traded_at``.
        """
        rows = self._conn.execute(
            """
            SELECT id, symbol, signal_type, price, quantity, total_krw, traded_at
            FROM   paper_trades
            ORDER  BY id DESC
            """
        ).fetchall()
        return [
            {
                "id": row[0],
                "symbol": row[1],
                "signal_type": row[2],
                "price": float(row[3]),
                "quantity": row[4],
                "total_krw": float(row[5]),
                "traded_at": row[6],
            }
            for row in rows
        ]

    def get_by_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        """Return all trades for *symbol*, newest first."""
        rows = self._conn.execute(
            """
            SELECT id, symbol, signal_type, price, quantity, total_krw, traded_at
            FROM   paper_trades
            WHERE  symbol = ?
            ORDER  BY id DESC
            """,
            (symbol,),
        ).fetchall()
        return [
            {
                "id": row[0],
                "symbol": row[1],
                "signal_type": row[2],
                "price": float(row[3]),
                "quantity": row[4],
                "total_krw": float(row[5]),
                "traded_at": row[6],
            }
            for row in rows
        ]

    def get_summary(self) -> Dict[str, Dict[str, Any]]:
        """Return realised P&L summary grouped by symbol.

        Returns:
            ``{symbol: {"bought_krw": float, "sold_krw": float,
            "pnl_krw": float, "trades": int}}``
        """
        rows = self._conn.execute(
            """
            SELECT symbol,
                   SUM(CASE WHEN signal_type = 'BUY'
                            THEN total_krw ELSE 0 END)          AS bought,
                   SUM(CASE WHEN signal_type IN ('SELL','STOP_LOSS')
                            THEN total_krw ELSE 0 END)          AS sold,
                   COUNT(*)                                      AS trades
            FROM   paper_trades
            GROUP  BY symbol
            """
        ).fetchall()
        return {
            row[0]: {
                "bought_krw": float(row[1]),
                "sold_krw": float(row[2]),
                "pnl_krw": float(row[2]) - float(row[1]),
                "trades": row[3],
            }
            for row in rows
        }

    def clear(self) -> None:
        """Delete all paper-trade records (useful in tests)."""
        self._conn.execute("DELETE FROM paper_trades")
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
