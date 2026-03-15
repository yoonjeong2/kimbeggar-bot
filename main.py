"""KimBeggar — main entry point.

Runs a scheduled monitoring loop that:
1. Checks market-index health once per cycle (HEDGE signal).
2. For each watched symbol, fetches daily OHLCV and evaluates trading signals.
3. Sends a Kakao Talk notification whenever a non-HOLD signal is detected.

Entry prices are persisted in a SQLite database (``data/bot_state.db``) via
:class:`~data_agent.position_store.PositionStore` so they survive bot restarts.

The bot loop runs in a background daemon thread while the FastAPI web dashboard
is served by uvicorn on the main thread (default: http://0.0.0.0:8000).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, Optional

import schedule
import uvicorn

from api.app import create_app
from config.settings import Settings
from data_agent.kis_api import KISClient
from data_agent.position_store import PositionStore
from logger.log_setup import setup_logger
from notifier import NotifierService
from notifier.kakao import KakaoNotifier
from strategy.hedge_logic import calculate_hedge_ratio, describe_hedge
from strategy.signal import Signal, SignalEngine, SignalType, is_market_open


def run_cycle(
    settings: Settings,
    kis: KISClient,
    engine: SignalEngine,
    notifier: NotifierService,
    position_store: PositionStore,
    signal_log: Optional[Deque[Dict[str, Any]]] = None,
) -> None:
    """Execute one full monitoring cycle across all watched symbols.

    Skips execution outside Korean market hours (weekdays 09:00–15:30).

    Sequence
    --------
    1. Check market hours — skip cycle if outside trading window.
    2. Fetch KOSPI index data → evaluate market-level HEDGE condition.
    3. For each symbol in ``settings.watch_symbols``:
       a. Fetch daily OHLCV (60-day window).
       b. Fetch real-time current price.
       c. Run :meth:`~strategy.signal.SignalEngine.evaluate`.
       d. Send notification for any non-HOLD signal.
       e. Persist entry price to SQLite when a BUY signal fires.
       f. Append signal metadata to ``signal_log`` for the web dashboard.

    Args:
        settings:        Application ``Settings`` instance.
        kis:             Authenticated :class:`~data_agent.kis_api.KISClient`.
        engine:          :class:`~strategy.signal.SignalEngine` instance.
        notifier:        :class:`~notifier.base.NotifierService` composite.
        position_store:  :class:`~data_agent.position_store.PositionStore` for
                         persistent entry-price tracking across restarts.
        signal_log:      Optional deque shared with the web dashboard; receives
                         a dict summary for every non-HOLD signal detected.
    """
    logger = logging.getLogger(__name__)
    if not is_market_open():
        logger.info("장 운영 시간 외 — 사이클 스킵")
        return
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
                current_price=0.0,  # no single stock — use index signal only
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
        notifier.send_error(f"지수 데이터 조회 실패: {exc}")

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
            price_data = kis.get_current_price(symbol)
            current_price = float(price_data.get("stck_prpr", 0))

            # Patch the latest close in OHLCV so indicators reflect live price
            if ohlcv_data and current_price > 0:
                ohlcv_data[-1]["stck_clpr"] = str(int(current_price))

            # 2c. Evaluate signal
            entry = position_store.get(symbol)
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
                position_store.set(symbol, signal.price)
                logger.info("%s: entry price recorded at %.0f", symbol, signal.price)

            # Clear entry price after stop-loss or sell
            if signal.signal_type in (SignalType.STOP_LOSS, SignalType.SELL):
                position_store.delete(symbol)

            # 2f. Push to web dashboard signal log
            if signal_log is not None and signal.signal_type != SignalType.HOLD:
                from datetime import datetime

                signal_log.appendleft(
                    {
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "symbol": signal.symbol,
                        "signal_type": signal.signal_type.value,
                        "price": signal.price,
                        "rsi": (
                            round(signal.rsi, 1) if signal.rsi is not None else None
                        ),
                        "reason": signal.reason,
                    }
                )

        except Exception as exc:
            logger.error("Error processing symbol %s: %s", symbol, exc)
            notifier.send_error(f"[{symbol}] 처리 중 오류 발생: {exc}")

    logger.info("=== Monitoring cycle complete ===")


def _run_scheduler(
    settings: Settings,
    kis: KISClient,
    engine: SignalEngine,
    notifier: NotifierService,
    position_store: PositionStore,
    signal_log: Deque[Dict[str, Any]],
) -> None:
    """Blocking scheduler loop — runs inside a daemon thread."""
    schedule.every(settings.monitor_interval_minutes).minutes.do(
        run_cycle, settings, kis, engine, notifier, position_store, signal_log
    )
    # Fire once immediately so the first output is not delayed
    run_cycle(settings, kis, engine, notifier, position_store, signal_log)

    logger = logging.getLogger(__name__)
    logger.info(
        "Scheduler active — next run in %d minute(s).",
        settings.monitor_interval_minutes,
    )
    while True:
        schedule.run_pending()
        time.sleep(1)


def main() -> None:
    """Initialise all components, start the bot in a background thread, and
    serve the FastAPI dashboard on the main thread via uvicorn.

    The scheduler loop (bot) runs as a daemon thread so it is automatically
    cleaned up when the uvicorn process exits.  The web dashboard is available
    at ``http://0.0.0.0:8000`` by default.
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

    # Shared state between bot loop and web dashboard
    position_store = PositionStore("data/bot_state.db")
    signal_log: Deque[Dict[str, Any]] = deque(maxlen=50)

    # Start the scheduler loop in a background daemon thread
    bot_thread = threading.Thread(
        target=_run_scheduler,
        args=(
            settings,
            KISClient(settings),
            SignalEngine(settings),
            NotifierService([KakaoNotifier(settings)]),
            position_store,
            signal_log,
        ),
        daemon=True,
        name="bot-scheduler",
    )
    bot_thread.start()
    logger.info("Bot scheduler thread started (daemon).")

    # Build the FastAPI app and serve it on the main thread
    app = create_app(position_store, signal_log)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()
