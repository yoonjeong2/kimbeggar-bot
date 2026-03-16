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

---

## 8. 모듈별 구현 상태 (Module Status)

> 범례: ✅ 완료 | 🔄 진행 중 | 🔲 TODO

### `config/`

| 파일 | 기능 | 상태 | 비고 |
|---|---|---|---|
| `config/settings.py` | `.env` 로드, 전역 설정 dataclass | ✅ 완료 | `dev_mode` 프로퍼티 포함 |
| `config/ssl.py` | 환경별 SSL 검증 플래그 | ✅ 완료 | `DEV_MODE` 기반 조건부 우회 |

### `data_agent/`

| 파일 | 기능 | 상태 | 비고 |
|---|---|---|---|
| `data_agent/kis_api.py` | OAuth 토큰 발급/갱신 | ✅ 완료 | 24시간 유효, 만료 5분 전 자동 재발급 |
| | 현재가 조회 (`inquire-price`) | ✅ 완료 | `tr_id=FHKST01010100` |
| | 5분봉 OHLCV | ✅ 완료 | `tr_id=FHKST03010200` |
| | 일봉 OHLCV | ✅ 완료 | `tr_id=FHKST03010100`, 기본 60일 |
| | 지수 조회 (KOSPI/KOSDAQ) | ✅ 완료 | `tr_id=FHPUP03500100` |
| | 웹소켓 실시간 시세 | 🔲 TODO | Phase 5 백로그 |

### `strategy/`

| 파일 | 기능 | 상태 | 비고 |
|---|---|---|---|
| `strategy/indicators.py` | RSI (Wilder 스무딩) | ✅ 완료 | `ta.momentum.RSIIndicator` 활용 |
| | SMA (단순 이동평균) | ✅ 완료 | `ta.trend.SMAIndicator` 활용 |
| | EMA (지수 이동평균) | ✅ 완료 | `ta.trend.EMAIndicator` 활용 |
| | 골든크로스 감지 | ✅ 완료 | shift(1) 비교, bar 단위 정확 감지 |
| | 데드크로스 감지 | ✅ 완료 | shift(1) 비교, bar 단위 정확 감지 |
| | 변동성 (rolling std) | ✅ 완료 | |
| | 변동성 기반 포지션 사이징 | 🔲 TODO | Kelly criterion 검토 예정 |
| `strategy/hedge_logic.py` | 동적 헤지 비율 계산 | ✅ 완료 | MA이탈률×5pp + 지수낙폭×3pp, 0~80% 클램프 |
| | 헤지 강도 설명 문자열 | ✅ 완료 | 강/중/약/불필요 4단계 |
| `strategy/signal.py` | BUY 시그널 | ✅ 완료 | RSI ≤ 30 AND 골든크로스 |
| | SELL 시그널 | ✅ 완료 | RSI ≥ 70 AND 데드크로스 |
| | STOP_LOSS 시그널 | ✅ 완료 | 현재가 ≤ 진입가×(1−rate), 최우선 |
| | HEDGE 시그널 | ✅ 완료 | 지수 등락률 ≤ −1.5% |
| | 백테스트 모드 | 🔲 TODO | 과거 OHLCV 시뮬레이션 |

### `notifier/`

| 파일 | 기능 | 상태 | 비고 |
|---|---|---|---|
| `notifier/base.py` | `BaseNotifier` ABC | ✅ 완료 | DIP 기반 채널 인터페이스 |
| | `NotifierService` 컴포짓 | ✅ 완료 | Observer 패턴, 런타임 채널 등록 |
| `notifier/kakao.py` | 카카오 메시지 전송 | ✅ 완료 | tenacity 3회 재시도 포함 |
| | 시그널 메시지 포맷팅 | ✅ 완료 | BUY/SELL/STOP_LOSS/HEDGE 레이블 |
| `notifier/kakao_token_manager.py` | 토큰 파일 저장 (원자적) | ✅ 완료 | tempfile → os.replace() |
| | access_token 자동 갱신 | ✅ 완료 | 만료 5분 전 자동 refresh |
| | refresh_token 만료 감지 | ✅ 완료 | 30일 이내 재인증 경고 |
| `notifier/telegram.py` | 텔레그램 채널 | 🔲 TODO | `BaseNotifier` 구현만으로 추가 가능 |

