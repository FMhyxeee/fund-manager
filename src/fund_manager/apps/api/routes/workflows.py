"""Workflow API routes for triggering manual workflow runs."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from fund_manager.apps.api.dependencies import get_db
from fund_manager.agents.workflows.daily_decision import DailyDecisionWorkflow
from fund_manager.agents.workflows.strategy_debate import StrategyDebateWorkflow
from fund_manager.agents.workflows.weekly_review import WeeklyReviewWorkflow
from fund_manager.core.serialization import serialize_for_json
from fund_manager.core.services import FundDataSyncService, PortfolioService
from fund_manager.core.services.portfolio_service import (
    IncompletePortfolioSnapshotError,
    PortfolioNotFoundError,
)
from fund_manager.storage.models import Portfolio
from sqlalchemy import select

router = APIRouter(prefix="/workflows", tags=["workflows"])


class DailySnapshotRunRequest(BaseModel):
    portfolio_id: int
    as_of_date: date | None = None
    trigger_source: str = "api"


class DailyDecisionRunRequest(BaseModel):
    portfolio_id: int
    decision_date: date | None = None
    trigger_source: str = "api"


class DailySnapshotRunResponse(BaseModel):
    run_id: str
    workflow_name: str
    portfolio_id: int
    as_of_date: date
    sync: dict[str, Any]
    snapshot: dict[str, Any]
    message: str


class DailyDecisionRunResponse(BaseModel):
    run_id: str
    workflow_name: str
    portfolio_id: int
    decision_date: date
    decision_run_id: int
    final_decision: str
    action_count: int
    decision: dict[str, Any]
    message: str


class WeeklyReviewRunRequest(BaseModel):
    portfolio_id: int
    period_start: date | None = None
    period_end: date | None = None


class WeeklyReviewRunResponse(BaseModel):
    run_id: str
    portfolio_id: int
    period_start: date
    period_end: date
    report_record_id: int
    message: str


class MonthlyStrategyDebateRunRequest(BaseModel):
    portfolio_id: int
    period_start: date | None = None
    period_end: date | None = None
    trigger_source: str = "api"


class MonthlyStrategyDebateRunResponse(BaseModel):
    run_id: str
    workflow_name: str
    portfolio_id: int
    period_start: date
    period_end: date
    strategy_proposal_record_id: int
    final_decision: str
    confidence_score: float
    strategy_output: dict[str, Any]
    challenger_output: dict[str, Any]
    judge_output: dict[str, Any]
    message: str


@router.post("/daily-snapshot/run", response_model=DailySnapshotRunResponse)
def run_daily_snapshot(
    request: DailySnapshotRunRequest,
    session: Annotated[Session, Depends(get_db)],
) -> DailySnapshotRunResponse:
    portfolio = session.execute(
        select(Portfolio).where(Portfolio.id == request.portfolio_id)
    ).scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    as_of_date = request.as_of_date or date.today()
    workflow_name = "daily_snapshot"
    run_id = f"daily-snapshot-{as_of_date:%Y%m%d}-{uuid4().hex[:8]}"

    try:
        sync_result = FundDataSyncService(session).sync_portfolio_funds(
            request.portfolio_id,
            as_of_date=as_of_date,
        )
        session.commit()
        snapshot = PortfolioService(session).save_portfolio_snapshot(
            request.portfolio_id,
            as_of_date=as_of_date,
            run_id=run_id,
            workflow_name=workflow_name,
        )
    except PortfolioNotFoundError:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    except IncompletePortfolioSnapshotError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return DailySnapshotRunResponse(
        run_id=run_id,
        workflow_name=workflow_name,
        portfolio_id=request.portfolio_id,
        as_of_date=as_of_date,
        sync=serialize_for_json(sync_result.to_dict()),
        snapshot=serialize_for_json(snapshot.to_dict()),
        message=f"Daily snapshot completed. Run ID: {run_id}",
    )


@router.post("/daily-decision/run", response_model=DailyDecisionRunResponse)
def run_daily_decision(
    request: DailyDecisionRunRequest,
    session: Annotated[Session, Depends(get_db)],
) -> DailyDecisionRunResponse:
    portfolio = session.execute(
        select(Portfolio).where(Portfolio.id == request.portfolio_id)
    ).scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    workflow = DailyDecisionWorkflow(session)
    try:
        result = workflow.run(
            portfolio_id=request.portfolio_id,
            decision_date=request.decision_date or date.today(),
            trigger_source=request.trigger_source,
        )
    except PortfolioNotFoundError:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    decision_payload = serialize_for_json(result.decision.to_dict())
    return DailyDecisionRunResponse(
        run_id=result.run_id,
        workflow_name=result.workflow_name,
        portfolio_id=result.portfolio_id,
        decision_date=result.decision_date,
        decision_run_id=result.decision_run_record_id,
        final_decision=result.decision.final_decision,
        action_count=result.decision.action_count,
        decision=decision_payload,
        message=f"Daily decision completed. Run ID: {result.run_id}",
    )


@router.post(
    "/monthly-strategy-debate/run",
    response_model=MonthlyStrategyDebateRunResponse,
)
def run_monthly_strategy_debate(
    request: MonthlyStrategyDebateRunRequest,
    session: Annotated[Session, Depends(get_db)],
) -> MonthlyStrategyDebateRunResponse:
    portfolio = session.execute(
        select(Portfolio).where(Portfolio.id == request.portfolio_id)
    ).scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    period_end = request.period_end or date.today()
    period_start = request.period_start or period_end.replace(day=1)

    workflow = StrategyDebateWorkflow(session)
    try:
        result = workflow.run(
            portfolio_id=request.portfolio_id,
            period_start=period_start,
            period_end=period_end,
            trigger_source=request.trigger_source,
        )
    except PortfolioNotFoundError:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return MonthlyStrategyDebateRunResponse(
        run_id=result.run_id,
        workflow_name=result.workflow_name,
        portfolio_id=result.portfolio_id,
        period_start=result.period_start,
        period_end=result.period_end,
        strategy_proposal_record_id=result.strategy_proposal_record_id,
        final_decision=result.judge_output.final_judgment,
        confidence_score=float(result.judge_output.confidence_score),
        strategy_output=serialize_for_json(asdict(result.strategy_output)),
        challenger_output=serialize_for_json(asdict(result.challenger_output)),
        judge_output=serialize_for_json(asdict(result.judge_output)),
        message=f"Monthly strategy debate completed. Run ID: {result.run_id}",
    )


@router.post("/weekly-review/run", response_model=WeeklyReviewRunResponse)
def run_weekly_review(
    request: WeeklyReviewRunRequest,
    session: Annotated[Session, Depends(get_db)],
) -> WeeklyReviewRunResponse:
    portfolio = session.execute(
        select(Portfolio).where(Portfolio.id == request.portfolio_id)
    ).scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    period_start = request.period_start
    period_end = request.period_end
    if period_end is None:
        period_end = date.today()
    if period_start is None:
        from datetime import timedelta
        period_start = period_end - timedelta(days=7)

    workflow = WeeklyReviewWorkflow(session)
    try:
        result = workflow.run(
            portfolio_id=request.portfolio_id,
            period_start=period_start,
            period_end=period_end,
        )
    except PortfolioNotFoundError:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    session.commit()

    return WeeklyReviewRunResponse(
        run_id=result.run_id,
        portfolio_id=result.portfolio_id,
        period_start=result.period_start,
        period_end=result.period_end,
        report_record_id=result.report_record_id,
        message=f"Weekly review completed. Run ID: {result.run_id}",
    )
