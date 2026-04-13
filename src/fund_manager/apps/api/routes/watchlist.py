"""Watchlist API routes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from fund_manager.apps.api.dependencies import get_db
from fund_manager.core.serialization import serialize_for_json
from fund_manager.core.watchlist import FundWatchlistService

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


class WatchlistCandidateResponse(BaseModel):
    fund_code: str
    fund_name: str
    category: str
    fit_label: str
    reason: str
    caution: str
    risk_level: str
    score: float


class WatchlistCandidatesResponse(BaseModel):
    portfolio_id: int | None = None
    portfolio_name: str | None = None
    as_of_date: date
    risk_profile: str
    core_watchlist: list[WatchlistCandidateResponse] = Field(default_factory=list)
    extended_watchlist: list[WatchlistCandidateResponse] = Field(default_factory=list)


class WatchlistCandidateFitResponse(BaseModel):
    fund_code: str
    fund_name: str
    category: str
    fit_label: str
    overlap_level: str
    estimated_style_impact: str
    reasoning: str
    notes: list[str] = Field(default_factory=list)


class WatchlistStyleLeaderResponse(BaseModel):
    fund_code: str
    fund_name: str
    category: str
    latest_nav_date: date
    latest_unit_nav_amount: Decimal
    leader_reason: str
    caution: str


class WatchlistStyleLeadersResponse(BaseModel):
    as_of_date: date
    leaders: dict[str, list[WatchlistStyleLeaderResponse]] = Field(default_factory=dict)


@router.get("/candidates", response_model=WatchlistCandidatesResponse)
def get_watchlist_candidates(
    as_of_date: Annotated[date, Query()],
    portfolio_id: Annotated[int | None, Query()] = None,
    portfolio_name: Annotated[str | None, Query()] = None,
    risk_profile: Annotated[
        Literal["conservative", "balanced", "aggressive"],
        Query(),
    ] = "balanced",
    max_results: Annotated[int, Query(ge=1, le=20)] = 6,
    category: Annotated[list[str] | None, Query()] = None,
    include_high_overlap: Annotated[bool, Query()] = False,
    session: Annotated[Session, Depends(get_db)] = None,
) -> WatchlistCandidatesResponse:
    service = FundWatchlistService(session)
    try:
        result = service.build_watchlist_candidates(
            as_of_date=as_of_date,
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
            risk_profile=risk_profile,
            max_results=max_results,
            include_categories=tuple(category) if category else None,
            exclude_high_overlap=not include_high_overlap,
        )
    except ValueError as exc:
        raise _translate_watchlist_error(exc) from exc
    return WatchlistCandidatesResponse.model_validate(serialize_for_json(result))


@router.get("/fit", response_model=WatchlistCandidateFitResponse)
def get_watchlist_candidate_fit(
    fund_code: str,
    as_of_date: Annotated[date, Query()],
    portfolio_id: Annotated[int | None, Query()] = None,
    portfolio_name: Annotated[str | None, Query()] = None,
    session: Annotated[Session, Depends(get_db)] = None,
) -> WatchlistCandidateFitResponse:
    service = FundWatchlistService(session)
    try:
        result = service.analyze_candidate_fit(
            as_of_date=as_of_date,
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
            fund_code=fund_code,
        )
    except ValueError as exc:
        raise _translate_watchlist_error(exc) from exc
    return WatchlistCandidateFitResponse.model_validate(serialize_for_json(result))


@router.get("/style-leaders", response_model=WatchlistStyleLeadersResponse)
def get_watchlist_style_leaders(
    as_of_date: Annotated[date, Query()],
    category: Annotated[list[str] | None, Query()] = None,
    max_per_category: Annotated[int, Query(ge=1, le=10)] = 1,
    session: Annotated[Session, Depends(get_db)] = None,
) -> WatchlistStyleLeadersResponse:
    service = FundWatchlistService(session)
    result = service.build_style_leaders(
        as_of_date=as_of_date,
        categories=tuple(category) if category else None,
        max_per_category=max_per_category,
    )
    return WatchlistStyleLeadersResponse.model_validate(
        serialize_for_json({"as_of_date": as_of_date, "leaders": result})
    )


def _translate_watchlist_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    normalized = message.lower()
    if "portfolio" in normalized and "not found" in normalized:
        return HTTPException(status_code=404, detail="Portfolio not found")
    if "fund " in normalized and (
        "was not found" in normalized or "not configured in watchlist seed" in normalized
    ):
        return HTTPException(status_code=404, detail="Fund not found")
    return HTTPException(status_code=400, detail=message)