### `main.py` / `logger/` / `scripts/`

| 파일 | 기능 | 상태 | 비고 |
|---|---|---|---|
| `main.py` | 메인 루프 (`run_cycle`) | ✅ 완료 | schedule 기반 N분 주기 |
| | 지수 헤지 체크 (선행) | ✅ 완료 | KOSPI 먼저 확인 후 종목별 평가 |
| | 진입가 인메모리 추적 | ✅ 완료 | BUY→기록, SELL/STOP_LOSS→해제 |
| | 장 시간 필터 | 🔲 TODO | 09:00~15:20 외 사이클 스킵 |
| | 진입가 영속성 | 🔲 TODO | 재시작 시 초기화 문제 |
| `logger/log_setup.py` | 일자별 로테이팅 파일 로거 | ✅ 완료 | 자정 교체, 30일 보관 |
| `scripts/kakao_auth_setup.py` | 카카오 최초 OAuth 인증 | ✅ 완료 | 1회 실행용 |
| `scripts/test_kis.py` | KIS API 연결 테스트 | ✅ 완료 | 토큰 발급 + 삼성전자 현재가 |
| `scripts/test_kakao.py` | 카카오 메시지 전송 테스트 | ✅ 완료 | "김거지 봇 테스트 성공!" |

---

## 9. AI 도구 활용 기록 (AI-Assisted Development Log)

> 이 프로젝트의 전체 코드는 **Claude Sonnet 4.6** (Anthropic)을 통해 설계 및 구현되었습니다.
> 각 항목은 `날짜: 작업 내용 — 사용 도구 — 결과` 형식으로 기록합니다.

---

### `config/`

| 날짜 | 파일 | 작업 | AI 도구 | 결과 |
|---|---|---|---|---|
| 2026-03-13 | `config/settings.py` | Settings dataclass 설계, `dev_mode` 프로퍼티 추가, Google Docstring 전면 적용 | Claude Sonnet 4.6 | 완료, 테스트 통과 |
| 2026-03-13 | `config/ssl.py` | `ssl_verify()` 함수 신규 생성 — DEV_MODE 기반 환경별 SSL 우회 로직, 영문 주석 | Claude Sonnet 4.6 | 완료, 전 모듈 공유 |

---

### `data_agent/kis_api.py`

| 날짜 | 작업 | AI 도구 | 결과 |
|---|---|---|---|
| 2026-03-13 | `_issue_token()` — KIS OAuth `client_credentials` 토큰 발급 구현 (TODO → 실제 코드) | Claude Sonnet 4.6 | 완료, 모의투자 서버 86400초 토큰 발급 성공 |
| 2026-03-13 | `get_current_price()` 신규 추가, `get_ohlcv_5min()` / `get_ohlcv_daily()` / `get_index_data()` TODO 구현 | Claude Sonnet 4.6 | 완료, 삼성전자 184,200원 조회 확인 |
| 2026-03-13 | `_request()` 공통 핸들러 구현 — KIS 인증 헤더 자동 주입, `rt_cd` 오류 감지 | Claude Sonnet 4.6 | 완료 |
| 2026-03-13 | `_get_with_retry()` / `_post_with_retry()` — tenacity 재시도 데코레이터 적용, 지수 백오프 1→2→4s | Claude Sonnet 4.6 | 완료 |
| 2026-03-13 | PEP 484 타입 힌팅 전면 적용, Google Docstring 추가 | Claude Sonnet 4.6 | 완료 |

---

### `strategy/indicators.py`

