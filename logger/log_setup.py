"""Logging configuration module.

Sets up a daily-rotating file handler and a console handler on the root
logger.  Also provides a lightweight ``gettext``-based i18n skeleton so
log messages can be translated at runtime by swapping locale catalogues.

i18n quick-start
----------------
1. Create a message catalogue directory::

       locale/ko_KR/LC_MESSAGES/

2. Generate a ``.po`` template with ``pygettext`` or ``xgettext``::

       xgettext -d kimbeggar -o locale/kimbeggar.pot **/*.py

3. Compile the ``.po`` file to a binary ``.mo``::

       msgfmt locale/ko_KR/LC_MESSAGES/kimbeggar.po \\
              -o locale/ko_KR/LC_MESSAGES/kimbeggar.mo

4. Activate at application startup (before any log calls)::

       from logger.log_setup import configure_i18n
       configure_i18n("ko_KR")
"""

from __future__ import annotations

import gettext
import logging
import logging.handlers
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# File / format constants
# ---------------------------------------------------------------------------

LOG_DIR: Path = Path(__file__).parent.parent / "logs"
LOG_FILE: Path = LOG_DIR / "bot.log"
LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"

# ---------------------------------------------------------------------------
# i18n skeleton — gettext translation support
# ---------------------------------------------------------------------------

#: Directory that holds ``<locale>/LC_MESSAGES/<domain>.mo`` catalogues.
_locale_dir: Path = Path(__file__).parent.parent / "locale"

#: Active translation object.  Defaults to ``NullTranslations`` (pass-through)
#: so the application works correctly even without any ``.mo`` files.
_translation: gettext.NullTranslations = gettext.NullTranslations()


def configure_i18n(
    locale_name: str = "en_US",
    domain: str = "kimbeggar",
) -> None:
    """Load a gettext message catalogue for the given locale.

    Call this **once** at application startup, before any translated messages
    are logged.  If the catalogue file cannot be found the module falls back
    to a pass-through (no-op) translation and the application continues to
    work with the original source strings.

    Catalogue files are expected at::

        locale/<locale_name>/LC_MESSAGES/<domain>.mo

    Args:
        locale_name: POSIX locale string, e.g. ``"ko_KR"`` for Korean or
            ``"en_US"`` for English (default).
        domain:      Message catalogue domain (default ``"kimbeggar"``).
    """
    global _translation  # noqa: PLW0603
    try:
        _translation = gettext.translation(
            domain=domain,
            localedir=str(_locale_dir),
            languages=[locale_name],
        )
    except FileNotFoundError:
        # Catalogue not found — silently keep NullTranslations.
        _translation = gettext.NullTranslations()


def _(message: str) -> str:  # noqa: N802
    """Translate *message* using the currently active locale catalogue.

    Wrap any log string with ``_()`` to make it translatable::

        from logger.log_setup import _
        logger.info(_("Monitoring cycle started."))

    Args:
        message: Source (English) message string.

    Returns:
        Translated string, or the original *message* when no translation
        is available for the active locale.
    """
    return _translation.gettext(message)


# ---------------------------------------------------------------------------
# Logger initialisation
# ---------------------------------------------------------------------------


def setup_logger(level: int = logging.INFO) -> None:
    """Configure the root logger with a rotating file handler and console handler.

    - File handler   : ``logs/bot.log``, rotated at midnight, 30-day retention.
    - Console handler: writes to stdout.

    Args:
        level: Logging level (default ``logging.INFO``).
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # Daily rotating file handler — rolls over at midnight, keeps 30 days.
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=LOG_FILE,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.suffix = "%Y-%m-%d"

    # Console handler — writes to stdout.
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
