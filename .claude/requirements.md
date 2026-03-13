# 프로젝트명: 김거지 햇지 트레이딩 시그널 봇 (Kim-Geoji Hedge Signal Bot)

## 1. 프로젝트 개요
- **목적**: 잃지 않는 매매가 최우선. 철저한 리스크 관리와 헤지 비율 계산을 통해 생계형 시그널을 생성하는 봇.
- **운영 방식**: 실제 주문(매수/매도)은 API로 실행하지 않음. 철저히 시그널만 생성하고 알림을 전송하는 읽기 전용(Read-only) 봇.

## 2. 기술 스택 및 환경
- **언어**: Python 3.10+
- **증권사 API**: 한국투자증권 (KIS Developers) REST API
- **핵심 라이브러리**:
  - 데이터 처리: `pandas`, `numpy`
  - 보조 지표: `ta-lib` 또는 `pandas-ta`
  - HTTP 통신: `requests`
  - 환경변수 관리: `python-dotenv`
- **알림 수단**: 카카오톡 "나에게 보내기" (카카오 REST API OAuth2 + 메모 전송 API)
- **보안**: `.env` 파일을 통한 KIS API Key, Secret, 계좌번호 관리 (절대 하드코딩 금지)

## 3. 타겟 종목 및 데이터
- **모니터링 대상**: KOSPI/KOSDAQ 우량주 (예: 삼성전자, SK하이닉스 등)
- **헤지 수단**: KODEX 200선물인버스2X (또는 KOSPI 200 선물)
- **데이터 주기**: 5분봉 및 일봉 (시그널 확인용)

## 4. 트레이딩 전략 (The Vibe: 김거지 마인드셋)
- **절대 원칙**: "수익을 덜 내더라도 손실은 무조건 막는다." MDD(최대 낙폭) 최소화.
- **진입 조건 (Buy Signal)**:
    - 시장 전체가 폭락하는 중이 아닐 것 (지수 이동평균선 확인).
    - 특정 종목의 RSI가 30 이하에서 위로 꺾일 때 (확실한 과매도 구간 탈출).
- **청산 및 손절 조건 (Sell/Stop-loss Signal)**:
    - -2% 하락 시 즉각적인 '도망쳐' 손절 시그널 발생.
    - +3% 수익 도달 시 절반 매도 시그널 (수익 실현).
- **헤지 전략 (Hedge Signal)**:
    - 개별 종목 매수 시그널 발생 시, 해당 종목의 투자 금액 대비 30% 비율로 인버스 ETF 매수 시그널을 동시 발생.
    - 지수 데드크로스 발생 시 헤지 비율을 50%로 상향.

## 5. 아키텍처 및 모듈 분리 요구사항
- **Config**: `.env` 로드 및 전역 설정 관리
- **Data Agent**: 한국투자증권 API 인증(Oauth 토큰 발급) 및 시세 데이터 수집
- **Strategy**: 수집된 데이터(Pandas DataFrame)를 바탕으로 기술적 지표 계산 및 조건 판별
- **Notifier**: 시그널 발생 시 카카오톡 "나에게 보내기" 메시지 전송
- **Logger**: 모든 데이터 페치 및 시그널 발생 내역을 `logs/bot.log`에 일자별로 기록

## 6. 실행 흐름
- 메인 루프에서 N분마다 `Data Agent`를 통해 최신 봉 데이터를 가져옴 -> `Strategy` 모듈에 전달 -> 시그널 발생 시 `Notifier` 호출.

---

## 7. 개발 진행 상황 (Progress Tracker)

> 마지막 업데이트: 2026-03-13

### ✅ Phase 1 — 인프라 & API 연동

| 항목 | 파일 | 상태 |
|---|---|---|
| KIS OAuth 토큰 발급 | `data_agent/kis_api.py` | 완료 |
| KIS 현재가 조회 | `data_agent/kis_api.py` | 완료 |
| KIS 5분봉 / 일봉 OHLCV | `data_agent/kis_api.py` | 완료 |
| KIS 지수 조회 (KOSPI/KOSDAQ) | `data_agent/kis_api.py` | 완료 |
| KIS 연결 테스트 스크립트 | `scripts/test_kis.py` | 완료 |
| 카카오 OAuth 최초 인증 | `scripts/kakao_auth_setup.py` | 완료 |
| 카카오 토큰 저장 / 자동 갱신 | `notifier/kakao_token_manager.py` | 완료 |
| 카카오 "나에게 보내기" 전송 | `notifier/kakao.py` | 완료 |
| 카카오 연결 테스트 스크립트 | `scripts/test_kakao.py` | 완료 |
| 전역 설정 관리 | `config/settings.py` | 완료 |
| 일자별 로테이팅 로거 | `logger/log_setup.py` | 완료 |

**검증 결과**
- KIS 모의투자 서버에서 삼성전자(005930) 현재가 조회 성공 (184,200원)
- 카카오톡 "나에게 보내기"로 테스트 메시지 전송 성공

---

### ✅ Phase 2 — 코드 품질 고도화

| 항목 | 파일 | 상태 |
|---|---|---|
| PEP 484 타입 힌팅 전면 적용 | 전체 모듈 | 완료 |
| Google 스타일 Docstring 추가 | 전체 모듈 | 완료 |
| tenacity 재시도 데코레이터 | `kakao.py`, `kakao_token_manager.py`, `kis_api.py` | 완료 |
| Observer 패턴 알림 인터페이스 | `notifier/base.py` | 완료 |
| NotifierService 컴포짓 | `notifier/base.py` | 완료 |
| 환경별 SSL 검증 분리 | `config/ssl.py` | 완료 |
| `.gitignore` 보안 설정 | `.gitignore` | 완료 |
| `README.md` 작성 | `README.md` | 완료 |