| 날짜 | 작업 | AI 도구 | 결과 |
|---|---|---|---|
| 2026-03-13 | `calculate_rsi()` — `ta.momentum.RSIIndicator` 활용, Wilder 스무딩 방식으로 구현 (TODO 제거) | Claude Sonnet 4.6 | 완료, `RSI[-1]=9.77` 단조 하락 시리즈 검증 통과 |
| 2026-03-13 | `calculate_moving_average()` — `ta.trend.SMAIndicator` 활용 (TODO 제거) | Claude Sonnet 4.6 | 완료, SMA 산술평균 단위 테스트 통과 |
| 2026-03-13 | `calculate_ema()` — `ta.trend.EMAIndicator` 활용 (TODO 제거) | Claude Sonnet 4.6 | 완료, EMA가 SMA보다 spike에 빠르게 반응함 확인 |
| 2026-03-13 | `detect_golden_cross()` / `detect_dead_cross()` — shift(1) 비교 방식, bar 단위 정확 감지 (TODO 제거) | Claude Sonnet 4.6 | 완료, V자/A자 합성 시리즈로 크로스 감지 검증 |
| 2026-03-13 | `calculate_volatility()` — rolling std 구현 (TODO 제거) | Claude Sonnet 4.6 | 완료, 상수 시리즈 변동성=0 확인 |

---

### `strategy/hedge_logic.py`

| 날짜 | 작업 | AI 도구 | 결과 |
|---|---|---|---|
| 2026-03-13 | `hedge_logic.py` 신규 파일 생성 — MA이탈률×5pp + 지수낙폭×3pp 헤지 비율 공식 설계 | Claude Sonnet 4.6 | 완료 |
| 2026-03-13 | `calculate_hedge_ratio()` — 0~80% 클램프, 강세장에서 기본값 유지 검증 | Claude Sonnet 4.6 | 완료, 수식 단위 테스트 7개 통과 |
| 2026-03-13 | `describe_hedge()` — 강/중/약/불필요 4단계 설명 문자열 | Claude Sonnet 4.6 | 완료 |

---

### `strategy/signal.py`

| 날짜 | 작업 | AI 도구 | 결과 |
|---|---|---|---|
| 2026-03-13 | `SignalEngine.evaluate()` — OHLCV list → pd.Series 변환, 지표 계산, 우선순위 판별 (STOP_LOSS > SELL > BUY > HOLD) 구현 (TODO 제거) | Claude Sonnet 4.6 | 완료 |
| 2026-03-13 | `check_buy_signal()` — RSI ≤ 30 AND 골든크로스 조건 구현 (TODO 제거) | Claude Sonnet 4.6 | 완료, 단일 조건만 충족 시 미발동 검증 |
| 2026-03-13 | `check_sell_signal()` — RSI ≥ 70 AND 데드크로스 조건 구현 (TODO 제거) | Claude Sonnet 4.6 | 완료 |
| 2026-03-13 | `check_stop_loss()` — `price ≤ entry × (1 − rate)` 구현 (TODO 제거) | Claude Sonnet 4.6 | 완료, 경계값(floor 정확히 일치) 테스트 통과 |
| 2026-03-13 | `check_hedge_signal()` — `bstp_nmix_prdy_ctrt` 파싱, ≤ −1.5% 트리거 (TODO 제거) | Claude Sonnet 4.6 | 완료, 잘못된 문자열 입력 방어 처리 확인 |
| 2026-03-13 | PEP 484 타입 힌팅 전면 적용, Google Docstring 추가, 시그널 우선순위 주석 | Claude Sonnet 4.6 | 완료 |

---

### `notifier/`

| 날짜 | 파일 | 작업 | AI 도구 | 결과 |
|---|---|---|---|---|
| 2026-03-13 | `notifier/base.py` | `BaseNotifier` ABC + `NotifierService` 컴포짓 신규 설계 (Observer 패턴, DIP) | Claude Sonnet 4.6 | 완료, KakaoNotifier 연동 확인 |
| 2026-03-13 | `notifier/kakao.py` | `KakaoNotifier(BaseNotifier)` 리팩토링 — `_post_with_retry()` tenacity 3회 재시도, Google Docstring | Claude Sonnet 4.6 | 완료, "김거지 봇 테스트 성공!" 실제 전송 확인 |
| 2026-03-13 | `notifier/kakao_token_manager.py` | `_post_token_with_retry()` tenacity 적용, `import os` 중복 제거, Google Docstring 전면 작성 | Claude Sonnet 4.6 | 완료 |

---

### `main.py`

