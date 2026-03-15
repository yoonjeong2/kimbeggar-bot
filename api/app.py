"""KimBeggar — FastAPI web dashboard.

Exposes a minimal HTTP interface so the bot can be monitored via browser or
REST client without touching log files.

Endpoints
---------
GET /              — HTML dashboard (positions + recent signals at a glance)
GET /api/status    — JSON health-check { status, uptime_seconds, ... }
GET /api/positions — JSON { symbol: entry_price, ... } from SQLite
GET /api/signals   — JSON list of the last N signal events (in-memory)
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Deque, Dict, List

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from data_agent.position_store import PositionStore

_STARTED_AT: float = time.time()

# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>KimBeggar Dashboard</title>
  <style>
    body  {{ font-family: sans-serif; max-width: 900px; margin: 40px auto; padding: 0 16px; }}
    h1   {{ color: #2c3e50; }}
    h2   {{ color: #34495e; border-bottom: 1px solid #ccc; padding-bottom: 4px; }}
    .badge {{ display:inline-block; padding:2px 8px; border-radius:4px;
              font-size:.85em; font-weight:bold; }}
    .green  {{ background:#d4edda; color:#155724; }}
    .yellow {{ background:#fff3cd; color:#856404; }}
    .red    {{ background:#f8d7da; color:#721c24; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th,td {{ border: 1px solid #dee2e6; padding: 8px 12px; text-align: left; }}
    th    {{ background: #f8f9fa; }}
    tr:nth-child(even) {{ background: #fdfdfd; }}
    .empty {{ color: #888; font-style: italic; }}
  </style>
</head>
<body>
  <h1>🤖 KimBeggar Dashboard</h1>
  <p>가동 시간: <strong>{uptime}</strong> &nbsp;|&nbsp;
     상태: <span class="badge green">RUNNING</span></p>

  <h2>📂 오픈 포지션</h2>
  {positions_html}

  <h2>📡 최근 시그널 (최대 50건)</h2>
  {signals_html}
</body>
</html>
"""

_POSITIONS_EMPTY = '<p class="empty">보유 포지션 없음</p>'
_SIGNALS_EMPTY = '<p class="empty">아직 기록된 시그널 없음</p>'


def _fmt_uptime(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"


def _positions_table(positions: Dict[str, float]) -> str:
    if not positions:
        return _POSITIONS_EMPTY
    rows = "".join(
        f"<tr><td>{sym}</td><td>{price:,.0f} 원</td></tr>"
        for sym, price in positions.items()
    )
    return f"<table><thead><tr><th>종목코드</th><th>진입가</th></tr></thead><tbody>{rows}</tbody></table>"


def _signals_table(signals: List[Dict[str, Any]]) -> str:
    if not signals:
        return _SIGNALS_EMPTY
    badge_class = {"BUY": "green", "SELL": "red", "STOP_LOSS": "red", "HEDGE": "yellow"}
    rows = []
    for s in signals:
        stype = s.get("signal_type", "HOLD")
        cls = badge_class.get(stype, "")
        badge = f'<span class="badge {cls}">{stype}</span>' if cls else stype
        rows.append(
            f"<tr>"
            f"<td>{s.get('time', '')}</td>"
            f"<td>{s.get('symbol', '')}</td>"
            f"<td>{badge}</td>"
            f"<td>{s.get('price', 0):,.0f}</td>"
            f"<td>{s.get('rsi', 'N/A')}</td>"
            f"<td style='max-width:300px;font-size:.85em'>{s.get('reason', '')}</td>"
            f"</tr>"
        )
    header = (
        "<table><thead><tr>"
        "<th>시각</th><th>종목</th><th>시그널</th>"
        "<th>가격</th><th>RSI</th><th>사유</th>"
        "</tr></thead><tbody>"
    )
    return header + "".join(rows) + "</tbody></table>"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_app(
    position_store: PositionStore,
    signal_log: Deque[Dict[str, Any]],
) -> FastAPI:
    """Return a configured FastAPI application.

    Args:
        position_store: SQLite-backed position store shared with the bot loop.
        signal_log:     Deque of recent signal dicts shared with the bot loop.
    """
    app = FastAPI(title="KimBeggar Dashboard", version="1.0.0")

    @app.get("/", response_class=HTMLResponse, summary="HTML 대시보드")
    def dashboard() -> str:
        uptime = _fmt_uptime(time.time() - _STARTED_AT)
        positions = position_store.get_all()
        signals = list(signal_log)
        return _HTML_TEMPLATE.format(
            uptime=uptime,
            positions_html=_positions_table(positions),
            signals_html=_signals_table(signals),
        )

    @app.get("/api/status", summary="헬스체크")
    def status() -> Dict[str, Any]:
        return {
            "status": "running",
            "uptime_seconds": round(time.time() - _STARTED_AT, 1),
            "open_positions": len(position_store.get_all()),
            "recent_signals": len(signal_log),
        }

    @app.get("/api/positions", summary="오픈 포지션 목록")
    def positions() -> Dict[str, float]:
        return position_store.get_all()

    @app.get("/api/signals", summary="최근 시그널 목록")
    def signals() -> List[Dict[str, Any]]:
        return list(signal_log)

    return app
