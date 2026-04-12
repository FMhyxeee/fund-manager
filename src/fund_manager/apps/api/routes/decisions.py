"""Decision API routes for manual feedback capture."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from fund_manager.apps.api.dependencies import get_db
from fund_manager.core.services import (
    DecisionActionNotFoundError,
    DecisionFeedbackService,
    DecisionRunNotFoundError,
)
from fund_manager.storage.models import DecisionFeedback, DecisionFeedbackStatus, DecisionRun
from fund_manager.storage.repo import DecisionFeedbackRepository, DecisionRunRepository

router = APIRouter(prefix="/decisions", tags=["decisions"])


class DecisionRunListItemResponse(BaseModel):
    id: int
    portfolio_id: int
    portfolio_code: str
    portfolio_name: str
    policy_id: int | None = None
    policy_name: str | None = None
    run_id: str | None = None
    workflow_name: str | None = None
    decision_date: date
    trigger_source: str | None = None
    summary: str
    final_decision: str
    confidence_score: float | None = None
    action_count: int
    created_by_agent: str | None = None
    created_at: datetime


class DecisionRunDetailResponse(DecisionRunListItemResponse):
    actions_json: list[dict[str, Any]] | dict[str, Any] | None = None
    decision_summary_json: dict[str, Any] | list[Any] | None = None


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


class DecisionFeedbackResponse(BaseModel):
    id: int
    decision_run_id: int
    portfolio_id: int
    fund_id: int | None = None
    fund_code: str | None = None
    fund_name: str | None = None
    action_index: int
    action_type: str
    feedback_status: DecisionFeedbackStatus
    feedback_date: date
    note: str | None = None
    created_by: str | None = None
    linked_transaction_ids: list[int]
    created_at: datetime


@router.get("", response_model=list[DecisionRunListItemResponse])
def list_decision_runs(
    portfolio_id: Annotated[int | None, Query()] = None,
    decision_date: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    session: Annotated[Session, Depends(get_db)] = None,
) -> list[DecisionRunListItemResponse]:
    decision_runs = DecisionRunRepository(session).list_recent(
        portfolio_id=portfolio_id,
        decision_date=decision_date,
        limit=limit,
    )
    return [_build_decision_run_summary_response(decision_run) for decision_run in decision_runs]


@router.get("/{decision_run_id}", response_model=DecisionRunDetailResponse)
def get_decision_run(
    decision_run_id: int,
    session: Annotated[Session, Depends(get_db)],
) -> DecisionRunDetailResponse:
    decision_run = DecisionRunRepository(session).get_detail_by_id(decision_run_id)
    if decision_run is None:
        raise HTTPException(status_code=404, detail="Decision run not found")
    return _build_decision_run_detail_response(decision_run)


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


@router.get("/{decision_run_id}/feedback", response_model=list[DecisionFeedbackResponse])
def list_decision_feedback(
    decision_run_id: int,
    session: Annotated[Session, Depends(get_db)],
) -> list[DecisionFeedbackResponse]:
    decision_run_repo = DecisionRunRepository(session)
    if decision_run_repo.get_by_id(decision_run_id) is None:
        raise HTTPException(status_code=404, detail="Decision run not found")

    feedback_entries = DecisionFeedbackRepository(session).list_for_decision_run(decision_run_id)
    return [_build_decision_feedback_response(feedback) for feedback in feedback_entries]


def _build_decision_run_summary_response(decision_run: DecisionRun) -> DecisionRunListItemResponse:
    return DecisionRunListItemResponse(
        id=decision_run.id,
        portfolio_id=decision_run.portfolio_id,
        portfolio_code=decision_run.portfolio.portfolio_code,
        portfolio_name=decision_run.portfolio.portfolio_name,
        policy_id=decision_run.policy_id,
        policy_name=decision_run.policy.policy_name if decision_run.policy is not None else None,
        run_id=decision_run.run_id,
        workflow_name=decision_run.workflow_name,
        decision_date=decision_run.decision_date,
        trigger_source=decision_run.trigger_source,
        summary=decision_run.summary,
        final_decision=decision_run.final_decision,
        confidence_score=(
            float(decision_run.confidence_score)
            if decision_run.confidence_score is not None
            else None
        ),
        action_count=_count_actions(decision_run.actions_json),
        created_by_agent=decision_run.created_by_agent,
        created_at=decision_run.created_at,
    )


def _build_decision_run_detail_response(decision_run: DecisionRun) -> DecisionRunDetailResponse:
    summary = _build_decision_run_summary_response(decision_run)
    return DecisionRunDetailResponse(
        **summary.model_dump(),
        actions_json=decision_run.actions_json,
        decision_summary_json=decision_run.decision_summary_json,
    )


def _build_decision_feedback_response(feedback: DecisionFeedback) -> DecisionFeedbackResponse:
    linked_transaction_ids = sorted(
        transaction_link.transaction_id for transaction_link in feedback.transaction_links
    )
    return DecisionFeedbackResponse(
        id=feedback.id,
        decision_run_id=feedback.decision_run_id,
        portfolio_id=feedback.portfolio_id,
        fund_id=feedback.fund_id,
        fund_code=feedback.fund.fund_code if feedback.fund is not None else None,
        fund_name=feedback.fund.fund_name if feedback.fund is not None else None,
        action_index=feedback.action_index,
        action_type=feedback.action_type,
        feedback_status=feedback.feedback_status,
        feedback_date=feedback.feedback_date,
        note=feedback.note,
        created_by=feedback.created_by,
        linked_transaction_ids=linked_transaction_ids,
        created_at=feedback.created_at,
    )


def _count_actions(actions_json: list[dict[str, Any]] | dict[str, Any] | None) -> int:
    if isinstance(actions_json, list):
        return len(actions_json)
    if isinstance(actions_json, dict):
        return 1
    return 0
