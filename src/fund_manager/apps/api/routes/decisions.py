"""Decision API routes for manual feedback capture."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from fund_manager.apps.api.dependencies import get_db
from fund_manager.core.services import (
    DecisionActionNotFoundError,
    DecisionFeedbackService,
    DecisionRunNotFoundError,
)
from fund_manager.storage.models import DecisionFeedbackStatus

router = APIRouter(prefix="/decisions", tags=["decisions"])


class DecisionFeedbackCreateRequest(BaseModel):
    action_index: int
    feedback_status: DecisionFeedbackStatus
    feedback_date: date | None = None
    note: str | None = None
    created_by: str | None = None


class DecisionFeedbackCreateResponse(BaseModel):
    feedback_id: int
    decision_run_id: int
    portfolio_id: int
    fund_id: int | None = None
    action_index: int
    action_type: str
    feedback_status: DecisionFeedbackStatus
    feedback_date: date
    linked_transaction_ids: list[int]
    message: str


@router.post("/{decision_run_id}/feedback", response_model=DecisionFeedbackCreateResponse)
def create_decision_feedback(
    decision_run_id: int,
    request: DecisionFeedbackCreateRequest,
    session: Annotated[Session, Depends(get_db)],
) -> DecisionFeedbackCreateResponse:
    try:
        result = DecisionFeedbackService(session).record_feedback(
            decision_run_id=decision_run_id,
            action_index=request.action_index,
            feedback_status=request.feedback_status,
            feedback_date=request.feedback_date,
            note=request.note,
            created_by=request.created_by,
        )
    except DecisionRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except DecisionActionNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return DecisionFeedbackCreateResponse(
        feedback_id=result.feedback_id,
        decision_run_id=result.decision_run_id,
        portfolio_id=result.portfolio_id,
        fund_id=result.fund_id,
        action_index=result.action_index,
        action_type=result.action_type,
        feedback_status=result.feedback_status,
        feedback_date=result.feedback_date,
        linked_transaction_ids=list(result.linked_transaction_ids),
        message=f"Recorded {result.feedback_status.value} feedback for action {result.action_index}.",
    )
