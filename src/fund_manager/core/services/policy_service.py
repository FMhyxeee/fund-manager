"""Deterministic helpers for resolving effective portfolio policy snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from fund_manager.storage.repo import PortfolioPolicyRepository
from fund_manager.storage.repo.protocols import PortfolioPolicyRepositoryProtocol


@dataclass(frozen=True)
class PortfolioPolicyTargetDTO:
    """Resolved fund-level target weights for an active policy."""

    fund_id: int
    fund_code: str
    fund_name: str
    target_weight_ratio: Decimal
    min_weight_ratio: Decimal | None
    max_weight_ratio: Decimal | None
    add_allowed: bool
    trim_allowed: bool


@dataclass(frozen=True)
class PortfolioPolicyDTO:
    """JSON-safe shape for one effective portfolio policy."""

    policy_id: int
    portfolio_id: int
    run_id: str | None
    policy_name: str
    effective_from: date
    effective_to: date | None
    rebalance_threshold_ratio: Decimal
    max_single_position_weight_ratio: Decimal | None
    created_by: str | None
    notes: str | None
    targets: tuple[PortfolioPolicyTargetDTO, ...]


class PolicyService:
    """Resolve active policy snapshots into detached DTOs for deterministic services."""

    def __init__(
        self,
        session: Session,
        *,
        policy_repo: PortfolioPolicyRepositoryProtocol | None = None,
    ) -> None:
        self._policy_repo = policy_repo or PortfolioPolicyRepository(session)

    def get_active_policy(
        self,
        *,
        portfolio_id: int,
        as_of_date: date,
    ) -> PortfolioPolicyDTO | None:
        """Return the effective portfolio policy for one date when available."""
        policy = self._policy_repo.get_active_for_date(
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
        )
        if policy is None:
            return None

        targets = tuple(
            PortfolioPolicyTargetDTO(
                fund_id=target.fund_id,
                fund_code=target.fund.fund_code,
                fund_name=target.fund.fund_name,
                target_weight_ratio=target.target_weight_ratio,
                min_weight_ratio=target.min_weight_ratio,
                max_weight_ratio=target.max_weight_ratio,
                add_allowed=target.add_allowed,
                trim_allowed=target.trim_allowed,
            )
            for target in sorted(policy.targets, key=lambda item: (item.fund.fund_code, item.id))
        )
        return PortfolioPolicyDTO(
            policy_id=policy.id,
            portfolio_id=policy.portfolio_id,
            run_id=policy.run_id,
            policy_name=policy.policy_name,
            effective_from=policy.effective_from,
            effective_to=policy.effective_to,
            rebalance_threshold_ratio=policy.rebalance_threshold_ratio,
            max_single_position_weight_ratio=policy.max_single_position_weight_ratio,
            created_by=policy.created_by,
            notes=policy.notes,
            targets=targets,
        )


__all__ = ["PolicyService", "PortfolioPolicyDTO", "PortfolioPolicyTargetDTO"]
