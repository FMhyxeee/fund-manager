"""Repository helpers for append-only position lot snapshots."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from fund_manager.storage.models import FundMaster, PositionLot


@dataclass(frozen=True)
class ActivePortfolioFund:
    """One actively held fund resolved from authoritative position lots."""

    fund_id: int
    fund_code: str
    fund_name: str


def resolve_authoritative_position_lots(
    position_lots: Iterable[PositionLot],
) -> tuple[PositionLot, ...]:
    """Resolve append-only lot rows to the authoritative lot set at one point in time."""
    latest_by_lot_key: dict[str, PositionLot] = {}
    for position_lot in position_lots:
        latest_by_lot_key[position_lot.lot_key] = position_lot

    bootstrap_batches: dict[str, list[PositionLot]] = {}
    tracked_lots: list[PositionLot] = []
    for position_lot in latest_by_lot_key.values():
        if position_lot.lot_key.startswith("initial:"):
            batch_key = position_lot.run_id or f"bootstrap:{position_lot.id}"
            bootstrap_batches.setdefault(batch_key, []).append(position_lot)
        else:
            tracked_lots.append(position_lot)

    if bootstrap_batches:
        latest_batch_key = max(
            bootstrap_batches,
            key=lambda batch_key: (
                max(lot.as_of_date for lot in bootstrap_batches[batch_key]),
                max(lot.id for lot in bootstrap_batches[batch_key]),
            ),
        )
        tracked_lots.extend(bootstrap_batches[latest_batch_key])

    return tuple(
        sorted(
            tracked_lots,
            key=lambda position_lot: (
                position_lot.fund.fund_code,
                position_lot.lot_key,
                position_lot.id,
            ),
        )
    )


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

    def list_active_funds_for_portfolio_up_to(
        self,
        *,
        portfolio_id: int,
        as_of_date: date,
    ) -> tuple[ActivePortfolioFund, ...]:
        """Return the actively held funds for one portfolio as of a given date."""
        position_lots = self.list_for_portfolio_up_to(
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
        )
        authoritative_lots = resolve_authoritative_position_lots(position_lots)
        active_funds: dict[int, FundMaster] = {}
        for position_lot in authoritative_lots:
            if position_lot.remaining_units <= 0:
                continue
            active_funds[position_lot.fund_id] = position_lot.fund

        return tuple(
            ActivePortfolioFund(
                fund_id=fund.id,
                fund_code=fund.fund_code,
                fund_name=fund.fund_name,
            )
            for fund in sorted(
                active_funds.values(),
                key=lambda fund: (fund.fund_code, fund.fund_name),
            )
        )
