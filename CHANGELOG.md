# Changelog

All notable changes to KimBeggar are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

> **AI-Native 문서화 정책**: 각 릴리스마다 Claude에게 전달한 프롬프트 요약과
> 생성된 핵심 코드 스니펫을 함께 기록합니다.

---

## [Unreleased]

### Added
- `data_agent/position_store.py` — SQLite-backed `PositionStore` class; entry prices
  now survive bot restarts (`data/bot_state.db`).
- `data_agent/paper_trade_store.py` — `PaperTradeStore` class; virtual fill ledger in
  `paper_trades` SQLite table; `record()` / `get_all()` / `get_by_symbol()` /
  `get_summary()` (P&L per symbol); 24 unit tests.
- `strategy.signal.is_market_open()` — Korean market hours filter (weekdays 09:00–15:30);
  `run_cycle()` skips execution outside trading hours.
- `strategy.hedge_logic.predict_volatility()` — walk-forward scikit-learn
  `LinearRegression` volatility forecast; features: mean / std / slope / min / max;
  annualised output; falls back to rolling std when data is insufficient.
- `api/app.py` — `ConnectionManager` event-driven WebSocket broadcast hub
  (per-client `asyncio.Queue`; `broadcast_threadsafe()` for cross-thread use);
  `/ws` endpoint with 2 s heartbeat fallback; mobile-responsive CSS Grid HTML
  dashboard; JS exponential-backoff reconnect.
- `api/app.py` — FastAPI REST 엔드포인트 (`/`, `/api/status`, `/api/positions`, `/api/signals`).
- `scripts/backtest_2022_crash.py` — 2022 코스피 대폭락 7-phase GBM 시뮬레이션;
  Buy&Hold -31.90% vs KimBeggar 방어선 비교; ML 헤지 권고 11회.
- `tests/test_paper_trade_store.py` — PaperTradeStore CRUD + P&L + 영속성 검증 (24 tests).
- `tests/test_position_store.py` — PositionStore CRUD + upsert 검증 (11 tests).
- `tests/test_e2e.py` — FastAPI TestClient E2E + WebSocket + DEV_MODE 시뮬레이션 (43 tests).
- `tests/test_main.py` — market-hours 스킵 + PositionStore mock 주입.
- `tests/test_strategy.py` — `TestIsMarketOpen` 경계값 7개 테스트.
- `.github/workflows/python-app.yml` — Deploy to Render CD + Heroku 옵션 + Codecov 업로드.
- `PROGRESS.md` — Phase 1~6 타임라인 및 AI 도구 활용 기록.
- `README.md` — 페이퍼 트레이딩 섹션(19), Phase 6 Alpaca 기술 로드맵 섹션(20).

### Changed
- `main.py` — `entry_prices` dict → `PositionStore`; 스케줄러를 데몬 스레드로 분리;
  uvicorn으로 FastAPI 대시보드 기동; `run_cycle()` 파라미터 갱신
  (`broadcaster`, `paper_trade_store` 추가); PORT 환경변수 지원.
- `config/settings.py` — `paper_trading: bool` 필드 추가 (`PAPER_TRADING` env var).
- `requirements.txt` — `fastapi`, `uvicorn[standard]`, `scikit-learn>=1.4.0` 추가.

> **🤖 Claude 프롬프트 요약 — ML 변동성 예측 + 백테스트**
>
> *"predict_volatility() TODO 스텁을 scikit-learn LinearRegression walk-forward로*
> *구현해 줘. scripts/backtest_2022_crash.py로 2022 하락장 시뮬레이션 결과를 출력해 줘."*

```python
# strategy/hedge_logic.py — predict_volatility() walk-forward 핵심 로직
def predict_volatility(returns: List[float], window: int = 10) -> float:
    arr = np.array(returns, dtype=float)
    if len(arr) < 2 * window + 1:
        return round(float(np.std(arr, ddof=1)) * (252**0.5), 6)
    X_rows, y_vals = [], []
    t = np.arange(window, dtype=float)
    for i in range(len(arr) - 2 * window):
        w = arr[i:i+window]; nxt = arr[i+window:i+2*window]
        X_rows.append([w.mean(), w.std(ddof=1), np.polyfit(t,w,1)[0], w.min(), w.max()])
        y_vals.append(float(nxt.std(ddof=1)))
    lr = LinearRegression().fit(np.array(X_rows), np.array(y_vals))
    last = arr[-window:]
    pred = max(float(lr.predict([[last.mean(), last.std(ddof=1),
                np.polyfit(t,last,1)[0], last.min(), last.max()]])[0]), 0.0)
    return round(pred * (252**0.5), 6)
```

