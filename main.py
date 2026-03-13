"""
메인 엔트리포인트
N분마다 Data Agent -> Strategy -> Notifier 호출 흐름을 관리하는 실행 루프
"""

import time
import schedule
import logging

from config.settings import Settings
from data_agent.kis_api import KISClient
from strategy.signal import SignalEngine
from notifier.kakao import KakaoNotifier
from logger.log_setup import setup_logger


def run_cycle(settings: Settings, kis_client: KISClient, signal_engine: SignalEngine, notifier: KakaoNotifier) -> None:
    """단일 모니터링 사이클 실행: 데이터 수집 -> 시그널 판별 -> 알림 전송"""
    logger = logging.getLogger(__name__)
    logger.info("모니터링 사이클 시작")

    for symbol in settings.watch_symbols:
        # 1. Data Agent: 시세 데이터 수집
        # 2. Strategy: 보조지표 계산 및 시그널 판별
        # 3. Notifier: 시그널 발생 시 카카오톡 알림 전송
        pass

    logger.info("모니터링 사이클 완료")


def main() -> None:
    """메인 함수: 초기화 및 스케줄 루프 실행"""
    settings = Settings()
    setup_logger()

    logger = logging.getLogger(__name__)
    logger.info("KimBeggar 봇 시작")

    kis_client = KISClient(settings)
    signal_engine = SignalEngine(settings)
    notifier = KakaoNotifier(settings)

    # N분마다 run_cycle 실행
    schedule.every(settings.monitor_interval_minutes).minutes.do(
        run_cycle, settings, kis_client, signal_engine, notifier
    )

    # 시작 즉시 1회 실행
    run_cycle(settings, kis_client, signal_engine, notifier)

    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
