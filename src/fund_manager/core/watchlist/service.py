"""Persistent watchlist service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from fund_manager.storage.models import WatchlistItem
from fund_manager.storage.repo import FundMasterRepository, WatchlistRepository
from fund_manager.storage.repo.protocols import (
    FundMasterRepositoryProtocol,
    WatchlistRepositoryProtocol,
)

_DEFAULT_SOURCE_NAME = "watchlist_api"
_MAX_FUND_CODE_LENGTH = 32
_MAX_FUND_NAME_LENGTH = 255
_MAX_CATEGORY_LENGTH = 64
_MAX_RISK_LEVEL_LENGTH = 64
_MAX_SOURCE_NAME_LENGTH = 64


@dataclass(frozen=True)
class WatchlistItemDTO:
    """JSON-safe watchlist entry contract."""

    watchlist_item_id: int
    fund_id: int
    fund_code: str
    fund_name: str
    category: str | None
    style_tags: tuple[str, ...]
    risk_level: str | None
    note: str | None
    source_name: str | None
    created_at: datetime
    updated_at: datetime
    removed_at: datetime | None


@dataclass(frozen=True)
class WatchlistAddResult:
    """Structured outcome for a watchlist add operation."""

    item: WatchlistItemDTO
    fund_created: bool
    fund_updated: bool
    watchlist_created: bool
    watchlist_updated: bool


class FundWatchlistService:
    """Manage the operator's fund observation list."""

    def __init__(
        self,
        session: Session,
        *,
        fund_repo: FundMasterRepositoryProtocol | None = None,
        watchlist_repo: WatchlistRepositoryProtocol | None = None,
    ) -> None:
        self._session = session
        self._fund_repo = fund_repo or FundMasterRepository(session)
        self._watchlist_repo = watchlist_repo or WatchlistRepository(session)

    def list_items(self, *, include_removed: bool = False) -> tuple[WatchlistItemDTO, ...]:
        """List watchlist entries."""
        return tuple(
            self._to_dto(item)
            for item in self._watchlist_repo.list_items(include_removed=include_removed)
        )

    def add_item(
        self,
        *,
        fund_code: str,
        fund_name: str,
        category: str | None = None,
        style_tags: tuple[str, ...] = (),
        risk_level: str | None = None,
        note: str | None = None,
        source_name: str | None = _DEFAULT_SOURCE_NAME,
    ) -> WatchlistAddResult:
        """Add or reactivate one fund in the watchlist."""
        normalized_fund_code = self._normalize_required_text(
            fund_code,
            field_name="fund_code",
            max_length=_MAX_FUND_CODE_LENGTH,
        )
        normalized_fund_name = self._normalize_required_text(
            fund_name,
            field_name="fund_name",
            max_length=_MAX_FUND_NAME_LENGTH,
        )
        normalized_source_name = self._normalize_optional_text(
            source_name,
            field_name="source_name",
            max_length=_MAX_SOURCE_NAME_LENGTH,
        ) or _DEFAULT_SOURCE_NAME
        fund_result = self._fund_repo.upsert(
            fund_code=normalized_fund_code,
            fund_name=normalized_fund_name,
            source_name=normalized_source_name,
        )
        item, watchlist_created, watchlist_updated = self._watchlist_repo.upsert_active(
            fund_id=fund_result.fund.id,
            category=self._normalize_optional_text(
                category,
                field_name="category",
                max_length=_MAX_CATEGORY_LENGTH,
            ),
            style_tags=self._normalize_style_tags(style_tags),
            risk_level=self._normalize_optional_text(
                risk_level,
                field_name="risk_level",
                max_length=_MAX_RISK_LEVEL_LENGTH,
            ),
            note=self._normalize_optional_text(note, field_name="note"),
            source_name=normalized_source_name,
        )
        self._session.flush()
        return WatchlistAddResult(
            item=self._to_dto(item),
            fund_created=fund_result.created,
            fund_updated=fund_result.updated,
            watchlist_created=watchlist_created,
            watchlist_updated=watchlist_updated,
        )

    def remove_item(self, *, fund_code: str) -> WatchlistItemDTO:
        """Remove one fund from the active watchlist."""
        normalized_fund_code = self._normalize_required_text(
            fund_code,
            field_name="fund_code",
            max_length=_MAX_FUND_CODE_LENGTH,
        )
        fund = self._fund_repo.get_by_code(normalized_fund_code)
        if fund is None:
            msg = f"Fund '{normalized_fund_code}' was not found."
            raise ValueError(msg)

        item = self._watchlist_repo.get_by_fund_id(fund.id)
        if item is None or item.removed_at is not None:
            msg = f"Fund '{normalized_fund_code}' is not in the active watchlist."
            raise ValueError(msg)

        removed = self._watchlist_repo.soft_remove(item)
        self._session.flush()
        return self._to_dto(removed)

    def _to_dto(self, item: WatchlistItem) -> WatchlistItemDTO:
        raw_tags = item.style_tags_json or []
        style_tags = tuple(str(tag) for tag in raw_tags) if isinstance(raw_tags, list) else ()
        return WatchlistItemDTO(
            watchlist_item_id=item.id,
            fund_id=item.fund_id,
            fund_code=item.fund.fund_code,
            fund_name=item.fund.fund_name,
            category=item.category,
            style_tags=style_tags,
            risk_level=item.risk_level,
            note=item.note,
            source_name=item.source_name,
            created_at=item.created_at,
            updated_at=item.updated_at,
            removed_at=item.removed_at,
        )

    def _normalize_style_tags(self, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            tag = self._normalize_optional_text(value, field_name="style_tags")
            if tag is None or tag in seen:
                continue
            normalized.append(tag)
            seen.add(tag)
        return tuple(normalized)

    def _normalize_required_text(
        self,
        value: str,
        *,
        field_name: str,
        max_length: int,
    ) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            msg = f"{field_name} cannot be blank."
            raise ValueError(msg)
        if len(normalized_value) > max_length:
            msg = f"{field_name} cannot exceed {max_length} characters."
            raise ValueError(msg)
        return normalized_value

    def _normalize_optional_text(
        self,
        value: str | None,
        *,
        field_name: str,
        max_length: int | None = None,
    ) -> str | None:
        if value is None:
            return None
        normalized_value = value.strip()
        if not normalized_value:
            return None
        if max_length is not None and len(normalized_value) > max_length:
            msg = f"{field_name} cannot exceed {max_length} characters."
            raise ValueError(msg)
        return normalized_value


__all__ = [
    "FundWatchlistService",
    "WatchlistAddResult",
    "WatchlistItemDTO",
]
