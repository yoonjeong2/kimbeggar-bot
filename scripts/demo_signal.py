"""MVP demo: generate a dummy signal and send it via Kakao Talk.

Run this to verify your Kakao credentials and notification format
**without** connecting to the KIS API.  No real stock data is fetched.

Usage
-----
::

    python scripts/demo_signal.py                # sends a BUY demo
    python scripts/demo_signal.py --type SELL
    python scripts/demo_signal.py --type STOP_LOSS
    python scripts/demo_signal.py --type HEDGE
    python scripts/demo_signal.py --dry-run      # print only, do not send
"""

from __future__ import annotations

import argparse
import sys

# Allow running from the project root without installing the package.
sys.path.insert(0, ".")

from config.settings import Settings  # noqa: E402
from notifier.kakao import KakaoNotifier  # noqa: E402
from strategy.signal import Signal, SignalType  # noqa: E402

# ---------------------------------------------------------------------------
# Pre-built demo signals — realistic Samsung Electronics (005930) values
# ---------------------------------------------------------------------------
_DEMO_SIGNALS: dict = {
    "BUY": Signal(
        symbol="005930",
        signal_type=SignalType.BUY,
        price=71_500.0,
        reason="RSI=28.3 (≤30) + golden cross (MA5 crossed above MA20)",
        rsi=28.3,
        ma_short=70_800.0,
        ma_long=69_500.0,
    ),
    "SELL": Signal(
        symbol="005930",
        signal_type=SignalType.SELL,
        price=75_200.0,
        reason="RSI=72.1 (≥70) + dead cross (MA5 crossed below MA20)",
        rsi=72.1,
        ma_short=74_800.0,
        ma_long=75_300.0,
    ),
    "STOP_LOSS": Signal(
        symbol="005930",
        signal_type=SignalType.STOP_LOSS,
        price=67_900.0,
        reason="Stop-loss triggered: entry 71,500 → 67,900 (-5.0%)",
        rsi=35.2,
        ma_short=68_200.0,
        ma_long=69_500.0,
    ),
    "HEDGE": Signal(
        symbol="KOSPI",
        signal_type=SignalType.HEDGE,
        price=2_480.0,
        reason="KOSPI down -2.1% (≤-1.5%)",
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send a demo trading signal via Kakao Talk"
    )
    parser.add_argument(
        "--type",
        choices=list(_DEMO_SIGNALS),
        default="BUY",
        help="Signal type to send (default: BUY)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the formatted message without sending it",
    )
    args = parser.parse_args()

    settings = Settings()
    notifier = KakaoNotifier(settings)
    signal = _DEMO_SIGNALS[args.type]

    # Show what the message looks like
    formatted = notifier._format_signal_message(signal)  # noqa: SLF001
    print()
    print("─" * 50)
    print(formatted)
    print("─" * 50)
    print(f"  Length: {len(formatted)} / 200 chars")
    print()

    if args.dry_run:
        print("[dry-run] Message NOT sent.")
        return 0

    print(f"Sending {args.type} demo signal via Kakao Talk…")
    success = notifier.send_signal(signal)

    if success:
        print("✓  Message sent successfully!  Check your KakaoTalk.")
        return 0
    else:
        print("✗  Failed to send. Check your .env credentials and kakao_token.json.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
