"""
카카오톡 메시지 전송 테스트 스크립트
저장된 kakao_token.json을 읽어 '나에게 보내기'로 테스트 메시지를 전송
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from notifier.kakao_token_manager import KakaoTokenManager
from notifier.kakao import KakaoNotifier
from config.settings import Settings


def main() -> None:
    load_dotenv()

    settings = Settings()
    notifier = KakaoNotifier(settings)

    print("카카오톡 테스트 메시지 전송 중...")
    success = notifier.send_message("김거지 봇 테스트 성공!")

    if success:
        print("[성공] 카카오톡으로 테스트 메시지가 전송되었습니다.")
    else:
        print("[실패] 메시지 전송에 실패했습니다. 로그를 확인하세요.")
        sys.exit(1)


if __name__ == "__main__":
    main()
