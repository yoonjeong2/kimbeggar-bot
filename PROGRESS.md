# KimBeggar — 개발 진행 타임라인 (PROGRESS)

> **AI-Native 문서**: 이 파일은 Claude Sonnet 4.6이 주도한 전체 개발 흐름을
> Phase별로 기록합니다. 각 Phase에는 날짜, 주요 작업, 핵심 커밋, AI 도구 활용
> 비율, 그리고 Claude에게 실제 전달한 프롬프트 요약이 포함됩니다.

---

## Phase 타임라인 요약

| Phase | 기간 | 주요 작업 | 커밋 | 테스트 수 | AI 활용 비율 |
|---|---|---|---|---|---|
| **Phase 1** | 2026-03-13 | KIS·Kakao API 연동, OAuth, 로거, 전역 설정 | `80b4d5c` | 0 | **100 %** |
| **Phase 2** | 2026-03-13 | 코드 품질 고도화 (타입힌팅, Observer 패턴, tenacity) | `6c90711` | 0 | **100 %** |
| **Phase 3** | 2026-03-13 | 핵심 트레이딩 로직 (SignalEngine, 지표, 헤지 비율) | `6c90711`, `78fa626` | 58 | **100 %** |
| **Phase 4** | 2026-03-13~14 | 테스트 스위트 92 %, Docker CI, backtrader 백테스트 | `0c64e81`, `2ec64d5`, `877ca1c` | 185 | **100 %** |
| **Phase 5** | 2026-03-16 | SQLite 영속성, 장시간 필터, FastAPI 대시보드, CD | `f48fc6f` | 207 | **100 %** |
| **Phase 6** | 2026-03-16 | ML 변동성 예측, WebSocket 대시보드, 페이퍼 트레이딩, 2022 백테스트 | `de29e38`, 현재 | **252** | **100 %** |

---

## Phase 1 — 인프라 & API 연동

**기간**: 2026-03-13
**커밋**: `80b4d5c` (Initial Commit)

### 수행 작업

| 항목 | 파일 | 결과 |
|---|---|---|
| KIS OAuth 토큰 발급 / 24시간 캐싱 | `data_agent/kis_api.py` | ✅ 모의투자 서버 토큰 발급 성공 |
| 현재가 / 5분봉 / 일봉 / 지수 조회 | `data_agent/kis_api.py` | ✅ 삼성전자 184,200원 조회 확인 |
| 카카오 OAuth 최초 인증 & 토큰 갱신 | `notifier/kakao_token_manager.py` | ✅ "나에게 보내기" 전송 성공 |
| pydantic 전역 설정 (`.env` 로드) | `config/settings.py` | ✅ |
| 일자별 로테이팅 파일 로거 | `logger/log_setup.py` | ✅ |
| 보안 설정 (`.gitignore`, `.env`) | 프로젝트 루트 | ✅ |

### AI 프롬프트 (요약)

> *"김거지 헷지 트레이딩 봇 아키텍처를 설계하고 KIS API 연동을 완료해 줘.*
> *OAuth 토큰 발급, 현재가·OHLCV·지수 조회, 카카오 나에게 보내기, pydantic*
> *전역 설정, 로테이팅 로거를 구현하고 .env/.gitignore 보안을 설정해 줘."*

### AI 활용 내역

| 작업 유형 | Claude 기여 | 개발자 기여 |
|---|---|---|
| 아키텍처 설계 | 모듈 분리 구조 제안 (Config/DataAgent/Strategy/Notifier/Logger) | 비즈니스 요구사항 정의 |
| KIS API 구현 | OAuth 흐름, 헤더 구조, 재시도 패턴 전체 코드 생성 | API 키 / 계좌번호 제공 |
| 카카오 연동 | OAuth2 + 나에게 보내기 전체 구현 | 실제 토큰 발급 실행 |
| 보안 설정 | `.gitignore` 패턴, `.env` 구조 생성 | 승인 |

---

## Phase 2 — 코드 품질 고도화

**기간**: 2026-03-13
**커밋**: `6c90711`

### 수행 작업

