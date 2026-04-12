"""Helpers for stable run identifiers and idempotency-friendly execution keys."""

from __future__ import annotations

from datetime import date
from hashlib import sha1
from uuid import uuid4


def resolve_run_id(
    *,
    prefix: str,
    scope_date: date,
    run_id: str | None = None,
    idempotency_key: str | None = None,
) -> str:
    """Resolve one run identifier from an explicit run ID or an idempotency key."""
    normalized_run_id = _normalize_optional_token(run_id)
    if normalized_run_id is not None:
        return normalized_run_id

    normalized_idempotency_key = _normalize_optional_token(idempotency_key)
    if normalized_idempotency_key is not None:
        suffix = sha1(normalized_idempotency_key.encode("utf-8")).hexdigest()[:8]
        return f"{prefix}-{scope_date:%Y%m%d}-{suffix}"

    return f"{prefix}-{scope_date:%Y%m%d}-{uuid4().hex[:8]}"


def _normalize_optional_token(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized


__all__ = ["resolve_run_id"]
