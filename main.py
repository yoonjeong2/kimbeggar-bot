"""KimBeggar — main entry point.

Runs a scheduled monitoring loop that:
1. Checks market-index health once per cycle (HEDGE signal).
2. For each watched symbol, fetches daily OHLCV and evaluates trading signals.
3. Sends a Kakao Talk notification whenever a non-HOLD signal is detected.

Entry prices are tracked in-memory (reset on restart).  For a persistent
position tracker, replace the ``entry_prices`` dict with a database or
JSON-file backed store.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional

import schedule

from config.settings import Settings
from data_agent.kis_api import KISClient
from logger.log_setup import setup_logger
from notifier import NotifierService
from notifier.kakao import KakaoNotifier
from strategy.hedge_logic import calculate_hedge_ratio, describe_hedge
from strategy.signal import Signal, SignalEngine, SignalType


def run_cycle(
    settings: Settings,
    kis: KISClient,
    engine: SignalEngine,
    notifier: NotifierService,
    entry_prices: Dict[str, Optional[float]],
) -> None:
    """Execute one full monitoring cycle across all watched symbols.

    Sequence
    --------
    1. Fetch KOSPI index data → evaluate market-level HEDGE condition.
    2. For each symbol in ``settings.watch_symbols``:
       a. Fetch daily OHLCV (60-day window).
       b. Fetch real-time current price.
       c. Run :meth:`~strategy.signal.SignalEngine.evaluate`.
       d. Send notification for any non-HOLD signal.
       e. Record entry price when a BUY signal fires.

    Args:
        settings:      Application ``Settings`` instance.
        kis:           Authenticated :class:`~data_agent.kis_api.KISClient`.
        engine:        :class:`~strategy.signal.SignalEngine` instance.
        notifier:      :class:`~notifier.base.NotifierService` composite.
        entry_prices:  Mutable dict mapping symbol → entry price.  Updated
                       in-place when BUY signals are generated.
    """
    logger = logging.getLogger(__name__)
    logger.info("=== Monitoring cycle start ===")

    # ------------------------------------------------------------------
    # Step 1 — Market-level hedge check (KOSPI: 0001 / KOSDAQ: 1001)
    # ------------------------------------------------------------------
    try:
        kospi_data = kis.get_index_data("0001")
        if engine.check_hedge_signal(kospi_data):
            # Compute a dynamic hedge ratio using KOSPI change rate
            index_change_rate = float(kospi_data.get("bstp_nmix_prdy_ctrt", "0"))
            ratio = calculate_hedge_ratio(
                current_price=0.0,   # no single stock — use index signal only
                long_ma=0.0,
                base_ratio=settings.hedge_ratio,
                index_change_rate=index_change_rate,
            )
            message = (
                f"[헤지 경고] 코스피 급락 감지 ({index_change_rate:+.2f}%)\n"
                f"{describe_hedge(ratio)}"
            )
            notifier.send_message(message)
            logger.warning("HEDGE alert sent: KOSPI %+.2f%%", index_change_rate)
    except Exception as exc:
        logger.error("Index data fetch failed: %s", exc)

    # ------------------------------------------------------------------
    # Step 2 — Per-symbol signal evaluation
    # ------------------------------------------------------------------
    for symbol in settings.watch_symbols:
        symbol = symbol.strip()
        if not symbol:
            continue

        try:
            # 2a. Fetch daily OHLCV for indicator calculation
            ohlcv_data = kis.get_ohlcv_daily(symbol, period=60)

            # 2b. Fetch real-time price to update the last close value
            price_data    = kis.get_current_price(symbol)
            current_price = float(price_data.get("stck_prpr", 0))

            # Patch the latest close in OHLCV so indicators reflect live price
            if ohlcv_data and current_price > 0:
                ohlcv_data[-1]["stck_clpr"] = str(int(current_price))

            # 2c. Evaluate signal
            entry = entry_prices.get(symbol)
            signal: Signal = engine.evaluate(symbol, ohlcv_data, entry_price=entry)

            logger.info(
                "%s | %s | price=%.0f | RSI=%s",
                symbol,
                signal.signal_type.value,
                signal.price,
                f"{signal.rsi:.1f}" if signal.rsi is not None else "N/A",
            )

            # 2d. Notify on actionable signals
            if signal.signal_type != SignalType.HOLD:
                notifier.send_signal(signal)

                # Also attach a dynamic hedge ratio to STOP_LOSS / HEDGE signals
                if signal.signal_type in (SignalType.STOP_LOSS, SignalType.HEDGE):
                    long_ma_val = signal.ma_long or signal.price
                    ratio = calculate_hedge_ratio(
                        current_price=signal.price,
                        long_ma=long_ma_val,
                        base_ratio=settings.hedge_ratio,
                    )
                    notifier.send_message(
                        f"[헤지 권고] {symbol}\n{describe_hedge(ratio)}"
                    )

            # 2e. Track entry price when a buy fires
            if signal.signal_type == SignalType.BUY:
                entry_prices[symbol] = signal.price
                logger.info(
                    "%s: entry price recorded at %.0f", symbol, signal.price
                )

            # Clear entry price after stop-loss or sell
            if signal.signal_type in (SignalType.STOP_LOSS, SignalType.SELL):
                entry_prices.pop(symbol, None)

        except Exception as exc:
            logger.error("Error processing symbol %s: %s", symbol, exc)

    logger.info("=== Monitoring cycle complete ===")


def main() -> None:
    """Initialise all components and start the scheduling loop.

    The bot fires immediately on startup (so you see output right away) and
    then repeats every ``settings.monitor_interval_minutes`` minutes via the
    ``schedule`` library.
    """
    settings = Settings()
    setup_logger()

    logger = logging.getLogger(__name__)
    logger.info("KimBeggar bot starting up.")
    logger.info(
        "Watching %d symbols every %d minute(s): %s",
        len(settings.watch_symbols),
        settings.monitor_interval_minutes,
        ", ".join(settings.watch_symbols),
    )

    # Initialise API clients and engine
    kis      = KISClient(settings)
    engine   = SignalEngine(settings)
    notifier = NotifierService([KakaoNotifier(settings)])

    # In-memory entry-price tracker { symbol: entry_price }
    entry_prices: Dict[str, Optional[float]] = {}

    # Register the recurring job
    schedule.every(settings.monitor_interval_minutes).minutes.do(
        run_cycle, settings, kis, engine, notifier, entry_prices
    )

    # Run once immediately so the first output is not delayed
    run_cycle(settings, kis, engine, notifier, entry_prices)

    logger.info(
        "Scheduler active — next run in %d minute(s).",
        settings.monitor_interval_minutes,
    )

    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
