"""Reusable request metadata models for write and workflow endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class WriteRequestMetadata(BaseModel):
    """Shared metadata fields for append-only write requests."""

    created_by: str | None = None
    run_id: str | None = None
    idempotency_key: str | None = None


class WorkflowRequestMetadata(WriteRequestMetadata):
    """Shared metadata fields for workflow trigger requests."""

    trigger_source: str = "api"


__all__ = ["WorkflowRequestMetadata", "WriteRequestMetadata"]