> **🤖 Claude 프롬프트 요약 — WebSocket 대시보드**
>
> *"api/app.py에 /ws WebSocket 엔드포인트를 추가해서, 봇에서 새로운 시그널이*
> *발생하거나 포지션이 변경될 때 연결된 클라이언트에게 JSON을 실시간으로*
> *브로드캐스팅하도록 리팩토링해 줘. 대시보드 HTML도 모바일 반응형으로 개선해 줘."*

```python
# api/app.py — ConnectionManager 핵심 설계
class ConnectionManager:
    async def connect(self, ws: WebSocket) -> asyncio.Queue:
        await ws.accept()
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._clients[ws] = q
        return q

    def broadcast_threadsafe(self, payload: Dict[str, Any]) -> None:
        """bot 스레드에서 FastAPI 이벤트 루프로 안전하게 브로드캐스트."""
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self.broadcast(payload), self._loop)

# /ws 엔드포인트 — 이벤트 구동 + 2초 heartbeat 폴백
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    q = await mgr.connect(ws)
    try:
        await ws.send_json({"type": "full", "positions": ..., "signals": ...})
        while True:
            try:
                raw = await asyncio.wait_for(q.get(), timeout=2.0)
            except asyncio.TimeoutError:
                raw = {"type": "ping", "positions": ..., "signals": ...}
            await ws.send_json({**raw, "uptime": ..., "clients": mgr.connection_count})
    except (WebSocketDisconnect, RuntimeError):
        mgr.disconnect(ws)
```

> **🤖 Claude 프롬프트 요약 — 페이퍼 트레이딩**
>
> *"config에 'PAPER_TRADING' 모드를 추가해서, 이 모드가 켜져 있으면 KIS API로*
> *실제 주문을 넣는 대신 SQLite DB의 'paper_trades' 테이블에 가상으로 체결 내역을*
> *기록하도록 기능을 추가해 줘."*

```python
# data_agent/paper_trade_store.py — 핵심 생성 코드
class PaperTradeStore:
    def record(self, symbol: str, signal_type: str,
               price: float, quantity: int = 1) -> Dict[str, Any]:
        total_krw = price * quantity
        self._conn.execute(
            "INSERT INTO paper_trades (symbol, signal_type, price, quantity, total_krw)"
            " VALUES (?, ?, ?, ?, ?)",
            (symbol, signal_type, price, quantity, total_krw),
        )
        self._conn.commit()
        return {"symbol": symbol, "signal_type": signal_type,
                "price": price, "quantity": quantity, "total_krw": total_krw}

    def get_summary(self) -> Dict[str, Dict[str, Any]]:
        rows = self._conn.execute("""
            SELECT symbol,
                   SUM(CASE WHEN signal_type='BUY' THEN total_krw ELSE 0 END),
                   SUM(CASE WHEN signal_type IN ('SELL','STOP_LOSS') THEN total_krw ELSE 0 END),
                   COUNT(*)
            FROM paper_trades GROUP BY symbol
        """).fetchall()
        return {r[0]: {"bought_krw": r[1], "sold_krw": r[2],
                        "pnl_krw": r[2]-r[1], "trades": r[3]} for r in rows}

# main.py — PAPER_TRADING 모드 연결
paper_store = PaperTradeStore("data/bot_state.db") if settings.paper_trading else None
```

> **🤖 Claude 프롬프트 요약 — SQLite 영속성 + 장시간 필터**
>
> *"AI 심사관 피드백을 반영하여 3가지 개선을 수행한다: (1) CHANGELOG.md 생성,*
> *(2) SQLite 포지션 영속성 — entry_prices 딕셔너리를 data/bot_state.db로 교체,*
> *(3) 장 시간 필터 — 평일 09:00~15:30에만 매매 로직 동작..."*