| 항목 | 파일 | 결과 |
|---|---|---|
| PEP 484 타입 힌팅 전면 적용 | 전체 모듈 | ✅ |
| Google 스타일 Docstring | 전체 모듈 | ✅ |
| tenacity 재시도 (지수 백오프 1→2→4s) | `kis_api.py`, `kakao.py`, `kakao_token_manager.py` | ✅ |
| `BaseNotifier` ABC + Observer 패턴 | `notifier/base.py` | ✅ |
| `NotifierService` 컴포짓 | `notifier/base.py` | ✅ |
| 환경별 SSL 검증 분리 | `config/ssl.py` | ✅ |

### AI 프롬프트 (요약)

> *"전체 모듈에 PEP 484 타입 힌팅과 Google 스타일 Docstring을 적용하고,*
> *tenacity 재시도 데코레이터(지수 백오프)를 추가해 줘. Observer 패턴으로*
> *BaseNotifier ABC와 NotifierService 컴포짓을 설계하고, SSL 검증을*
> *DEV_MODE 환경변수로 분리해 줘."*

### 핵심 설계 결정 (Claude 제안)

```
BaseNotifier (ABC)
    └── KakaoNotifier   ← 현재 구현
    └── TelegramNotifier  ← 확장 시 코어 코드 수정 불필요 (DIP)

NotifierService (Composite)
    - register(channel)  ← 런타임 채널 추가
    - send_message() / send_signal() / send_error()  ← 일괄 브로드캐스트
```

---

## Phase 3 — 핵심 트레이딩 로직 구현

**기간**: 2026-03-13
**커밋**: `6c90711`, `78fa626`

### 수행 작업

| 항목 | 파일 | 결과 |
|---|---|---|
| RSI (Wilder 스무딩, pandas/numpy 순수 구현) | `strategy/indicators.py` | ✅ |
| SMA / EMA / 골든크로스 / 데드크로스 / 변동성 | `strategy/indicators.py` | ✅ |
| 동적 헤지 비율 공식 (`base + MA이탈×5pp + 지수낙폭×3pp`) | `strategy/hedge_logic.py` | ✅ |
| `SignalEngine.evaluate()` 우선순위 판별 | `strategy/signal.py` | ✅ |
| `run_cycle()` 메인 루프 구현 | `main.py` | ✅ |
| `ta` 라이브러리 → 순수 pandas/numpy 전환 | `strategy/indicators.py` | ✅ C 확장 의존성 제거 |
| KIS API 오류 처리 강화 | `data_agent/kis_api.py` | ✅ HTTP 4xx/5xx 명확한 예외 |

### AI 프롬프트 (요약)

> *(1) "핵심 트레이딩 로직을 구현해 줘: SignalEngine BUY/SELL/STOP_LOSS/HEDGE,*
> *RSI·SMA·EMA·크로스 지표, 동적 헤지 비율."*
>
> *(2) "ta 라이브러리를 순수 pandas/numpy로 교체해 줘 — C 확장 빌드 의존성 제거.*
> *KIS API 오류 처리도 강화해서 HTTP 4xx/5xx 시 명확한 예외를 던지도록 수정해."*

### 시그널 우선순위 로직

```
STOP_LOSS  (1순위) — price ≤ entry × (1 − stop_loss_rate)
SELL       (2순위) — RSI ≥ 70 AND 데드크로스
BUY        (3순위) — RSI ≤ 30 AND 골든크로스
HOLD       (기본)  — 조건 미충족
```

---

## Phase 4 — 테스트 & CI/CD

**기간**: 2026-03-13 ~ 2026-03-14
**커밋**: `47729b2`, `0c64e81`, `2ec64d5`, `877ca1c`

### 수행 작업

| 항목 | 파일 | 테스트 수 | 결과 |
|---|---|---|---|
| 공용 fixture | `tests/conftest.py` | — | ✅ |
| strategy 단위 테스트 | `tests/test_strategy.py` | 58 | ✅ 58/58 PASSED |
| main 단위 테스트 | `tests/test_main.py` | 14 | ✅ |
| notifier 단위 테스트 | `tests/test_notifier.py` | 20 | ✅ |
| KIS API 단위 테스트 | `tests/test_kis_api.py` | 22 | ✅ |
| backtrader 백테스트 모듈 | `backtest/run_backtest.py` | 15 | ✅ |
| GitHub Actions CI (flake8 + pytest --cov) | `.github/workflows/python-app.yml` | — | ✅ |
| Docker build CI | `.github/workflows/python-app.yml` | — | ✅ |
| `Dockerfile` 컨테이너화 | `Dockerfile` | — | ✅ |
| 최종 커버리지 | 전체 | **185** | **92 %** |

