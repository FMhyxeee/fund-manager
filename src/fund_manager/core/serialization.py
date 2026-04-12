"""Shared JSON-safe serialization helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import date
from decimal import Decimal
from typing import Any


def serialize_for_json(value: Any) -> Any:
    """Convert dataclasses, dates, and decimals into JSON-safe values."""
    if is_dataclass(value) and not isinstance(value, type):
        return serialize_for_json(asdict(value))
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): serialize_for_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [serialize_for_json(item) for item in value]
    if isinstance(value, list):
        return [serialize_for_json(item) for item in value]
    return value


__all__ = ["serialize_for_json"]
