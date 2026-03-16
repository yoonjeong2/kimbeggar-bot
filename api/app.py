"""KimBeggar — FastAPI web dashboard with event-driven WebSocket broadcasting.

Architecture
------------
Signal flow when the bot detects a new trade signal:

  Bot thread (run_cycle)
      │  ConnectionManager.broadcast_threadsafe(payload)
      │  └─ asyncio.run_coroutine_threadsafe → FastAPI event loop
      │
  FastAPI event loop
      │  ConnectionManager.broadcast(payload)
      │  └─ payload → each client's asyncio.Queue
      │
  Per-client WebSocket handler
      └─ q.get() → ws.send_json(payload)

When the bot is idle the WebSocket handler falls back to a 2-second
heartbeat so clients always stay alive and the uptime counter ticks.

Endpoints
---------
GET  /              HTML dashboard (mobile-responsive, CSS Grid)
GET  /api/status    JSON health-check
GET  /api/positions JSON { symbol: entry_price, ... }
GET  /api/signals   JSON list of the last N signal events
WS   /ws            Event-driven push; 2 s heartbeat when idle
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from data_agent.name_resolver import get_resolver
from data_agent.position_store import PositionStore

_STARTED_AT: float = time.time()

# ---------------------------------------------------------------------------
# ConnectionManager — event-driven WebSocket broadcast hub
# ---------------------------------------------------------------------------


class ConnectionManager:
    """Manages connected WebSocket clients and distributes state updates.

    Each accepted connection receives a private :class:`asyncio.Queue`.
    The bot scheduler (a background OS thread) calls
    :meth:`broadcast_threadsafe`, which schedules :meth:`broadcast` on
    the FastAPI event loop via :func:`asyncio.run_coroutine_threadsafe`.
    The coroutine places the payload into every client's queue; each
    WebSocket handler then ``await``-s its queue and forwards the message.

    Usage::

        # In main.py (bot thread):
        ws_manager.broadcast_threadsafe({"type": "update", ...})

        # In create_app() startup event:
        ws_manager.set_loop(asyncio.get_running_loop())
    """

    def __init__(self) -> None:
        self._clients: Dict[WebSocket, asyncio.Queue] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Capture the running event loop (called once at app startup)."""
        self._loop = loop

    @property
    def connection_count(self) -> int:
        """Number of currently connected WebSocket clients."""
        return len(self._clients)

    async def connect(self, ws: WebSocket) -> "asyncio.Queue[Dict[str, Any]]":
        """Accept the WebSocket and return the client's private message queue."""
        await ws.accept()
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._clients[ws] = q
        return q

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a disconnected client."""
        self._clients.pop(ws, None)

    async def broadcast(self, payload: Dict[str, Any]) -> None:
        """Place *payload* in every connected client's queue (async-safe).

        Clients whose queue is full (lagging) are silently removed.
        """
        overflow: List[WebSocket] = []
        for ws, q in list(self._clients.items()):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                overflow.append(ws)
        for ws in overflow:
            self._clients.pop(ws, None)

    def broadcast_threadsafe(self, payload: Dict[str, Any]) -> None:
        """Schedule a broadcast from a non-async context (bot scheduler thread).

        No-op if the event loop has not yet been set or is already closed.
        """
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self.broadcast(payload), self._loop)


# ---------------------------------------------------------------------------
# HTML template (server-side rendered; JS takes over immediately via WS)
# ---------------------------------------------------------------------------

_HTML = """\
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>KimBeggar Dashboard</title>
  <style>
    :root {
      --primary: #1e293b; --accent: #3b82f6;
      --ok: #22c55e;  --warn: #f59e0b; --danger: #ef4444;
      --bg: #f1f5f9;  --card: #fff;   --border: #e2e8f0;
      --text: #0f172a; --muted: #64748b; --r: 10px;
    }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
           background: var(--bg); color: var(--text); min-height: 100vh; }

    /* ── Header ── */
    .hdr { background: var(--primary); color: #fff; padding: 14px 24px;
           display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
    .hdr-title { font-size: 1.15rem; font-weight: 700; flex: 1; }
    .hdr-meta  { display: flex; align-items: center; gap: 10px;
                 font-size: .82rem; color: #94a3b8; flex-wrap: wrap; }
    .hdr-meta strong { color: #e2e8f0; }

    /* ── WS status dot ── */
    .dot { width: 9px; height: 9px; border-radius: 50%;
           background: #475569; display: inline-block; flex-shrink: 0;
           transition: background .4s; }
    .dot.live  { background: var(--ok);   animation: pulse 2s infinite; }
    .dot.error { background: var(--danger); }
    @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:.35; } }

    /* ── Stats row ── */
    .stats { display: grid;
             grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
             gap: 12px; padding: 20px 24px 0; }
    .stat { background: var(--card); border-radius: var(--r);
            padding: 16px 12px; text-align: center;
            box-shadow: 0 1px 3px rgba(0,0,0,.07); }
    .stat-val { font-size: 1.65rem; font-weight: 700; color: var(--accent);
                line-height: 1.2; }
    .stat-lbl { font-size: .72rem; color: var(--muted); margin-top: 3px;
                text-transform: uppercase; letter-spacing: .04em; }

    /* ── Main grid ── */
    .grid { display: grid;
            grid-template-columns: 280px 1fr;
            gap: 20px; padding: 20px 24px; }
    @media (max-width: 800px) {
      .grid { grid-template-columns: 1fr; padding: 16px; }
      .stats { padding: 16px 16px 0; }
      .hdr  { padding: 12px 16px; }
    }

    /* ── Card ── */
    .card { background: var(--card); border-radius: var(--r);
            box-shadow: 0 1px 3px rgba(0,0,0,.07); overflow: hidden; }
    .card-hdr { padding: 11px 16px; border-bottom: 1px solid var(--border);
                font-weight: 600; font-size: .88rem; background: #f8fafc;
                display: flex; align-items: center; gap: 8px; }
    .card-hdr .sub { font-weight: 400; color: var(--muted); font-size: .77rem; }
    .card-body { overflow-x: auto; }

    /* ── Tables ── */
    table { border-collapse: collapse; width: 100%; font-size: .855rem; }
    th { background: #f8fafc; font-weight: 600; color: var(--muted);
         font-size: .75rem; text-transform: uppercase; letter-spacing: .03em; }
    th, td { padding: 9px 14px; border-bottom: 1px solid var(--border);
             white-space: nowrap; }
    tr:last-child td { border-bottom: none; }
    tbody tr:hover { background: #f8fafc; }

    /* ── Badges ── */
    .b { display: inline-flex; align-items: center;
         padding: 2px 9px; border-radius: 99px;
         font-size: .75rem; font-weight: 600; line-height: 1.7; }
    .b-buy  { background: #dcfce7; color: #15803d; }
    .b-sell { background: #fee2e2; color: #b91c1c; }
    .b-stop { background: #fef9c3; color: #92400e; }
    .b-hedge{ background: #e0f2fe; color: #0369a1; }
    .b-drop { background: #fee2e2; color: #b91c1c; }
    .b-vol  { background: #fef9c3; color: #92400e; }
    .b-fb   { background: #f1f5f9; color: #475569; }

    /* ── Empty ── */
    .empty { padding: 36px 16px; text-align: center;
             color: var(--muted); font-size: .88rem; }

    /* ── Reason cell ── */
    td.rsn { max-width: 200px; overflow: hidden;
             text-overflow: ellipsis; color: var(--muted); font-size: .8rem; }

    /* ── Flash animation for new row ── */
    .flash { animation: rowflash .9s ease-out; }
    @keyframes rowflash {
      0%   { background: #dbeafe; }
      100% { background: transparent; }
    }

    /* ── Screener section ── */
    .scr-section { padding: 0 24px 24px; }
    @media (max-width: 800px) { .scr-section { padding: 0 16px 20px; } }
    .up   { color: #15803d; font-weight: 600; }
    .down { color: #b91c1c; font-weight: 600; }
  </style>
</head>
<body>

<!-- ── Header ── -->
<header class="hdr">
  <span class="hdr-title">KimBeggar Dashboard</span>
  <div class="hdr-meta">
    <span>가동: <strong id="uptime">__UPTIME__</strong></span>
    <span class="dot" id="dot"></span>
    <span id="ws-lbl">연결 중…</span>
  </div>
</header>

<!-- ── Stats ── -->
<div class="stats">
  <div class="stat">
    <div class="stat-val" id="st-pos">0</div>
    <div class="stat-lbl">오픈 포지션</div>
  </div>
  <div class="stat">
    <div class="stat-val" id="st-sig">0</div>
    <div class="stat-lbl">최근 시그널</div>
  </div>
  <div class="stat">
    <div class="stat-val" id="st-cli">—</div>
    <div class="stat-lbl">WS 클라이언트</div>
  </div>
  <div class="stat">
    <div class="stat-val" id="st-scr">0</div>
    <div class="stat-lbl">스크리너 탐색</div>
  </div>
</div>

<!-- ── Main ── -->
<main class="grid">

  <div class="card">
    <div class="card-hdr">오픈 포지션</div>
    <div class="card-body" id="pos-body">__POSITIONS__</div>
  </div>

  <div class="card">
    <div class="card-hdr">
      최근 시그널
      <span class="sub">(최대 50건)</span>
    </div>
    <div class="card-body" id="sig-body">__SIGNALS__</div>
  </div>

</main>

<!-- ── Screener ── -->
<section class="scr-section">
  <div class="card">
    <div class="card-hdr">
      자동 탐색 종목 (스크리너)
      <span class="sub" id="scr-updated"></span>
    </div>
    <div class="card-body" id="scr-body">__SCREENER__</div>
  </div>
</section>

<script>
(function () {
  // ── render helpers ──────────────────────────────────────────────────
  function krw(n) {
    return Number(n).toLocaleString("ko-KR") + " 원";
  }

  const BADGE = {
    BUY:       ["b-buy",  "매수"],
    SELL:      ["b-sell", "매도"],
    STOP_LOSS: ["b-stop", "손절"],
    HEDGE:     ["b-hedge","헤지"],
  };

  function badge(t) {
    const [cls, lbl] = BADGE[t] || ["", t];
    return cls ? `<span class="b ${cls}">${lbl}</span>` : t;
  }

  let _names = {};

  function renderPos(pos, names) {
    if (names) _names = Object.assign(_names, names);
    const el = document.getElementById("pos-body");
    const rows = Object.entries(pos);
    document.getElementById("st-pos").textContent = rows.length;
    if (!rows.length) {
      el.innerHTML = '<div class="empty">보유 포지션 없음</div>';
      return;
    }
    const body = rows.map(([s, p]) =>
      `<tr><td><strong>${_names[s] || s}</strong></td><td>${krw(p)}</td></tr>`
    ).join("");
    el.innerHTML =
      `<table><thead><tr><th>종목</th><th>진입가</th></tr></thead>` +
      `<tbody>${body}</tbody></table>`;
  }

  let _prevSigLen = 0;
  function renderSig(sigs, names) {
    if (names) _names = Object.assign(_names, names);
    const el = document.getElementById("sig-body");
    document.getElementById("st-sig").textContent = sigs.length;
    if (!sigs.length) {
      el.innerHTML = '<div class="empty">아직 기록된 시그널 없음</div>';
      _prevSigLen = 0;
      return;
    }
    const isNew = sigs.length > _prevSigLen && _prevSigLen > 0;
    const rows = sigs.map((s, i) => {
      const flash = (isNew && i === 0) ? ' class="flash"' : "";
      const rsi   = s.rsi != null ? Number(s.rsi).toFixed(1) : "N/A";
      const disp  = s.display_name || _names[s.symbol] || s.symbol || "";
      return `<tr${flash}>` +
        `<td>${s.time || ""}</td>` +
        `<td><strong>${disp}</strong></td>` +
        `<td>${badge(s.signal_type)}</td>` +
        `<td>${krw(s.price || 0)}</td>` +
        `<td>${rsi}</td>` +
        `<td class="rsn" title="${s.reason || ""}">${s.reason || ""}</td>` +
        `</tr>`;
    }).join("");
    el.innerHTML =
      `<table><thead><tr>` +
      `<th>시각</th><th>종목</th><th>시그널</th>` +
      `<th>가격</th><th>RSI</th><th>사유</th>` +
      `</tr></thead><tbody>${rows}</tbody></table>`;
    _prevSigLen = sigs.length;
  }

  const SCR_SRC = {
    drop_rank:   ["b-drop", "낙폭과대"],
    volume_rank: ["b-vol",  "거래량"],
    fallback:    ["b-fb",   "폴백"],
  };
  function scrBadge(src) {
    const [cls, lbl] = SCR_SRC[src] || ["b-fb", src];
    return `<span class="b ${cls}">${lbl}</span>`;
  }
  function renderScr(items) {
    const el = document.getElementById("scr-body");
    const cnt = document.getElementById("st-scr");
    if (cnt) cnt.textContent = items.length;
    if (!items || !items.length) {
      el.innerHTML = '<div class="empty">탐색된 종목 없음 (장 마감 또는 API 대기 중)</div>';
      return;
    }
    const rows = items.map(t => {
      const cr = Number(t.change_rate);
      const crCls = cr > 0 ? "up" : cr < 0 ? "down" : "";
      const crStr = (cr >= 0 ? "+" : "") + cr.toFixed(2) + "%";
      const vol = t.volume ? Number(t.volume).toLocaleString("ko-KR") : "-";
      return `<tr>
        <td><strong>${t.symbol}</strong></td>
        <td>${t.name || "-"}</td>
        <td>${t.price ? Number(t.price).toLocaleString("ko-KR") + " 원" : "-"}</td>
        <td class="${crCls}">${crStr}</td>
        <td style="color:var(--muted);font-size:.8rem">${vol}</td>
        <td>${scrBadge(t.source)}</td>
        <td style="color:var(--muted);font-size:.78rem">${t.discovered_at || ""}</td>
      </tr>`;
    }).join("");
    el.innerHTML =
      `<table><thead><tr>` +
      `<th>종목코드</th><th>종목명</th><th>현재가</th>` +
      `<th>등락률</th><th>거래량</th><th>출처</th><th>발굴시각</th>` +
      `</tr></thead><tbody>${rows}</tbody></table>`;
    const upd = document.getElementById("scr-updated");
    if (upd) upd.textContent = "갱신: " + new Date().toLocaleTimeString("ko-KR");
  }

  // ── WebSocket ──────────────────────────────────────────────────────
  let retryMs = 1_000;
  const MAX_MS = 30_000;

  function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(proto + "//" + location.host + "/ws");
    const dot = document.getElementById("dot");
    const lbl = document.getElementById("ws-lbl");

    ws.onopen = () => {
      dot.className = "dot live";
      lbl.textContent = "실시간 연결됨";
      lbl.style.color  = "#22c55e";
      retryMs = 1_000;
    };

    ws.onclose = () => {
      dot.className = "dot";
      lbl.textContent = `재연결 중… (${(retryMs / 1000).toFixed(0)}s)`;
      lbl.style.color  = "#94a3b8";
      setTimeout(connect, retryMs);
      retryMs = Math.min(retryMs * 2, MAX_MS);
    };

    ws.onerror = () => {
      dot.className = "dot error";
      lbl.textContent = "연결 오류";
      lbl.style.color  = "#ef4444";
    };

    ws.onmessage = (evt) => {
      const d = JSON.parse(evt.data);
      if (d.uptime)    document.getElementById("uptime").textContent = d.uptime;
      if (d.clients != null)
        document.getElementById("st-cli").textContent = d.clients;
      if (d.positions != null) renderPos(d.positions, d.names);
      if (d.signals   != null) renderSig(d.signals,   d.names);
      if (d.screener  != null) renderScr(d.screener);
    };
  }

  connect();
})();
</script>

</body>
</html>
"""

_POSITIONS_EMPTY = '<div class="empty">보유 포지션 없음</div>'
_SIGNALS_EMPTY = '<div class="empty">아직 기록된 시그널 없음</div>'
_SCREENER_EMPTY = '<div class="empty">탐색된 종목 없음 (장 마감 또는 API 대기 중)</div>'


# ---------------------------------------------------------------------------
# Server-side render helpers (initial page load before WS connects)
# ---------------------------------------------------------------------------


def _fmt_uptime(seconds: float) -> str:
    t = int(seconds)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"


def _ssr_positions(positions: Dict[str, float]) -> str:
    if not positions:
        return _POSITIONS_EMPTY
    resolver = get_resolver()
    rows = "".join(
        f"<tr><td><strong>{resolver.display(sym)}</strong></td><td>{price:,.0f} 원</td></tr>"
        for sym, price in positions.items()
    )
    return (
        "<table><thead><tr><th>종목</th><th>진입가</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _ssr_signals(signals: List[Dict[str, Any]]) -> str:
    if not signals:
        return _SIGNALS_EMPTY
    badge_cls = {"BUY": "b-buy", "SELL": "b-sell", "STOP_LOSS": "b-stop", "HEDGE": "b-hedge"}
    badge_lbl = {"BUY": "매수", "SELL": "매도", "STOP_LOSS": "손절", "HEDGE": "헤지"}
    rows = []
    for s in signals:
        st = s.get("signal_type", "")
        cls = badge_cls.get(st, "")
        lbl = badge_lbl.get(st, st)
        bdg = f'<span class="b {cls}">{lbl}</span>' if cls else st
        rsi = f"{s['rsi']:.1f}" if s.get("rsi") is not None else "N/A"
        resolver = get_resolver()
        sym = s.get("symbol", "")
        display = s.get("display_name") or resolver.display(sym)
        rows.append(
            f"<tr><td>{s.get('time','')}</td>"
            f"<td><strong>{display}</strong></td>"
            f"<td>{bdg}</td>"
            f"<td>{s.get('price', 0):,.0f} 원</td>"
            f"<td>{rsi}</td>"
            f"<td class='rsn'>{s.get('reason','')}</td></tr>"
        )
    header = (
        "<table><thead><tr>"
        "<th>시각</th><th>종목</th><th>시그널</th>"
        "<th>가격</th><th>RSI</th><th>사유</th>"
        "</tr></thead><tbody>"
    )
    return header + "".join(rows) + "</tbody></table>"


def _ssr_screener(targets: List[Dict[str, Any]]) -> str:
    if not targets:
        return _SCREENER_EMPTY
    src_lbl = {"drop_rank": "낙폭과대", "volume_rank": "거래량", "fallback": "폴백"}
    src_cls = {"drop_rank": "b-drop", "volume_rank": "b-vol", "fallback": "b-fb"}
    rows = []
    for t in targets:
        cr = float(t.get("change_rate", 0))
        cr_cls = "up" if cr > 0 else ("down" if cr < 0 else "")
        cr_str = f"{'+'if cr>=0 else ''}{cr:.2f}%"
        vol = t.get("volume", 0)
        vol_str = f"{int(vol):,}" if vol else "-"
        src = t.get("source", "")
        bdg = (
            f'<span class="b {src_cls.get(src, "b-fb")}">'
            f'{src_lbl.get(src, src)}</span>'
        )
        rows.append(
            f"<tr>"
            f"<td><strong>{t.get('symbol','')}</strong></td>"
            f"<td>{t.get('name','') or '-'}</td>"
            f"<td>{t.get('price',0):,.0f} 원</td>"
            f"<td class='{cr_cls}'>{cr_str}</td>"
            f"<td style='color:var(--muted);font-size:.8rem'>{vol_str}</td>"
            f"<td>{bdg}</td>"
            f"<td style='color:var(--muted);font-size:.78rem'>"
            f"{t.get('discovered_at','')}</td></tr>"
        )
    header = (
        "<table><thead><tr>"
        "<th>종목코드</th><th>종목명</th><th>현재가</th>"
        "<th>등락률</th><th>거래량</th><th>출처</th><th>발굴시각</th>"
        "</tr></thead><tbody>"
    )
    return header + "".join(rows) + "</tbody></table>"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_app(
    position_store: PositionStore,
    signal_log: Deque[Dict[str, Any]],
    ws_manager: Optional[ConnectionManager] = None,
    screener_targets: Optional[List] = None,
) -> FastAPI:
    """Return a configured FastAPI application.

    Args:
        position_store:   SQLite-backed position store shared with the bot loop.
        signal_log:       Deque of recent signal dicts shared with the bot loop.
        ws_manager:       :class:`ConnectionManager` instance.  When omitted a
                          new manager is created internally (useful for testing).
                          Pass an explicit instance from ``main.py`` so the bot
                          scheduler thread can call
                          :meth:`~ConnectionManager.broadcast_threadsafe`.
        screener_targets: Shared list of :class:`~data_agent.screener.ScreenerResult`
                          objects populated by the dynamic screener.  Read as a
                          snapshot via ``list()`` on every request.
    """
    mgr = ws_manager if ws_manager is not None else ConnectionManager()
    _screener: List = screener_targets if screener_targets is not None else []

    app = FastAPI(title="KimBeggar Dashboard", version="1.0.0")

    @app.on_event("startup")
    async def _capture_loop() -> None:
        mgr.set_loop(asyncio.get_running_loop())

    # ── REST endpoints ───────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse, summary="HTML 대시보드")
    def dashboard() -> str:
        scr_dicts = [t.to_dict() if hasattr(t, "to_dict") else t for t in list(_screener)]
        return (
            _HTML
            .replace("__UPTIME__", _fmt_uptime(time.time() - _STARTED_AT))
            .replace("__POSITIONS__", _ssr_positions(position_store.get_all()))
            .replace("__SIGNALS__", _ssr_signals(list(signal_log)))
            .replace("__SCREENER__", _ssr_screener(scr_dicts))
        )

    @app.get("/api/status", summary="헬스체크")
    def api_status() -> Dict[str, Any]:
        return {
            "status": "running",
            "uptime_seconds": round(time.time() - _STARTED_AT, 1),
            "open_positions": len(position_store.get_all()),
            "recent_signals": len(signal_log),
            "ws_clients": mgr.connection_count,
            "screener_targets": len(_screener),
        }

    @app.get("/api/targets", summary="스크리너 탐색 종목 목록")
    def api_targets() -> List[Dict[str, Any]]:
        return [
            t.to_dict() if hasattr(t, "to_dict") else t for t in list(_screener)
        ]

    @app.get("/api/positions", summary="오픈 포지션 목록")
    def api_positions() -> Dict[str, float]:
        return position_store.get_all()

    @app.get("/api/signals", summary="최근 시그널 목록")
    def api_signals() -> List[Dict[str, Any]]:
        return list(signal_log)

    # ── WebSocket endpoint ───────────────────────────────────────────────

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        """Event-driven push; falls back to a 2-second heartbeat when idle.

        On connect the client immediately receives the full current state.
        After that, messages arrive whenever the bot broadcasts a state
        change (new signal / position update).  If no broadcast has been
        queued within 2 seconds a heartbeat with the latest state is sent
        automatically to keep the connection alive and the uptime ticking.
        """
        q = await mgr.connect(ws)
        try:
            # ── Initial full-state push ──────────────────────────────────
            _resolver = get_resolver()
            _pos = position_store.get_all()
            _sigs = list(signal_log)
            _scr = [t.to_dict() if hasattr(t, "to_dict") else t for t in list(_screener)]
            _all_syms = (
                list(_pos.keys())
                + [s.get("symbol", "") for s in _sigs]
                + [t.get("symbol", "") if isinstance(t, dict) else t.symbol for t in list(_screener)]
            )
            await ws.send_json(
                {
                    "type": "full",
                    "uptime": _fmt_uptime(time.time() - _STARTED_AT),
                    "positions": _pos,
                    "signals": _sigs,
                    "clients": mgr.connection_count,
                    "screener": _scr,
                    "names": _resolver.names_dict(s for s in _all_syms if s),
                }
            )

            # ── Relay broadcasts or heartbeat ────────────────────────────
            while True:
                try:
                    raw = await asyncio.wait_for(q.get(), timeout=2.0)
                    # Enrich with server-side fields the bot thread doesn't know
                    payload = {
                        **raw,
                        "uptime": _fmt_uptime(time.time() - _STARTED_AT),
                        "clients": mgr.connection_count,
                    }
                except asyncio.TimeoutError:
                    # Idle heartbeat — refresh full state
                    _hb_pos = position_store.get_all()
                    _hb_sigs = list(signal_log)
                    _hb_scr = [
                        t.to_dict() if hasattr(t, "to_dict") else t
                        for t in list(_screener)
                    ]
                    _hb_syms = (
                        list(_hb_pos.keys())
                        + [s.get("symbol", "") for s in _hb_sigs]
                        + [
                            t.get("symbol", "") if isinstance(t, dict) else t.symbol
                            for t in list(_screener)
                        ]
                    )
                    payload = {
                        "type": "ping",
                        "uptime": _fmt_uptime(time.time() - _STARTED_AT),
                        "positions": _hb_pos,
                        "signals": _hb_sigs,
                        "clients": mgr.connection_count,
                        "screener": _hb_scr,
                        "names": get_resolver().names_dict(s for s in _hb_syms if s),
                    }
                await ws.send_json(payload)

        except (WebSocketDisconnect, RuntimeError):
            mgr.disconnect(ws)

    return app
