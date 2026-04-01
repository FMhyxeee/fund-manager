"""Repository helpers for append-only NAV snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_manager.storage.models import NavSnapshot


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
