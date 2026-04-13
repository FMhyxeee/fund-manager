"""Repository helpers for append-only NAV snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_manager.storage.models import NavSnapshot


@dataclass(frozen=True)
class NavSnapshotCreate:
    """One append-only NAV row to persist."""

    nav_date: date
    unit_nav_amount: Decimal
    accumulated_nav_amount: Decimal | None = None
    daily_return_ratio: Decimal | None = None
    source_name: str | None = None
    source_reference: str | None = None


class NavSnapshotRepository:
    """Read NAV snapshots for valuation and analytics services."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_funds_up_to(
        self,
        *,
        fund_ids: Sequence[int],
        as_of_date: date,
    ) -> list[NavSnapshot]:
        """Return NAV history for a set of funds up to a requested date."""
        if not fund_ids:
            return []

        statement = (
            select(NavSnapshot)
            .where(
                NavSnapshot.fund_id.in_(tuple(fund_ids)),
                NavSnapshot.nav_date <= as_of_date,
            )
            .order_by(NavSnapshot.nav_date.asc(), NavSnapshot.id.asc())
        )
        return list(self._session.execute(statement).scalars())

    def get_latest_nav_date(
        self,
        *,
        fund_id: int,
    ) -> date | None:
        """Return the latest stored NAV date for one fund."""
        statement = (
            select(NavSnapshot.nav_date)
            .where(NavSnapshot.fund_id == fund_id)
            .order_by(NavSnapshot.nav_date.desc(), NavSnapshot.id.desc())
            .limit(1)
        )
        return self._session.execute(statement).scalars().first()

    def append_many(
        self,
        *,
        fund_id: int,
        snapshots: Sequence[NavSnapshotCreate],
    ) -> int:
        """Append multiple NAV snapshots for one fund."""
        for snapshot in snapshots:
            self._session.add(
                NavSnapshot(
                    fund_id=fund_id,
                    nav_date=snapshot.nav_date,
                    unit_nav_amount=snapshot.unit_nav_amount,
                    accumulated_nav_amount=snapshot.accumulated_nav_amount,
                    daily_return_ratio=snapshot.daily_return_ratio,
                    source_name=snapshot.source_name,
                    source_reference=snapshot.source_reference,
                )
            )
        return len(snapshots)
