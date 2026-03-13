"""
로깅 설정 모듈
일자별 로테이팅 파일 핸들러 및 콘솔 핸들러 설정
"""

import logging
import logging.handlers
import os
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_FILE = LOG_DIR / "bot.log"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logger(level: int = logging.INFO) -> None:
    """
    루트 로거 설정
    - 파일 핸들러: logs/bot.log, 일자별 로테이션, 최대 30일 보관
    - 콘솔 핸들러: stdout 출력

    Args:
        level: 로깅 레벨 (기본값: logging.INFO)
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # 일자별 로테이팅 파일 핸들러 (자정 교체, 30일 보관)
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=LOG_FILE,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.suffix = "%Y-%m-%d"

    # 콘솔 핸들러
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
