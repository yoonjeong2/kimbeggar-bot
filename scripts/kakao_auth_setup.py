"""
카카오 OAuth 최초 인증 스크립트
최초 1회 실행하여 access_token / refresh_token 발급 및 저장
"""

import json
import os
import sys
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlparse, parse_qs

import requests
import urllib3
from dotenv import load_dotenv


def _ssl_verify() -> bool:
    """DEV_MODE=true(개발환경)일 때만 SSL 검증 비활성화"""
    if os.getenv("DEV_MODE", "false").lower() == "true":
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return False
    return True

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from notifier.kakao_token_manager import KakaoTokenManager


AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
REDIRECT_URI = "https://localhost"


def main() -> None:
    load_dotenv()

    rest_api_key = os.getenv("KAKAO_REST_API_KEY", "")
    token_file = os.getenv("KAKAO_TOKEN_FILE", "data/kakao_token.json")

    if not rest_api_key:
        print("[ERROR] .env 파일에 KAKAO_REST_API_KEY가 설정되지 않았습니다.")
        sys.exit(1)

    # 1단계: 인증 URL 출력
    params = {
        "client_id": rest_api_key,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "talk_message",
    }
    auth_url = f"{AUTH_URL}?{urlencode(params)}"

    print("=" * 60)
    print("카카오 OAuth 인증 절차")
    print("=" * 60)
    print("\n1. 아래 URL을 브라우저에서 열고 카카오 계정으로 로그인하세요:\n")
    print(f"  {auth_url}\n")
    print("2. 동의 후 리다이렉트된 URL 전체를 복사하세요.")
    print("   (예: https://localhost?code=ABCDEFG...)\n")

    # 2단계: 사용자로부터 리다이렉트 URL 또는 code 입력
    redirected = input("리다이렉트된 URL 또는 code만 붙여넣기: ").strip()

    if redirected.startswith("http"):
        parsed = urlparse(redirected)
        code = parse_qs(parsed.query).get("code", [None])[0]
    else:
        code = redirected

    if not code:
        print("[ERROR] code를 추출할 수 없습니다. URL 또는 code를 다시 확인하세요.")
        sys.exit(1)

    # 3단계: code → token 교환
    payload = {
        "grant_type": "authorization_code",
        "client_id": rest_api_key,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }

    print("\n토큰 발급 중...")
    try:
        resp = requests.post(TOKEN_URL, data=payload, timeout=10, verify=_ssl_verify())
        if not resp.ok:
            print(f"[ERROR] 토큰 발급 요청 실패 (HTTP {resp.status_code})")
            try:
                print(f"  응답 본문: {resp.json()}")
            except ValueError:
                print(f"  응답 본문: {resp.text}")
            sys.exit(1)
        token_data = resp.json()
    except requests.RequestException as e:
        print(f"[ERROR] 토큰 발급 요청 실패: {e}")
        sys.exit(1)

    if "error" in token_data:
        print(f"[ERROR] 토큰 발급 실패: {token_data.get('error')} - {token_data.get('error_description')}")
        sys.exit(1)

    # 만료 시각 계산
    now = datetime.now()
    token_data["access_token_expires_at"] = (
        now + timedelta(seconds=token_data.get("expires_in", 21600))
    ).isoformat()
    token_data["refresh_token_expires_at"] = (
        now + timedelta(seconds=token_data.get("refresh_token_expires_in", 5184000))
    ).isoformat()

    # 4단계: 토큰 파일 저장
    manager = KakaoTokenManager(token_file=token_file, rest_api_key=rest_api_key)
    manager.save(token_data)
    print(f"\n토큰 저장 완료: {token_file}")

    # 5단계: 테스트 메시지 전송
    print("\n카카오톡 테스트 메시지 전송 중...")
    from notifier.kakao import KakaoNotifier
    from config.settings import Settings

    settings = Settings()
    notifier = KakaoNotifier(settings)
    success = notifier.send_message("카카오 알림 설정 완료! KimBeggar 봇이 연결되었습니다.")

    if success:
        print("[성공] 카카오톡 '나에게 보내기'로 테스트 메시지가 전송되었습니다.")
    else:
        print("[실패] 테스트 메시지 전송 실패. 로그를 확인하세요.")

    print("\n설정 완료. python main.py 로 봇을 실행할 수 있습니다.")


if __name__ == "__main__":
    main()
