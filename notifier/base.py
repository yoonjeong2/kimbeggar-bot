"""Abstract base classes for the notification subsystem.

Architecture
------------
``BaseNotifier`` defines the interface contract every notification channel
must fulfil.  ``NotifierService`` is a *composite* that fans out to all
registered channels, implementing a lightweight **Observer** pattern:

* The trading core (subject) publishes events through ``NotifierService``
  without knowing which concrete channels are registered.
* Each ``BaseNotifier`` implementation (observer) handles delivery
  independently, making it trivial to add or remove channels at runtime.

Extending with a new channel (e.g. Telegram)::

    class TelegramNotifier(BaseNotifier):
        def send_message(self, text: str) -> bool: ...
        def send_signal(self, signal: Signal) -> bool: ...
        def send_error(self, error_msg: str) -> None: ...

    service = NotifierService([KakaoNotifier(settings)])
    service.register(TelegramNotifier(settings))   # zero changes to core
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import List, Optional

from strategy.signal import Signal


class BaseNotifier(ABC):
    """Abstract interface for all notification channel implementations.

    Every concrete notifier (Kakao, Telegram, Slack …) must implement the
    three delivery methods defined here.  The rest of the codebase depends
    on this abstraction rather than on any concrete class, satisfying the
    Dependency-Inversion Principle.
    """

    @abstractmethod
    def send_message(self, text: str) -> bool:
        """Send a plain-text message to this channel.

        Args:
            text: Message content.  Implementations may truncate long strings.

        Returns:
            ``True`` if the message was accepted by the remote service,
            ``False`` otherwise.
        """

    @abstractmethod
    def send_signal(self, signal: Signal) -> bool:
        """Format and deliver a trading-signal notification.

        Args:
            signal: The ``Signal`` object containing trade details.

        Returns:
            ``True`` if delivery succeeded, ``False`` otherwise.
        """

    @abstractmethod
    def send_error(self, error_msg: str) -> None:
        """Deliver an error / alert notification.

        Implementations should not raise exceptions; failures must be logged
        internally so that the caller's error-handling flow is not disrupted.

        Args:
            error_msg: Human-readable description of the error condition.
        """


class NotifierService(BaseNotifier):
    """Composite notifier that broadcasts to every registered channel.

    Implements ``BaseNotifier`` so it can itself be used wherever a single
    notifier is expected, enabling nested composition if required.

    Example:
        >>> service = NotifierService([KakaoNotifier(settings)])
        >>> service.register(TelegramNotifier(settings))
        >>> service.send_message("Bot started")   # delivered to both channels
    """

    def __init__(self, notifiers: Optional[List[BaseNotifier]] = None) -> None:
        """Initialise the service with an optional list of notifiers.

        Args:
            notifiers: Initial list of ``BaseNotifier`` instances.  More can
                be added later via :meth:`register`.
        """
        self._notifiers: List[BaseNotifier] = list(notifiers or [])
        self._logger = logging.getLogger(__name__)

    def register(self, notifier: BaseNotifier) -> None:
        """Register an additional notification channel at runtime.

        Args:
            notifier: Concrete ``BaseNotifier`` instance to add.
        """
        self._notifiers.append(notifier)

    def send_message(self, text: str) -> bool:
        """Broadcast a plain-text message to all registered channels.

        Args:
            text: Message content.

        Returns:
            ``True`` only when *all* channels report success.
        """
        results = [n.send_message(text) for n in self._notifiers]
        return all(results)

    def send_signal(self, signal: Signal) -> bool:
        """Broadcast a trading-signal notification to all registered channels.

        Args:
            signal: The ``Signal`` object to broadcast.

        Returns:
            ``True`` only when *all* channels report success.
        """
        results = [n.send_signal(signal) for n in self._notifiers]
        return all(results)

    def send_error(self, error_msg: str) -> None:
        """Broadcast an error notification to all registered channels.

        Args:
            error_msg: Human-readable description of the error condition.
        """
        for notifier in self._notifiers:
            notifier.send_error(error_msg)
