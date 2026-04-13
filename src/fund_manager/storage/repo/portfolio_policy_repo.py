"""Repository helpers for append-only portfolio policy records."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from fund_manager.storage.models import PortfolioPolicy, PortfolioPolicyTarget


@dataclass(frozen=True)
class PortfolioPolicyTargetCreate:
    """Typed input for one fund-level policy target."""

    fund_id: int
    target_weight_ratio: Decimal
    min_weight_ratio: Decimal | None = None
    max_weight_ratio: Decimal | None = None
    add_allowed: bool = True
    trim_allowed: bool = True


class PortfolioPolicyRepository:
    """Persist and resolve effective portfolio policy snapshots."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_active_for_date(
        self,
        *,
        portfolio_id: int,
        as_of_date: date,
    ) -> PortfolioPolicy | None:
        """Return the most recent policy whose effective range covers one date."""
        statement = (
            select(PortfolioPolicy)
            .options(
                selectinload(PortfolioPolicy.targets).selectinload(PortfolioPolicyTarget.fund)
            )
            .where(
                PortfolioPolicy.portfolio_id == portfolio_id,
                PortfolioPolicy.effective_from <= as_of_date,
                or_(
                    PortfolioPolicy.effective_to.is_(None),
                    PortfolioPolicy.effective_to >= as_of_date,
                ),
            )
            .order_by(PortfolioPolicy.effective_from.desc(), PortfolioPolicy.id.desc())
            .limit(1)
        )
        return self._session.execute(statement).scalars().first()

    def get_by_run_id(self, run_id: str) -> PortfolioPolicy | None:
        """Fetch one policy snapshot by run ID."""
        statement = (
            select(PortfolioPolicy)
            .options(
                selectinload(PortfolioPolicy.targets).selectinload(PortfolioPolicyTarget.fund)
            )
            .where(PortfolioPolicy.run_id == run_id)
            .limit(1)
        )
        return self._session.execute(statement).scalars().first()

    def append(
        self,
        *,
        portfolio_id: int,
        policy_name: str,
        effective_from: date,
        rebalance_threshold_ratio: Decimal,
        targets: Sequence[PortfolioPolicyTargetCreate],
        effective_to: date | None = None,
        max_single_position_weight_ratio: Decimal | None = None,
        created_by: str | None = None,
        notes: str | None = None,
        run_id: str | None = None,
    ) -> PortfolioPolicy:
        """Append a new effective policy snapshot with its target allocations."""
        policy = PortfolioPolicy(
            portfolio_id=portfolio_id,
            run_id=run_id,
            policy_name=policy_name,
            effective_from=effective_from,
            effective_to=effective_to,
            rebalance_threshold_ratio=rebalance_threshold_ratio,
            max_single_position_weight_ratio=max_single_position_weight_ratio,
            created_by=created_by,
            notes=notes,
            targets=[
                PortfolioPolicyTarget(
                    fund_id=target.fund_id,
                    target_weight_ratio=target.target_weight_ratio,
                    min_weight_ratio=target.min_weight_ratio,
                    max_weight_ratio=target.max_weight_ratio,
                    add_allowed=target.add_allowed,
                    trim_allowed=target.trim_allowed,
                )
                for target in targets
            ],
        )
        self._session.add(policy)
        self._session.flush()
        return policy


__all__ = ["PortfolioPolicyRepository", "PortfolioPolicyTargetCreate"]
