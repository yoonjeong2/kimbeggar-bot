"""Application-wide configuration management.

Loads environment variables from ``.env`` via *python-dotenv* and exposes
them through a single ``Settings`` dataclass.  All other modules should
depend on ``Settings`` rather than reading ``os.getenv`` directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv


@dataclass
class Settings:
    """Centralised application settings loaded from environment variables.

    Reads ``.env`` on first instantiation (via ``__post_init__``).  Field
    defaults are evaluated at import time using ``default_factory`` lambdas;
    ``__post_init__`` then re-reads the environment after ``load_dotenv()``
    so that values from ``.env`` always take precedence.

    Attributes:
        kis_app_key: KIS Open API application key.
        kis_app_secret: KIS Open API application secret.
        kis_account_no: KIS brokerage account number.
        kis_account_product_code: Account product code (default ``"01"``).
        kis_is_real: ``True`` for live trading, ``False`` for the sandbox.
        kakao_rest_api_key: Kakao REST API key.
        kakao_token_file: Path to the Kakao OAuth token JSON file.
        watch_symbols: List of KRX stock codes to monitor.
        monitor_interval_minutes: Polling interval in minutes.
        rsi_period: Look-back period for RSI calculation.
        rsi_oversold: RSI threshold below which the market is considered
            oversold (buy signal candidate).
        rsi_overbought: RSI threshold above which the market is considered
            overbought (sell signal candidate).
        ma_short: Short-window period for the moving-average crossover.
        ma_long: Long-window period for the moving-average crossover.
        stop_loss_rate: Fractional stop-loss threshold (e.g. ``0.05`` = 5 %).
        hedge_ratio: Fraction of position to hedge (e.g. ``0.3`` = 30 %).
        dev_mode: ``True`` when running in development mode (``DEV_MODE=true``
            in ``.env``).  Used by :mod:`config.ssl` to bypass TLS
            verification for local environments.
    """

    # --- KIS API -------------------------------------------------------
    kis_app_key: str = field(default_factory=lambda: os.getenv("KIS_APP_KEY", ""))
    kis_app_secret: str = field(default_factory=lambda: os.getenv("KIS_APP_SECRET", ""))
    kis_account_no: str = field(default_factory=lambda: os.getenv("KIS_ACCOUNT_NO", ""))
    kis_account_product_code: str = field(
        default_factory=lambda: os.getenv("KIS_ACCOUNT_PRODUCT_CODE", "01")
    )
    kis_is_real: bool = field(
        default_factory=lambda: os.getenv("KIS_IS_REAL", "true").lower() == "true"
    )

    # --- Kakao ---------------------------------------------------------
    kakao_rest_api_key: str = field(
        default_factory=lambda: os.getenv("KAKAO_REST_API_KEY", "")
    )
    kakao_token_file: str = field(
        default_factory=lambda: os.getenv("KAKAO_TOKEN_FILE", "data/kakao_token.json")
    )

    # --- Monitoring ----------------------------------------------------
    watch_symbols: List[str] = field(
        default_factory=lambda: os.getenv("WATCH_SYMBOLS", "").split(",")
    )

    # --- Strategy ------------------------------------------------------
    monitor_interval_minutes: int = field(
        default_factory=lambda: int(os.getenv("MONITOR_INTERVAL_MINUTES", "5"))
    )
    rsi_period: int = field(default_factory=lambda: int(os.getenv("RSI_PERIOD", "14")))
    rsi_oversold: float = field(
        default_factory=lambda: float(os.getenv("RSI_OVERSOLD", "30"))
    )
    rsi_overbought: float = field(
        default_factory=lambda: float(os.getenv("RSI_OVERBOUGHT", "70"))
    )
    ma_short: int = field(
        default_factory=lambda: int(os.getenv("MOVING_AVERAGE_SHORT", "5"))
    )
    ma_long: int = field(
        default_factory=lambda: int(os.getenv("MOVING_AVERAGE_LONG", "20"))
    )
    stop_loss_rate: float = field(
        default_factory=lambda: float(os.getenv("STOP_LOSS_RATE", "0.05"))
    )
    hedge_ratio: float = field(
        default_factory=lambda: float(os.getenv("HEDGE_RATIO", "0.3"))
    )

    # --- Runtime environment -------------------------------------------
    dev_mode: bool = field(
        default_factory=lambda: os.getenv("DEV_MODE", "false").lower() == "true"
    )
    paper_trading: bool = field(
        default_factory=lambda: os.getenv("PAPER_TRADING", "false").lower() == "true"
    )

    # --- Leverage + Call Option Strategy --------------------------------
    lev_call_enabled: bool = field(
        default_factory=lambda: os.getenv("LEV_CALL_ENABLED", "false").lower() == "true"
    )
    lev_etf_symbol: str = field(
        default_factory=lambda: os.getenv("LEV_ETF_SYMBOL", "122630")
    )
    lev_etf_alloc: float = field(
        default_factory=lambda: float(os.getenv("LEV_ETF_ALLOC", "0.70"))
    )
    call_option_alloc: float = field(
        default_factory=lambda: float(os.getenv("CALL_OPTION_ALLOC", "0.30"))
    )
    call_strike: float = field(
        default_factory=lambda: float(os.getenv("CALL_STRIKE", "5500.0"))
    )
    call_expiry_months: int = field(
        default_factory=lambda: int(os.getenv("CALL_EXPIRY_MONTHS", "2"))
    )
    entry_kospi_level: float = field(
        default_factory=lambda: float(os.getenv("ENTRY_KOSPI_LEVEL", "5400.0"))
    )
    exit_kospi_level: float = field(
        default_factory=lambda: float(os.getenv("EXIT_KOSPI_LEVEL", "6000.0"))
    )
    take_profit_pct: float = field(
        default_factory=lambda: float(os.getenv("TAKE_PROFIT_PCT", "0.20"))
    )
    take_profit_sell_ratio: float = field(
        default_factory=lambda: float(os.getenv("TAKE_PROFIT_SELL_RATIO", "0.50"))
    )
    margin_leverage: float = field(
        default_factory=lambda: float(os.getenv("MARGIN_LEVERAGE", "3.0"))
    )
    vkospi_option_add_threshold: float = field(
        default_factory=lambda: float(os.getenv("VKOSPI_OPTION_ADD_THRESHOLD", "30.0"))
    )

    def __post_init__(self) -> None:
        """Load ``.env`` and re-apply environment variables over field defaults.

        Called automatically by ``@dataclass`` after ``__init__``.
        Re-reads all KIS and Kakao credentials after ``load_dotenv()`` so
        that values defined in ``.env`` always take precedence over defaults
        set in ``default_factory`` lambdas that ran before ``load_dotenv()``.
        """
        load_dotenv()
        self.kis_app_key = os.getenv("KIS_APP_KEY", self.kis_app_key)
        self.kis_app_secret = os.getenv("KIS_APP_SECRET", self.kis_app_secret)
        self.kis_account_no = os.getenv("KIS_ACCOUNT_NO", self.kis_account_no)
        self.kis_is_real = os.getenv("KIS_IS_REAL", "true").lower() == "true"
        self.kakao_rest_api_key = os.getenv(
            "KAKAO_REST_API_KEY", self.kakao_rest_api_key
        )
        self.kakao_token_file = os.getenv("KAKAO_TOKEN_FILE", self.kakao_token_file)
        self.dev_mode = os.getenv("DEV_MODE", "false").lower() == "true"
        self.paper_trading = os.getenv("PAPER_TRADING", "false").lower() == "true"
        self.lev_call_enabled = (
            os.getenv("LEV_CALL_ENABLED", "false").lower() == "true"
        )
        self.lev_etf_symbol = os.getenv("LEV_ETF_SYMBOL", self.lev_etf_symbol)
        self.lev_etf_alloc = float(os.getenv("LEV_ETF_ALLOC", str(self.lev_etf_alloc)))
        self.call_option_alloc = float(
            os.getenv("CALL_OPTION_ALLOC", str(self.call_option_alloc))
        )
        self.call_strike = float(os.getenv("CALL_STRIKE", str(self.call_strike)))
        self.call_expiry_months = int(
            os.getenv("CALL_EXPIRY_MONTHS", str(self.call_expiry_months))
        )
        self.entry_kospi_level = float(
            os.getenv("ENTRY_KOSPI_LEVEL", str(self.entry_kospi_level))
        )
        self.exit_kospi_level = float(
            os.getenv("EXIT_KOSPI_LEVEL", str(self.exit_kospi_level))
        )
        self.take_profit_pct = float(
            os.getenv("TAKE_PROFIT_PCT", str(self.take_profit_pct))
        )
        self.take_profit_sell_ratio = float(
            os.getenv("TAKE_PROFIT_SELL_RATIO", str(self.take_profit_sell_ratio))
        )
        self.margin_leverage = float(
            os.getenv("MARGIN_LEVERAGE", str(self.margin_leverage))
        )
        self.vkospi_option_add_threshold = float(
            os.getenv(
                "VKOSPI_OPTION_ADD_THRESHOLD", str(self.vkospi_option_add_threshold)
            )
        )

    @property
    def kis_base_url(self) -> str:
        """KIS API base URL selected by the ``kis_is_real`` flag.

        Returns:
            Production URL when ``kis_is_real`` is ``True``, sandbox URL
            otherwise.
        """
        if self.kis_is_real:
            return "https://openapi.koreainvestment.com:9443"
        return "https://openapivts.koreainvestment.com:29443"
