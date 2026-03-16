# 김거지: 퀀텀 점프 (KimBeggar: Quantum Jump)

> **"거지의 삶을 단계적으로 벗어나는 게 아니라,**
> **옵션의 비대칭성(Asymmetric Payoff)과 변동성을 이용해 단숨에 신분 상승(퀀텀 점프)을 노리는 퀀트 전략 봇."**

![CI](https://github.com/yoonjeong2/kimbeggar-bot/actions/workflows/python-app.yml/badge.svg)
[![codecov](https://codecov.io/gh/yoonjeong2/kimbeggar-bot/graph/badge.svg)](https://codecov.io/gh/yoonjeong2/kimbeggar-bot)
![Python](https://img.shields.io/badge/python-3.11-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## 철학: 왜 퀀텀 점프인가?

전통적인 투자 방식은 **선형적 성장**을 추구합니다. 매년 10~20% 수익을 복리로 쌓아 점진적으로 자산을 늘려가는 방식입니다. 그러나 이미 밑바닥에서 시작하는 "거지"에게 선형 성장은 너무 느립니다.

퀀텀 점프 전략의 핵심은 **비대칭성(Asymmetry)** 입니다:

```
일반 주식 매수: 최대 손실 -100%, 최대 수익 +100% (대칭적)
콜 옵션 매수:  최대 손실 -100% (프리미엄만), 최대 수익 이론상 무한대 (비대칭적)
레버리지 ETF:  2배 수익 기대, 단기 급반등에서 폭발적 성과
```

시장이 급락한 후 반등하는 순간(코스피 -12% -> 반등)에 **레버리지 ETF(70%) + 콜 옵션(30%)** 을 조합하면, 소액 자금으로 수배의 수익을 狙할 수 있습니다. 이것이 퀀텀 점프의 본질입니다.

---

## 목차

1. [전략 개요](#1-전략-개요)
2. [핵심 기능](#2-핵심-기능)
3. [아키텍처](#3-아키텍처)
4. [디렉터리 구조](#4-디렉터리-구조)
5. [의존성 & 기술 스택](#5-의존성--기술-스택)
6. [설치 및 환경 구성](#6-설치-및-환경-구성)
7. [카카오 OAuth 최초 인증](#7-카카오-oauth-최초-인증)
8. [실행 & 샘플 출력 로그](#8-실행--샘플-출력-로그)
9. [동적 종목 발굴 (Screener)](#9-동적-종목-발굴-screener)
10. [레버리지+콜 전략 (Quantum Jump)](#10-레버리지콜-전략-quantum-jump)
11. [백테스팅](#11-백테스팅)
12. [웹 대시보드](#12-웹-대시보드)
13. [페이퍼 트레이딩](#13-페이퍼-트레이딩)
14. [설계 원칙 & 패턴](#14-설계-원칙--패턴)
15. [운영 체크리스트](#15-운영-체크리스트)
16. [기여 가이드](#16-기여-가이드)

---

## 1. 전략 개요

KimBeggar: Quantum Jump는 **3개 전략 레이어**를 동시에 운용합니다:

### Layer 1 — 기본 RSI+MA 방어 전략 (항상 활성)

```
┌─────────────────────────────────────────────────────────┐
│  진입 필터   RSI < 30 (과매도) + 골든크로스 -> 매수 시그널  │
│  이익 실현   RSI > 70 (과매수) + 데드크로스 -> 매도 시그널  │
│  손실 차단   현재가 <= 진입가 x (1 - stop_loss_rate)       │
│                                      -> 즉시 손절 알림    │
│  [비상] 헤지  시장 지수 급락 감지 -> 인버스 ETF 헤지 알림   │
└─────────────────────────────────────────────────────────┘
```

### Layer 2 — 자동 종목 발굴 (Screener, 60분 주기)

```
1차: pykrx 낙폭과대 스크리닝 (당일 하락률 상위)
     -- RSI 과매도 반등 후보 자동 발굴
2차: KIS 거래량 순위 API
     -- 유동성 급증 종목 (모멘텀 플레이)
3차: KOSPI 상위 50 폴백
     -- API 장애 / 장 마감 환경 대응
```

### Layer 3 — 레버리지 롱 + 콜 옵션 전략 (LEV_CALL_ENABLED=true)

```
포트폴리오: KODEX 200 레버리지 ETF 70% + 코스피 콜 옵션 30%
진입 조건:  코스피 <= 5,400pt OR (ETF RSI <= 30 AND 골든크로스)
익절 조건:  +20% 도달 -> 50% 부분 청산
청산 조건:  코스피 >= 6,000pt OR 데드크로스
옵션 추가:  VKOSPI 추정치 > 30 -> 공포 극대화 시 옵션 비중 확대
기대 수익:  코스피 +11% 반등 시 -> 전략 수익 ~+39% (마진 3배 가정)
```

---

## 2. 핵심 기능

| 기능 | 설명 | 상태 |
|---|---|---|
| **RSI + MA 시그널** | 과매도/과매수 + 골든/데드크로스 복합 판별 | 구현 완료 |
| **동적 헤지** | ML 변동성 예측(scikit-learn) 기반 인버스 ETF 헤지 비율 자동 산출 | 구현 완료 |
| **자동 종목 발굴** | pykrx 낙폭과대 + KIS 거래량 + 폴백 3단 Screener | 구현 완료 |
| **종목명 표시** | NameResolver: pykrx + 정적맵으로 "삼성전자(005930)" 형태 출력 | 구현 완료 |
| **레버리지+콜 전략** | Black-Scholes 옵션 가격 + VKOSPI 추정 + 포트폴리오 추적 | 구현 완료 |
| **WebSocket 대시보드** | 실시간 이벤트 드리븐 브로드캐스트, 모바일 반응형 UI | 구현 완료 |
| **페이퍼 트레이딩** | 가상 체결을 SQLite에 기록, P&L 집계 | 구현 완료 |
| **백테스팅** | backtrader 기반 과거 데이터 전략 검증 | 구현 완료 |
| **2026 퀀텀점프 시뮬레이션** | 6-Phase GBM 기반 코스피 반등 시나리오 | 구현 완료 |
| **카카오톡 알림** | 매수/매도/손절/헤지/레버리지 이벤트 실시간 알림 | 구현 완료 |
| **Tenacity 재시도** | 네트워크 오류 시 지수 백오프 자동 복구 | 구현 완료 |

---

## 3. 아키텍처

```
┌────────────────────────────────────────────────────────────────────────┐
│                    KimBeggar: Quantum Jump                             │
│                                                                        │
│  ┌──────────────────┐   ┌──────────────────────┐   ┌────────────────┐  │
│  │   data_agent/    │   │      strategy/       │   │   notifier/    │  │
│  │                  │   │                      │   │                │  │
│  │  KISClient       │-->│  SignalEngine        │-->│NotifierService │  │
│  │  (OHLCV, 지수,   │   │  (RSI+MA, 헤지)      │   │  KakaoNotifier │  │
│  │   현재가, 거래량)  │   │                      │   │                │  │
│  │                  │   │  LevCallSignalEngine  │   └────────────────┘  │
│  │  Screener        │   │  (레버리지+콜 전략)    │                       │
│  │  (pykrx + KIS    │   │                      │   ┌────────────────┐  │
│  │   + fallback)    │   │  option_pricing.py   │   │   api/app.py   │  │
│  │                  │   │  (Black-Scholes)      │   │                │  │
│  │  NameResolver    │   │                      │   │  FastAPI       │  │
│  │  (pykrx + 정적맵)│   │  vkospi_estimator.py │   │  WebSocket     │  │
│  │                  │   │  portfolio_tracker.py│   │  Dashboard     │  │
│  └──────────────────┘   └──────────────────────┘   └────────────────┘  │
│                                                                        │
│  ┌──────────────────┐   ┌──────────────────────┐                       │
│  │   backtest/      │   │   data_agent/        │                       │
│  │   runner.py      │   │   position_store.py  │                       │
│  │   lev_call_      │   │   paper_trade_store  │                       │
│  │   strategy.py    │   │   (SQLite)           │                       │
│  └──────────────────┘   └──────────────────────┘                       │
└────────────────────────────────────────────────────────────────────────┘
```

### 스레드 모델

```
main thread          bot-scheduler thread       FastAPI event loop
    │                        │                          │
uvicorn.run()       _run_scheduler()           WebSocket /ws
    │                        │                          │
    │               [60분] screener 갱신         queue.get()
    │               [N분]  run_cycle()          ws.send_json()
    │                        │
    │               broadcast_threadsafe()
    │               └-> run_coroutine_threadsafe -> event loop
```

### 데이터 흐름

```
[스케줄러 N분마다]
    │
    ├── [60분 주기] Screener.get_dynamic_targets()
    │       │ pykrx 낙폭과대 -> KIS 거래량 -> KOSPI 폴백
    │       └-> screener_targets[] 갱신
    │
    ├── KISClient: 코스피 지수 -> HEDGE 체크
    │
    ├── 감시 종목(정적+동적) 순회
    │       KISClient: OHLCV + 현재가
    │       SignalEngine: RSI / MA -> BUY/SELL/STOP_LOSS/HOLD
    │       NotifierService -> 카카오톡
    │       PositionStore -> SQLite
    │       signal_log deque -> WebSocket broadcast
    │
    └── [LEV_CALL_ENABLED=true]
            ETF OHLCV -> VKOSPI 추정 -> BS 옵션 프리미엄
            LevCallSignalEngine -> ENTRY/EXIT/PARTIAL_EXIT/ADD_OPTIONS
            NotifierService -> 카카오톡
```

---

## 4. 디렉터리 구조

```
kimbeggar/
│
├── config/
│   ├── settings.py            # 전역 설정 (dataclass + .env 로드)
│   │                          # lev_call 전략 설정 12개 포함
│   └── ssl.py                 # 환경별 SSL 검증 플래그
│
├── data_agent/
│   ├── kis_api.py             # KIS Open API (OAuth, OHLCV, 지수, 거래량순위)
│   ├── screener.py            # 동적 종목 발굴 (pykrx + KIS + 폴백)
│   ├── name_resolver.py       # 종목코드 -> 한글명 (pykrx + 정적맵)
│   ├── position_store.py      # SQLite 진입가 영속화
│   └── paper_trade_store.py   # SQLite 페이퍼 트레이딩 기록
│
├── strategy/
│   ├── indicators.py          # RSI, SMA, EMA, 골든/데드크로스, 변동성
│   ├── signal.py              # SignalType enum, SignalEngine
│   ├── hedge_logic.py         # 동적 헤지 비율 + ML 변동성 예측
│   ├── option_pricing.py      # Black-Scholes 콜 옵션 (scipy 불필요)
│   ├── vkospi_estimator.py    # 합성 VKOSPI 추정 (20일 롤링 변동성)
│   ├── portfolio_tracker.py   # LevCallPortfolio (ETF+옵션 상태 추적)
│   └── lev_call_signal.py     # LevCallSignalEngine (퀀텀점프 시그널)
│
├── backtest/
│   ├── strategy.py            # backtrader RSI+MA 전략
│   ├── lev_call_strategy.py   # backtrader 레버리지+콜 전략
│   └── runner.py              # BacktestResult, run_backtest(), run_lev_call_backtest()
│
├── api/
│   └── app.py                 # FastAPI 대시보드 + WebSocket 허브
│
├── notifier/
│   ├── base.py                # BaseNotifier (ABC) + NotifierService
│   ├── kakao.py               # 카카오톡 "나에게 보내기"
│   └── kakao_token_manager.py # OAuth 토큰 자동 갱신
│
├── scripts/
│   ├── kakao_auth_setup.py    # 카카오 OAuth 최초 인증 (1회)
│   ├── backtest_2022_crash.py # 2022 코스피 대폭락 시뮬레이션
│   └── backtest_lev_call_2026.py  # 2026 퀀텀점프 시뮬레이션
│
├── tests/                     # pytest 단위 + 통합 테스트 (297개)
│
├── logger/
│   └── log_setup.py           # 일자별 로테이팅 로그
│
├── data/                      # SQLite DB, 카카오 토큰 (자동 생성)
├── logs/                      # bot.log (자동 생성)
├── .env                       # 환경 변수 (절대 커밋 금지)
└── requirements.txt
```

---

## 5. 의존성 & 기술 스택

| 라이브러리 | 버전 | 용도 |
|---|---|---|
| `requests` | >= 2.31 | KIS / Kakao REST API |
| `python-dotenv` | >= 1.0 | `.env` 로드 |
| `pandas` | >= 2.0 | OHLCV 시계열 처리 |
| `numpy` | >= 1.24 | RSI / 지표 수치 연산 |
| `pykrx` | >= 0.6.0 | 낙폭과대 스크리닝, 종목명 조회 |
| `tenacity` | >= 8.2 | 네트워크 오류 자동 재시도 |
| `schedule` | >= 1.2 | N분 주기 폴링 스케줄러 |
| `backtrader` | >= 1.9.78 | 과거 데이터 백테스팅 |
| `fastapi` | >= 0.110 | 웹 대시보드 + REST API |
| `uvicorn` | >= 0.29 | ASGI 서버 |
| `scikit-learn` | >= 1.4 | ML 변동성 예측 (hedge_logic) |
| `TA-Lib` | >= 0.4.28 | 고성능 C 기반 지표 (옵션, 폴백 있음) |

**Python >= 3.10** 권장

---

## 6. 설치 및 환경 구성

### 저장소 클론 & 가상환경

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

### `.env` 파일 작성

```dotenv
# ── KIS (한국투자증권) ─────────────────────────────────────────────
KIS_APP_KEY=발급받은_앱키
KIS_APP_SECRET=발급받은_앱시크릿
KIS_ACCOUNT_NO=계좌번호
KIS_ACCOUNT_PRODUCT_CODE=01
KIS_IS_REAL=true           # true: 실전투자 / false: 모의투자

# ── 카카오톡 ──────────────────────────────────────────────────────
KAKAO_REST_API_KEY=카카오_REST_API_키
KAKAO_TOKEN_FILE=data/kakao_token.json

# ── 기본 감시 종목 (동적 스크리너가 추가 종목 자동 발굴) ────────────
WATCH_SYMBOLS=005930,000660,122630

# ── 기본 전략 파라미터 ────────────────────────────────────────────
MONITOR_INTERVAL_MINUTES=5
RSI_PERIOD=14
RSI_OVERSOLD=30
RSI_OVERBOUGHT=70
MOVING_AVERAGE_SHORT=5
MOVING_AVERAGE_LONG=20
STOP_LOSS_RATE=0.05
HEDGE_RATIO=0.3

# ── 레버리지+콜 옵션 전략 (퀀텀 점프) ─────────────────────────────
LEV_CALL_ENABLED=false      # true로 변경하면 전략 활성화
LEV_ETF_SYMBOL=122630       # KODEX 200 레버리지
LEV_ETF_ALLOC=0.70          # ETF 배분 비율 70%
CALL_OPTION_ALLOC=0.30      # 콜 옵션 배분 비율 30%
CALL_STRIKE=5500.0          # 콜 옵션 행사가
CALL_EXPIRY_MONTHS=2        # 만기 (개월)
ENTRY_KOSPI_LEVEL=5400.0    # 코스피 진입 수준
EXIT_KOSPI_LEVEL=6000.0     # 코스피 청산 수준
TAKE_PROFIT_PCT=0.20        # 익절 기준 +20%
TAKE_PROFIT_SELL_RATIO=0.50 # 익절 시 50% 부분 청산
MARGIN_LEVERAGE=3.0         # 마진 레버리지 배율
VKOSPI_OPTION_ADD_THRESHOLD=30.0  # VKOSPI > 30 시 옵션 추가 매수

# ── 환경 플래그 ───────────────────────────────────────────────────
DEV_MODE=false              # true: 개발(SSL 우회) / false: 운영(TLS 검증)
PAPER_TRADING=false         # true: 가상 체결 기록 모드
```

### KIS Open API 앱 키 발급

1. [한국투자증권 Open API](https://apiportal.koreainvestment.com) 접속
2. 앱 등록 -> `AppKey` / `AppSecret` 복사 -> `.env` 기입
3. 모의투자: `KIS_IS_REAL=false` | 실전투자: `KIS_IS_REAL=true`

### 카카오 REST API 키 발급

1. [Kakao Developers](https://developers.kakao.com) -> 내 애플리케이션 -> 앱 추가
2. **플랫폼** -> Web -> `https://localhost` 등록
3. **카카오 로그인** 활성화, Redirect URI `https://localhost` 등록
4. **동의 항목** -> `talk_message` 활성화
5. 앱 키 -> REST API 키 복사 -> `.env` 기입

---

## 7. 카카오 OAuth 최초 인증

봇 최초 실행 전 **1회** 수행합니다.

```bash
python scripts/kakao_auth_setup.py
```

```
1. 터미널에 카카오 로그인 URL 출력
2. 브라우저로 URL 열기 -> 카카오 계정 로그인 -> 동의
3. 리다이렉트된 URL (https://localhost?code=XXXX) 전체 복사
4. 터미널에 붙여넣기 -> Enter
5. data/kakao_token.json 저장
6. 테스트 메시지 자동 전송
```

---

## 8. 실행 & 샘플 출력 로그

```bash
python main.py
```

```
2026-03-16 09:01:00 [INFO] KimBeggar bot starting up.
2026-03-16 09:01:01 [INFO] Watching 3 symbols every 5 minute(s): 005930, 000660, 122630
2026-03-16 09:01:01 [INFO] Bot scheduler thread started (daemon).
2026-03-16 09:01:02 [INFO] === Monitoring cycle start ===
2026-03-16 09:01:02 [INFO] Screener [낙폭과대/pykrx]: 5개 종목 발굴 -- ['035720', '066570', '000270', ...]
2026-03-16 09:01:03 [INFO] 삼성전자(005930) | HOLD | price=71500 | RSI=52.3
2026-03-16 09:01:04 [INFO] SK하이닉스(000660) | HOLD | price=183000 | RSI=44.1
2026-03-16 09:01:05 [INFO] KODEX 레버리지(122630) | BUY | price=11250 | RSI=27.8
2026-03-16 09:01:05 [INFO] KODEX 레버리지(122630): entry price recorded at 11250
2026-03-16 09:01:06 [INFO] LevCall | 122630 | KOSPI=5380 | VKOSPI=28.4 | 옵션프리미엄=3250000 | signal=ENTRY
2026-03-16 09:01:06 [INFO] === Monitoring cycle complete ===
```

---

## 9. 동적 종목 발굴 (Screener)

`data_agent/screener.py`의 `get_dynamic_targets()` 함수가 장 시작 시 1회, 이후 60분 주기로 실행됩니다.

### 3단 폴백 전략

```
1차 [pykrx 낙폭과대]
    pykrx.stock.get_market_ohlcv_by_ticker(today, market="KOSPI")
    -> 등락률 < 0 종목을 하락률 오름차순 정렬
    -> 상위 N개 선택 (RSI 과매도 반등 후보)
    -> source: "drop_rank"

    실패 (pykrx 미설치 or 장 마감) ->

2차 [KIS 거래량 순위]
    GET /uapi/domestic-stock/v1/quotations/volume-rank
    tr_id: FHPST01710000
    -> 당일 거래대금 상위 N개 (모멘텀 플레이)
    -> source: "volume_rank"

    실패 (API 오류 or 샌드박스) ->

3차 [KOSPI Top-50 폴백]
    _KOSPI_TOP50 리스트에서 랜덤 N개
    + KISClient.get_current_price() 실시간 가격 조회
    -> source: "fallback"
```

### NameResolver: 종목명 자동 표시

```python
from data_agent.name_resolver import get_resolver

resolver = get_resolver()
resolver.display("005930")   # -> "삼성전자(005930)"
resolver.display("122630")   # -> "KODEX 레버리지(122630)"
```

- **1차**: pykrx `stock.get_market_ticker_name(symbol)`
- **2차**: 내장 정적 맵 (KOSPI 50종목 + 주요 ETF)
- 결과 캐싱으로 반복 API 호출 없음

### 대시보드 스크리너 섹션

웹 대시보드(http://0.0.0.0:8000)의 하단 "자동 탐색 종목" 섹션에서 실시간으로 확인할 수 있습니다.

```
| 종목              | 현재가     | 등락률   | 거래량      | 출처    | 발굴시각 |
|-------------------|-----------|---------|------------|--------|---------|
| 카카오(035720)    | 43,200 원  | -4.21%  | 12,345,678 | 낙폭과대 | 09:01  |
| LG전자(066570)    | 71,500 원  | -3.87%  | 8,234,567  | 낙폭과대 | 09:01  |
```

### REST API

```bash
GET /api/targets   # 현재 스크리너 결과 JSON
GET /api/status    # 헬스체크 (screener_targets 개수 포함)
```

---

## 10. 레버리지+콜 전략 (Quantum Jump)

`.env`에 `LEV_CALL_ENABLED=true`를 설정하면 활성화됩니다.

### 전략 구조

```
┌──────────────────────────────────────────────────────────────┐
│              LevCall Quantum Jump Strategy                    │
│                                                              │
│  포트폴리오  ETF(122630) 70% + 코스피 콜 옵션 30%              │
│             + 마진 레버리지 3배 (ETF 매수 시)                  │
│                                                              │
│  ENTRY     코스피 <= 5,400pt                                  │
│         OR ETF RSI <= 30 AND 골든크로스                       │
│                                                              │
│  PARTIAL   포트폴리오 수익률 >= +20% -> 50% 청산              │
│  EXIT                                                        │
│                                                              │
│  EXIT      코스피 >= 6,000pt                                  │
│         OR ETF 데드크로스                                     │
│                                                              │
│  ADD_OPT   VKOSPI 추정치 > 30 -> 공포 극대 시 옵션 추가 매수  │
└──────────────────────────────────────────────────────────────┘
```

### 옵션 가격 모델 (Black-Scholes, scipy 불필요)

```python
from strategy.option_pricing import black_scholes_call, estimate_premium_per_contract

# KOSPI 200 콜 옵션 가격 계산
premium = black_scholes_call(
    S=5400.0,   # 현재 코스피 수준
    K=5500.0,   # 행사가
    T=2/12,     # 2개월 만기
    r=0.035,    # 한국 10Y 국채 3.5%
    sigma=0.25, # 내재 변동성
)
# -> 약 7.8pt (거래승수 250,000원/pt 적용 시 계약당 ~195만원)
```

### VKOSPI 합성 추정

KIS API에 VKOSPI가 없으므로 실현 변동성 기반으로 합성합니다:

```python
from strategy.vkospi_estimator import estimate_vkospi

vkospi = estimate_vkospi(close_prices, window=20)
# 20일 롤링 표준편차 연율화 x 1.2(공포 프리미엄) + 드로다운 추가분
# -> 정상: 15~20, 공포 극대: 40~60
```

### 2026 퀀텀점프 백테스트 시뮬레이션

```bash
python scripts/backtest_lev_call_2026.py
```

6-Phase GBM 시나리오 (코스피 5,600 -> -12% 조정 -> 6,000 돌파):

```
Phase 1:  코스피 5,600 횡보  (10일, vol=15%)
Phase 2:  5,400 조정         ( 8일, vol=40%) <- ENTRY 트리거
Phase 3:  바닥 형성          ( 5일, vol=35%) <- 골든크로스
Phase 4:  5,800 회복 랠리    (15일, vol=25%)
Phase 5:  중간 조정          ( 5일, vol=30%)
Phase 6:  6,000 돌파 청산    (10일, vol=20%) <- EXIT

결과 (1,000만원 기준):
  ENTRY: 5,368pt @ 2026-03-30
  PARTIAL EXIT +20%: 2026-03-31
  EXIT: 2026-04-24
  최종 수익률: +10.4% (마진 3배 적용 시 ~+31%)

vs. 코스피 Buy&Hold: +5.2%
vs. ETF Buy&Hold: +10.4%
```

---

## 11. 백테스팅

### 단일 종목 RSI+MA 백테스트

```bash
python scripts/run_backtest.py --symbol 005930 --days 365 --cash 10000000
```

```
=======================================================
  Symbol        : 005930
  Period        : 2025-03-16 ~ 2026-03-16
  Initial cash  :      10,000,000 KRW
  Final value   :      11,243,850 KRW
  PnL           :      +1,243,850 KRW  (+12.44%)
  Total trades  : 4  |  Won/Lost: 3/1  |  Win rate: 75.0%
=======================================================
```

### 2022 코스피 대폭락 시뮬레이션

```bash
python scripts/backtest_2022_crash.py
```

2022년 코스피 -28% 폭락 환경에서 헤지 전략 효과 검증:

```
  초기 자본  :  10,000,000 KRW
  최종 평가  :   9,870,000 KRW  (-1.3%)
  코스피 낙폭:             -28.4%
  대비 초과  :            +27.1%p  <- 헤지 효과
  최대 낙폭  :              -6.2%  <- 손절 5% 발동
```

---

## 12. 웹 대시보드

```bash
python main.py
# -> http://localhost:8000
```

### 대시보드 구성

```
┌─────────────────────────────────────────────────────────┐
│  KimBeggar Dashboard                    [실시간 연결됨]   │
├──────────┬───────────┬──────────────┬──────────────────┤
│ 오픈 포지션│ 최근 시그널 │ WS 클라이언트  │  스크리너 탐색     │
│    2     │     8     │      1       │       5          │
├──────────┴───────────┴──────────────┴──────────────────┤
│ [오픈 포지션]             [최근 시그널]                    │
│ 종목           진입가    시각  종목      시그널  가격  RSI  │
│ KODEX레버리지  11,250   ...  삼성전자   매수   71,500 27.8│
│ 삼성전자       71,500   ...  카카오     손절   43,200 31.2│
├─────────────────────────────────────────────────────────┤
│ [자동 탐색 종목 (스크리너)]                                │
│ 종목         현재가     등락률   거래량      출처    발굴시각│
│ 카카오       43,200    -4.21%  12,345,678  낙폭과대 09:01│
└─────────────────────────────────────────────────────────┘
```

- **실시간 WebSocket 업데이트**: 시그널 발생 즉시 브라우저에 반영
- **종목명 표시**: "삼성전자(005930)" 형태로 모든 테이블에 표시
- **모바일 반응형**: 800px 이하에서 단일 컬럼 레이아웃
- **자동 재연결**: 연결 끊김 시 지수 백오프(1s -> 30s)로 자동 복구

### REST API 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/` | HTML 대시보드 (SSR) |
| `GET` | `/api/status` | 헬스체크 + 통계 |
| `GET` | `/api/positions` | 오픈 포지션 목록 |
| `GET` | `/api/signals` | 최근 시그널 목록 (최대 50건) |
| `GET` | `/api/targets` | 스크리너 탐색 종목 목록 |
| `WS`  | `/ws` | 이벤트 드리븐 실시간 푸시 |

---

## 13. 페이퍼 트레이딩

```dotenv
PAPER_TRADING=true
```

시그널 발생 시 KIS API 주문 대신 SQLite `paper_trades` 테이블에 기록합니다.

```sql
CREATE TABLE IF NOT EXISTS paper_trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL,
    signal_type TEXT    NOT NULL,  -- BUY | SELL | STOP_LOSS | HEDGE | LEV_ENTRY...
    price       REAL    NOT NULL,
    quantity    INTEGER NOT NULL DEFAULT 1,
    total_krw   REAL    NOT NULL,
    traded_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
```

```python
from data_agent.paper_trade_store import PaperTradeStore

store = PaperTradeStore("data/bot_state.db")
trades = store.get_all()   # 전체 체결 내역
summary = store.get_summary()  # 종목별 P&L: {"005930": {"pnl_krw": 50000.0, ...}}
```

---

## 14. 설계 원칙 & 패턴

### Observer 패턴 — 알림 채널 확장

```
BaseNotifier (ABC)
  ├── KakaoNotifier       <- 현재 구현
  ├── TelegramNotifier    <- 확장 예시
  └── SlackNotifier       <- 확장 예시

NotifierService (Composite)
  └── 등록된 모든 채널에 브로드캐스트
```

코어 코드(`SignalEngine`, `main.py`) 수정 없이 채널 추가 가능.

```python
# main.py 한 줄 추가만으로 텔레그램 연동
service = NotifierService([
    KakaoNotifier(settings),
    TelegramNotifier(settings),   # <- 이 줄만 추가
])
```

### Tenacity 재시도

```python
@retry(
    retry=retry_if_exception_type(requests.RequestException),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),  # 1s->2s->4s
)
```

KIS API, Kakao API의 모든 HTTP 호출에 적용. 일시적 네트워크 장애에서 자동 복구.

### SSL 보안

```python
# DEV_MODE=true  -> verify=False  (로컬 인증서 우회)
# DEV_MODE=false -> verify=True   (운영: 완전한 TLS 검증)
```

### 의존성 주입

```python
engine = SignalEngine(settings)
service = NotifierService([KakaoNotifier(settings)])
# SignalEngine은 어떤 알림 채널이 연결되어 있는지 알 필요 없음
```

### TA-Lib 자동 폴백

TA-Lib 미설치 환경에서 `strategy/indicators.py`가 자동으로 pandas/NumPy 구현으로 전환됩니다.

---

## 15. 운영 체크리스트

배포 전 확인:

- [ ] `.env`에 `DEV_MODE=false` 설정 -> TLS 검증 복원
- [ ] `.env`에 `KIS_IS_REAL=true` 설정 -> 실전투자 서버
- [ ] `data/kakao_token.json`이 `.gitignore`에 포함
- [ ] `.env`가 `.gitignore`에 포함
- [ ] `logs/`, `data/` 디렉터리 쓰기 권한 확인
- [ ] 카카오 `refresh_token` 만료 전 갱신 확인 (만료 30일 전 자동 갱신)
- [ ] `LEV_CALL_ENABLED=true` 시 `CALL_STRIKE`, `ENTRY_KOSPI_LEVEL` 현재 시장 수준으로 조정

---

## 16. 기여 가이드

### 기여 절차

```bash
git checkout -b feat/your-feature-name

# 코드 작성 + 테스트
pytest tests/ --cov-fail-under=80

# 스타일 확인
black .
flake8 .

git commit -m "feat: describe your change"
git push origin feat/your-feature-name
# -> GitHub에서 Pull Request 생성
```

### 기여 체크리스트

- [ ] 새 기능에 대한 단위 테스트 추가 (커버리지 80% 이상)
- [ ] `black .` 포맷 통과
- [ ] `flake8 .` 경고 없음
- [ ] 환경 변수 추가 시 `.env` 예시에 문서화
- [ ] PR 설명에 변경 이유와 테스트 방법 기재

### 코드 스타일

- **포맷**: `black` (line-length=100)
- **린트**: `flake8` (E203, W503 제외)
- **타입 힌트**: 모든 public 함수에 PEP 484 타입 어노테이션
- **독스트링**: Google 스타일 (`Args:`, `Returns:`, `Raises:`)
- **커밋**: Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`)

---

## 라이선스

MIT License — 자유롭게 사용, 수정, 배포 가능합니다.
실전 투자 활용 시 KIS Open API 이용약관 및 관련 금융 법규를 준수하세요.

> **면책 고지**: 이 봇은 교육 및 연구 목적으로 제작되었습니다.
> 실제 투자 결과에 대한 책임은 전적으로 사용자 본인에게 있습니다.
> 레버리지 및 옵션 거래는 원금 이상의 손실이 발생할 수 있습니다.

```
Copyright (c) 2026 KimBeggar Contributors
```
