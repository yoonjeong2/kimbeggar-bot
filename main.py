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
import os
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, Optional

import schedule
import uvicorn

from api.app import ConnectionManager, create_app
from config.settings import Settings
from data_agent.kis_api import KISClient
from data_agent.paper_trade_store import PaperTradeStore
from data_agent.position_store import PositionStore
from data_agent.name_resolver import get_resolver
from data_agent.screener import ScreenerResult, get_dynamic_targets
from logger.log_setup import setup_logger
from notifier import NotifierService
from notifier.kakao import KakaoNotifier
from strategy.hedge_logic import calculate_hedge_ratio, describe_hedge
from strategy.lev_call_signal import LevCallSignalEngine, LevCallSignalType
from strategy.option_pricing import estimate_premium_per_contract
from strategy.portfolio_tracker import LevCallPortfolio
from strategy.signal import Signal, SignalEngine, SignalType, is_market_open
from strategy.vkospi_estimator import estimate_vkospi


def run_cycle(
    settings: Settings,
    kis: KISClient,
    engine: SignalEngine,
    notifier: NotifierService,
    position_store: PositionStore,
    signal_log: Optional[Deque[Dict[str, Any]]] = None,
    broadcaster: Optional[ConnectionManager] = None,
    paper_trade_store: Optional[PaperTradeStore] = None,
    screener_targets: Optional[list] = None,
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
       g. Broadcast updated state to all connected WebSocket clients.
       h. Record simulated fill to ``paper_trades`` when PAPER_TRADING is on.

    Args:
        settings:          Application ``Settings`` instance.
        kis:               Authenticated :class:`~data_agent.kis_api.KISClient`.
        engine:            :class:`~strategy.signal.SignalEngine` instance.
        notifier:          :class:`~notifier.base.NotifierService` composite.
        position_store:    :class:`~data_agent.position_store.PositionStore` for
                           persistent entry-price tracking across restarts.
        signal_log:        Optional deque shared with the web dashboard; receives
                           a dict summary for every non-HOLD signal detected.
        broadcaster:       Optional :class:`~api.app.ConnectionManager` used to
                           push real-time updates to connected WebSocket clients.
        paper_trade_store: Optional :class:`~data_agent.paper_trade_store.PaperTradeStore`
                           active when ``settings.paper_trading`` is ``True``.
                           Every non-HOLD signal is recorded as a virtual fill.
        screener_targets:  Optional list of :class:`~data_agent.screener.ScreenerResult`
                           from the dynamic screener.  Their symbols are merged
                           with ``settings.watch_symbols`` for this cycle.
    """
    logger = logging.getLogger(__name__)
    if not is_market_open():
        logger.info("Market hours filter — cycle skipped.")
        return
    logger.info("=== Monitoring cycle start ===")
    resolver = get_resolver()

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
        notifier.send_error(f"Index data fetch failed: {exc}")

    # ------------------------------------------------------------------
    # Step 2 — Per-symbol signal evaluation
    # 정적 watch_symbols + 스크리너 동적 종목 합산 (중복 제거, 순서 유지)
    # ------------------------------------------------------------------
    _static = [s.strip() for s in settings.watch_symbols if s.strip()]
    _dynamic = [t.symbol for t in (screener_targets or []) if t.symbol]
    all_symbols = list(dict.fromkeys(_static + _dynamic))

    for symbol in all_symbols:
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
                resolver.display(symbol),
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
                        f"[헤지 권고] {resolver.display(symbol)}\n{describe_hedge(ratio)}"
                    )

            # 2e. Track entry price when a buy fires
            if signal.signal_type == SignalType.BUY:
                position_store.set(symbol, signal.price)
                logger.info(
                    "%s: entry price recorded at %.0f",
                    resolver.display(symbol),
                    signal.price,
                )

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
                        "display_name": resolver.display(signal.symbol),
                        "signal_type": signal.signal_type.value,
                        "price": signal.price,
                        "rsi": (
                            round(signal.rsi, 1) if signal.rsi is not None else None
                        ),
                        "reason": signal.reason,
                    }
                )

                # 2g. Broadcast real-time update to all WebSocket clients
                if broadcaster is not None:
                    broadcaster.broadcast_threadsafe(
                        {
                            "type": "update",
                            "positions": position_store.get_all(),
                            "signals": list(signal_log),
                            "screener": [
                                t.to_dict()
                                for t in (screener_targets or [])
                            ],
                        }
                    )

                # 2h. Paper-trading: record simulated fill (no real order)
                if paper_trade_store is not None:
                    paper_trade_store.record(
                        symbol=signal.symbol,
                        signal_type=signal.signal_type.value,
                        price=signal.price,
                    )
                    logger.info(
                        "[PAPER] %s %s @ %.0f 체결 기록",
                        signal.signal_type.value,
                        signal.symbol,
                        signal.price,
                    )

        except Exception as exc:
            logger.error("Error processing symbol %s: %s", symbol, exc)
            notifier.send_error(f"[{symbol}] Error processing symbol: {exc}")

    # ------------------------------------------------------------------
    # Step 3 — Leverage + Call Option Strategy (조건부)
    # ------------------------------------------------------------------
    if settings.lev_call_enabled:
        try:
            _run_lev_call_cycle(
                settings=settings,
                kis=kis,
                notifier=notifier,
                signal_log=signal_log,
                paper_trade_store=paper_trade_store,
            )
        except Exception as exc:
            logger.error("LevCall strategy error: %s", exc)
            notifier.send_error(f"[LevCall] 전략 오류: {exc}")

    logger.info("=== Monitoring cycle complete ===")


def _run_lev_call_cycle(
    settings: Settings,
    kis: KISClient,
    notifier: NotifierService,
    signal_log: Optional[Deque[Dict[str, Any]]] = None,
    paper_trade_store: Optional[PaperTradeStore] = None,
) -> None:
    """레버리지+콜 옵션 전략 사이클을 실행합니다.

    ETF OHLCV 조회 → VKOSPI 추정 → BS 옵션 가격 계산 →
    시그널 평가 → 알림 전송 → 페이퍼 트레이딩 기록.

    Args:
        settings:          전략 설정.
        kis:               KIS API 클라이언트.
        notifier:          알림 서비스.
        signal_log:        웹 대시보드용 시그널 로그 큐.
        paper_trade_store: 페이퍼 트레이딩 저장소.
    """
    from datetime import datetime

    logger = logging.getLogger(__name__)
    symbol = settings.lev_etf_symbol

    # ETF OHLCV 조회
    ohlcv_data = kis.get_ohlcv_daily(symbol, period=60)
    price_data = kis.get_current_price(symbol)
    current_price = float(price_data.get("stck_prpr", 0))
    if ohlcv_data and current_price > 0:
        ohlcv_data[-1]["stck_clpr"] = str(int(current_price))

    if not ohlcv_data:
        logger.warning("LevCall: ETF(%s) OHLCV 조회 실패", symbol)
        return

    import pandas as pd
    closes = pd.Series(
        [float(d.get("stck_clpr", 0)) for d in ohlcv_data],
        dtype=float,
    )

    # 코스피 수준 조회 (기존 kospi_data 활용)
    try:
        kospi_raw = kis.get_index_data("0001")
        kospi_level = float(kospi_raw.get("bstp_nmix_prpr", settings.entry_kospi_level))
    except Exception:
        kospi_level = settings.entry_kospi_level

    # VKOSPI 추정
    vkospi = estimate_vkospi(closes, window=20)

    # BS 옵션 현재 프리미엄 추정
    option_premium = estimate_premium_per_contract(
        S=kospi_level,
        K=settings.call_strike,
        T=settings.call_expiry_months / 12.0,
        sigma=max(vkospi / 100.0, 0.15),
    )

    # 시그널 평가 (포트폴리오 상태는 간소화: 항상 미보유 가정)
    lev_engine = LevCallSignalEngine(settings)
    lev_signal = lev_engine.evaluate(
        etf_closes=closes,
        kospi_level=kospi_level,
        vkospi=vkospi,
        has_position=False,
    )

    logger.info(
        "LevCall | %s | KOSPI=%.0f | VKOSPI=%.1f | 옵션프리미엄=%.0f | signal=%s",
        symbol,
        kospi_level,
        vkospi,
        option_premium,
        lev_signal.signal_type.value,
    )

    if lev_signal.signal_type != LevCallSignalType.HOLD:
        message = (
            f"[레버리지+콜] {lev_signal.signal_type.value}\n"
            f"ETF({symbol}): {current_price:,.0f}원\n"
            f"코스피: {kospi_level:,.0f}pt\n"
            f"VKOSPI: {vkospi:.1f}\n"
            f"옵션프리미엄: {option_premium:,.0f}원/계약\n"
            f"사유: {lev_signal.reason}"
        )
        notifier.send_message(message)

        if signal_log is not None:
            signal_log.appendleft(
                {
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "symbol": symbol,
                    "signal_type": f"LEV_{lev_signal.signal_type.value}",
                    "price": current_price,
                    "rsi": (
                        round(lev_signal.rsi, 1) if lev_signal.rsi is not None else None
                    ),
                    "reason": lev_signal.reason,
                }
            )

        if paper_trade_store is not None:
            paper_trade_store.record(
                symbol=symbol,
                signal_type=f"LEV_{lev_signal.signal_type.value}",
                price=current_price,
            )


def _refresh_screener(
    kis: KISClient,
    screener_targets: list,
    top_n: int = 5,
) -> None:
    """스크리너를 실행하고 공유 리스트를 갱신합니다.

    Args:
        kis:              KIS API 클라이언트.
        screener_targets: 갱신할 공유 리스트 (in-place 수정).
        top_n:            발굴할 종목 수.
    """
    logger = logging.getLogger(__name__)
    try:
        new_targets = get_dynamic_targets(kis, top_n=top_n)
        screener_targets.clear()
        screener_targets.extend(new_targets)
        logger.info(
            "Screener refreshed: %d 종목 발굴 — %s",
            len(new_targets),
            [t.symbol for t in new_targets],
        )
    except Exception as exc:
        logger.error("Screener refresh failed: %s", exc)


def _run_scheduler(
    settings: Settings,
    kis: KISClient,
    engine: SignalEngine,
    notifier: NotifierService,
    position_store: PositionStore,
    signal_log: Deque[Dict[str, Any]],
    broadcaster: Optional[ConnectionManager] = None,
    paper_trade_store: Optional[PaperTradeStore] = None,
    screener_targets: Optional[list] = None,
) -> None:
    """Blocking scheduler loop — runs inside a daemon thread."""
    _targets = screener_targets if screener_targets is not None else []

    # 스크리너: 장 시작 시 1회 + 매 60분 주기 갱신
    _refresh_screener(kis, _targets)
    schedule.every(60).minutes.do(_refresh_screener, kis, _targets)

    schedule.every(settings.monitor_interval_minutes).minutes.do(
        run_cycle,
        settings,
        kis,
        engine,
        notifier,
        position_store,
        signal_log,
        broadcaster,
        paper_trade_store,
        _targets,
    )
    # Fire once immediately so the first output is not delayed
    run_cycle(
        settings,
        kis,
        engine,
        notifier,
        position_store,
        signal_log,
        broadcaster,
        paper_trade_store,
        _targets,
    )

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
    ws_manager = ConnectionManager()
    paper_store: Optional[PaperTradeStore] = (
        PaperTradeStore("data/bot_state.db") if settings.paper_trading else None
    )
    if paper_store is not None:
        logger.info("PAPER_TRADING mode active — all fills recorded to data/bot_state.db")

    # 동적 종목 발굴 결과 (bot thread에서 갱신, web thread에서 읽기)
    screener_targets: list = []

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
            ws_manager,
            paper_store,
            screener_targets,
        ),
        daemon=True,
        name="bot-scheduler",
    )
    bot_thread.start()
    logger.info("Bot scheduler thread started (daemon).")

    # Build the FastAPI app and serve it on the main thread
    app = create_app(position_store, signal_log, ws_manager, screener_targets)
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
