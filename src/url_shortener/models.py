"""Pydantic request/response schemas -- also the input validation layer (requirement N1)."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, HttpUrl, field_validator

ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")


class LinkCreateRequest(BaseModel):
    target_url: HttpUrl  # Pydantic restricts this to http(s) schemes -- rejects e.g. file://, javascript:
    owner_id: str = Field(min_length=1, max_length=128)
    custom_alias: str | None = None
    ttl_seconds: int | None = Field(default=None, gt=0)

    @field_validator("custom_alias")
    @classmethod
    def validate_alias(cls, v: str | None) -> str | None:
        if v is not None and not ALIAS_RE.match(v):
            raise ValueError("custom_alias must be 3-32 chars of letters, digits, '-' or '_'")
        return v


class LinkResponse(BaseModel):
    code: str
    target_url: str
    owner_id: str
    created_at: float
    expires_at: float | None


class AnalyticsResponse(BaseModel):
    code: str
    click_count: int
    first_click_at: float | None
    last_click_at: float | None
    referrers: dict[str, int]
    unique_visitors: int
    unique_visitors_last_24h: int
