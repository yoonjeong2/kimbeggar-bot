"""레버리지 ETF + 콜 옵션 포트폴리오 상태 추적기.

``LevCallPortfolio`` 클래스는 ETF 레그(70%)와 옵션 레그(30%) 두 개의
가상 포지션을 관리합니다. 실제 주문을 내지 않으므로 backtrader 브로커 외부에서
독립적으로 작동합니다.

KOSPI 200 옵션 거래승수: 250,000원/포인트
마진 레버리지: ETF 매수 시에만 적용 (옵션은 프리미엄 전액 현금 지급)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from strategy.option_pricing import call_option_pnl, _KOSPI200_MULTIPLIER


@dataclass
class LevCallPortfolio:
    """레버리지 ETF + 콜 옵션 2-레그 포트폴리오 추적기.

    Attributes:
        initial_cash:         투자 가능 초기 현금 (KRW).
        etf_alloc:            ETF 배분 비율 (0~1, 기본 0.70).
        option_alloc:         옵션 배분 비율 (0~1, 기본 0.30).
        margin_leverage:      ETF 마진 레버리지 배율 (기본 3.0).
        etf_shares:           보유 ETF 주수.
        etf_entry_price:      ETF 진입 단가 (KRW).
        option_contracts:     보유 옵션 계약 수 (가상, 소수 허용).
        option_entry_premium: 옵션 진입 프리미엄 (포인트).
        cash_used_etf:        ETF에 투입한 실제 현금 (마진 전).
        cash_used_option:     옵션 프리미엄으로 지급한 현금.
        is_active:            포지션 활성 여부.
        partial_exits:        부분 청산 횟수.
        option_adds:          옵션 추가 매수 횟수.
        events:               이벤트 로그 리스트.
    """

    initial_cash: float
    etf_alloc: float = 0.70
    option_alloc: float = 0.30
    margin_leverage: float = 3.0

    # Position state
    etf_shares: float = field(default=0.0, init=False)
    etf_entry_price: float = field(default=0.0, init=False)
    option_contracts: float = field(default=0.0, init=False)
    option_entry_premium: float = field(default=0.0, init=False)
    cash_used_etf: float = field(default=0.0, init=False)
    cash_used_option: float = field(default=0.0, init=False)
    is_active: bool = field(default=False, init=False)
    partial_exits: int = field(default=0, init=False)
    option_adds: int = field(default=0, init=False)
    events: List[Dict] = field(default_factory=list, init=False)

    def allocate_initial(
        self,
        etf_price: float,
        option_premium: float,
    ) -> Dict:
        """초기 포지션을 ETF 70% + 옵션 30%로 배분합니다.

        ETF는 마진 레버리지를 적용하여 실제 현금보다 많은 수량을 매수합니다.
        옵션은 프리미엄 전액을 현금으로 지급합니다.

        Args:
            etf_price:       ETF 현재가 (KRW).
            option_premium:  콜 옵션 계약당 프리미엄 (KRW).

        Returns:
            배분 결과 딕셔너리 (etf_shares, option_contracts, total_exposure).
        """
        if self.is_active:
            return {"error": "Portfolio already active"}

        etf_cash = self.initial_cash * self.etf_alloc
        option_cash = self.initial_cash * self.option_alloc

        # ETF: 마진 레버리지 적용 (실제 현금의 배수만큼 노출)
        etf_exposure = etf_cash * self.margin_leverage
        self.etf_shares = etf_exposure / etf_price if etf_price > 0 else 0.0
        self.etf_entry_price = etf_price
        self.cash_used_etf = etf_cash

        # 옵션: 프리미엄 전액 현금 지급
        if option_premium > 0:
            self.option_contracts = option_cash / option_premium
        else:
            self.option_contracts = 0.0
        self.option_entry_premium = option_premium
        self.cash_used_option = option_cash

        self.is_active = True
        result = {
            "etf_shares": self.etf_shares,
            "etf_entry_price": self.etf_entry_price,
            "option_contracts": self.option_contracts,
            "option_entry_premium": self.option_entry_premium,
            "total_exposure": etf_exposure + option_cash,
        }
        self.events.append({"type": "ENTRY", **result})
        return result

    def mark_to_market(
        self,
        etf_price: float,
        option_premium: float,
    ) -> Dict:
        """현재 시가로 포트폴리오를 평가합니다.

        Args:
            etf_price:      현재 ETF 가격 (KRW).
            option_premium: 현재 옵션 계약당 프리미엄 (KRW).

        Returns:
            시가평가 결과 딕셔너리.
        """
        if not self.is_active:
            return {
                "etf_value": 0.0,
                "option_value": 0.0,
                "total_value": self.initial_cash,
                "pnl": 0.0,
                "pnl_pct": 0.0,
            }

        # ETF 평가 (마진 비용 미반영 — 간소화)
        etf_value = self.etf_shares * etf_price

        # 옵션 평가
        option_pnl = call_option_pnl(
            self.option_entry_premium / _KOSPI200_MULTIPLIER,
            option_premium / _KOSPI200_MULTIPLIER,
            self.option_contracts,
        )
        option_value = self.cash_used_option + option_pnl

        total_value = (
            etf_value
            + option_value
            + (self.initial_cash - self.cash_used_etf - self.cash_used_option)
        )
        pnl = total_value - self.initial_cash
        pnl_pct = pnl / self.initial_cash if self.initial_cash > 0 else 0.0

        return {
            "etf_value": etf_value,
            "option_value": option_value,
            "total_value": total_value,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "etf_pnl": etf_value - self.cash_used_etf * self.margin_leverage,
            "option_pnl": option_pnl,
        }

    def partial_exit(
        self,
        etf_price: float,
        option_premium: float,
        sell_ratio: float = 0.50,
    ) -> Dict:
        """포지션의 일부를 청산합니다 (익절 부분 청산용).

        Args:
            etf_price:      현재 ETF 가격 (KRW).
            option_premium: 현재 옵션 계약당 프리미엄 (KRW).
            sell_ratio:     청산 비율 (기본 50%).

        Returns:
            청산 결과 딕셔너리.
        """
        if not self.is_active:
            return {"error": "No active position"}

        mtm = self.mark_to_market(etf_price, option_premium)

        # 비율만큼 축소
        etf_sold = self.etf_shares * sell_ratio
        options_closed = self.option_contracts * sell_ratio

        # 실현 손익 (비율 기준)
        realized_pnl = mtm["pnl"] * sell_ratio

        self.etf_shares -= etf_sold
        self.option_contracts -= options_closed
        self.cash_used_etf *= (1.0 - sell_ratio)
        self.cash_used_option *= (1.0 - sell_ratio)
        self.partial_exits += 1

        result = {
            "type": "PARTIAL_EXIT",
            "sell_ratio": sell_ratio,
            "etf_sold": etf_sold,
            "options_closed": options_closed,
            "realized_pnl": realized_pnl,
        }
        self.events.append(result)
        return result

    def full_exit(
        self,
        etf_price: float,
        option_premium: float,
    ) -> Dict:
        """포지션 전량을 청산합니다.

        Args:
            etf_price:      현재 ETF 가격 (KRW).
            option_premium: 현재 옵션 계약당 프리미엄 (KRW).

        Returns:
            청산 결과 딕셔너리.
        """
        if not self.is_active:
            return {"error": "No active position"}

        mtm = self.mark_to_market(etf_price, option_premium)

        result = {
            "type": "FULL_EXIT",
            "final_value": mtm["total_value"],
            "pnl": mtm["pnl"],
            "pnl_pct": mtm["pnl_pct"],
            "etf_pnl": mtm["etf_pnl"],
            "option_pnl": mtm["option_pnl"],
        }
        self.events.append(result)

        # 포지션 초기화
        self.etf_shares = 0.0
        self.etf_entry_price = 0.0
        self.option_contracts = 0.0
        self.option_entry_premium = 0.0
        self.cash_used_etf = 0.0
        self.cash_used_option = 0.0
        self.is_active = False

        return result

    def add_options(
        self,
        cash_amount: float,
        option_premium: float,
    ) -> Dict:
        """VKOSPI 급등 시 추가 옵션을 매수합니다.

        Args:
            cash_amount:    추가 매수에 사용할 현금 (KRW).
            option_premium: 현재 옵션 계약당 프리미엄 (KRW).

        Returns:
            추가 매수 결과 딕셔너리.
        """
        if option_premium <= 0:
            return {"error": "Invalid option premium"}

        added_contracts = cash_amount / option_premium
        self.option_contracts += added_contracts
        self.cash_used_option += cash_amount
        self.option_adds += 1

        result = {
            "type": "ADD_OPTIONS",
            "added_contracts": added_contracts,
            "cash_used": cash_amount,
            "total_option_contracts": self.option_contracts,
        }
        self.events.append(result)
        return result
