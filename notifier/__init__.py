"""Notification subsystem public API.

Import the interface and composite service from here to avoid coupling
consumer code to concrete implementation modules.

Example:
    >>> from notifier import BaseNotifier, NotifierService
    >>> from notifier.kakao import KakaoNotifier
"""

from notifier.base import BaseNotifier, NotifierService

__all__ = ["BaseNotifier", "NotifierService"]
