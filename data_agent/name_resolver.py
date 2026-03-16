"""종목 코드 -> 한글 종목명 변환 모듈.

pykrx를 우선 사용하고, 설치되지 않은 경우 정적 매핑으로 폴백합니다.
스레드 안전 싱글턴으로 동작하며 결과를 캐싱하여 중복 호출을 최소화합니다.
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, Optional

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 정적 폴백 맵 (KOSPI 주요 종목 + 자주 사용되는 ETF)
# ---------------------------------------------------------------------------
_STATIC_NAMES: Dict[str, str] = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "005935": "삼성전자우",
    "005380": "현대차",
    "000270": "기아",
    "051910": "LG화학",
    "035420": "NAVER",
    "035720": "카카오",
    "207940": "삼성바이오로직스",
    "006400": "삼성SDI",
    "068270": "셀트리온",
    "003670": "포스코홀딩스",
    "105560": "KB금융",
    "012330": "현대모비스",
    "055550": "신한지주",
    "032830": "삼성생명",
    "028260": "삼성물산",
    "015760": "한국전력",
    "066570": "LG전자",
    "018260": "삼성에스디에스",
    "034730": "SK",
    "017670": "SK텔레콤",
    "030200": "KT",
    "003550": "LG",
    "316140": "우리금융지주",
    "086790": "하나금융지주",
    "011200": "HMM",
    "009150": "삼성전기",
    "032640": "LG유플러스",
    "010130": "고려아연",
    "011070": "LG이노텍",
    "009830": "한화솔루션",
    "139480": "이마트",
    "271560": "오리온",
    "096770": "SK이노베이션",
    "010950": "S-Oil",
    "000810": "삼성화재",
    "090430": "아모레퍼시픽",
    "042660": "한화오션",
    "078930": "GS",
    "180640": "한진칼",
    "021240": "코웨이",
    "000720": "현대건설",
    "024110": "기업은행",
    "023530": "롯데쇼핑",
    "011170": "롯데케미칼",
    # ETF
    "122630": "KODEX 레버리지",
    "114800": "KODEX 인버스",
    "069500": "KODEX 200",
    "229200": "KODEX 코스닥150",
    "252670": "KODEX 200선물인버스2X",
    "233740": "KODEX 코스닥150레버리지",
    "091160": "KODEX 반도체",
    "091180": "KODEX 자동차",
    "139220": "KODEX IT",
}


# ---------------------------------------------------------------------------
# NameResolver 클래스
# ---------------------------------------------------------------------------


class NameResolver:
    """종목 코드를 한글 종목명으로 변환합니다.

    pykrx를 우선 사용하고, 미설치 시 정적 맵으로 폴백합니다.
    결과는 내부 캐시에 저장되어 반복 API 호출을 방지합니다.
    """

    def __init__(self) -> None:
        self._cache: Dict[str, str] = {}
        self._pykrx_available: Optional[bool] = None
        self._lock = threading.Lock()

    def _try_pykrx(self) -> bool:
        """pykrx 사용 가능 여부를 캐싱하여 반환합니다."""
        if self._pykrx_available is not None:
            return self._pykrx_available
        try:
            import pykrx.stock as _  # noqa: F401
            self._pykrx_available = True
            _logger.debug("pykrx available for name resolution")
        except ImportError:
            self._pykrx_available = False
            _logger.info("pykrx not installed; using static name map for symbol resolution")
        return self._pykrx_available

    def get_name(self, symbol: str) -> str:
        """종목 코드로 한글 종목명을 조회합니다.

        Args:
            symbol: 6자리 KRX 종목코드.

        Returns:
            한글 종목명. 조회 실패 시 종목코드를 그대로 반환합니다.
        """
        with self._lock:
            if symbol in self._cache:
                return self._cache[symbol]

        # 1차: pykrx
        if self._try_pykrx():
            try:
                from pykrx import stock
                name = stock.get_market_ticker_name(symbol)
                if name and name != symbol:
                    with self._lock:
                        self._cache[symbol] = name
                    return name
            except Exception as exc:
                _logger.debug("pykrx name lookup failed for %s: %s", symbol, exc)

        # 2차: 정적 맵
        name = _STATIC_NAMES.get(symbol, symbol)
        with self._lock:
            self._cache[symbol] = name
        return name

    def display(self, symbol: str) -> str:
        """'삼성전자(005930)' 형태의 표시 문자열을 반환합니다.

        Args:
            symbol: 6자리 KRX 종목코드.

        Returns:
            '종목명(종목코드)' 형식. 종목명을 알 수 없으면 종목코드만 반환합니다.
        """
        name = self.get_name(symbol)
        if name and name != symbol:
            return f"{name}({symbol})"
        return symbol

    def names_dict(self, symbols) -> Dict[str, str]:
        """여러 종목코드를 한 번에 조회하여 딕셔너리로 반환합니다.

        Args:
            symbols: 종목코드 이터러블.

        Returns:
            {symbol: display_name} 딕셔너리.
        """
        return {s: self.display(s) for s in symbols}


# ---------------------------------------------------------------------------
# 싱글턴 접근자
# ---------------------------------------------------------------------------

_resolver: Optional[NameResolver] = None
_resolver_lock = threading.Lock()


def get_resolver() -> NameResolver:
    """스레드 안전 싱글턴 :class:`NameResolver` 인스턴스를 반환합니다."""
    global _resolver
    if _resolver is None:
        with _resolver_lock:
            if _resolver is None:
                _resolver = NameResolver()
    return _resolver
