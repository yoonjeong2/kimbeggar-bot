"""동적 종목 발굴 (Screener) 모듈.

당일 낙폭이 과대하거나 거래량이 급증한 종목을 자동으로 발굴합니다.

발굴 전략 (3단계 폴백)
----------------------
1. **낙폭 과대 순위** (1차): pykrx로 코스피 전 종목 등락률 조회 -> 하락률 상위 N개
   (낙폭 과대 = RSI 과매도 반등 후보)
2. **거래량 순위** (2차): KIS 거래량 순위 API -> 거래대금 상위 N개
   (API 장애 또는 pykrx 미설치 시)
3. **폴백** (3차): KOSPI 시가총액 상위 50 종목에서 랜덤 N개 추출
   + 실시간 가격 조회 (네트워크 없는 테스트 환경 포함)

사용 예시::

    from data_agent.screener import get_dynamic_targets
    targets = get_dynamic_targets(kis_client, top_n=5)
    for t in targets:
        print(t.symbol, t.name, t.change_rate)
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from data_agent.kis_api import KISClient

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 폴백용 KOSPI 시가총액 상위 50 종목 (2026년 3월 기준 추정)
# ---------------------------------------------------------------------------
_KOSPI_TOP50: List[str] = [
    "005930",  # 삼성전자
    "000660",  # SK하이닉스
    "005935",  # 삼성전자우
    "005380",  # 현대차
    "000270",  # 기아
    "051910",  # LG화학
    "035420",  # NAVER
    "035720",  # 카카오
    "207940",  # 삼성바이오로직스
    "006400",  # 삼성SDI
    "068270",  # 셀트리온
    "003670",  # 포스코홀딩스
    "105560",  # KB금융
    "012330",  # 현대모비스
    "055550",  # 신한지주
    "032830",  # 삼성생명
    "028260",  # 삼성물산
    "015760",  # 한국전력
    "066570",  # LG전자
    "018260",  # 삼성에스디에스
    "034730",  # SK
    "017670",  # SK텔레콤
    "030200",  # KT
    "003550",  # LG
    "316140",  # 우리금융지주
    "086790",  # 하나금융지주
    "011200",  # HMM
    "009150",  # 삼성전기
    "032640",  # LG유플러스
    "010130",  # 고려아연
    "011070",  # LG이노텍
    "009830",  # 한화솔루션
    "139480",  # 이마트
    "271560",  # 오리온
    "096770",  # SK이노베이션
    "010950",  # S-Oil
    "000810",  # 삼성화재
    "090430",  # 아모레퍼시픽
    "042660",  # 한화오션
    "078930",  # GS
    "180640",  # 한진칼
    "021240",  # 코웨이
    "000720",  # 현대건설
    "024110",  # 기업은행
    "023530",  # 롯데쇼핑
    "011170",  # 롯데케미칼
    "122630",  # KODEX 레버리지
    "114800",  # KODEX 인버스
    "069500",  # KODEX 200
    "229200",  # KODEX 코스닥150
]


# ---------------------------------------------------------------------------
# ScreenerResult 데이터클래스
# ---------------------------------------------------------------------------


@dataclass
class ScreenerResult:
    """스크리너가 발굴한 종목 정보.

    Attributes:
        symbol:      6자리 KRX 종목코드.
        name:        종목명 (API 응답에서 추출; 폴백 시 빈 문자열).
        price:       현재가 (KRW).
        change_rate: 전일 대비 등락률 (%, 음수=하락).
        volume:      당일 누적 거래량.
        source:      발굴 출처 -- ``"drop_rank"``, ``"volume_rank"``,
                     ``"fallback"`` 중 하나.
        discovered_at: 발굴 시각 (ISO 8601 문자열).
    """

    symbol: str
    name: str = ""
    price: float = 0.0
    change_rate: float = 0.0
    volume: int = 0
    source: str = "unknown"
    discovered_at: str = ""

    def __post_init__(self) -> None:
        if not self.discovered_at:
            self.discovered_at = datetime.now().strftime("%H:%M:%S")

    def to_dict(self) -> Dict[str, Any]:
        """대시보드 직렬화용 딕셔너리로 변환합니다."""
        return {
            "symbol": self.symbol,
            "name": self.name,
            "price": self.price,
            "change_rate": self.change_rate,
            "volume": self.volume,
            "source": self.source,
            "discovered_at": self.discovered_at,
        }


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _parse_ranking_items(
    raw_items: List[Dict[str, Any]],
    source: str,
    top_n: int,
) -> List[ScreenerResult]:
    """KIS 순위 API 응답 리스트를 ``ScreenerResult`` 리스트로 변환합니다."""
    results: List[ScreenerResult] = []
    for item in raw_items[:top_n]:
        symbol = item.get("mksc_shrn_iscd", "").strip()
        if not symbol or len(symbol) != 6:
            continue
        try:
            price = float(item.get("stck_prpr", 0) or 0)
            change_rate = float(item.get("prdy_ctrt", 0) or 0)
            volume = int(float(item.get("acml_vol", 0) or 0))
        except (ValueError, TypeError):
            price, change_rate, volume = 0.0, 0.0, 0
        results.append(
            ScreenerResult(
                symbol=symbol,
                name=item.get("hts_kor_isnm", "").strip(),
                price=price,
                change_rate=change_rate,
                volume=volume,
                source=source,
            )
        )
    return results


def _pykrx_drop_screener(top_n: int) -> Optional[List[ScreenerResult]]:
    """pykrx로 당일 코스피 낙폭 과대 종목을 발굴합니다.

    Args:
        top_n: 반환할 종목 수.

    Returns:
        ``ScreenerResult`` 리스트. pykrx 미설치 또는 오류 시 ``None``.
    """
    try:
        from pykrx import stock  # type: ignore[import]
    except ImportError:
        _logger.debug("pykrx not installed; skipping drop screener")
        return None

    try:
        today = datetime.now().strftime("%Y%m%d")
        df = stock.get_market_ohlcv_by_ticker(today, market="KOSPI")
        if df is None or df.empty:
            _logger.debug("pykrx returned empty DataFrame for %s", today)
            return None

        # 등락률 컬럼명은 '등락률' 또는 '수익률'로 다를 수 있음
        rate_col = None
        for col in ["등락률", "수익률", "PER"]:
            if col in df.columns:
                rate_col = col
                break
        if rate_col is None:
            _logger.debug("pykrx DataFrame columns: %s", list(df.columns))
            return None

        # 하락 종목만, 등락률 오름차순 (가장 많이 하락한 순)
        df_drop = df[df[rate_col] < 0].sort_values(rate_col).head(top_n * 2)
        if df_drop.empty:
            return None

        results: List[ScreenerResult] = []
        for ticker, row in df_drop.iterrows():
            if len(str(ticker)) != 6:
                continue
            try:
                name = stock.get_market_ticker_name(str(ticker))
            except Exception:
                name = ""
            try:
                price = float(row.get("종가", row.get("close", 0)) or 0)
                change_rate = float(row[rate_col])
                volume = int(float(row.get("거래량", 0) or 0))
            except (ValueError, TypeError):
                price, change_rate, volume = 0.0, 0.0, 0
            results.append(
                ScreenerResult(
                    symbol=str(ticker),
                    name=name or "",
                    price=price,
                    change_rate=change_rate,
                    volume=volume,
                    source="drop_rank",
                )
            )
            if len(results) >= top_n:
                break

        return results if results else None
    except Exception as exc:
        _logger.warning("pykrx drop screener failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_dynamic_targets(
    kis: "KISClient",
    top_n: int = 5,
) -> List[ScreenerResult]:
    """KIS API 또는 pykrx로 당일 낙폭 과대 또는 거래량 상위 종목을 동적으로 발굴합니다.

    3단계 폴백 전략을 사용하므로 API 장애나 샌드박스 환경에서도 항상
    ``top_n``개의 종목을 반환합니다.

    Args:
        kis:    인증된 :class:`~data_agent.kis_api.KISClient` 인스턴스.
        top_n:  발굴할 종목 수 (기본 5).

    Returns:
        :class:`ScreenerResult` 리스트 (최대 ``top_n``개).
    """
    from data_agent.name_resolver import get_resolver
    resolver = get_resolver()

    # -- 1차: pykrx 낙폭 과대 (등락률 기준 하락 상위) ---------------------
    results = _pykrx_drop_screener(top_n)
    if results:
        # 종목명 보완 (pykrx에서 이미 가져왔지만 빈 경우 resolver로 보완)
        for r in results:
            if not r.name:
                r.name = resolver.get_name(r.symbol)
        _logger.info(
            "Screener [낙폭과대/pykrx]: %d개 종목 발굴 -- %s",
            len(results),
            [r.symbol for r in results],
        )
        return results

    # -- 2차: KIS 거래량 순위 (유동성 높은 활성 종목) ---------------------
    try:
        raw = kis.get_volume_ranking(top_n=top_n * 2)
        results = _parse_ranking_items(raw, source="volume_rank", top_n=top_n)
        if results:
            # 종목명 resolver로 보완
            for r in results:
                if not r.name:
                    r.name = resolver.get_name(r.symbol)
            _logger.info(
                "Screener [거래량순위/KIS]: %d개 종목 발굴 -- %s",
                len(results),
                [r.symbol for r in results],
            )
            return results
    except Exception as exc:
        _logger.warning("Screener 거래량 순위 API 실패: %s", exc)

    # -- 3차 폴백: KOSPI 상위 50에서 랜덤 N개 + 실시간 가격 조회 ----------
    _logger.info("Screener 폴백: KOSPI 상위 50에서 랜덤 %d개 선택", top_n)
    chosen = random.sample(_KOSPI_TOP50, min(top_n, len(_KOSPI_TOP50)))
    fallback_results: List[ScreenerResult] = []
    for sym in chosen:
        name = resolver.get_name(sym)
        try:
            price_data = kis.get_current_price(sym)
            fallback_results.append(
                ScreenerResult(
                    symbol=sym,
                    name=name,
                    price=float(price_data.get("stck_prpr", 0) or 0),
                    change_rate=float(price_data.get("prdy_ctrt", 0) or 0),
                    volume=int(float(price_data.get("acml_vol", 0) or 0)),
                    source="fallback",
                )
            )
        except Exception as exc:
            _logger.debug("폴백 가격 조회 실패 (%s): %s", sym, exc)
            fallback_results.append(
                ScreenerResult(symbol=sym, name=name, source="fallback")
            )

    _logger.info(
        "Screener [폴백]: %d개 종목 발굴 -- %s",
        len(fallback_results),
        [r.symbol for r in fallback_results],
    )
    return fallback_results[:top_n]
