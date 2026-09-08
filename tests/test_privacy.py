"""Unit tests for IP hashing (docs/brownfield-analysis.md: never store raw IPs)."""
from __future__ import annotations

from url_shortener.privacy import hash_ip


def test_hash_ip_is_deterministic():
    assert hash_ip("203.0.113.5") == hash_ip("203.0.113.5")


def test_hash_ip_differs_for_different_inputs():
    assert hash_ip("203.0.113.5") != hash_ip("203.0.113.6")


def test_hash_ip_does_not_contain_the_raw_ip():
    ip = "203.0.113.5"
    assert ip not in hash_ip(ip)


def test_hash_ip_none_for_missing_ip():
    assert hash_ip(None) is None
    assert hash_ip("") is None