### AI 프롬프트 (요약)

> *(1) "전체 모듈에 대한 pytest 테스트 스위트를 작성하고 black/pylint 자동화,*
> *MVP 데모 스크립트, README 업그레이드를 해줘."*
>
> *(2) "92% 테스트 커버리지, Dockerfile 및 Docker CI 워크플로우를 작성하고,*
> *README에 기여 가이드와 2022년 시나리오를 추가해 줘."*

### CI 파이프라인 구조

```
push / PR → main
    ├── Job 1: lint-and-test
    │       ├── black --check
    │       ├── flake8
    │       ├── pylint (continue-on-error)
    │       ├── pytest --cov (≥80% 강제)
    │       └── coverage.xml Artifact 보관 (7일)
    └── Job 2: docker-build  (needs: lint-and-test)
            └── docker build -t kimbeggar:$SHA .
```

---

## Phase 5 — 고도화: SQLite 영속성 · 장시간 필터 · FastAPI 대시보드 · CD

**기간**: 2026-03-16
**커밋**: `f48fc6f`

### 수행 작업

| 항목 | 파일 | 테스트 수 | 결과 |
|---|---|---|---|
| SQLite `PositionStore` (재시작 생존) | `data_agent/position_store.py` | 11 | ✅ |
| `is_market_open()` 장시간 필터 | `strategy/signal.py` | 7 | ✅ |
| FastAPI 대시보드 (`/`, `/api/*`) | `api/app.py` | 22 (E2E) | ✅ |
| 스케줄러 → 데몬 스레드 + uvicorn 기동 | `main.py` | — | ✅ |
| Deploy to Render CD 스텝 | `.github/workflows/python-app.yml` | — | ✅ |
| `fastapi`, `uvicorn[standard]` 추가 | `requirements.txt` | — | ✅ |
| CHANGELOG.md AI-Native 문서화 | `CHANGELOG.md` | — | ✅ |
| **최종 테스트 수** | 전체 | **207** | **207/207 PASSED** |

### AI 프롬프트 (요약)

> **세션 1** — *"AI 심사관 피드백을 반영: (1) CHANGELOG.md 생성, (2) SQLite 포지션*
> *영속성 — entry_prices를 data/bot_state.db로 교체, (3) 장 시간 필터 — 평일*
> *09:00~15:30에만 매매 로직 동작."*
>
> **세션 2** — *"봇에 경량 웹 서버를 달 거야. api/app.py를 만들고 봇의 현재 상태를*
> *보여주는 대시보드를 루트('/')에 띄워줘. 스케줄러 루프는 BackgroundTasks로*
> *돌아가게 main.py 진입점을 수정해 줘."*
>
> **세션 3** — *"python-app.yml에 'Deploy to Render' CD 스텝을 추가해 줘.*
> *지금까지 작업을 git commit/push해 줘."*

### FastAPI 대시보드 엔드포인트

| 경로 | 반환 타입 | 설명 |
|---|---|---|
| `GET /` | `text/html` | 포지션 + 최근 시그널 HTML 대시보드 |
| `GET /api/status` | JSON | 가동시간, 포지션 수, 시그널 수 |
| `GET /api/positions` | JSON | SQLite 전체 포지션 `{symbol: price}` |
| `GET /api/signals` | JSON | 최근 50건 시그널 (newest-first) |

### CD 파이프라인 확장 구조

```
push → main
    └── Job 2: docker-build  (needs: lint-and-test)
            ├── docker build -t kimbeggar:$SHA .
            └── Deploy to Render        ← Phase 5 추가
                    curl $RENDER_DEPLOY_HOOK
                    (main 브랜치 push 시에만 실행)
```

---

## Phase 6 — ML 변동성 예측 · WebSocket 대시보드 · 페이퍼 트레이딩 · 2022 백테스트

**기간**: 2026-03-16
**커밋**: `de29e38` + 현재 작업

### 수행 작업

