"""레버리지 ETF + 콜 옵션 복합 전략 시그널 엔진.

기존 ``SignalEngine``과 병렬 구조로, RSI/MA 크로스오버 + 코스피 레벨 기반의
복합 진입/청산 시그널을 생성합니다.

시그널 우선순위
--------------
1. EXIT       - 전량 청산 (코스피 >= exit_level OR 데드크로스)
2. PARTIAL_EXIT - 익절 부분 청산 (+take_profit_pct 도달)
3. ADD_OPTIONS - 옵션 추가 매수 (VKOSPI > threshold)
4. ENTRY      - 신규 진입 (코스피 <= entry_level OR RSI<30+골든크로스)
5. HOLD       - 대기

사용 예시::

    engine = LevCallSignalEngine(settings)
    signal = engine.evaluate(
        etf_closes=etf_series,
        kospi_level=5350.0,
        vkospi=28.5,
        portfolio=portfolio,
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd

from config.settings import Settings
from strategy.indicators import (
    calculate_rsi,
    calculate_moving_average,
    detect_golden_cross,
    detect_dead_cross,
)


class LevCallSignalType(str, Enum):
    """레버리지+콜 전략의 시그널 타입."""

    ENTRY = "ENTRY"
    EXIT = "EXIT"
    PARTIAL_EXIT = "PARTIAL_EXIT"
    ADD_OPTIONS = "ADD_OPTIONS"
    HOLD = "HOLD"


@dataclass
class LevCallSignal:
    """시그널 평가 결과.

    Attributes:
        signal_type: 시그널 종류.
        kospi_level: 평가 시점의 코스피 지수.
        etf_price:   ETF 현재가.
        reason:      시그널 발생 이유 (한국어 설명).
        rsi:         ETF RSI 값 (없으면 None).
        vkospi:      VKOSPI 추정값 (없으면 None).
        portfolio_pnl_pct: 현재 포트폴리오 손익률 (없으면 None).
    """

    signal_type: LevCallSignalType
    kospi_level: float
    etf_price: float
    reason: str
    rsi: Optional[float] = None
    vkospi: Optional[float] = None
    portfolio_pnl_pct: Optional[float] = None


class LevCallSignalEngine:
    """레버리지 ETF + 콜 옵션 복합 전략 시그널 엔진.

    Args:
        settings: 전략 파라미터를 포함한 ``Settings`` 인스턴스.
    """

    _MIN_BARS: int = 30  # 지표 계산에 필요한 최소 봉 수

    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def evaluate(
        self,
        etf_closes: pd.Series,
        kospi_level: float,
        vkospi: float = 20.0,
        portfolio_pnl_pct: Optional[float] = None,
        has_position: bool = False,
    ) -> LevCallSignal:
        """현재 시장 상태를 평가하여 시그널을 반환합니다.

        Args:
            etf_closes:        ETF 일봉 종가 시계열 (오래된 순).
            kospi_level:       현재 코스피 지수 포인트.
            vkospi:            합성 VKOSPI 추정값 (기본 20.0).
            portfolio_pnl_pct: 현재 포트폴리오 손익률 (포지션 있을 때만 유효).
            has_position:      현재 포지션 보유 여부.

        Returns:
            :class:`LevCallSignal` - 가장 높은 우선순위의 시그널.
        """
        etf_price = float(etf_closes.iloc[-1]) if len(etf_closes) > 0 else 0.0

        if len(etf_closes) < self._MIN_BARS:
            return LevCallSignal(
                signal_type=LevCallSignalType.HOLD,
                kospi_level=kospi_level,
                etf_price=etf_price,
                reason=f"데이터 부족 ({len(etf_closes)}/{self._MIN_BARS}봉)",
            )

        # 기술적 지표 계산
        rsi_series = calculate_rsi(etf_closes, period=self._s.rsi_period)
        sma_short = calculate_moving_average(etf_closes, period=self._s.ma_short)
        sma_long = calculate_moving_average(etf_closes, period=self._s.ma_long)
        golden = detect_golden_cross(sma_short, sma_long)
        dead = detect_dead_cross(sma_short, sma_long)

        rsi_now = float(rsi_series.iloc[-1]) if not rsi_series.empty else None
        is_golden = bool(golden.iloc[-1]) if not golden.empty else False
        is_dead = bool(dead.iloc[-1]) if not dead.empty else False

        # ── 우선순위 1: EXIT ──────────────────────────────────────────────
        if has_position:
            if kospi_level >= self._s.exit_kospi_level:
                return LevCallSignal(
                    signal_type=LevCallSignalType.EXIT,
                    kospi_level=kospi_level,
                    etf_price=etf_price,
                    reason=(
                        f"코스피 목표 도달 "
                        f"({kospi_level:.0f} >= {self._s.exit_kospi_level:.0f})"
                    ),
                    rsi=rsi_now,
                    vkospi=vkospi,
                    portfolio_pnl_pct=portfolio_pnl_pct,
                )
            if is_dead:
                return LevCallSignal(
                    signal_type=LevCallSignalType.EXIT,
                    kospi_level=kospi_level,
                    etf_price=etf_price,
                    reason="ETF 데드크로스 - 청산",
                    rsi=rsi_now,
                    vkospi=vkospi,
                    portfolio_pnl_pct=portfolio_pnl_pct,
                )

            # ── 우선순위 2: PARTIAL_EXIT ──────────────────────────────────
            if (
                portfolio_pnl_pct is not None
                and portfolio_pnl_pct >= self._s.take_profit_pct
            ):
                return LevCallSignal(
                    signal_type=LevCallSignalType.PARTIAL_EXIT,
                    kospi_level=kospi_level,
                    etf_price=etf_price,
                    reason=(
                        f"익절 목표 달성 "
                        f"(+{portfolio_pnl_pct:.1%} >= "
                        f"+{self._s.take_profit_pct:.1%})"
                    ),
                    rsi=rsi_now,
                    vkospi=vkospi,
                    portfolio_pnl_pct=portfolio_pnl_pct,
                )

            # ── 우선순위 3: ADD_OPTIONS ───────────────────────────────────
            if vkospi > self._s.vkospi_option_add_threshold:
                return LevCallSignal(
                    signal_type=LevCallSignalType.ADD_OPTIONS,
                    kospi_level=kospi_level,
                    etf_price=etf_price,
                    reason=(
                        f"VKOSPI 급등 "
                        f"({vkospi:.1f} > "
                        f"{self._s.vkospi_option_add_threshold:.1f})"
                    ),
                    rsi=rsi_now,
                    vkospi=vkospi,
                    portfolio_pnl_pct=portfolio_pnl_pct,
                )

        # ── 우선순위 4: ENTRY ─────────────────────────────────────────────
        if not has_position:
            # 조건 A: 코스피 <= entry_level
            if kospi_level <= self._s.entry_kospi_level:
                return LevCallSignal(
                    signal_type=LevCallSignalType.ENTRY,
                    kospi_level=kospi_level,
                    etf_price=etf_price,
                    reason=(
                        f"코스피 저점 진입 "
                        f"({kospi_level:.0f} <= {self._s.entry_kospi_level:.0f})"
                    ),
                    rsi=rsi_now,
                    vkospi=vkospi,
                )
            # 조건 B: RSI <= 30 AND 골든크로스
            if rsi_now is not None and rsi_now <= self._s.rsi_oversold and is_golden:
                return LevCallSignal(
                    signal_type=LevCallSignalType.ENTRY,
                    kospi_level=kospi_level,
                    etf_price=etf_price,
                    reason=(
                        f"RSI 과매도+골든크로스 진입 "
                        f"(RSI={rsi_now:.1f})"
                    ),
                    rsi=rsi_now,
                    vkospi=vkospi,
                )

        return LevCallSignal(
            signal_type=LevCallSignalType.HOLD,
            kospi_level=kospi_level,
            etf_price=etf_price,
            reason="조건 미충족 - 대기",
            rsi=rsi_now,
            vkospi=vkospi,
            portfolio_pnl_pct=portfolio_pnl_pct,
        )
