"""Unit tests for collision-safe code generation (F6), isolated from the API/storage layers."""
from __future__ import annotations

import pytest

from url_shortener.codegen import CollisionExhaustedError, generate_code, generate_unique_code


def test_generate_code_length_and_alphabet():
    code = generate_code()
    assert len(code) == 7
    assert code.isalnum()


def test_generate_unique_code_retries_past_a_collision():
    seen = {"AAAAAAA"}  # first attempt "collides" via a stubbed exists_fn

    calls = {"n": 0}

    def exists_fn(code: str) -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            return True  # force a collision on the first attempt
        return code in seen

    code = generate_unique_code(exists_fn)
    assert code not in seen
    assert calls["n"] >= 2


def test_generate_unique_code_raises_after_exhausting_retries():
    with pytest.raises(CollisionExhaustedError):
        generate_unique_code(lambda code: True)