```python
# data_agent/position_store.py
class PositionStore:
    def __init__(self, db_path: str = "data/bot_state.db") -> None:
        if dir_name := os.path.dirname(db_path):
            os.makedirs(dir_name, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                entry_price REAL NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            )""")

# strategy/signal.py — is_market_open()
def is_market_open(now: Optional[datetime] = None) -> bool:
    if now is None:
        now = datetime.now()
    if now.weekday() >= 5:
        return False
    return (now.replace(hour=9, minute=0, second=0, microsecond=0)
            <= now <=
            now.replace(hour=15, minute=30, second=0, microsecond=0))
```

---

## [0.6.0] — 2026-03-14 (877ca1c)

### Added
- `Dockerfile` and Docker Compose for containerised deployment.
- GitHub Actions Docker CI workflow (`docker-ci.yml`).
- README sections: contributor guide and 2022 back-test scenario walk-through.

### Changed
- Test coverage raised to **92 %** (branch + line).

> **🤖 Claude 프롬프트 요약**
>
> *"92% 테스트 커버리지, Dockerfile 및 Docker CI 워크플로우를 작성하고,*
> *README에 기여 가이드와 2022년 시나리오를 추가해 줘."*

```dockerfile
# Dockerfile — 핵심 생성 코드
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

---

## [0.5.0] — 2026-03-13 (2ec64d5)

### Added
- Full pytest test suite (`tests/test_strategy.py`, `tests/test_main.py`,
  `tests/test_notifier.py`, `tests/test_data_agent.py`).
- `conftest.py` with shared fixtures (`mock_settings`, `ascending_prices`,
  `ohlcv_ascending`, etc.).
- `black` and `pylint` automation via `Makefile` and CI.
- MVP demo script (`demo.py`) with synthetic walk-through.

### Changed
- README upgraded with architecture diagram and quick-start guide.

> **🤖 Claude 프롬프트 요약**
>
> *"전체 모듈에 대한 pytest 테스트 스위트를 작성하고 black/pylint 자동화,*
> *MVP 데모 스크립트, README 업그레이드를 해줘."*

```python
# tests/conftest.py — 핵심 생성 코드
@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.rsi_period, s.rsi_oversold, s.rsi_overbought = 14, 30, 70
    s.ma_short, s.ma_long, s.stop_loss_rate = 5, 20, 0.05
    return s

@pytest.fixture
def ascending_prices():
    return pd.Series([float(50 + i) for i in range(60)])
```

---

## [0.4.0] — 2026-03-13 (0c64e81)

### Added
- `backtest/` module using `backtrader` for historical strategy simulation.
- TA-Lib optional dependency note in `requirements.txt`.

> **🤖 Claude 프롬프트 요약**
>
> *"backtrader를 활용한 백테스팅 모듈을 추가하고 requirements.txt에*
> *TA-Lib 설치 안내를 포함해 줘."*

```python
# backtest/run_backtest.py — 핵심 생성 코드
def run_backtest(df: pd.DataFrame,
                 initial_cash: float = 10_000_000,
                 stop_loss_rate: float = 0.05) -> BacktestResult:
    cerebro = bt.Cerebro()
    cerebro.adddata(bt.feeds.PandasData(dataname=_normalise_columns(df)))
    cerebro.addsizer(bt.sizers.PercentSizer, percents=95)
    cerebro.broker.setcash(initial_cash)
    cerebro.addstrategy(KimBeggarStrategy, stop_loss_rate=stop_loss_rate)
    results = cerebro.run()
    return BacktestResult(initial_cash=initial_cash,
                          final_value=cerebro.broker.getvalue(), ...)
```

---

## [0.3.0] — 2026-03-13 (78fa626)

### Changed
- Replaced `ta` library with pure **pandas / numpy** indicator implementations
  (`strategy/indicators.py`) — eliminates C-extension build dependency.

### Fixed
- KIS API error handling hardened: HTTP 4xx/5xx responses now raise descriptive
  exceptions instead of silently returning empty data.

> **🤖 Claude 프롬프트 요약**
>
> *"ta 라이브러리를 순수 pandas/numpy 구현으로 교체해 줘 — C 확장 의존성 제거.*
> *KIS API 오류 처리도 강화해서 HTTP 4xx/5xx 시 명확한 예외를 던지도록 수정해."*

```python
# strategy/indicators.py — 순수 pandas 구현 (ta 제거 후)
def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period,
                        adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period,
                        adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))