**주요 설계 결정**
- `DEV_MODE=true` → `verify=False` (로컬 인증서 우회), `false` → TLS 완전 검증
- `BaseNotifier` ABC 도입: Kakao 외 Telegram 등 채널을 코어 코드 수정 없이 확장 가능
- tenacity 설정: 최대 3회 재시도, 지수 백오프 1s → 2s → 4s (max 8s)

---

### ✅ Phase 3 — 핵심 트레이딩 로직 구현

| 항목 | 파일 | 상태 |
|---|---|---|
| RSI 계산 (Wilder 스무딩) | `strategy/indicators.py` | 완료 |
| SMA / EMA 계산 | `strategy/indicators.py` | 완료 |
| 골든크로스 / 데드크로스 감지 | `strategy/indicators.py` | 완료 |
| 변동성 계산 (rolling std) | `strategy/indicators.py` | 완료 |
| 동적 헤지 비율 계산 | `strategy/hedge_logic.py` | 완료 |
| SignalEngine — BUY 시그널 | `strategy/signal.py` | 완료 |
| SignalEngine — SELL 시그널 | `strategy/signal.py` | 완료 |
| SignalEngine — STOP_LOSS 시그널 | `strategy/signal.py` | 완료 |
| SignalEngine — HEDGE 시그널 | `strategy/signal.py` | 완료 |
| 메인 루프 `run_cycle()` 구현 | `main.py` | 완료 |

**시그널 로직 요약**
- **BUY**: RSI ≤ 30 (과매도) AND 골든크로스 발생
- **SELL**: RSI ≥ 70 (과매수) AND 데드크로스 발생
- **STOP_LOSS**: 현재가 ≤ 진입가 × (1 − stop_loss_rate), 우선순위 최고
- **HEDGE**: KOSPI/KOSDAQ 당일 등락률 ≤ −1.5%, 동적 헤지 비율 자동 계산
  - 헤지 비율 공식: `base + MA이탈률 × 5pp + 지수낙폭 × 3pp` (0~80% 클램프)

**사용 라이브러리**
- `ta` (Technical Analysis) — RSI, SMA, EMA 계산

---

### ✅ Phase 4 — 테스트 & CI/CD

| 항목 | 파일 | 상태 |
|---|---|---|
| pytest 단위 테스트 (58개) | `tests/test_strategy.py` | 완료 |
| 공용 fixture (mock_settings, price series) | `tests/conftest.py` | 완료 |
| GitHub Actions 파이프라인 | `.github/workflows/python-app.yml` | 완료 |
| flake8 린팅 설정 | `setup.cfg` | 완료 |
| 개발 전용 의존성 분리 | `requirements-dev.txt` | 완료 |

**테스트 커버리지 (`strategy` 모듈)**

| 테스트 클래스 | 케이스 수 | 검증 내용 |
|---|---|---|
| `TestCalculateRsi` | 6 | 반환 타입, 길이, NaN 워밍업, 범위, 방향성 |
| `TestCalculateMovingAverage` | 4 | NaN 구간, 수식 정확도, 단/장기 관계 |
| `TestCalculateEma` | 2 | 반환 타입, SMA 대비 빠른 반응 |
| `TestDetectGoldenCross` | 4 | bar 단위 감지, 오탐 없음, V자 시리즈 |
| `TestDetectDeadCross` | 3 | bar 단위 감지, A자 시리즈, GC/DC 상호배타성 |
| `TestCalculateVolatility` | 3 | 반환 타입, 상수=0, 변동성 대소 |
| `TestCalculateHedgeRatio` | 7 | base, MA리스크, 지수리스크, 수식, 클램프 |
| `TestDescribeHedge` | 5 | 강/중/약/불필요 레이블, 비율 텍스트 |
| `TestCheckStopLoss` | 4 | 임계 이하/경계/이상/진입가 동일 |
| `TestCheckBuySignal` | 3 | 양조건, RSI만, 크로스만 |
| `TestCheckSellSignal` | 3 | 양조건, RSI만, 크로스만 |
| `TestCheckHedgeSignal` | 5 | 임계 초과/경계/미달/양수/잘못된 데이터 |
| `TestSignalEngineEvaluate` | 9 | 빈 데이터, 부족, 심볼, 가격, RSI, 손절 우선순위 등 |
| **합계** | **58** | **58 / 58 PASSED** |

**CI/CD 파이프라인 동작**
- `main` 브랜치 push / PR 시 자동 실행 (GitHub Actions)
- `flake8` 린팅 → `pytest --cov=strategy` 순서로 실행
- 커버리지 리포트 XML을 Artifact로 7일간 보관

---

### 🔲 Phase 5 — 향후 과제 (Backlog)

| 항목 | 우선순위 | 비고 |
|---|---|---|
| `strategy/indicators.py` — 변동성 기반 포지션 사이징 | 중 | Kelly criterion 검토 |
| `strategy/signal.py` — 백테스트 모드 추가 | 중 | 과거 OHLCV로 시그널 검증 |
| `notifier/telegram.py` — 텔레그램 채널 추가 | 저 | `BaseNotifier` 구현만으로 가능 |
| `data_agent/kis_api.py` — 웹소켓 실시간 시세 | 저 | KIS WebSocket API 검토 |
| 진입가 영속성 — JSON / SQLite 저장 | 중 | 현재 인메모리(재시작 시 초기화) |
| `main.py` — 장 시작/마감 시간 필터 | 중 | 09:00~15:20 외 사이클 스킵 |