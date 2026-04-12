"""Policy API routes for reading and appending portfolio policy snapshots."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from fund_manager.apps.api.dependencies import get_db
from fund_manager.core.services import PolicyService
from fund_manager.storage.repo import (
    FundMasterRepository,
    PortfolioPolicyRepository,
    PortfolioPolicyTargetCreate,
    PortfolioRepository,
)

router = APIRouter(prefix="/policies", tags=["policies"])


class PolicyTargetResponse(BaseModel):
    fund_id: int
    fund_code: str
    fund_name: str
    target_weight_ratio: Decimal
    min_weight_ratio: Decimal | None = None
    max_weight_ratio: Decimal | None = None
    add_allowed: bool
    trim_allowed: bool


class PolicyResponse(BaseModel):
    policy_id: int
    portfolio_id: int
    policy_name: str
    effective_from: date
    effective_to: date | None = None
    rebalance_threshold_ratio: Decimal
    max_single_position_weight_ratio: Decimal | None = None
    created_by: str | None = None
    notes: str | None = None
    targets: list[PolicyTargetResponse]


class PolicyTargetCreateRequest(BaseModel):
    fund_code: str
    target_weight_ratio: Decimal
    min_weight_ratio: Decimal | None = None
    max_weight_ratio: Decimal | None = None
    add_allowed: bool = True
    trim_allowed: bool = True


class PolicyCreateRequest(BaseModel):
    portfolio_id: int
    policy_name: str
    effective_from: date
    rebalance_threshold_ratio: Decimal
    targets: list[PolicyTargetCreateRequest] = Field(min_length=1)
    effective_to: date | None = None
    max_single_position_weight_ratio: Decimal | None = None
    created_by: str | None = None
    notes: str | None = None
    run_id: str | None = None


@router.get("/active", response_model=PolicyResponse)
def get_active_policy(
    portfolio_id: Annotated[int, Query()],
    as_of_date: Annotated[date | None, Query()] = None,
    session: Annotated[Session, Depends(get_db)] = None,
) -> PolicyResponse:
    portfolio = PortfolioRepository(session).get_by_id(portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    policy = PolicyService(session).get_active_policy(
        portfolio_id=portfolio_id,
        as_of_date=as_of_date or date.today(),
    )
    if policy is None:
        raise HTTPException(status_code=404, detail="Active policy not found")

    return _build_policy_response(policy)


@router.post("", response_model=PolicyResponse, status_code=status.HTTP_201_CREATED)
def create_policy(
    request: PolicyCreateRequest,
    session: Annotated[Session, Depends(get_db)],
) -> PolicyResponse:
    portfolio = PortfolioRepository(session).get_by_id(request.portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    targets = _resolve_policy_targets(request.targets, session)
    policy_repo = PortfolioPolicyRepository(session)
    policy_repo.append(
        portfolio_id=request.portfolio_id,
        policy_name=request.policy_name,
        effective_from=request.effective_from,
        effective_to=request.effective_to,
        rebalance_threshold_ratio=request.rebalance_threshold_ratio,
        max_single_position_weight_ratio=request.max_single_position_weight_ratio,
        created_by=request.created_by,
        notes=request.notes,
        run_id=request.run_id,
        targets=targets,
    )
    session.commit()

    policy = PolicyService(session).get_active_policy(
        portfolio_id=request.portfolio_id,
        as_of_date=request.effective_from,
    )
    if policy is None:
        raise HTTPException(status_code=500, detail="Created policy could not be reloaded")

    return _build_policy_response(policy)


def _resolve_policy_targets(
    target_requests: list[PolicyTargetCreateRequest],
    session: Session,
) -> tuple[PortfolioPolicyTargetCreate, ...]:
    normalized_codes: set[str] = set()
    targets: list[PortfolioPolicyTargetCreate] = []
    fund_repo = FundMasterRepository(session)

    for target in target_requests:
        fund_code = target.fund_code.strip()
        if not fund_code:
            raise HTTPException(status_code=400, detail="fund_code cannot be blank")
        if fund_code in normalized_codes:
            raise HTTPException(
                status_code=400,
                detail=f"Duplicate fund_code '{fund_code}' in policy targets",
            )
        normalized_codes.add(fund_code)
        _validate_policy_target_ranges(target)

        fund = fund_repo.get_by_code(fund_code)
        if fund is None:
            raise HTTPException(status_code=400, detail=f"Fund '{fund_code}' was not found")

        targets.append(
            PortfolioPolicyTargetCreate(
                fund_id=fund.id,
                target_weight_ratio=target.target_weight_ratio,
                min_weight_ratio=target.min_weight_ratio,
                max_weight_ratio=target.max_weight_ratio,
                add_allowed=target.add_allowed,
                trim_allowed=target.trim_allowed,
            )
        )

    return tuple(targets)


def _validate_policy_target_ranges(target: PolicyTargetCreateRequest) -> None:
    if target.min_weight_ratio is not None and target.max_weight_ratio is not None:
        if target.min_weight_ratio > target.max_weight_ratio:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Target range for fund '{target.fund_code}' is invalid: "
                    "min_weight_ratio cannot exceed max_weight_ratio"
                ),
            )
    if target.min_weight_ratio is not None and target.min_weight_ratio > target.target_weight_ratio:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Target range for fund '{target.fund_code}' is invalid: "
                "min_weight_ratio cannot exceed target_weight_ratio"
            ),
        )
    if target.max_weight_ratio is not None and target.max_weight_ratio < target.target_weight_ratio:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Target range for fund '{target.fund_code}' is invalid: "
                "max_weight_ratio cannot be below target_weight_ratio"
            ),
        )


def _build_policy_response(policy: object) -> PolicyResponse:
    from fund_manager.core.services import PortfolioPolicyDTO

    assert isinstance(policy, PortfolioPolicyDTO)
    return PolicyResponse(
        policy_id=policy.policy_id,
        portfolio_id=policy.portfolio_id,
        policy_name=policy.policy_name,
        effective_from=policy.effective_from,
        effective_to=policy.effective_to,
        rebalance_threshold_ratio=policy.rebalance_threshold_ratio,
        max_single_position_weight_ratio=policy.max_single_position_weight_ratio,
        created_by=policy.created_by,
        notes=policy.notes,
        targets=[
            PolicyTargetResponse(
                fund_id=target.fund_id,
                fund_code=target.fund_code,
                fund_name=target.fund_name,
                target_weight_ratio=target.target_weight_ratio,
                min_weight_ratio=target.min_weight_ratio,
                max_weight_ratio=target.max_weight_ratio,
                add_allowed=target.add_allowed,
                trim_allowed=target.trim_allowed,
            )
            for target in policy.targets
        ],
    )


__all__ = [
    "router",
]
