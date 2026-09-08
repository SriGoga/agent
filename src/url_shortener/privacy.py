"""Visitor identification for unique-visitor analytics, without storing raw IPs.

The client IP is PII the moment it's queryable via an analytics endpoint. We hash it instead
of storing it raw -- see docs/brownfield-analysis.md for the reasoning.
"""
from __future__ import annotations

import hashlib
import os

_SALT_ENV_VAR = "URL_SHORTENER_IP_SALT"
_DEV_DEFAULT_SALT = "dev-salt-change-in-production"  # see docs/risks.md


def hash_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    salt = os.environ.get(_SALT_ENV_VAR, _DEV_DEFAULT_SALT)
    return hashlib.sha256(f"{salt}{ip}".encode("utf-8")).hexdigest()[:16]
