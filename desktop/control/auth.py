"""Constant-time secret comparison that stays 401/403-safe across Python versions."""

from __future__ import annotations

import hmac


def secrets_match(supplied: object, expected: str) -> bool:
    """Return True when *supplied* equals *expected*.

    ``hmac.compare_digest`` raises ``ValueError`` on length mismatch in Python
    3.11 (Debian Bookworm). Map that case to False so a wrong token cannot
    become HTTP 500.
    """
    if not isinstance(supplied, str) or not isinstance(expected, str):
        return False
    left = supplied.encode("utf-8")
    right = expected.encode("utf-8")
    if len(left) != len(right):
        hmac.compare_digest(right, right)
        return False
    return hmac.compare_digest(left, right)
