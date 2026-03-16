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
from dataclasses import dataclass, field
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


@dataclass
class LevCallBacktestResult:
    """레버리지+콜 전략 백테스트 결과.

    Attributes:
        initial_cash:       초기 투자금 (KRW).
        final_value:        최종 포트폴리오 가치 (KRW).
        pnl:                절대 손익 (KRW).
        pnl_pct:            손익률 (%).
        total_trades:       완결 거래 수.
        won_trades:         수익 거래 수.
        lost_trades:        손실 거래 수.
        win_rate:           승률 (0–1).
        etf_pnl:            ETF 레그 손익 (KRW).
        option_pnl:         옵션 레그 손익 (KRW).
        max_drawdown_pct:   최대 낙폭 (%).
        partial_exits:      부분 청산 횟수.
        option_adds:        옵션 추가 매수 횟수.
        events:             이벤트 로그.
        effective_leverage: 실효 레버리지 배율.
    """

    initial_cash: float
    final_value: float
    pnl: float
    pnl_pct: float
    total_trades: int
    won_trades: int
    lost_trades: int
    win_rate: Optional[float]
    etf_pnl: float = 0.0
    option_pnl: float = 0.0
    max_drawdown_pct: float = 0.0
    partial_exits: int = 0
    option_adds: int = 0
    events: List[Any] = field(default_factory=list)
    effective_leverage: float = 1.0

    def __str__(self) -> str:
        win_str = f"{self.win_rate:.1%}" if self.win_rate is not None else "N/A"
        return (
            f"LevCallBacktestResult("
            f"initial={self.initial_cash:,.0f}  "
            f"final={self.final_value:,.0f}  "
            f"PnL={self.pnl:+,.0f} ({self.pnl_pct:+.2f}%)  "
            f"ETF={self.etf_pnl:+,.0f}  "
            f"Option={self.option_pnl:+,.0f}  "
            f"MDD={self.max_drawdown_pct:.2f}%  "
            f"trades={self.total_trades}  "
            f"win_rate={win_str}  "
            f"leverage={self.effective_leverage:.1f}x)"
        )


def run_lev_call_backtest(
    etf_ohlcv_df: pd.DataFrame,
    settings: Optional[Settings] = None,
    initial_cash: float = 10_000_000.0,
) -> LevCallBacktestResult:
    """레버리지 ETF + 콜 옵션 전략을 역사적 OHLCV 데이터로 백테스트합니다.

    Args:
        etf_ohlcv_df: ETF(122630) 일봉 OHLCV DataFrame.
            DatetimeIndex + open/high/low/close/volume 컬럼 필요.
        settings:     전략 파라미터. None이면 ``Settings()``(기본값) 사용.
        initial_cash: 초기 투자금 (KRW, 기본 10,000,000).

    Returns:
        :class:`LevCallBacktestResult` 백테스트 결과.

    Raises:
        ValueError: DataFrame이 비었거나 필수 컬럼이 없을 경우.
    """
    from backtest.lev_call_strategy import LevCallStrategy

    if settings is None:
        settings = Settings()

    df = _normalise_columns(etf_ohlcv_df)

    if df.empty:
        raise ValueError("etf_ohlcv_df is empty — nothing to backtest.")

    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"etf_ohlcv_df is missing columns: {missing}")

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.addstrategy(
        LevCallStrategy,
        initial_cash=initial_cash,
        etf_alloc=settings.lev_etf_alloc,
        option_alloc=settings.call_option_alloc,
        call_strike=settings.call_strike,
        call_expiry_months=settings.call_expiry_months,
        entry_kospi_level=settings.entry_kospi_level,
        exit_kospi_level=settings.exit_kospi_level,
        take_profit_pct=settings.take_profit_pct,
        take_profit_sell_ratio=settings.take_profit_sell_ratio,
        margin_leverage=settings.margin_leverage,
        vkospi_threshold=settings.vkospi_option_add_threshold,
        rsi_period=settings.rsi_period,
        rsi_oversold=settings.rsi_oversold,
        ma_short=settings.ma_short,
        ma_long=settings.ma_long,
    )

    cerebro.adddata(bt.feeds.PandasData(dataname=df))
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=_KRX_COMMISSION)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")

    _logger.info(
        "Starting lev_call backtest: %d bars | cash=%.0f",
        len(df),
        initial_cash,
    )
    results: List[bt.Strategy] = cerebro.run()
    final_value: float = cerebro.broker.getvalue()

    strat = results[0]
    trade_stats: Dict[str, Any] = strat.analyzers.trades.get_analysis()
    dd_stats: Dict[str, Any] = strat.analyzers.drawdown.get_analysis()

    total: int = trade_stats.get("total", {}).get("total", 0)
    won: int = trade_stats.get("won", {}).get("total", 0)
    lost: int = trade_stats.get("lost", {}).get("total", 0)
    win_rate: Optional[float] = won / total if total > 0 else None
    max_dd: float = -dd_stats.get("max", {}).get("drawdown", 0.0)

    pnl = final_value - initial_cash

    # 가상 포트폴리오에서 ETF/옵션 분해 손익 추출
    portfolio = strat._portfolio
    etf_pnl = 0.0
    option_pnl = 0.0
    for ev in portfolio.events:
        if ev.get("type") == "FULL_EXIT":
            etf_pnl += ev.get("etf_pnl", 0.0)
            option_pnl += ev.get("option_pnl", 0.0)

    # 실효 레버리지 = 총 노출 / 실제 투입 현금
    effective_leverage = settings.margin_leverage * settings.lev_etf_alloc + settings.call_option_alloc

    result = LevCallBacktestResult(
        initial_cash=initial_cash,
        final_value=final_value,
        pnl=pnl,
        pnl_pct=pnl / initial_cash * 100,
        total_trades=total,
        won_trades=won,
        lost_trades=lost,
        win_rate=win_rate,
        etf_pnl=etf_pnl,
        option_pnl=option_pnl,
        max_drawdown_pct=max_dd,
        partial_exits=portfolio.partial_exits,
        option_adds=portfolio.option_adds,
        events=strat.events,
        effective_leverage=effective_leverage,
    )
    _logger.info("Lev+Call backtest complete: %s", result)
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
