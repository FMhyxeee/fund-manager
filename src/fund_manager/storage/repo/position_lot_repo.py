"""Repository helpers for append-only position lot snapshots."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from fund_manager.storage.models import PositionLot


class PositionLotRepository:
    """Create and read append-only lot snapshots."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_portfolio_up_to(
        self,
        *,
        portfolio_id: int,
        as_of_date: date,
    ) -> list[PositionLot]:
        """Return lot snapshots up to a requested date with fund metadata loaded."""
        statement = (
            select(PositionLot)
            .options(joinedload(PositionLot.fund))
            .where(
                PositionLot.portfolio_id == portfolio_id,
                PositionLot.as_of_date <= as_of_date,
            )
            .order_by(PositionLot.as_of_date.asc(), PositionLot.id.asc())
        )
        return list(self._session.execute(statement).scalars().unique())

    def append_import_snapshot(
        self,
        *,
        portfolio_id: int,
        fund_id: int,
        fund_code: str,
        as_of_date: date,
        run_id: str,
        remaining_units: Decimal,
        average_cost_per_unit: Decimal,
        total_cost_amount: Decimal,
    ) -> PositionLot:
        """Persist an imported opening lot without overwriting earlier snapshots."""
        # The initial holdings importer seeds one aggregate opening lot per
        # portfolio/fund snapshot. Later rebuild workflows can replace this
        # bootstrap path with transaction-derived lots, but this write path stays
        # append-only so earlier imports remain auditable.
        lot_key = f"initial:{fund_code}:{as_of_date:%Y%m%d}:{run_id[-8:]}"
        position_lot = PositionLot(
            portfolio_id=portfolio_id,
            fund_id=fund_id,
            run_id=run_id,
            lot_key=lot_key,
            opened_on=as_of_date,
            as_of_date=as_of_date,
            remaining_units=remaining_units,
            average_cost_per_unit=average_cost_per_unit,
            total_cost_amount=total_cost_amount,
        )
        self._session.add(position_lot)
        return position_lot
