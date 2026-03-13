"""
KIS (한국투자증권) API 연동 테스트 스크립트
1. OAuth 액세스 토큰 발급
2. 삼성전자(005930) 현재가 조회
"""

import os
import sys

import urllib3
import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()


def _ssl_verify() -> bool:
    """DEV_MODE=true(개발환경)일 때만 SSL 검증 비활성화"""
    if os.getenv("DEV_MODE", "false").lower() == "true":
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return False
    return True


APP_KEY = os.getenv("KIS_APP_KEY", "")
APP_SECRET = os.getenv("KIS_APP_SECRET", "")
IS_REAL = os.getenv("KIS_IS_REAL", "false").strip().lower() == "true"
BASE_URL = (
    "https://openapi.koreainvestment.com:9443"
    if IS_REAL
    else "https://openapivts.koreainvestment.com:29443"
)

SYMBOL = "005930"


def issue_token() -> str:
    url = f"{BASE_URL}/oauth2/tokenP"
    body = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
    }
    resp = requests.post(url, json=body, timeout=10, verify=_ssl_verify())
    if not resp.ok:
        print(f"[ERROR] 토큰 발급 실패 (HTTP {resp.status_code})")
        try:
            print(f"  응답: {resp.json()}")
        except ValueError:
            print(f"  응답: {resp.text}")
        sys.exit(1)
    data = resp.json()
    token = data.get("access_token")
    if not token:
        print(f"[ERROR] 응답에 access_token 없음: {data}")
        sys.exit(1)
    print(f"[토큰 발급 성공] expires_in={data.get('expires_in')}초")
    return token


def get_current_price(token: str, symbol: str) -> None:
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = {
        "Authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "FHKST01010100",
        "custtype": "P",
    }
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": symbol,
    }
    resp = requests.get(
        url, headers=headers, params=params, timeout=10, verify=_ssl_verify()
    )
    if not resp.ok:
        print(f"[ERROR] 시세 조회 실패 (HTTP {resp.status_code})")
        try:
            print(f"  응답: {resp.json()}")
        except ValueError:
            print(f"  응답: {resp.text}")
        sys.exit(1)

    data = resp.json()
    output = data.get("output", {})
    rt_cd = data.get("rt_cd")
    msg = data.get("msg1", "")

    if rt_cd != "0":
        print(f"[ERROR] API 오류 (rt_cd={rt_cd}): {msg}")
        print(f"  전체 응답: {data}")
        sys.exit(1)

    price = output.get("stck_prpr", "N/A")  # 현재가
    prev_close = output.get("stck_sdpr", "N/A")  # 전일종가
    change_rt = output.get("prdy_ctrt", "N/A")  # 전일대비율(%)
    volume = output.get("acml_vol", "N/A")  # 누적거래량

    print()
    print(f"{'=' * 40}")
    print(f"  삼성전자({symbol}) 현재가 조회 결과")
    print(f"{'=' * 40}")
    print(
        f"  현재가    : {int(price):,}원"
        if price != "N/A"
        else f"  현재가    : {price}"
    )
    print(
        f"  전일종가  : {int(prev_close):,}원"
        if prev_close != "N/A"
        else f"  전일종가  : {prev_close}"
    )
    print(f"  전일대비율: {change_rt}%")
    print(
        f"  누적거래량: {int(volume):,}주"
        if volume != "N/A"
        else f"  누적거래량: {volume}"
    )
    print(f"{'=' * 40}")
    print(f"  환경: {'실전투자' if IS_REAL else '모의투자'} | 서버: {BASE_URL}")
    print(f"{'=' * 40}")


def main() -> None:
    if not APP_KEY or not APP_SECRET:
        print("[ERROR] .env에 KIS_APP_KEY 또는 KIS_APP_SECRET이 없습니다.")
        sys.exit(1)

    print(f"KIS API 테스트 시작 ({'실전' if IS_REAL else '모의'} 투자 서버)")
    print(f"Base URL: {BASE_URL}\n")

    print("[1] 액세스 토큰 발급...")
    token = issue_token()

    print(f"\n[2] 삼성전자({SYMBOL}) 현재가 조회...")
    get_current_price(token, SYMBOL)


if __name__ == "__main__":
    main()