```

---

## [0.2.1] — 2026-03-13 (47729b2)

### Added
- `.claude/requirements.md` — module implementation status, AI usage log,
  and change log for internal tracking.

> **🤖 Claude 프롬프트 요약**
>
> *"requirements.md에 모듈 구현 상태, AI 활용 기록, 변경 로그를 추가해 줘."*

---

## [0.2.0] — 2026-03-13 (6c90711)

### Added
- Core trading logic: `strategy/signal.py` (`SignalEngine`, `Signal`, `SignalType`).
- `strategy/indicators.py` — RSI, SMA, EMA, golden/dead cross, volatility.
- `strategy/hedge_logic.py` — dynamic hedge-ratio calculation.
- `notifier/kakao.py` — KakaoTalk notification integration.
- `main.py` — scheduling loop with `schedule` library.
- GitHub Actions CI pipeline (lint + test).

> **🤖 Claude 프롬프트 요약**
>
> *"핵심 트레이딩 로직을 구현해 줘: SignalEngine(BUY/SELL/STOP_LOSS/HEDGE),*
> *RSI·SMA·EMA·골든크로스·데드크로스 지표, 동적 헤지 비율 계산, 카카오 알림,*
> *schedule 기반 메인 루프, GitHub Actions CI 파이프라인."*

```python
# strategy/signal.py — SignalEngine 우선순위 판별 핵심 로직
def evaluate(self, symbol, ohlcv_data, entry_price=None) -> Signal:
    # 1. STOP_LOSS (최우선 — 자본 보전)
    if entry_price and self.check_stop_loss(current_price, entry_price):
        return Signal(symbol, SignalType.STOP_LOSS, ...)
    # 2. SELL — RSI 과매수 + 데드크로스
    if self.check_sell_signal(close, rsi, short_ma, long_ma):
        return Signal(symbol, SignalType.SELL, ...)
    # 3. BUY — RSI 과매도 + 골든크로스
    if self.check_buy_signal(close, rsi, short_ma, long_ma):
        return Signal(symbol, SignalType.BUY, ...)
    # 4. HOLD
    return Signal(symbol, SignalType.HOLD, ...)

# strategy/hedge_logic.py — 동적 헤지 비율
def calculate_hedge_ratio(current_price, long_ma, base_ratio,
                           index_change_rate=0.0) -> float:
    ma_dev   = max(0.0, (long_ma - current_price) / long_ma) if long_ma else 0.0
    idx_risk = max(0.0, -index_change_rate / 100)
    ratio    = base_ratio + ma_dev * MA_DEVIATION_SCALE + idx_risk * INDEX_DROP_SCALE
    return float(max(MIN_RATIO, min(MAX_RATIO, ratio)))
```

---

## [0.1.0] — 2026-03-13 (80b4d5c)

### Added
- Initial commit: project architecture and KIS (Korea Investment & Securities) API
  integration (`data_agent/kis_api.py`).
- `config/settings.py` — environment-variable based configuration via `pydantic`.
- `logger/log_setup.py` — structured logging setup.

> **🤖 Claude 프롬프트 요약**
>
> *"김거지 헷지 트레이딩 봇 아키텍처를 설계하고 KIS API 연동을 완료해 줘.*
> *OAuth 토큰 발급, 현재가·OHLCV·지수 조회, 카카오 나에게 보내기, 전역 설정,*
> *로거를 구현하고 보안(.env, .gitignore)을 설정해 줘."*

```python
# data_agent/kis_api.py — OAuth 토큰 발급 핵심 로직
def _issue_token(self) -> None:
    payload = {"grant_type": "client_credentials",
               "appkey": self._settings.kis_api_key,
               "appsecret": self._settings.kis_api_secret}
    data = self._post_with_retry(
        f"{self._settings.kis_base_url}/oauth2/tokenP", json=payload)
    self._access_token = data["access_token"]
    self._token_expires_at = (
        datetime.now() + timedelta(seconds=int(data.get("expires_in", 86400))))

# config/settings.py — pydantic 환경변수 로드
class Settings(BaseSettings):
    kis_api_key: str = Field(..., env="KIS_API_KEY")
    watch_symbols: List[str] = Field(default=["005930"], env="WATCH_SYMBOLS")
    stop_loss_rate: float = Field(default=0.05, env="STOP_LOSS_RATE")
    hedge_ratio: float = Field(default=0.30, env="HEDGE_RATIO")
```
