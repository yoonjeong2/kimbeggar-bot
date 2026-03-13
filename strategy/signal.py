"""
매매 시그널 판별 모듈
보조지표를 기반으로 매수/매도/손절/헤지 시그널 조건 판별
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

import pandas as pd

from config.settings import Settings
from strategy.indicators import (
    calculate_rsi,
    calculate_moving_average,
    detect_dead_cross,
    detect_golden_cross,
)


class SignalType(Enum):
    """시그널 유형"""
    BUY = "BUY"           # 매수
    SELL = "SELL"         # 매도
    STOP_LOSS = "STOP_LOSS"   # 손절
    HEDGE = "HEDGE"       # 헤지
    HOLD = "HOLD"         # 관망


@dataclass
class Signal:
    """
    시그널 정보

    Attributes:
        symbol: 종목코드
        signal_type: 시그널 유형
        price: 현재가
        reason: 시그널 발생 이유
        rsi: 현재 RSI 값
        ma_short: 단기 이동평균
        ma_long: 장기 이동평균
    """
    symbol: str
    signal_type: SignalType
    price: float
    reason: str
    rsi: Optional[float] = None
    ma_short: Optional[float] = None
    ma_long: Optional[float] = None


class SignalEngine:
    """
    매매 시그널 판별 엔진

    보조지표(RSI, 이동평균, 데드크로스 등)를 종합하여
    매수/매도/손절/헤지 시그널을 생성
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = logging.getLogger(__name__)

    def evaluate(self, symbol: str, ohlcv_data: List[Dict[str, Any]], entry_price: Optional[float] = None) -> Signal:
        """
        종목의 시그널 종합 판별

        Args:
            symbol: 종목코드
            ohlcv_data: OHLCV 캔들 데이터 리스트
            entry_price: 진입가 (손절 시그널 판별에 사용, None이면 손절 체크 생략)

        Returns:
            판별된 Signal 객체
        """
        # TODO: 보조지표 계산 후 시그널 종합 판별 구현
        pass

    def check_buy_signal(self, prices: pd.Series, rsi: pd.Series, short_ma: pd.Series, long_ma: pd.Series) -> bool:
        """
        매수 시그널 조건 확인
        조건: RSI 과매도 + 골든크로스 발생

        Args:
            prices: 종가 시계열
            rsi: RSI 시계열
            short_ma: 단기 이동평균 시계열
            long_ma: 장기 이동평균 시계열

        Returns:
            매수 시그널 발생 여부
        """
        # TODO: 매수 시그널 조건 구현
        pass

    def check_sell_signal(self, prices: pd.Series, rsi: pd.Series, short_ma: pd.Series, long_ma: pd.Series) -> bool:
        """
        매도 시그널 조건 확인
        조건: RSI 과매수 + 데드크로스 발생

        Args:
            prices: 종가 시계열
            rsi: RSI 시계열
            short_ma: 단기 이동평균 시계열
            long_ma: 장기 이동평균 시계열

        Returns:
            매도 시그널 발생 여부
        """
        # TODO: 매도 시그널 조건 구현
        pass

    def check_stop_loss(self, current_price: float, entry_price: float) -> bool:
        """
        손절 시그널 조건 확인
        조건: 현재가가 진입가 대비 손절 비율 이하로 하락

        Args:
            current_price: 현재가
            entry_price: 진입가

        Returns:
            손절 시그널 발생 여부
        """
        # TODO: 손절 조건 구현
        pass

    def check_hedge_signal(self, index_data: Dict[str, Any]) -> bool:
        """
        헤지 시그널 조건 확인
        조건: 시장 지수 급락 감지 시 헤지 포지션 진입 필요

        Args:
            index_data: 시장 지수 데이터 (코스피/코스닥)

        Returns:
            헤지 시그널 발생 여부
        """
        # TODO: 헤지 조건 구현
        pass