| 항목 | 파일 | 테스트 수 | 결과 |
|---|---|---|---|
| `predict_volatility()` walk-forward LinearRegression 구현 | `strategy/hedge_logic.py` | (기존 포함) | ✅ |
| 2022 코스피 대폭락 7-phase GBM 시뮬레이션 스크립트 | `scripts/backtest_2022_crash.py` | — | ✅ B&H -31.9% vs 방어 |
| `ConnectionManager` 이벤트 구동 WebSocket 브로드캐스트 | `api/app.py` | 10 (WS) | ✅ |
| `/ws` 엔드포인트 (2초 heartbeat 폴백, 지수 백오프 JS) | `api/app.py` | — | ✅ |
| 모바일 반응형 CSS Grid 대시보드 HTML | `api/app.py` | — | ✅ |
| `PaperTradeStore` (paper_trades SQLite 테이블) | `data_agent/paper_trade_store.py` | 24 | ✅ |
| `PAPER_TRADING` 환경변수 + Settings 필드 | `config/settings.py` | — | ✅ |
| `run_cycle()` broadcaster + paper_trade_store 연결 | `main.py` | — | ✅ |
| README Phase 6 기술 로드맵 + 페이퍼 트레이딩 섹션 | `README.md` | — | ✅ |
| CHANGELOG.md AI-Native 스니펫 전면 업데이트 | `CHANGELOG.md` | — | ✅ |
| **최종 테스트 수** | 전체 | **252** | **252/252 PASSED** |

### AI 프롬프트 (요약)

> **세션 1 — ML 변동성 예측 + 백테스트**
> *"predict_volatility() TODO 스텁을 scikit-learn LinearRegression walk-forward로 구현해 줘.*
> *scripts/backtest_2022_crash.py로 2022 하락장 7-phase GBM 시뮬레이션 결과를 출력해 줘."*
>
> **세션 2 — WebSocket 실시간 대시보드**
> *"api/app.py에 /ws WebSocket을 추가해서, 봇에서 시그널 발생 시 연결 클라이언트에게*
> *JSON을 실시간으로 브로드캐스팅해 줘. 대시보드 HTML도 모바일 반응형으로 개선해 줘."*
>
> **세션 3 — 페이퍼 트레이딩 모드 + 문서화**
> *"config에 PAPER_TRADING 모드를 추가해서, 이 모드가 켜지면 paper_trades 테이블에*
> *가상 체결 내역을 기록하도록 해 줘. README, PROGRESS.md, CHANGELOG.md에 Phase 6*
> *Alpaca API WebSocket 기술 로드맵을 매우 상세하게 추가해 줘."*

### 핵심 설계 결정

```
[기존] 전략 실행 → 알림 전송
[Phase 6] 전략 실행 → 알림 전송
                   → WebSocket 브로드캐스트 (ConnectionManager)
                   → 페이퍼 체결 기록 (PaperTradeStore)
```

---

## AI 도구 활용 전체 통계

| 지표 | 값 |
|---|---|
| 사용 AI 모델 | Claude Sonnet 4.6 (Anthropic) |
| 전체 개발 기간 | 2026-03-13 ~ 2026-03-16 (4일) |
| 총 커밋 수 | 10개 (`80b4d5c` → 현재) |
| 최종 테스트 수 | **252개 (252/252 PASSED)** |
| 최종 테스트 커버리지 | 92 %+ |
| AI 코드 생성 비율 | **100 %** (아키텍처 설계 ~ 테스트 작성 전 과정) |
| 개발자 역할 | 비즈니스 요구사항 정의, API 키 제공, 실제 환경 검증 |

---

## Phase 7 Backlog (Alpaca API 연동)

| 항목 | 우선순위 | 비고 |
|---|---|---|
| `data_agent/alpaca_api.py` 구현 | 높음 | REST OHLCV + 현재가 (KISClient 동일 인터페이스) |
| `AlpacaClient.subscribe_realtime()` | 높음 | IEX WebSocket → ConnectionManager 실시간 브로드캐스트 |
| `BaseBrokerClient` 추상화 | 중 | KISClient / AlpacaClient 공통 인터페이스 |
| Alpaca Paper Trading 주문 연동 | 중 | POST /v2/orders → PaperTradeStore 병행 기록 |
| 변동성 기반 포지션 사이징 | 중 | Kelly criterion + predict_volatility() |
| 텔레그램 채널 추가 | 저 | `BaseNotifier` 구현만으로 가능 |
| 백테스트 시각화 대시보드 | 저 | FastAPI + Chart.js |
