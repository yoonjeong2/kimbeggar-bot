"""Backtest runner for the KimBeggar strategy.

Wraps ``backtrader.Cerebro`` so callers only need to supply a pandas DataFrame
and optional ``Settings``; all broker / analyser wiring is handled internally.

Usage example
-------------
::

    import pandas as pd
    from backtest.runner import run_backtest

    df = pd.read_csv("samsung_daily.csv", index_col="date", parse_dates=True)
    result = run_backtest(df)
    print(result)

DataFrame column requirements
------------------------------
The DataFrame must have a ``DatetimeIndex`` (oldest bar first) and the
following columns (case-insensitive mapping is handled automatically):

    open, high, low, close, volume

Any extra columns are silently ignored.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import backtrader as bt
import pandas as pd

from backtest.strategy import KimBeggarStrategy
from config.settings import Settings

_logger = logging.getLogger(__name__)

# KRX standard one-way commission rate
_KRX_COMMISSION: float = 0.00015  # 0.015 %


@dataclass
class BacktestResult:
    """Summary statistics produced after a single backtest run.

    Attributes:
        initial_cash:  Starting portfolio cash (KRW).
        final_value:   Final portfolio value including open positions (KRW).
        pnl:           Absolute profit-and-loss (KRW).
        pnl_pct:       P&L as a percentage of initial cash.
        total_trades:  Total number of completed round-trip trades.
        won_trades:    Number of profitable trades.
        lost_trades:   Number of losing trades.
        win_rate:      Won / total (0–1); ``None`` when no trades were made.
    """

    initial_cash: float
    final_value: float
    pnl: float
    pnl_pct: float
    total_trades: int
    won_trades: int
    lost_trades: int
    win_rate: Optional[float]

    def __str__(self) -> str:
        return (
            f"BacktestResult("
            f"initial={self.initial_cash:,.0f}  "
            f"final={self.final_value:,.0f}  "
            f"PnL={self.pnl:+,.0f} ({self.pnl_pct:+.2f}%)  "
            f"trades={self.total_trades}  "
            f"win_rate={self.win_rate:.1%})"
            if self.win_rate is not None
            else (
                f"BacktestResult("
                f"initial={self.initial_cash:,.0f}  "
                f"final={self.final_value:,.0f}  "
                f"PnL={self.pnl:+,.0f} ({self.pnl_pct:+.2f}%)  "
                f"trades=0)"
            )
        )


def run_backtest(
    ohlcv_df: pd.DataFrame,
    settings: Optional[Settings] = None,
    initial_cash: float = 10_000_000.0,
) -> BacktestResult:
    """Run the KimBeggar strategy against historical OHLCV data.

    Args:
        ohlcv_df: DataFrame with a ``DatetimeIndex`` and columns
            ``open``, ``high``, ``low``, ``close``, ``volume``
            (case-insensitive).  Must contain at least
            ``Settings.ma_long + Settings.rsi_period`` rows.
        settings: Strategy parameters.  Defaults to ``Settings()`` (reads
            from ``.env`` / environment variables).
        initial_cash: Starting cash in KRW (default 10,000,000).

    Returns:
        :class:`BacktestResult` with final portfolio value and trade stats.

    Raises:
        ValueError: If ``ohlcv_df`` is missing required columns or is empty.
    """
    if settings is None:
        settings = Settings()

    df: pd.DataFrame = _normalise_columns(ohlcv_df)

    if df.empty:
        raise ValueError("ohlcv_df is empty — nothing to backtest.")

    required: set = {"open", "high", "low", "close", "volume"}
    missing: set = required - set(df.columns)
    if missing:
        raise ValueError(f"ohlcv_df is missing columns: {missing}")

    cerebro: bt.Cerebro = bt.Cerebro(stdstats=False)

    cerebro.addstrategy(
        KimBeggarStrategy,
        rsi_period=settings.rsi_period,
        rsi_oversold=settings.rsi_oversold,
        rsi_overbought=settings.rsi_overbought,
        ma_short=settings.ma_short,
        ma_long=settings.ma_long,
        stop_loss_rate=settings.stop_loss_rate,
    )

    cerebro.adddata(bt.feeds.PandasData(dataname=df))
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=_KRX_COMMISSION)

    # Analysers for trade statistics
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    _logger.info(
        "Starting backtest: %d bars | cash=%.0f",
        len(df),
        initial_cash,
    )
    results: List[bt.Strategy] = cerebro.run()
    final_value: float = cerebro.broker.getvalue()

    # --- Parse trade analyser results ----------------------------------
    trade_stats: Dict[str, Any] = results[0].analyzers.trades.get_analysis()
    total: int = trade_stats.get("total", {}).get("total", 0)
    won: int = trade_stats.get("won", {}).get("total", 0)
    lost: int = trade_stats.get("lost", {}).get("total", 0)
    win_rate: Optional[float] = won / total if total > 0 else None

    pnl: float = final_value - initial_cash

    result = BacktestResult(
        initial_cash=initial_cash,
        final_value=final_value,
        pnl=pnl,
        pnl_pct=pnl / initial_cash * 100,
        total_trades=total,
        won_trades=won,
        lost_trades=lost,
        win_rate=win_rate,
    )
    _logger.info("Backtest complete: %s", result)
    return result


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of *df* with lowercased column names.

    backtrader's ``PandasData`` expects lowercase ``open``, ``high``,
    ``low``, ``close``, ``volume``.

    Args:
        df: Input DataFrame (not mutated).

    Returns:
        New DataFrame with lowercase column names.
    """
    renamed: pd.DataFrame = df.copy()
    renamed.columns = pd.Index([c.lower() for c in renamed.columns])
    return renamed