| 날짜 | 작업 | AI 도구 | 결과 |
|---|---|---|---|
| 2026-03-13 | `run_cycle()` 스켈레톤(pass) → 실제 구현: KOSPI 선행 헤지 체크, 종목별 OHLCV+현재가 수집, 시그널 평가, 알림 전송, 진입가 추적 | Claude Sonnet 4.6 | 완료 |

---

### `tests/`

| 날짜 | 파일 | 작업 | AI 도구 | 결과 |
|---|---|---|---|---|
| 2026-03-13 | `tests/conftest.py` | `mock_settings`, `ascending_prices`, `descending_prices`, `ohlcv_*` fixture 작성 | Claude Sonnet 4.6 | 완료 |
| 2026-03-13 | `tests/test_strategy.py` | indicators 22개, hedge_logic 12개, signal 24개 총 58개 단위 테스트 작성 | Claude Sonnet 4.6 | 완료, **58 / 58 PASSED** (0.15s) |
| 2026-03-13 | 테스트 버그 수정: RSI 워밍업 `[:14]` → `[:13]`, V/A자 크로스 시리즈, `pytest.approx` Series 비교 수정 | Claude Sonnet 4.6 | 완료 |

---

### CI/CD & 프로젝트 설정

| 날짜 | 파일 | 작업 | AI 도구 | 결과 |
|---|---|---|---|---|
| 2026-03-13 | `.github/workflows/python-app.yml` | GitHub Actions CI/CD 파이프라인 구축 — flake8 린팅 + pytest --cov + coverage Artifact | Claude Sonnet 4.6 | 완료 |
| 2026-03-13 | `setup.cfg` | flake8(max-line-length=100) + pytest testpaths 통합 설정 | Claude Sonnet 4.6 | 완료 |
| 2026-03-13 | `requirements-dev.txt` | pytest, pytest-cov, flake8 개발 전용 의존성 분리 | Claude Sonnet 4.6 | 완료 |
| 2026-03-13 | `.gitignore` | `.env`, `venv/`, `data/kakao_token.json`, `__pycache__/`, `logs/` 보안 설정 | Claude Sonnet 4.6 | 완료 |
| 2026-03-13 | `README.md` | 프로젝트 목적, 아키텍처 다이어그램, 설치/실행/테스트 가이드, 확장 가이드 작성 | Claude Sonnet 4.6 | 완료 |

---

## 10. 변경 로그 및 개발 타임라인

> **이 섹션은 [`PROGRESS.md`](../PROGRESS.md)로 통합되었습니다.**
>
> Phase별 상세 타임라인(날짜, 주요 작업, AI 프롬프트 요약, 활용 비율)과
> 전체 변경 이력은 아래 파일에서 관리됩니다:
>
> - **[`PROGRESS.md`](../PROGRESS.md)** — Phase 1~5 타임라인, AI 도구 활용 통계, Backlog
> - **[`CHANGELOG.md`](../CHANGELOG.md)** — Keep-a-Changelog 형식 버전별 변경 이력
>   (각 릴리스에 Claude 프롬프트 요약 + 핵심 코드 스니펫 포함)

### 빠른 참조

| 문서 | 내용 | 경로 |
|---|---|---|
| PROGRESS.md | Phase 타임라인, AI 활용 비율, Backlog | `../PROGRESS.md` |
| CHANGELOG.md | 버전별 Added/Changed/Fixed + 프롬프트 | `../CHANGELOG.md` |

---

### Phase 완료 현황

| Phase | 상태 | 핵심 산출물 |
|---|---|---|
| Phase 1 — 인프라 & API 연동 | ✅ 완료 | KIS API, Kakao OAuth, 전역 설정, 로거 |
| Phase 2 — 코드 품질 고도화 | ✅ 완료 | 타입힌팅, Observer 패턴, tenacity |
| Phase 3 — 핵심 트레이딩 로직 | ✅ 완료 | SignalEngine, 지표, 헤지 비율 |
| Phase 4 — 테스트 & CI/CD | ✅ 완료 | 185 tests, 92 % coverage, Docker CI |
| Phase 5 — 고도화 | ✅ 완료 | SQLite, 장시간 필터, FastAPI, Render CD |
| Phase 6 — 향후 과제 | 🔲 백로그 | 웹소켓, 포지션 사이징, 텔레그램 |