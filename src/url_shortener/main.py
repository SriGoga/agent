"""The URL Shortener FastAPI app: F1-F6, N1-N4 from docs/requirements.md."""
from __future__ import annotations

import os
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from url_shortener.codegen import CollisionExhaustedError, generate_unique_code
from url_shortener.models import AnalyticsResponse, LinkCreateRequest, LinkResponse
from url_shortener.ratelimit import RateLimiter
from url_shortener.storage import Link, LinkRepository

DB_PATH = os.environ.get("URL_SHORTENER_DB_PATH", "url_shortener.db")

app = FastAPI(title="URL Shortener")

_repo = LinkRepository(DB_PATH)
_rate_limiter = RateLimiter(max_requests=10, window_seconds=60)


def get_repo() -> LinkRepository:
    return _repo


def get_rate_limiter() -> RateLimiter:
    return _rate_limiter


def _to_response(link: Link) -> LinkResponse:
    return LinkResponse(
        code=link.code,
        target_url=link.target_url,
        owner_id=link.owner_id,
        created_at=link.created_at,
        expires_at=link.expires_at,
    )


# Specific paths are declared before the catch-all "/{code}" redirect route below --
# Starlette matches routes in registration order, not by specificity.


@app.post("/links", response_model=LinkResponse, status_code=201)
def create_link(
    payload: LinkCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    repo: LinkRepository = Depends(get_repo),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> LinkResponse:
    if idempotency_key:
        existing_code = repo.find_idempotent_code(idempotency_key, payload.owner_id)
        if existing_code:
            existing = repo.get_link(existing_code)
            if existing is not None:
                return _to_response(existing)

    if not rate_limiter.allow(payload.owner_id):
        raise HTTPException(status_code=429, detail="rate limit exceeded")

    if payload.custom_alias:
        if repo.code_exists(payload.custom_alias):
            raise HTTPException(status_code=409, detail="alias already taken")
        code = payload.custom_alias
    else:
        try:
            code = generate_unique_code(repo.code_exists)
        except CollisionExhaustedError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    expires_at = time.time() + payload.ttl_seconds if payload.ttl_seconds else None
    link = repo.create_link(code, str(payload.target_url), payload.owner_id, expires_at)

    if idempotency_key:
        repo.save_idempotency_key(idempotency_key, payload.owner_id, code)

    return _to_response(link)


@app.get("/links", response_model=list[LinkResponse])
def list_links(owner_id: str, repo: LinkRepository = Depends(get_repo)) -> list[LinkResponse]:
    return [_to_response(link) for link in repo.list_links(owner_id)]


@app.get("/links/{code}/analytics", response_model=AnalyticsResponse)
def get_analytics(code: str, owner_id: str, repo: LinkRepository = Depends(get_repo)) -> AnalyticsResponse:
    link = repo.get_link(code)
    if link is None or link.owner_id != owner_id or link.deleted_at is not None:
        raise HTTPException(status_code=404, detail="not found")
    data = repo.analytics(code)
    return AnalyticsResponse(code=code, **data)


@app.delete("/links/{code}", status_code=204)
def delete_link(code: str, owner_id: str, repo: LinkRepository = Depends(get_repo)) -> Response:
    if not repo.soft_delete(code, owner_id):
        raise HTTPException(status_code=404, detail="not found")
    return Response(status_code=204)


@app.get("/{code}")
def redirect(code: str, request: Request, repo: LinkRepository = Depends(get_repo)):
    link = repo.get_link(code)
    if link is None or link.deleted_at is not None:
        raise HTTPException(status_code=404, detail="not found")
    if link.expires_at is not None and link.expires_at < time.time():
        raise HTTPException(status_code=410, detail="expired")
    repo.record_click(code, request.headers.get("referer"), request.headers.get("user-agent"))
    return RedirectResponse(url=link.target_url, status_code=307)
