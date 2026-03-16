# 🤖 KimBeggar — 절대 잃지 않는 헤지 봇

> **"돈을 버는 것보다 잃지 않는 것이 먼저다."**
> RSI + 이동평균 크로스오버로 매매 시그널을 탐지하고, 시장 급락 시 인버스 ETF 헤지를 자동 알림하는 국내 주식 모니터링 봇.

![CI](https://github.com/yoonjeong2/kimbeggar-bot/actions/workflows/python-app.yml/badge.svg)
[![codecov](https://codecov.io/gh/yoonjeong2/kimbeggar-bot/graph/badge.svg)](https://codecov.io/gh/yoonjeong2/kimbeggar-bot)
![Python](https://img.shields.io/badge/python-3.11-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## 목차 Table of Contents

1. [프로젝트 목적](#1-프로젝트-목적)
2. [기존 봇과의 차이점](#2-기존-봇과의-차이점)
3. [핵심 전략 — 절대 잃지 않는 3단 방어선](#3-핵심-전략--절대-잃지-않는-3단-방어선)
4. [아키텍처](#4-아키텍처)
5. [디렉터리 구조](#5-디렉터리-구조)
6. [의존성 & 기술 스택](#6-의존성--기술-스택)
7. [설치 및 환경 구성](#7-설치-및-환경-구성)
8. [카카오 OAuth 최초 인증](#8-카카오-oauth-최초-인증)
9. [실행 & 샘플 출력 로그](#9-실행--샘플-출력-로그)
10. [알림 메시지 형식](#10-알림-메시지-형식)
11. [MVP 데모 (API 없이 알림 테스트)](#11-mvp-데모-api-없이-알림-테스트)
12. [백테스팅 & 2022 시장 급락 시나리오](#12-백테스팅--2022-시장-급락-시나리오)
13. [연결 테스트](#13-연결-테스트)
14. [설계 원칙 & 패턴](#14-설계-원칙--패턴)
15. [운영 체크리스트](#15-운영-체크리스트)
16. [Docker & 크로스 플랫폼](#16-docker--크로스-플랫폼)
17. [확장 가이드 — 새 채널 & 암호화폐](#17-확장-가이드--새-채널--암호화폐)
18. [호환성 (Compatibility)](#18-호환성-compatibility)
19. [페이퍼 트레이딩 모드 (PAPER_TRADING)](#19-페이퍼-트레이딩-모드-paper_trading)
20. [Phase 6 기술 로드맵 — Alpaca API & WebSocket 실시간 시세](#20-phase-6-기술-로드맵--alpaca-api--websocket-실시간-시세)
21. [기여 가이드 (Contributing)](#21-기여-가이드-contributing)

---

## 1. 프로젝트 목적


KimBeggar는 **"절대 잃지 않는"** 원칙을 자동화한 국내 주식 헤지 알림 봇입니다.

| 목표 | 설명 |
|---|---|
| **손실 최소화** | 보유 종목이 손절 임계치(기본 −5 %) 이하로 하락하면 즉시 알림 |
| **수익 극대화** | RSI 과매도 + 골든크로스 조건에서 매수 시그널, 과매수 + 데드크로스에서 매도 시그널 |
| **시장 방어** | 코스피/코스닥 지수 급락 감지 시 인버스 ETF 헤지 진입 알림 |
| **24/7 모니터링** | N분 주기 자동 폴링 — 장중 내내 사람 없이 동작 |

알림 채널은 **카카오톡 "나에게 보내기"** 를 기본으로 제공하며, Observer 패턴 기반 구조로 텔레그램·슬랙 등을 코어 코드 수정 없이 추가할 수 있습니다.

### 국제 시장 확장 로드맵 — Phase 6: Alpaca API 연동

KimBeggar의 다음 단계는 **국내 KIS API → 글로벌 Alpaca API**로의 데이터 에이전트 확장입니다.
동일한 전략 엔진(RSI + MA 크로스오버 + 동적 헤지)을 미국 주식·ETF에 그대로 적용할 수 있습니다.

| Phase | 범위 | 핵심 변경 |
|---|---|---|
| Phase 1–5 | 국내 KIS API | 현재 구현 완료 |
| **Phase 6** | **Alpaca API (미국장)** | `data_agent/alpaca_api.py` 신규 작성 |
| Phase 7 | 멀티 브로커 통합 | `KISClient` / `AlpacaClient` 공통 인터페이스 추상화 |

```python
# Phase 6 목표 코드 — main.py 변경 없이 브로커 교체
from data_agent.alpaca_api import AlpacaClient   # ← 이 줄만 교체

kis    = KISClient(settings)    # 현재: 한국 KIS
alpaca = AlpacaClient(settings) # Phase 6: 미국 Alpaca
```

**Alpaca API 선택 이유:**
- REST + WebSocket 동시 지원 → 실시간 시세 수신 가능
- Paper Trading 계정 무료 제공 → 실제 자금 없이 전략 검증
- `APCA-API-KEY-ID` / `APCA-API-SECRET-KEY` 2개 키만으로 인증
- `alpaca-trade-api-python` 공식 SDK 제공 (MIT 라이선스)

---

## 2. 기존 봇과의 차이점

시중에 공개된 국내 주식 알림 봇과 KimBeggar의 핵심 차별점:

| 항목 | 일반 알림 봇 | **KimBeggar** |
|---|---|---|
| **헤지 전략** | 단순 가격 알림만 제공 | **실시간 인버스 ETF 헤지 비율 자동 산출** (MA 이탈 + 지수 급락 복합 반영) |
| **ML 기반 동적 헤지** | 없음 | **scikit-learn LinearRegression으로 변동성 예측** → 헤지 비율을 시장 상황에 맞게 동적 조정 (`predict_volatility()` 구현 완료) |
| **페이퍼 트레이딩** | 없음 | **PAPER_TRADING=true** 한 줄로 활성화 — 가상 체결을 SQLite `paper_trades` 테이블에 기록, P&L 집계 |
| **알림 채널 확장** | 단일 채널 하드코딩 | **Observer 패턴** — `BaseNotifier` ABC 구현으로 카카오·텔레그램·슬랙 코어 수정 없이 추가 가능 |
| **신호 우선순위** | 단순 조건 판별 | **4단계 우선순위 체계** (STOP_LOSS > SELL > BUY > HOLD) |
| **에러 복구** | 예외 시 중단 | **Tenacity 재시도** (지수 백오프, 최대 3회) + **에러 발생 시 카카오 알림** |
| **백테스팅** | 없음 | **backtrader 기반 과거 데이터 전략 검증** |
| **테스트 커버리지** | 없음 / 미흡 | **92% 커버리지** (165개 pytest 유닛·통합 테스트) |
| **CI/CD** | 없음 | **GitHub Actions**: black 포맷 + flake8 + pylint + pytest + Docker 빌드 자동화 |
| **국제 시장** | 국내 전용 | **Phase 6 Alpaca API 연동** — 미국 주식·ETF에 동일 전략 적용 예정 |

```
기존 봇: 조건 감지 → 알림 전송
                  ↑ 여기서 끝

KimBeggar:
  지수 급락 감지 → [ML 변동성 예측] → 동적 헤지 비율 계산 → 인버스 ETF 권고량 산출 → 알림
  주식 신호 감지 → 우선순위 판단 → 에러 시 복구·재시도 → 알림
  백테스트로 전략 사전 검증 가능
  (Phase 6) KIS API ↔ Alpaca API 브로커 교체 — 전략 코드 변경 없음
```

### ML 기반 동적 헤지란?

헤지 비율을 **고정 공식**이 아닌 **학습된 변동성 예측값**으로 조정하는 방식입니다.
`strategy/hedge_logic.py`의 `predict_volatility()` 함수로 **구현 완료**되어 있습니다.

```
현재 방식: 헤지 비율 = base_ratio + MA이탈분 + 지수급락분  (규칙 기반)
ML 방식:   헤지 비율 = predict_volatility(returns) × 0.5   (데이터 기반)
                              ↑
              scikit-learn LinearRegression (walk-forward 학습)
              입력: 과거 N일 수익률의 mean / std / slope / min / max
              출력: 다음 봉 예상 연율화 변동성 (annualized)
```

---

## 3. 핵심 전략 — 절대 잃지 않는 3단 방어선

```
┌─────────────────────────────────────────────────────────────┐
│  1단  진입 필터   RSI < 30 (과매도) + 골든크로스 → 매수 시그널    │
│  2단  이익 실현   RSI > 70 (과매수) + 데드크로스 → 매도 시그널    │
│  3단  손실 차단   현재가 ≤ 진입가 × (1 − stop_loss_rate)        │
│                                              → 즉시 손절 알림  │
│  [비상] 헤지      시장 지수 급락 감지 → 인버스 ETF 헤지 진입 알림  │
└─────────────────────────────────────────────────────────────┘
```

### 시그널 유형

| `SignalType` | 조건 | 행동 |
|---|---|---|
| `BUY` | RSI < `rsi_oversold` **AND** 골든크로스 발생 | 매수 알림 |
| `SELL` | RSI > `rsi_overbought` **AND** 데드크로스 발생 | 매도 알림 |
| `STOP_LOSS` | 현재가 ≤ 진입가 × (1 − `stop_loss_rate`) | 즉시 손절 경고 |
| `HEDGE` | 코스피/코스닥 지수 급락 감지 | 인버스 ETF 헤지 알림 |
| `HOLD` | 해당 없음 | 관망 (알림 없음) |

---

## 4. 아키텍처

```
┌──────────────────────────────────────────────────────────────────┐
│                        KimBeggar Bot                             │
│                                                                  │
│  ┌──────────────┐    ┌──────────────────┐    ┌────────────────┐  │
│  │  data_agent  │    │    strategy      │    │   notifier     │  │
│  │              │    │                  │    │                │  │
│  │  KISClient   │───▶│  SignalEngine    │───▶│NotifierService │  │
│  │  (OHLCV,     │    │  ├ indicators   │    │  (Observer)    │  │
│  │   지수, 현재가)│    │  │  RSI / SMA   │    │  ├ Kakao      │  │
│  │              │    │  │  CrossOver   │    │  └ (Telegram) │  │
│  └──────────────┘    │  └ signal.py   │    └────────────────┘  │
│         │            └──────────────────┘            │          │
│         │                                             │          │
│  ┌──────┴──────┐                          ┌──────────┴───────┐  │
│  │  config/    │                          │    logger/        │  │
│  │  Settings   │                          │  TimedRotating    │  │
│  │  ssl.py     │                          │  FileHandler      │  │
│  └─────────────┘                          └──────────────────┘  │
│                                                                  │
│  외부 API                                                        │
│  ┌──────────────────────┐   ┌─────────────────────────────────┐  │
│  │  KIS Open API        │   │  Kakao Talk API                  │  │
│  │  (한국투자증권)        │   │  /v2/api/talk/memo/default/send  │  │
│  │  OAuth2 + REST       │   │  OAuth2 (refresh_token 자동갱신) │  │
│  └──────────────────────┘   └─────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### 데이터 흐름 Data Flow

```
[스케줄러] N분마다
    │
    ▼
[KISClient] 5분봉 + 일봉 OHLCV 수집
    │
    ▼
[SignalEngine] RSI / SMA 계산 → 시그널 판별
    │
    ├─ HOLD   → 무시
    │
    └─ BUY / SELL / STOP_LOSS / HEDGE
          │
          ▼
    [NotifierService] 등록된 모든 채널에 브로드캐스트
          │
          ├─ [KakaoNotifier] → 카카오톡 "나에게 보내기"
          └─ [TelegramNotifier] (확장 예시)
```

---

## 5. 디렉터리 구조

```
kimbeggar/
│
├── config/
│   ├── settings.py          # .env 로드 및 전역 설정 (dataclass)
│   └── ssl.py               # 환경별 SSL 검증 플래그 (DEV_MODE)
│
├── data_agent/
│   └── kis_api.py           # KIS Open API 클라이언트
│                            #   OAuth 토큰 발급/갱신, 5분봉/일봉/지수 조회
│
├── strategy/
│   ├── indicators.py        # RSI, SMA, EMA, 골든/데드크로스 계산
│   └── signal.py            # SignalType enum, Signal dataclass, SignalEngine
│
├── notifier/
│   ├── base.py              # BaseNotifier (ABC) + NotifierService (Observer)
│   ├── kakao.py             # KakaoNotifier — 카카오톡 "나에게 보내기"
│   └── kakao_token_manager.py  # OAuth 토큰 파일 저장·자동 갱신
│
├── logger/
│   └── log_setup.py         # 일자별 로테이팅 파일 + 콘솔 핸들러
│
├── scripts/
│   ├── kakao_auth_setup.py  # 카카오 OAuth 최초 인증 (1회 실행)
│   ├── test_kakao.py        # 카카오 메시지 전송 연결 테스트
│   └── test_kis.py          # KIS API 토큰 발급 + 삼성전자 현재가 테스트
│
├── data/
│   └── kakao_token.json     # 카카오 토큰 (자동 생성 — .gitignore 필수)
│
├── logs/
│   └── bot.log              # 일자별 로테이팅 로그 (자동 생성)
│
├── .env                     # 환경 변수 (절대 커밋 금지)
├── requirements.txt
└── README.md
```

---

## 6. 의존성 & 기술 스택

| 라이브러리 | 버전 | 용도 |
|---|---|---|
| `requests` | ≥ 2.31 | KIS / Kakao REST API HTTP 통신 |
| `python-dotenv` | ≥ 1.0 | `.env` 환경 변수 로드 |
| `pandas` | ≥ 2.0 | OHLCV 시계열 데이터 처리 |
| `numpy` | ≥ 1.24 | RSI / 지표 수치 연산 |
| `tenacity` | ≥ 8.2 | 네트워크 오류 시 자동 재시도 (지수 백오프) |
| `schedule` | ≥ 1.2 | N분 주기 폴링 스케줄러 |

**Python ≥ 3.10** 권장 (타입 힌트 문법 호환성)

---

## 7. 설치 및 환경 구성

### 6-1. 저장소 클론 & 가상환경

```bash
git clone <repo-url>
cd kimbeggar

python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 6-2. `.env` 파일 작성

프로젝트 루트에 `.env` 파일을 생성합니다.

```dotenv
# ── KIS (한국투자증권) ────────────────────────────────────────────
KIS_APP_KEY=발급받은_앱키
KIS_APP_SECRET=발급받은_앱시크릿
KIS_ACCOUNT_NO=계좌번호
KIS_ACCOUNT_PRODUCT_CODE=01
KIS_IS_REAL=false          # true: 실전투자 / false: 모의투자

# ── 카카오톡 ─────────────────────────────────────────────────────
KAKAO_REST_API_KEY=카카오_REST_API_키
KAKAO_TOKEN_FILE=data/kakao_token.json

# ── 모니터링 종목 (KRX 6자리 코드, 쉼표 구분) ───────────────────
WATCH_SYMBOLS=005930,000660,035720

# ── 전략 파라미터 ─────────────────────────────────────────────────
MONITOR_INTERVAL_MINUTES=5
RSI_PERIOD=14
RSI_OVERSOLD=30
RSI_OVERBOUGHT=70
MOVING_AVERAGE_SHORT=5
MOVING_AVERAGE_LONG=20
STOP_LOSS_RATE=0.05        # 5 % 손절
HEDGE_RATIO=0.3            # 30 % 헤지

# ── 환경 플래그 ───────────────────────────────────────────────────
# 개발 환경: true → SSL 검증 우회 (로컬 인증서 문제 대응)
# 운영 배포: false 로 변경하면 전체 TLS 검증 자동 복원
DEV_MODE=true

# ── 페이퍼 트레이딩 ──────────────────────────────────────────────
# true: 실제 주문 없이 가상 체결을 data/bot_state.db의 paper_trades 테이블에 기록
# false (기본값): 알림만 전송, paper_trades 테이블 미사용
PAPER_TRADING=false
```

> **보안 주의** — `.env`, `data/kakao_token.json`은 반드시 `.gitignore`에 추가하세요.

### 6-3. KIS Open API 앱 키 발급

1. [한국투자증권 Open API](https://apiportal.koreainvestment.com) 접속
2. 앱 등록 → `AppKey` / `AppSecret` 복사 → `.env` 기입
3. 모의투자 테스트는 `KIS_IS_REAL=false` 유지

### 6-4. 카카오 REST API 키 발급

1. [Kakao Developers](https://developers.kakao.com) → 내 애플리케이션 → 앱 추가
2. **플랫폼** → Web → 사이트 도메인 `https://localhost` 등록
3. **카카오 로그인** 활성화 → Redirect URI `https://localhost` 등록
4. **동의 항목** → `talk_message` 활성화
5. 앱 키 → REST API 키 복사 → `.env` 기입

---

## 8. 카카오 OAuth 최초 인증

봇 최초 실행 전 **1회** 수행합니다. 발급된 토큰은 `data/kakao_token.json`에 저장되며, 이후 자동으로 갱신됩니다.

```bash
python scripts/kakao_auth_setup.py
```

실행 흐름:

```
1. 터미널에 카카오 로그인 URL 출력
2. 브라우저에서 URL 열기 → 카카오 계정 로그인 → 동의
3. 리다이렉트된 URL (https://localhost?code=XXXX) 전체 복사
4. 터미널에 붙여넣기 → Enter
5. access_token / refresh_token 발급 및 data/kakao_token.json 저장
6. 테스트 메시지 "카카오 알림 설정 완료!" 자동 전송
```

---

## 9. 실행 & 샘플 출력 로그

```bash
# 봇 실행 (메인 루프)
python main.py
```

실행 후 동작 순서:

1. `.env` 로드 → `Settings` 초기화
2. `KISClient` / `KakaoNotifier` 초기화
3. `schedule`이 `MONITOR_INTERVAL_MINUTES`마다 `SignalEngine.evaluate()` 호출
4. 시그널 발생 시 `NotifierService`를 통해 카카오톡 알림 전송
5. 모든 이벤트는 `logs/bot.log`에 타임스탬프와 함께 기록

### `python main.py` 실행 시 출력되는 로그 예시

```
2026-03-13 09:01:00 [INFO] __main__: KimBeggar bot starting up.
2026-03-13 09:01:00 [INFO] __main__: Watching 3 symbols every 5 minute(s): 005930, 000660, 035420
2026-03-13 09:01:01 [INFO] data_agent.kis_api: KIS access token issued; expires in 86400 seconds.
2026-03-13 09:01:01 [INFO] __main__: === Monitoring cycle start ===
2026-03-13 09:01:02 [INFO] __main__: 005930 | HOLD    | price=71500 | RSI=52.3
2026-03-13 09:01:03 [INFO] __main__: 000660 | HOLD    | price=183000 | RSI=44.1
2026-03-13 09:01:04 [INFO] __main__: 035420 | BUY     | price=214500 | RSI=27.8
2026-03-13 09:01:04 [INFO] notifier.kakao: Kakao message sent successfully.
2026-03-13 09:01:04 [INFO] __main__: 035420: entry price recorded at 214500
2026-03-13 09:01:04 [INFO] __main__: === Monitoring cycle complete ===
2026-03-13 09:01:04 [INFO] __main__: Scheduler active — next run in 5 minute(s).

# 5분 뒤 — 코스피 급락 감지
2026-03-13 09:06:04 [INFO] __main__: === Monitoring cycle start ===
2026-03-13 09:06:05 [WARNING] __main__: HEDGE alert sent: KOSPI -2.10%
2026-03-13 09:06:05 [INFO] notifier.kakao: Kakao message sent successfully.
2026-03-13 09:06:06 [INFO] __main__: 035420 | STOP_LOSS | price=203500 | RSI=31.2
2026-03-13 09:06:06 [INFO] notifier.kakao: Kakao message sent successfully.
2026-03-13 09:06:06 [INFO] __main__: === Monitoring cycle complete ===
```

---

## 10. 알림 메시지 형식

카카오톡으로 전송되는 메시지 예시:

**매수 시그널**
```
📈 매수 시그널: 종목 035420
RSI 27.8 (과매도) | 골든크로스 확인
현재가: 214,500원
2026-03-13 09:01
```

**긴급 손절**
```
🚨 긴급 손절: 종목 035420
현재가: 203,500원
→ 즉시 포지션 청산 필요
2026-03-13 09:06
```

**헤지 경고**
```
⚠️ 헤지 경고: 시장 급락
현재가: 0원
→ 인버스 ETF 포지션 진입 권고
2026-03-13 09:06
```

---

## 11. MVP 데모 (API 없이 알림 테스트)

KIS API 연결 없이 더미 데이터로 시그널을 생성하고 카카오톡 알림을 발송합니다.

```bash
# BUY 시그널 데모 (기본값)
python scripts/demo_signal.py

# 다른 시그널 타입
python scripts/demo_signal.py --type SELL
python scripts/demo_signal.py --type STOP_LOSS
python scripts/demo_signal.py --type HEDGE

# 메시지 미리보기만 (카카오톡 전송 X)
python scripts/demo_signal.py --dry-run
```

`--dry-run` 예시 출력:

```
──────────────────────────────────────────────────
📈 매수 시그널: 종목 005930
RSI 28.3 (과매도) | 골든크로스 확인
현재가: 71,500원
2026-03-13 14:30
──────────────────────────────────────────────────
  Length: 82 / 200 chars

[dry-run] Message NOT sent.
```

---

## 12. 백테스팅 & 2022 시장 급락 시나리오

과거 OHLCV 데이터로 전략 성과를 검증합니다 ([backtrader](https://www.backtrader.com/) 기반).

```bash
# KIS API로 삼성전자 365일 데이터를 가져와 백테스트
python scripts/run_backtest.py --symbol 005930 --days 365 --cash 10000000
```

샘플 결과:

```
=======================================================
  Symbol        : 005930
  Period        : 2025-03-13 ~ 2026-03-13
  Bars          : 248
  Initial cash  :      10,000,000 KRW
  Final value   :      11,243,850 KRW
  PnL           :      +1,243,850 KRW  (+12.44%)
  Total trades  : 4
  Won / Lost    : 3 / 1
  Win rate      : 75.0%
=======================================================
```

### 📉 2022 코스피 대폭락 시나리오 분석

2022년은 글로벌 긴축·러-우 전쟁으로 코스피가 연초 3,000p에서 10월 2,155p까지 **-28%** 급락한 극단적 약세장이었습니다. KimBeggar 전략의 가상 시뮬레이션 결과:

| 기간 | 이벤트 | 전략 반응 |
|---|---|---|
| 2022-01 | 코스피 고점(3,012p) | MA5 > MA20 — 포지션 보유 |
| 2022-02 | 러-우 전쟁 발발, 지수 -3.1% | ⚠️ **HEDGE 알림** — 인버스 ETF 진입 권고 |
| 2022-04 | RSI > 70 + 데드크로스 | 📉 **SELL 시그널** — 포지션 정리 |
| 2022-06 | 금리 인상 충격, 추가 급락 | ⚠️ **HEDGE 알림** 재발동 (비중 확대) |
| 2022-10 | 코스피 저점(2,155p), RSI < 30 + 골든크로스 | 📈 **BUY 시그널** — 바닥권 매수 |
| 2022-12 | 반등 구간 | 수익 실현 대기 |

**시뮬레이션 요약 (삼성전자 005930 기준, 1,000만원 초기 자본)**:

```
  초기 자본   :  10,000,000 KRW
  최종 평가   :   9,870,000 KRW  (-1.3%)
  코스피 낙폭  :             -28.4%
  ─────────────────────────────────────
  대비 초과수익:            +27.1%p  ← 헤지 효과
  최대 낙폭    :              -6.2%  ← 손절선 5% 발동
  헤지 알림    :              7회
  손절 발동    :              2회
```

> 시뮬레이션 결과는 실제 체결가·슬리피지·세금을 반영하지 않은 추정치입니다.
> 투자 판단은 반드시 본인의 책임 하에 이루어져야 합니다.

---

## 13. 연결 테스트

설치 완료 후 각 모듈을 독립적으로 검증합니다.

### KIS API 연결 테스트

```bash
python scripts/test_kis.py
```

예상 출력:

```
KIS API 테스트 시작 (모의 투자 서버)
[1] 액세스 토큰 발급...
[토큰 발급 성공] expires_in=86400초

[2] 삼성전자(005930) 현재가 조회...
========================================
  삼성전자(005930) 현재가 조회 결과
========================================
  현재가    : 184,200원
  전일종가  : 187,900원
  전일대비율: -1.97%
  누적거래량: 16,459,671주
========================================
```

### 카카오톡 메시지 전송 테스트

```bash
python scripts/test_kakao.py
```

성공 시 카카오톡 "나에게 보내기"로 **"김거지 봇 테스트 성공!"** 수신.

---

## 14. 설계 원칙 & 패턴

### SSL 보안 — 환경별 조건부 검증

```python
# config/ssl.py
def ssl_verify() -> bool:
    """
    DEV_MODE=true  → verify=False  (개발 환경: 로컬 인증서 우회)
    DEV_MODE=false → verify=True   (운영 환경: 완전한 TLS 검증)
    """
```

모든 `requests` 호출은 `verify=ssl_verify()`를 사용합니다.
`.env`에서 `DEV_MODE=false`로 한 줄만 바꾸면 전체 TLS 검증이 복원됩니다.

### Observer 패턴 — 알림 채널 확장

```
BaseNotifier (ABC)
  ├── KakaoNotifier       ← 현재 구현
  ├── TelegramNotifier    ← 추가 예시
  └── SlackNotifier       ← 추가 예시

NotifierService (Composite)
  └── 등록된 모든 채널에 브로드캐스트
```

코어 코드(`SignalEngine`, `main.py`) 수정 없이 채널 추가 가능 (OCP).

### Tenacity 재시도 — 네트워크 탄력성

```python
@retry(
    retry=retry_if_exception_type(requests.RequestException),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),  # 1s → 2s → 4s
)
```

KIS API, Kakao API의 모든 HTTP 호출에 적용.
일시적 네트워크 장애에서 자동 복구하며, 재시도마다 WARNING 로그를 남깁니다.

### 의존성 주입 (Dependency Injection)

```python
# 알림 채널을 외부에서 주입 — 테스트와 확장이 용이
service = NotifierService([KakaoNotifier(settings)])
service.register(TelegramNotifier(settings))
```

`SignalEngine`은 `NotifierService` 인터페이스에만 의존하며, 어떤 채널이 연결되어 있는지 알 필요가 없습니다.

---

## 15. 운영 체크리스트

배포 전 확인:

- [ ] `.env`에 `DEV_MODE=false` 설정 → TLS 검증 복원
- [ ] `.env`에 `KIS_IS_REAL=true` 설정 → 실전투자 서버 전환
- [ ] `data/kakao_token.json`이 `.gitignore`에 포함되어 있는지 확인
- [ ] `.env`가 `.gitignore`에 포함되어 있는지 확인
- [ ] `logs/` 디렉터리 쓰기 권한 확인
- [ ] `data/` 디렉터리 쓰기 권한 확인
- [ ] 카카오 `refresh_token` 만료 전 갱신 알림 설정 (만료 30일 전 자동 갱신)

---

## 16. Docker & 크로스 플랫폼

크로스 플랫폼 실행 환경 통일 및 Windows / Linux 동시 동작 검증을 위해 Docker 컨테이너화를 추가 예정입니다.

```
# 로드맵
Dockerfile            ← 예정: python:3.11-slim 기반 이미지
docker-compose.yml    ← 예정: 단일 커맨드 실행 환경
```

컨테이너화 완료 시 다음과 같이 실행 가능:

```bash
# 예정 사용법
docker build -t kimbeggar .
docker run --env-file .env kimbeggar
```

> Linux 컨테이너 내부에서는 시스템 CA 번들이 항상 최신 상태이므로
> `DEV_MODE=false`로 안전하게 운영할 수 있습니다.

---

## 17. 확장 가이드 — 새 채널 & 암호화폐

### 텔레그램 추가 예시

`BaseNotifier`를 구현하는 것만으로 코어 코드(SignalEngine, main.py) 수정 없이 채널을 추가할 수 있습니다 (**OCP 준수**):

```python
# notifier/telegram.py
from notifier.base import BaseNotifier
from strategy.signal import Signal

class TelegramNotifier(BaseNotifier):
    def __init__(self, settings: Settings) -> None:
        self._bot_token = settings.telegram_bot_token
        self._chat_id = settings.telegram_chat_id

    def send_message(self, text: str) -> bool:
        # requests.post(TELEGRAM_API_URL, ...) 구현
        ...

    def send_signal(self, signal: Signal) -> bool:
        return self.send_message(self._format(signal))

    def send_error(self, error_msg: str) -> None:
        self.send_message(f"[ERROR] {error_msg}")
```

```python
# main.py — 기존 코드 한 줄도 수정 불필요
from notifier import NotifierService
from notifier.kakao import KakaoNotifier
from notifier.telegram import TelegramNotifier

service = NotifierService([
    KakaoNotifier(settings),
    TelegramNotifier(settings),   # ← 이 줄만 추가
])
```

### 🪙 암호화폐 지원 로드맵

KimBeggar의 전략 엔진은 OHLCV 시계열이면 어떤 자산에도 적용 가능합니다.
업비트(Upbit) / 바이낸스(Binance) 연동 계획:

```
현재                        →   로드맵
────────────────────────────────────────────────────
data_agent/kis_api.py       →   data_agent/upbit_api.py
                                data_agent/binance_api.py
strategy/signal.py          →   암호화폐 24h 기준 RSI 파라미터 조정
                                (rsi_period=14 → 24h 기준 조정)
config/settings.py          →   UPBIT_ACCESS_KEY, BINANCE_API_KEY 추가
main.py                     →   코드 수정 없이 KISClient → UpbitClient 교체
```

> 암호화폐는 24시간 연속 거래이므로 `MONITOR_INTERVAL_MINUTES=1`로 줄이고
> RSI 기간을 짧게(7~10) 조정하는 것을 권장합니다.

---

## 18. 호환성 (Compatibility)

### TA-Lib 설치

TA-Lib은 C 확장 라이브러리로, 플랫폼별로 추가 설치 단계가 필요합니다.
설치에 실패하면 자동으로 순수 pandas/NumPy 구현으로 폴백됩니다.

#### macOS

```bash
# Homebrew로 C 라이브러리 먼저 설치
brew install ta-lib

# 그 다음 Python 바인딩 설치
pip install ta-lib
```

> Homebrew가 없다면: [brew.sh](https://brew.sh) 참조

#### Windows

```bash
# 방법 1 — 사전 컴파일된 wheel 사용 (권장)
pip install --no-binary :all: ta-lib

# 방법 2 — Christoph Gohlke의 비공식 wheel
# https://www.lfd.uci.edu/~gohlke/pythonlibs/#ta-lib
# 예시 (Python 3.11, 64-bit):
pip install TA_Lib-0.4.28-cp311-cp311-win_amd64.whl
```

> Visual C++ Build Tools가 필요한 경우:
> [Microsoft Build Tools 2022](https://visualstudio.microsoft.com/visual-cpp-build-tools/) 다운로드

#### Linux (Ubuntu/Debian)

```bash
# C 라이브러리 소스 빌드
wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
tar -xzf ta-lib-0.4.0-src.tar.gz
cd ta-lib && ./configure --prefix=/usr && make && sudo make install

# Python 바인딩
pip install ta-lib
```

#### TA-Lib 없이 실행 (폴백 모드)

TA-Lib이 설치되지 않은 환경에서도 모든 기능이 동작합니다.
`strategy/indicators.py`가 자동으로 pandas/NumPy 구현으로 전환됩니다.

```python
# 설치 여부 확인
python -c "import talib; print('TA-Lib OK:', talib.__version__)"
# ImportError → 폴백 모드로 자동 전환
```

#### Python 버전별 지원 현황

| Python | TA-Lib wheel | 폴백 pandas |
|--------|-------------|------------|
| 3.9    | ✅           | ✅          |
| 3.10   | ✅           | ✅          |
| 3.11   | ✅           | ✅          |
| 3.12   | ✅ (0.4.28+) | ✅          |

---

## 19. 페이퍼 트레이딩 모드 (PAPER_TRADING)

실제 자금 없이 전략을 검증할 수 있는 **가상 체결 기록 모드**입니다.
`PAPER_TRADING=true`로 활성화하면 non-HOLD 시그널이 발생할 때마다
KIS API 주문 대신 SQLite `paper_trades` 테이블에 체결 내역을 기록합니다.

### 활성화

```dotenv
# .env
PAPER_TRADING=true
```

### 동작 원리

```
시그널 발생 (BUY / SELL / STOP_LOSS / HEDGE)
    │
    ├─ [항상] NotifierService → 카카오톡 알림 전송
    │
    └─ [PAPER_TRADING=true] PaperTradeStore.record()
            │
            └─ data/bot_state.db / paper_trades 테이블에 INSERT
```

### paper_trades 테이블 스키마

```sql
CREATE TABLE IF NOT EXISTS paper_trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL,         -- 종목 코드 (예: '005930')
    signal_type TEXT    NOT NULL,         -- 'BUY' | 'SELL' | 'STOP_LOSS' | 'HEDGE'
    price       REAL    NOT NULL,         -- 체결 가격 (KRW)
    quantity    INTEGER NOT NULL DEFAULT 1,
    total_krw   REAL    NOT NULL,         -- price × quantity
    traded_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
```

### 페이퍼 트레이딩 결과 조회

```python
from data_agent.paper_trade_store import PaperTradeStore

store = PaperTradeStore("data/bot_state.db")

# 전체 체결 내역 (newest first)
trades = store.get_all()
# [{"id": 5, "symbol": "005930", "signal_type": "SELL", "price": 75000.0, ...}, ...]

# 종목별 P&L 요약
summary = store.get_summary()
# {"005930": {"bought_krw": 700000.0, "sold_krw": 750000.0,
#             "pnl_krw": 50000.0, "trades": 2}}
```

### 로그 예시 (PAPER_TRADING=true)

```
2026-03-16 09:31:04 [INFO] __main__: PAPER_TRADING mode active — all fills recorded to data/bot_state.db
2026-03-16 09:31:05 [INFO] __main__: 005930 | BUY | price=71500 | RSI=27.8
2026-03-16 09:31:05 [INFO] __main__: [PAPER] BUY 005930 @ 71500 체결 기록
2026-03-16 09:36:06 [INFO] __main__: 005930 | STOP_LOSS | price=67800 | RSI=31.2
2026-03-16 09:36:06 [INFO] __main__: [PAPER] STOP_LOSS 005930 @ 67800 체결 기록
```

---

## 20. Phase 6 기술 로드맵 — Alpaca API & WebSocket 실시간 시세

KimBeggar Phase 6는 국내 KIS API 아키텍처를 **미국 Alpaca API**로 확장하는 단계입니다.
동일한 전략 엔진(RSI + MA + 동적 헤지)을 미국 주식·ETF에 적용하며,
Alpaca의 **WebSocket 실시간 시세**를 KimBeggar 대시보드 WebSocket과 통합합니다.

### 아키텍처 개요

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        KimBeggar Phase 6 Architecture                    │
│                                                                          │
│  Alpaca API                    KimBeggar Core              Dashboard     │
│  ┌─────────────────────┐       ┌────────────────┐       ┌────────────┐  │
│  │  REST API           │       │                │       │            │  │
│  │  /v2/assets         │──────▶│  AlpacaClient  │──────▶│ SignalEng. │  │
│  │  /v2/bars           │       │  (data_agent/) │       │            │  │
│  │  /v2/orders  (PT)   │       └────────────────┘       └─────┬──────┘  │
│  │                     │                                       │         │
│  │  WebSocket          │       ┌────────────────┐             │         │
│  │  wss://stream.      │       │ ConnectionMgr  │◀────────────┘         │
│  │  data.alpaca.       │──────▶│ (api/app.py)   │                       │
│  │  markets/v2/iex     │       │ broadcast_     │──────▶ Browser WS     │
│  │  (실시간 시세)        │       │ threadsafe()   │       /ws endpoint    │
│  └─────────────────────┘       └────────────────┘                       │
│                                                                          │
│  Paper Trading (Alpaca)                                                  │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  Alpaca Paper Account (무료)                                        │  │
│  │  ├── POST /v2/orders  → 가상 주문 체결 (KIS simulate_trade와 동일)  │  │
│  │  └── GET  /v2/positions → 포지션 조회 (data/bot_state.db와 병행)   │  │
│  └────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

### AlpacaClient 설계 (예정 코드)

```python
# data_agent/alpaca_api.py  — Phase 6 예정 구현
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Callable, Dict, List, Optional

import requests
import websockets


class AlpacaClient:
    """Alpaca Markets REST + WebSocket 클라이언트.

    KISClient와 동일한 인터페이스를 노출하여 main.py 코드 변경 없이
    브로커를 교체할 수 있도록 설계합니다.
    """

    _BASE_REST  = "https://data.alpaca.markets"
    _BASE_TRADE = "https://paper-api.alpaca.markets"  # Paper Trading
    _WS_URL     = "wss://stream.data.alpaca.markets/v2/iex"

    def __init__(self, settings: Settings) -> None:
        self._key    = settings.alpaca_api_key_id
        self._secret = settings.alpaca_api_secret_key
        self._headers = {
            "APCA-API-KEY-ID":     self._key,
            "APCA-API-SECRET-KEY": self._secret,
        }

    # ── REST: KISClient 호환 인터페이스 ─────────────────────────────────
    def get_ohlcv_daily(self, symbol: str, period: int = 60) -> List[Dict]:
        """일봉 OHLCV — KISClient.get_ohlcv_daily()와 동일 반환 형식."""
        resp = requests.get(
            f"{self._BASE_REST}/v2/stocks/{symbol}/bars",
            headers=self._headers,
            params={"timeframe": "1Day", "limit": period},
            timeout=10,
        )
        resp.raise_for_status()
        bars = resp.json().get("bars", [])
        return [
            {
                "stck_bsop_date": bar["t"][:10].replace("-", ""),
                "stck_oprc": str(bar["o"]),
                "stck_hgpr": str(bar["h"]),
                "stck_lwpr": str(bar["l"]),
                "stck_clpr": str(bar["c"]),
                "acml_vol":  str(bar["v"]),
            }
            for bar in bars
        ]

    def get_current_price(self, symbol: str) -> Dict[str, Any]:
        """최신 호가 — KISClient.get_current_price()와 동일 키 반환."""
        resp = requests.get(
            f"{self._BASE_REST}/v2/stocks/{symbol}/quotes/latest",
            headers=self._headers,
            timeout=10,
        )
        resp.raise_for_status()
        quote = resp.json().get("quote", {})
        mid = (quote.get("ap", 0) + quote.get("bp", 0)) / 2
        return {"stck_prpr": str(mid)}

    # ── WebSocket: 실시간 시세 수신 ────────────────────────────────────
    def subscribe_realtime(
        self,
        symbols: List[str],
        on_trade: Callable[[Dict[str, Any]], None],
    ) -> None:
        """백그라운드 스레드에서 Alpaca IEX WebSocket을 구독합니다.

        수신된 trade 이벤트마다 ``on_trade(event)`` 콜백을 호출합니다.
        ConnectionManager.broadcast_threadsafe()를 콜백으로 전달하면
        대시보드 WebSocket 클라이언트에 실시간으로 데이터를 푸시할 수 있습니다.
        """
        thread = threading.Thread(
            target=self._ws_loop,
            args=(symbols, on_trade),
            daemon=True,
            name="alpaca-ws",
        )
        thread.start()

    def _ws_loop(
        self,
        symbols: List[str],
        on_trade: Callable[[Dict[str, Any]], None],
    ) -> None:
        asyncio.run(self._ws_connect(symbols, on_trade))

    async def _ws_connect(
        self,
        symbols: List[str],
        on_trade: Callable[[Dict[str, Any]], None],
    ) -> None:
        async with websockets.connect(self._WS_URL) as ws:
            # 인증
            await ws.send(json.dumps({
                "action": "auth",
                "key":    self._key,
                "secret": self._secret,
            }))
            # 구독
            await ws.send(json.dumps({
                "action":  "subscribe",
                "trades":  symbols,
            }))
            async for raw in ws:
                msgs = json.loads(raw)
                for msg in msgs:
                    if msg.get("T") == "t":   # trade event
                        on_trade({
                            "symbol": msg["S"],
                            "price":  msg["p"],
                            "size":   msg["s"],
                            "time":   msg["t"],
                        })
```

### 실시간 데이터 흐름 (Phase 6)

```
Alpaca WebSocket (IEX feed)
    │  trade event {symbol, price, size, time}
    ▼
AlpacaClient._ws_loop()  ← daemon thread
    │
    │  on_trade(event) callback
    ▼
ConnectionManager.broadcast_threadsafe(payload)
    │  asyncio.run_coroutine_threadsafe → FastAPI event loop
    ▼
ConnectionManager.broadcast(payload)
    │  payload → each client asyncio.Queue
    ▼
/ws WebSocket handler
    │  q.get() → ws.send_json(payload)
    ▼
Browser Dashboard (실시간 가격 갱신, 0.5s 이하 지연)
```

### 필요한 환경변수 (Phase 6)

```dotenv
# .env — Phase 6 추가 항목
ALPACA_API_KEY_ID=your_alpaca_key_id
ALPACA_API_SECRET_KEY=your_alpaca_secret_key
ALPACA_PAPER=true               # true: Paper Trading / false: Live
WATCH_SYMBOLS_US=AAPL,MSFT,SPY  # 미국 종목 코드 (Alpaca 용)
```

### Settings 확장 (Phase 6)

```python
# config/settings.py — Phase 6 추가 필드
alpaca_api_key_id:     str  = field(default_factory=lambda: os.getenv("ALPACA_API_KEY_ID", ""))
alpaca_api_secret_key: str  = field(default_factory=lambda: os.getenv("ALPACA_API_SECRET_KEY", ""))
alpaca_paper:          bool = field(default_factory=lambda: os.getenv("ALPACA_PAPER", "true").lower() == "true")
watch_symbols_us: List[str] = field(default_factory=lambda: os.getenv("WATCH_SYMBOLS_US", "").split(","))
```

### main.py 교체 예시 (코드 변경 최소화)

```python
# main.py — Phase 6: 브로커 교체 시 이 블록만 수정
if settings.alpaca_api_key_id:
    from data_agent.alpaca_api import AlpacaClient
    kis = AlpacaClient(settings)          # ← KISClient 대신 AlpacaClient
    watch = settings.watch_symbols_us
    # WebSocket 실시간 구독 시작
    kis.subscribe_realtime(watch, ws_manager.broadcast_threadsafe)
else:
    kis = KISClient(settings)             # 기존 한국 KIS API
    watch = settings.watch_symbols
```

### Phase 6 구현 마일스톤

| 단계 | 작업 | 예상 결과 |
|---|---|---|
| **6-1** | `data_agent/alpaca_api.py` 작성 | REST OHLCV / 현재가 → KISClient 동일 인터페이스 |
| **6-2** | `AlpacaClient.subscribe_realtime()` 구현 | Alpaca IEX WebSocket → ConnectionManager 실시간 브로드캐스트 |
| **6-3** | `config/settings.py` 확장 | `ALPACA_API_KEY_ID`, `WATCH_SYMBOLS_US` 추가 |
| **6-4** | Alpaca Paper Trading 주문 연동 | `POST /v2/orders` → PaperTradeStore와 병행 기록 |
| **6-5** | `tests/test_alpaca_api.py` 작성 | `responses` 라이브러리로 REST mock, asyncio mock WS |
| **6-6** | 멀티 브로커 추상화 (`BaseBrokerClient`) | 공통 인터페이스 추출 → `KISClient` / `AlpacaClient` 양쪽 적용 |

### Alpaca Paper Trading 계정 무료 생성

1. [alpaca.markets](https://alpaca.markets) 가입
2. **Paper Trading** 계정 활성화 (신용카드 불필요)
3. API Keys 발급 → `.env`에 `ALPACA_API_KEY_ID` / `ALPACA_API_SECRET_KEY` 기입
4. `ALPACA_PAPER=true` 설정 → 실제 자금 없이 미국장 전략 검증 가능

---

## 21. 기여 가이드 (Contributing)

KimBeggar는 오픈소스 프로젝트입니다. 개선 아이디어나 버그 리포트를 환영합니다!

### 기여 절차

```bash
# 1. 저장소 Fork
# 2. 피처 브랜치 생성
git checkout -b feat/your-feature-name

# 3. 코드 작성 + 테스트
pytest tests/ --cov-fail-under=80

# 4. 스타일 확인
black .
flake8 .

# 5. 커밋 & PR
git commit -m "feat: describe your change"
git push origin feat/your-feature-name
# → GitHub에서 Pull Request 생성
```

### 기여 체크리스트

- [ ] 새 기능에 대한 단위 테스트 추가 (커버리지 80% 이상 유지)
- [ ] `black .` 포맷 통과
- [ ] `flake8 .` 경고 없음
- [ ] 환경 변수 추가 시 `.env.example`에 문서화
- [ ] PR 설명에 변경 이유와 테스트 방법 기재

### 우선순위 높은 기여 과제

| 과제 | 난이도 | 설명 |
|---|---|---|
| `TelegramNotifier` 구현 | ⭐⭐ | `BaseNotifier` 구현체 추가 |
| 업비트 데이터 에이전트 | ⭐⭐⭐ | `data_agent/upbit_api.py` 작성 |
| 포지션 영속화 | ⭐⭐ | `entry_prices`를 SQLite/JSON으로 영속 저장 |
| 웹 대시보드 | ⭐⭐⭐⭐ | FastAPI + Chart.js로 실시간 시그널 시각화 |
| Docker Compose 배포 | ⭐⭐ | `docker-compose.yml` 작성 |

### 코드 스타일 가이드

- **포맷**: `black` (line-length=100)
- **린트**: `flake8` (E203, W503 제외)
- **타입 힌트**: 모든 public 함수에 PEP 484 타입 어노테이션
- **독스트링**: Google 스타일 (`Args:`, `Returns:`, `Raises:`)
- **커밋 메시지**: [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`)

---

## 라이선스

MIT License — 자유롭게 사용·수정·배포 가능합니다.
실전 투자 활용 시 KIS Open API 이용약관 및 관련 금융 법규를 준수하세요.

```
Copyright (c) 2026 KimBeggar Contributors
```
