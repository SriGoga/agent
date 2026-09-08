"""Collision-safe short code generation (requirement F6)."""
from __future__ import annotations

import secrets
import string
from typing import Callable

ALPHABET = string.ascii_letters + string.digits  # base62
CODE_LENGTH = 7
MAX_COLLISION_RETRIES = 5


class CollisionExhaustedError(Exception):
    """Raised if every generation attempt collided with an existing code."""


def generate_code(length: int = CODE_LENGTH) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def generate_unique_code(exists_fn: Callable[[str], bool]) -> str:
    """Retries on collision instead of trusting randomness alone -- F6."""
    for _ in range(MAX_COLLISION_RETRIES):
        code = generate_code()
        if not exists_fn(code):
            return code
    raise CollisionExhaustedError(f"failed to generate a unique code after {MAX_COLLISION_RETRIES} attempts")
