"""Strategy proposal API routes."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from fund_manager.apps.api.dependencies import get_db
from fund_manager.storage.repo import StrategyProposalRepository

router = APIRouter(prefix="/strategy-proposals", tags=["strategy-proposals"])


class StrategyProposalDetailResponse(BaseModel):
    id: int
    portfolio_id: int
    portfolio_code: str
    portfolio_name: str
    run_id: str | None = None
    workflow_name: str | None = None
    proposal_date: date
    thesis: str
    evidence_json: dict[str, Any] | list[Any] | None = None
    recommended_actions_json: list[dict[str, Any]] | dict[str, Any] | None = None
    risk_notes: str | None = None
    counterarguments: str | None = None
    final_decision: str | None = None
    confidence_score: float | None = None
    created_by_agent: str | None = None
    created_at: datetime


@router.get("/{proposal_id}", response_model=StrategyProposalDetailResponse)
def get_strategy_proposal(
    proposal_id: int,
    session: Annotated[Session, Depends(get_db)],
) -> StrategyProposalDetailResponse:
    proposal = StrategyProposalRepository(session).get_by_id(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Strategy proposal not found")
    return _build_strategy_proposal_detail_response(proposal)


def _build_strategy_proposal_detail_response(
    proposal,
) -> StrategyProposalDetailResponse:
    return StrategyProposalDetailResponse(
        id=proposal.id,
        portfolio_id=proposal.portfolio_id,
        portfolio_code=proposal.portfolio.portfolio_code,
        portfolio_name=proposal.portfolio.portfolio_name,
        run_id=proposal.run_id,
        workflow_name=proposal.workflow_name,
        proposal_date=proposal.proposal_date,
        thesis=proposal.thesis,
        evidence_json=proposal.evidence_json,
        recommended_actions_json=proposal.recommended_actions_json,
        risk_notes=proposal.risk_notes,
        counterarguments=proposal.counterarguments,
        final_decision=proposal.final_decision,
        confidence_score=(
            float(proposal.confidence_score) if proposal.confidence_score is not None else None
        ),
        created_by_agent=proposal.created_by_agent,
        created_at=proposal.created_at,
    )
