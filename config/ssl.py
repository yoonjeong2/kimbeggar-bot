"""SSL verification helper shared across all HTTP clients.

Design intent
-------------
In development (DEV_MODE=true) the local Python certificate store may not
trust the certificates used by external APIs (KIS, Kakao).  Rather than
shipping ``verify=False`` everywhere unconditionally, we centralise the
decision here so that:

* Production / CI always uses full TLS verification (``verify=True``).
* Development environments opt-in by setting ``DEV_MODE=true`` in ``.env``.

A single change to ``.env`` is sufficient to restore strict verification
before deploying to production.
"""

import os

import urllib3


def ssl_verify() -> bool:
    """Return the appropriate SSL verification flag for the current environment.

    Reads the ``DEV_MODE`` environment variable at call-time (not at import
    time) so that ``load_dotenv()`` may be called after the module is first
    imported without affecting the result.

    Returns:
        ``False`` when ``DEV_MODE=true`` (development mode — SSL verification
        is intentionally bypassed).  ``True`` in all other cases so that TLS
        certificates are fully validated in production.
    """
    if os.getenv("DEV_MODE", "false").lower() == "true":
        # Suppress the urllib3 InsecureRequestWarning that is emitted for
        # every unverified HTTPS request.  This suppression is acceptable
        # in a local development environment only.
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return False
    return True
