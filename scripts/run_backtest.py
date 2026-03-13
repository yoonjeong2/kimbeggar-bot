"""Example script: run KimBeggar backtest against KIS daily OHLCV data.

Usage
-----
::

    python scripts/run_backtest.py --symbol 005930 --days 365

The script fetches daily OHLCV candles from the KIS API, converts them to
the backtrader-compatible format, runs the backtest, and prints a summary.

Requirements
------------
- A valid ``.env`` file with KIS credentials (``KIS_APP_KEY``, etc.)
- DEV_MODE=true for local environments without a trusted CA bundle
"""

from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

# Allow running from project root without installing the package
sys.path.insert(0, ".")

from config.settings import Settings
from data_agent.kis_api import KISClient
from backtest.runner import run_backtest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
_logger = logging.getLogger(__name__)


def _ohlcv_to_dataframe(candles: list) -> pd.DataFrame:
    """Convert a KIS daily OHLCV list to a backtrader-compatible DataFrame.

    KIS field mapping:
        stck_bsop_date → index (DatetimeIndex)
        stck_oprc      → open
        stck_hgpr      → high
        stck_lwpr      → low
        stck_clpr      → close
        acml_vol       → volume

    Args:
        candles: List of dicts returned by ``KISClient.get_ohlcv_daily()``.

    Returns:
        DataFrame sorted oldest-first with a DatetimeIndex.
    """
    rows = []
    for c in candles:
        rows.append(
            {
                "date": pd.to_datetime(c["stck_bsop_date"], format="%Y%m%d"),
                "open": float(c["stck_oprc"]),
                "high": float(c["stck_hgpr"]),
                "low": float(c["stck_lwpr"]),
                "close": float(c["stck_clpr"]),
                "volume": float(c["acml_vol"]),
            }
        )
    df = pd.DataFrame(rows).set_index("date").sort_index()
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="KimBeggar backtest runner")
    parser.add_argument(
        "--symbol", default="005930", help="KRX 6-digit stock code (default: 005930)"
    )
    parser.add_argument(
        "--days", type=int, default=365, help="Look-back period in calendar days"
    )
    parser.add_argument(
        "--cash", type=float, default=10_000_000, help="Initial cash in KRW"
    )
    args = parser.parse_args()

    settings = Settings()
    client = KISClient(settings)

    _logger.info("Fetching %d days of daily OHLCV for %s …", args.days, args.symbol)
    candles = client.get_ohlcv_daily(args.symbol, period=args.days)
    _logger.info("Received %d candles.", len(candles))

    df = _ohlcv_to_dataframe(candles)
    result = run_backtest(df, settings=settings, initial_cash=args.cash)

    print("\n" + "=" * 55)
    print(f"  Symbol        : {args.symbol}")
    print(f"  Period        : {df.index[0].date()} ~ {df.index[-1].date()}")
    print(f"  Bars          : {len(df)}")
    print(f"  Initial cash  : {result.initial_cash:>15,.0f} KRW")
    print(f"  Final value   : {result.final_value:>15,.0f} KRW")
    print(f"  PnL           : {result.pnl:>+15,.0f} KRW  ({result.pnl_pct:+.2f}%)")
    print(f"  Total trades  : {result.total_trades}")
    if result.win_rate is not None:
        print(f"  Won / Lost    : {result.won_trades} / {result.lost_trades}")
        print(f"  Win rate      : {result.win_rate:.1%}")
    print("=" * 55 + "\n")


if __name__ == "__main__":
    main()
