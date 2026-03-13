# 🤖 KimBeggar — 절대 잃지 않는 헤지 봇

> **"돈을 버는 것보다 잃지 않는 것이 먼저다."**
> RSI + 이동평균 크로스오버로 매매 시그널을 탐지하고, 시장 급락 시 인버스 ETF 헤지를 자동 알림하는 국내 주식 모니터링 봇.

---

## 목차 Table of Contents

1. [프로젝트 목적](#1-프로젝트-목적)
2. [핵심 전략 — 절대 잃지 않는 3단 방어선](#2-핵심-전략--절대-잃지-않는-3단-방어선)
3. [아키텍처](#3-아키텍처)
4. [디렉터리 구조](#4-디렉터리-구조)
5. [의존성 & 기술 스택](#5-의존성--기술-스택)
6. [설치 및 환경 구성](#6-설치-및-환경-구성)
7. [카카오 OAuth 최초 인증](#7-카카오-oauth-최초-인증)
8. [실행](#8-실행)
9. [연결 테스트](#9-연결-테스트)
10. [설계 원칙 & 패턴](#10-설계-원칙--패턴)
11. [운영 체크리스트](#11-운영-체크리스트)
12. [확장 가이드 — 새 알림 채널 추가](#12-확장-가이드--새-알림-채널-추가)

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

---

## 2. 핵심 전략 — 절대 잃지 않는 3단 방어선

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

## 3. 아키텍처

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

## 4. 디렉터리 구조

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

## 5. 의존성 & 기술 스택

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

## 6. 설치 및 환경 구성

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

## 7. 카카오 OAuth 최초 인증

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

## 8. 실행

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

---

## 9. 연결 테스트

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

## 10. 설계 원칙 & 패턴

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

## 11. 운영 체크리스트

배포 전 확인:

- [ ] `.env`에 `DEV_MODE=false` 설정 → TLS 검증 복원
- [ ] `.env`에 `KIS_IS_REAL=true` 설정 → 실전투자 서버 전환
- [ ] `data/kakao_token.json`이 `.gitignore`에 포함되어 있는지 확인
- [ ] `.env`가 `.gitignore`에 포함되어 있는지 확인
- [ ] `logs/` 디렉터리 쓰기 권한 확인
- [ ] `data/` 디렉터리 쓰기 권한 확인
- [ ] 카카오 `refresh_token` 만료 전 갱신 알림 설정 (만료 30일 전 자동 갱신)

---

## 12. 확장 가이드 — 새 알림 채널 추가

### 텔레그램 추가 예시

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

---

## 라이선스

This project is for internal competition purposes.
외부 배포 및 실전 투자 활용 시 KIS Open API 이용약관을 준수하세요.
