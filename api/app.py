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
  <title>&#x26A1; 김거지 퀀텀점프</title>
  <style>
    :root {
      --bg: #0a0f1e; --card: #0d1424; --primary: #070d1a;
      --border: #1a2f4a; --text: #cbd5e1; --muted: #4b6080;
      --neon-g: #10b981; --neon-r: #ef4444; --neon-c: #06b6d4;
      --warn: #f59e0b; --r: 6px;
      --glow-g: 0 0 10px rgba(16,185,129,.4);
      --glow-r: 0 0 10px rgba(239,68,68,.4);
      --glow-c: 0 0 10px rgba(6,182,212,.3);
    }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: "SF Mono","Fira Code","Cascadia Code","Segoe UI",monospace;
      background: var(--bg); color: var(--text); min-height: 100vh;
    }

    /* ── Header ── */
    .hdr {
      background: var(--primary);
      border-bottom: 1px solid var(--neon-g);
      box-shadow: 0 2px 24px rgba(16,185,129,.12);
      color: #fff; padding: 14px 24px;
      display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
    }
    .hdr-title {
      font-size: 1.05rem; font-weight: 700; flex: 1;
      color: var(--neon-g); letter-spacing: .07em; text-transform: uppercase;
      text-shadow: var(--glow-g);
    }
    .hdr-title .dim { color: #1e3a5f; font-size: .72rem; margin-left: 10px;
                      font-weight: 400; text-shadow: none; letter-spacing: .04em; }
    .hdr-meta { display: flex; align-items: center; gap: 10px;
                font-size: .76rem; color: var(--muted); flex-wrap: wrap; }
    .hdr-meta strong { color: #94a3b8; font-family: monospace; }

    /* ── WS dot ── */
    .dot { width: 8px; height: 8px; border-radius: 50%;
           background: #1e3a5f; display: inline-block; flex-shrink: 0;
           transition: background .4s; }
    .dot.live  { background: var(--neon-g); box-shadow: var(--glow-g);
                 animation: pulse 2s infinite; }
    .dot.error { background: var(--neon-r); box-shadow: var(--glow-r); }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.25} }

    /* ── Stats ── */
    .stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 10px; padding: 16px 24px 0;
    }
    .stat {
      background: var(--card);
      border: 1px solid var(--border);
      border-top: 2px solid var(--neon-g);
      border-radius: var(--r); padding: 14px 12px; text-align: center;
    }
    .stat-val {
      font-size: 1.7rem; font-weight: 700; color: var(--neon-g);
      line-height: 1.2; text-shadow: var(--glow-g); font-family: monospace;
    }
    .stat-lbl {
      font-size: .62rem; color: var(--muted); margin-top: 4px;
      text-transform: uppercase; letter-spacing: .1em;
    }

    /* ── Main grid ── */
    .grid {
      display: grid; grid-template-columns: 260px 1fr;
      gap: 14px; padding: 14px 24px;
    }
    @media (max-width: 800px) {
      .grid  { grid-template-columns: 1fr; padding: 10px; }
      .stats { padding: 10px 10px 0; }
      .hdr   { padding: 12px 16px; }
    }

    /* ── Card ── */
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--r); overflow: hidden;
    }
    .card-hdr {
      padding: 10px 16px; border-bottom: 1px solid var(--border);
      font-weight: 700; font-size: .8rem;
      background: rgba(16,185,129,.05);
      color: var(--neon-g); letter-spacing: .05em; text-transform: uppercase;
      display: flex; align-items: center; gap: 8px;
    }
    .card-hdr .sub { font-weight: 400; color: var(--muted);
                     font-size: .7rem; text-transform: none; letter-spacing: 0; }
    .card-body { overflow-x: auto; }

    /* ── Tables ── */
    table { border-collapse: collapse; width: 100%; font-size: .81rem; }
    th {
      background: rgba(16,185,129,.06);
      font-weight: 700; color: var(--neon-g);
      font-size: .66rem; text-transform: uppercase; letter-spacing: .08em;
    }
    th, td { padding: 8px 14px; border-bottom: 1px solid var(--border);
             white-space: nowrap; }
    tr:last-child td { border-bottom: none; }
    tbody tr:hover { background: rgba(16,185,129,.04); }
    td strong { color: var(--text); }

    /* ── Badges ── */
    .b {
      display: inline-flex; align-items: center;
      padding: 2px 8px; border-radius: 3px;
      font-size: .68rem; font-weight: 700; line-height: 1.8;
      letter-spacing: .05em;
    }
    .b-long  { background: rgba(16,185,129,.15); color: var(--neon-g);
               box-shadow: var(--glow-g); border: 1px solid var(--neon-g); }
    .b-liq   { background: rgba(239,68,68,.15);  color: var(--neon-r);
               box-shadow: var(--glow-r); border: 1px solid var(--neon-r); }
    .b-hedge { background: rgba(6,182,212,.12);  color: var(--neon-c);
               border: 1px solid rgba(6,182,212,.5); }
    .b-dip   { background: rgba(239,68,68,.1);   color: #f87171;
               border: 1px solid #7f1d1d; }
    .b-surge { background: rgba(245,158,11,.1);  color: #fbbf24;
               border: 1px solid #78350f; }
    .b-scan  { background: rgba(75,96,128,.12);  color: var(--muted);
               border: 1px solid #1e3a5f; }

    /* ── Empty ── */
    .empty {
      padding: 28px 16px; text-align: center;
      color: var(--muted); font-size: .8rem; font-style: italic;
    }
    .empty::before { content: "// "; color: #1e3a5f; }

    /* ── Reason cell ── */
    td.rsn { max-width: 200px; overflow: hidden;
             text-overflow: ellipsis; color: var(--muted); font-size: .76rem; }

    /* ── Flash ── */
    .flash { animation: rowflash 1s ease-out; }
    @keyframes rowflash {
      0%   { background: rgba(16,185,129,.18); }
      100% { background: transparent; }
    }

    /* ── Screener section ── */
    .scr-section { padding: 0 24px 24px; }
    @media (max-width: 800px) { .scr-section { padding: 0 10px 16px; } }
    .up   { color: var(--neon-g); font-weight: 700; }
    .down { color: var(--neon-r); font-weight: 700; }

    /* ── Screener table ── */
    .scr-tbl { table-layout: auto; width: 100%; }
    .scr-tbl th, .scr-tbl td { white-space: nowrap; }
    .scr-tbl th:nth-child(1), .scr-tbl td:nth-child(1) { min-width: 80px; }
    .scr-tbl th:nth-child(2), .scr-tbl td:nth-child(2) { min-width: 140px; max-width: 220px;
      overflow: hidden; text-overflow: ellipsis; }
    .scr-tbl th:nth-child(3), .scr-tbl td:nth-child(3) { min-width: 110px; }
    .scr-tbl th:nth-child(4), .scr-tbl td:nth-child(4) { min-width: 80px;  }
    .scr-tbl th:nth-child(5), .scr-tbl td:nth-child(5) { min-width: 100px; }
    .scr-tbl th:nth-child(6), .scr-tbl td:nth-child(6) { min-width: 90px;  }
    .scr-tbl th:nth-child(7), .scr-tbl td:nth-child(7) { min-width: 110px; }
  </style>
</head>
<body>

<!-- ── Header ── -->
<header class="hdr">
  <span class="hdr-title">&#x26A1; 김거지 퀀텀점프<span class="dim">// QUANTUM JUMP BOT v2</span></span>
  <div class="hdr-meta">
    <span>UPTIME <strong id="uptime">__UPTIME__</strong></span>
    <span class="dot" id="dot"></span>
    <span id="ws-lbl">CONNECTING...</span>
  </div>
</header>

<!-- ── Stats ── -->
<div class="stats">
  <div class="stat">
    <div class="stat-val" id="st-pos">0</div>
    <div class="stat-lbl">Leverage Pos</div>
  </div>
  <div class="stat">
    <div class="stat-val" id="st-sig">0</div>
    <div class="stat-lbl">Quantum Hits</div>
  </div>
  <div class="stat">
    <div class="stat-val" id="st-cli">&#x2014;</div>
    <div class="stat-lbl">Live Feeds</div>
  </div>
  <div class="stat">
    <div class="stat-val" id="st-scr">0</div>
    <div class="stat-lbl">Prey Found</div>
  </div>
</div>

<!-- ── Main ── -->
<main class="grid">

  <div class="card">
    <div class="card-hdr">&#x1F525; 레버리지 포지션 (3X)</div>
    <div class="card-body" id="pos-body">__POSITIONS__</div>
  </div>

  <div class="card">
    <div class="card-hdr">
      &#x26A1; 퀀텀 타격 로그
      <span class="sub">(최대 50건)</span>
    </div>
    <div class="card-body" id="sig-body">__SIGNALS__</div>
  </div>

</main>

<!-- ── Screener ── -->
<section class="scr-section">
  <div class="card">
    <div class="card-hdr">
      &#x1F3AF; 과매도 사냥감 (Deep Dive)
      <span class="sub" id="scr-updated"></span>
    </div>
    <div class="card-body" id="scr-body">__SCREENER__</div>
  </div>
</section>

<script>
(function () {
  function krw(n) {
    return Number(n).toLocaleString("ko-KR") + " \u20a9";
  }

  const BADGE = {
    BUY:               ["b-long",  "\u{1F680} LONG"],
    SELL:              ["b-liq",   "\u{1F4A5} LIQUIDATE"],
    STOP_LOSS:         ["b-liq",   "\u{1F4A5} LIQUIDATE"],
    HEDGE:             ["b-hedge", "\u{1F6E1} HEDGE"],
    LEV_ENTRY:         ["b-long",  "\u{1F680} LONG"],
    LEV_EXIT:          ["b-liq",   "\u{1F4A5} EXIT"],
    LEV_PARTIAL_EXIT:  ["b-liq",   "\u{1F4B0} PARTIAL"],
    LEV_ADD_OPTIONS:   ["b-surge", "\u26A1 ADD OPT"],
  };

  function badge(t) {
    const [cls, lbl] = BADGE[t] || ["b-scan", t || "—"];
    return `<span class="b ${cls}">${lbl}</span>`;
  }

  let _names = {};

  function renderPos(pos, names) {
    if (names) _names = Object.assign(_names, names);
    const el = document.getElementById("pos-body");
    const rows = Object.entries(pos);
    document.getElementById("st-pos").textContent = rows.length;
    if (!rows.length) {
      el.innerHTML = '<div class="empty">\uB300\uAE30 \uC911: \uB2E4\uC74C \uD3ED\uB77D(Dip)\uC744 \uAE30\uB2E4\uB9AC\uBA70 \uB9C8\uC9C4 \uC7A5\uC804 \uC644\uB8CC</div>';
      return;
    }
    const body = rows.map(([s, p]) =>
      `<tr><td><strong>${_names[s] || s}</strong></td>` +
      `<td style="font-family:monospace">${krw(p)}</td></tr>`
    ).join("");
    el.innerHTML =
      `<table><thead><tr><th>Asset</th><th>Entry</th></tr></thead>` +
      `<tbody>${body}</tbody></table>`;
  }

  let _prevSigLen = 0;
  function renderSig(sigs, names) {
    if (names) _names = Object.assign(_names, names);
    const el = document.getElementById("sig-body");
    document.getElementById("st-sig").textContent = sigs.length;
    if (!sigs.length) {
      el.innerHTML = '<div class="empty">\uC2E0\uD638 \uC5C6\uC74C \u2014 \uC2DC\uC7A5\uC774 \uC544\uC9C1 \uCDA9\uBD84\uD788 \uBB34\uB108\uC9C0\uC9C0 \uC54A\uC558\uB2E4</div>';
      _prevSigLen = 0;
      return;
    }
    const isNew = sigs.length > _prevSigLen && _prevSigLen > 0;
    const rows = sigs.map((s, i) => {
      const flash = (isNew && i === 0) ? ' class="flash"' : "";
      const rsi   = s.rsi != null ? Number(s.rsi).toFixed(1) : "\u2014";
      const disp  = s.display_name || _names[s.symbol] || s.symbol || "";
      return `<tr${flash}>` +
        `<td style="color:var(--muted);font-size:.72rem">${s.time || ""}</td>` +
        `<td><strong>${disp}</strong></td>` +
        `<td>${badge(s.signal_type)}</td>` +
        `<td style="font-family:monospace">${krw(s.price || 0)}</td>` +
        `<td style="font-family:monospace;color:var(--neon-c)">${rsi}</td>` +
        `<td class="rsn" title="${s.reason || ""}">${s.reason || ""}</td>` +
        `</tr>`;
    }).join("");
    el.innerHTML =
      `<table><thead><tr>` +
      `<th>Time</th><th>Target</th><th>Action</th>` +
      `<th>Exec Price</th><th>RSI</th><th>Trigger</th>` +
      `</tr></thead><tbody>${rows}</tbody></table>`;
    _prevSigLen = sigs.length;
  }

  const SCR_SRC = {
    drop_rank:   ["b-dip",   "\uD83E\uDE78 DIPPED"],
    volume_rank: ["b-surge", "\u26A1 SURGE"],
    fallback:    ["b-scan",  "\uD83D\uDCE1 SCAN"],
  };
  function scrBadge(src) {
    const [cls, lbl] = SCR_SRC[src] || ["b-scan", src];
    return `<span class="b ${cls}">${lbl}</span>`;
  }
  function renderScr(items) {
    const el = document.getElementById("scr-body");
    const cnt = document.getElementById("st-scr");
    if (cnt) cnt.textContent = items.length;
    if (!items || !items.length) {
      el.innerHTML = '<div class="empty">\uC0AC\uB0E5\uAC10 \uC5C6\uC74C \u2014 \uC7A5 \uB9C8\uAC10 \uB610\uB294 \uBA39\uC774\uAC00 \uB3C4\uB9DD\uAC14\uB2E4</div>';
      return;
    }
    const rows = items.map(t => {
      const cr = Number(t.change_rate);
      const crCls = cr > 0 ? "up" : cr < 0 ? "down" : "";
      const crStr = (cr >= 0 ? "+" : "") + cr.toFixed(2) + "%";
      const vol = t.volume ? Number(t.volume).toLocaleString("ko-KR") : "\u2014";
      return `<tr>` +
        `<td><strong>${t.symbol}</strong></td>` +
        `<td>${t.name || "\u2014"}</td>` +
        `<td style="font-family:monospace">${t.price ? Number(t.price).toLocaleString("ko-KR") + " \u20a9" : "\u2014"}</td>` +
        `<td class="${crCls}" style="font-family:monospace;font-weight:700">${crStr}</td>` +
        `<td style="color:var(--muted);font-size:.75rem;font-family:monospace">${vol}</td>` +
        `<td>${scrBadge(t.source)}</td>` +
        `<td style="color:var(--muted);font-size:.72rem">${t.discovered_at || ""}</td>` +
        `</tr>`;
    }).join("");
    el.innerHTML =
      `<table class="scr-tbl"><thead><tr>` +
      `<th>Code</th><th>Asset</th><th>Price</th>` +
      `<th>Move</th><th>Volume</th><th>Source</th><th>Found At</th>` +
      `</tr></thead><tbody>${rows}</tbody></table>`;
    const upd = document.getElementById("scr-updated");
    if (upd) upd.textContent = "SCAN: " + new Date().toLocaleTimeString("ko-KR");
  }

  // ── WebSocket ────────────────────────────────────────────────────
  let retryMs = 1_000;
  const MAX_MS = 30_000;

  function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(proto + "//" + location.host + "/ws");
    const dot = document.getElementById("dot");
    const lbl = document.getElementById("ws-lbl");

    ws.onopen = () => {
      dot.className = "dot live";
      lbl.textContent = "FEED LIVE";
      lbl.style.color  = "#10b981";
      retryMs = 1_000;
    };

    ws.onclose = () => {
      dot.className = "dot";
      lbl.textContent = `RECONNECTING... (${(retryMs / 1000).toFixed(0)}s)`;
      lbl.style.color  = "#4b6080";
      setTimeout(connect, retryMs);
      retryMs = Math.min(retryMs * 2, MAX_MS);
    };

    ws.onerror = () => {
      dot.className = "dot error";
      lbl.textContent = "FEED LOST";
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

_POSITIONS_EMPTY = '<div class="empty">대기 중: 다음 폭락(Dip)을 기다리며 마진 장전 완료</div>'
_SIGNALS_EMPTY = '<div class="empty">신호 없음 — 시장이 아직 충분히 무너지지 않았다</div>'
_SCREENER_EMPTY = '<div class="empty">사냥감 없음 — 장 마감 또는 먹이가 도망갔다</div>'


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
        f"<tr><td><strong>{resolver.display(sym)}</strong></td>"
        f"<td style='font-family:monospace'>{price:,.0f} &#x20a9;</td></tr>"
        for sym, price in positions.items()
    )
    return (
        "<table><thead><tr><th>Asset</th><th>Entry</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _ssr_signals(signals: List[Dict[str, Any]]) -> str:
    if not signals:
        return _SIGNALS_EMPTY
    badge_cls = {
        "BUY": "b-long", "SELL": "b-liq", "STOP_LOSS": "b-liq", "HEDGE": "b-hedge",
        "LEV_ENTRY": "b-long", "LEV_EXIT": "b-liq",
        "LEV_PARTIAL_EXIT": "b-liq", "LEV_ADD_OPTIONS": "b-surge",
    }
    badge_lbl = {
        "BUY": "&#x1F680; LONG", "SELL": "&#x1F4A5; LIQUIDATE",
        "STOP_LOSS": "&#x1F4A5; LIQUIDATE", "HEDGE": "&#x1F6E1; HEDGE",
        "LEV_ENTRY": "&#x1F680; LONG", "LEV_EXIT": "&#x1F4A5; EXIT",
        "LEV_PARTIAL_EXIT": "&#x1F4B0; PARTIAL", "LEV_ADD_OPTIONS": "&#x26A1; ADD OPT",
    }
    rows = []
    resolver = get_resolver()
    for s in signals:
        st = s.get("signal_type", "")
        cls = badge_cls.get(st, "b-scan")
        lbl = badge_lbl.get(st, st)
        bdg = f'<span class="b {cls}">{lbl}</span>'
        rsi = f"{s['rsi']:.1f}" if s.get("rsi") is not None else "&#x2014;"
        sym = s.get("symbol", "")
        display = s.get("display_name") or resolver.display(sym)
        rows.append(
            f"<tr>"
            f"<td style='color:var(--muted);font-size:.72rem'>{s.get('time','')}</td>"
            f"<td><strong>{display}</strong></td>"
            f"<td>{bdg}</td>"
            f"<td style='font-family:monospace'>{s.get('price', 0):,.0f} &#x20a9;</td>"
            f"<td style='font-family:monospace;color:var(--neon-c)'>{rsi}</td>"
            f"<td class='rsn'>{s.get('reason','')}</td></tr>"
        )
    header = (
        "<table><thead><tr>"
        "<th>Time</th><th>Target</th><th>Action</th>"
        "<th>Exec Price</th><th>RSI</th><th>Trigger</th>"
        "</tr></thead><tbody>"
    )
    return header + "".join(rows) + "</tbody></table>"


def _ssr_screener(targets: List[Dict[str, Any]]) -> str:
    if not targets:
        return _SCREENER_EMPTY
    src_lbl = {
        "drop_rank": "&#x1FA78; DIPPED",
        "volume_rank": "&#x26A1; SURGE",
        "fallback": "&#x1F4E1; SCAN",
    }
    src_cls = {"drop_rank": "b-dip", "volume_rank": "b-surge", "fallback": "b-scan"}
    rows = []
    for t in targets:
        cr = float(t.get("change_rate", 0))
        cr_cls = "up" if cr > 0 else ("down" if cr < 0 else "")
        cr_str = f"{'+'if cr>=0 else ''}{cr:.2f}%"
        vol = t.get("volume", 0)
        vol_str = f"{int(vol):,}" if vol else "&#x2014;"
        src = t.get("source", "")
        bdg = (
            f'<span class="b {src_cls.get(src, "b-scan")}">'
            f'{src_lbl.get(src, src)}</span>'
        )
        rows.append(
            f"<tr>"
            f"<td><strong>{t.get('symbol','')}</strong></td>"
            f"<td>{t.get('name','') or '&#x2014;'}</td>"
            f"<td style='font-family:monospace'>{t.get('price',0):,.0f} &#x20a9;</td>"
            f"<td class='{cr_cls}' style='font-family:monospace;font-weight:700'>{cr_str}</td>"
            f"<td style='color:var(--muted);font-size:.75rem;font-family:monospace'>{vol_str}</td>"
            f"<td>{bdg}</td>"
            f"<td style='color:var(--muted);font-size:.72rem'>"
            f"{t.get('discovered_at','')}</td></tr>"
        )
    header = (
        "<table class='scr-tbl'><thead><tr>"
        "<th>Code</th><th>Asset</th><th>Price</th>"
        "<th>Move</th><th>Volume</th><th>Source</th><th>Found At</th>"
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

    app = FastAPI(title="김거지 퀀텀점프", version="2.0.0")

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
