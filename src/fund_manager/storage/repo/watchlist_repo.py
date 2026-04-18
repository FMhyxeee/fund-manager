"""Repository helpers for persisted watchlist entries."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from fund_manager.storage.models import WatchlistItem


class WatchlistRepository:
    """Read and mutate the fund watchlist."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_items(self, *, include_removed: bool = False) -> tuple[WatchlistItem, ...]:
        """Return watchlist entries in stable fund-code order."""
        statement = select(WatchlistItem).options(selectinload(WatchlistItem.fund))
        if not include_removed:
            statement = statement.where(WatchlistItem.removed_at.is_(None))
        statement = statement.join(WatchlistItem.fund).order_by(WatchlistItem.fund_id.asc())
        return tuple(self._session.execute(statement).scalars().all())

    def get_by_fund_id(self, fund_id: int) -> WatchlistItem | None:
        """Return a watchlist entry for one fund when present."""
        statement = (
            select(WatchlistItem)
            .options(selectinload(WatchlistItem.fund))
            .where(WatchlistItem.fund_id == fund_id)
            .limit(1)
        )
        return self._session.execute(statement).scalars().first()

    def upsert_active(
        self,
        *,
        fund_id: int,
        category: str | None,
        style_tags: tuple[str, ...],
        risk_level: str | None,
        note: str | None,
        source_name: str | None,
    ) -> tuple[WatchlistItem, bool, bool]:
        """Create, reactivate, or update one active watchlist entry."""
        existing = self.get_by_fund_id(fund_id)
        if existing is None:
            item = WatchlistItem(
                fund_id=fund_id,
                category=category,
                style_tags_json=list(style_tags),
                risk_level=risk_level,
                note=note,
                source_name=source_name,
            )
            self._session.add(item)
            self._session.flush()
            return item, True, False

        updated = False
        for field_name, field_value in {
            "category": category,
            "style_tags_json": list(style_tags),
            "risk_level": risk_level,
            "note": note,
            "source_name": source_name,
        }.items():
            if getattr(existing, field_name) != field_value:
                setattr(existing, field_name, field_value)
                updated = True

        if existing.removed_at is not None:
            existing.removed_at = None
            updated = True

        self._session.flush()
        return existing, False, updated

    def soft_remove(self, item: WatchlistItem) -> WatchlistItem:
        """Mark one watchlist entry as removed."""
        item.removed_at = datetime.now(UTC)
        self._session.flush()
        return item


__all__ = ["WatchlistRepository"]
