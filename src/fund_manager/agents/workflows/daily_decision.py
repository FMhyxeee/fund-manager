"""Deterministic daily decision workflow orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from fund_manager.core.serialization import serialize_for_json
from fund_manager.core.services import DECISION_ENGINE_NAME, DecisionService, PortfolioDecisionDTO
from fund_manager.storage.repo import DecisionRunRepository, SystemEventLogRepository
from fund_manager.storage.repo.protocols import (
    DecisionRunRepositoryProtocol,
    SystemEventLogRepositoryProtocol,
)

WORKFLOW_NAME = "daily_decision"


@dataclass(frozen=True)
class DailyDecisionWorkflowResult:
    """Structured result returned after a daily decision run completes."""

    run_id: str
    workflow_name: str
    portfolio_id: int
    decision_date: date
    decision_run_record_id: int
    decision: PortfolioDecisionDTO


class DailyDecisionWorkflow:
    """Coordinate the first deterministic daily decision workflow."""

    def __init__(
        self,
        session: Session,
        *,
        decision_service: DecisionService | None = None,
        decision_run_repo: DecisionRunRepositoryProtocol | None = None,
        system_event_log_repo: SystemEventLogRepositoryProtocol | None = None,
    ) -> None:
        self._session = session
        self._decision_service = decision_service or DecisionService(session)
        self._decision_run_repo = decision_run_repo or DecisionRunRepository(session)
        self._system_event_log_repo = system_event_log_repo or SystemEventLogRepository(session)

    def run(
        self,
        *,
        portfolio_id: int,
        decision_date: date,
        trigger_source: str = "manual",
        created_by: str | None = None,
        idempotency_key: str | None = None,
        run_id: str | None = None,
    ) -> DailyDecisionWorkflowResult:
        """Run the deterministic daily decision workflow for one portfolio."""
        resolved_run_id = run_id or build_daily_decision_run_id(decision_date)
        self._record_event(
            event_type="workflow_started",
            status="started",
            portfolio_id=portfolio_id,
            run_id=resolved_run_id,
            event_message="Daily decision workflow started.",
            payload_json={
                "decision_date": decision_date,
                "trigger_source": trigger_source,
                "created_by": created_by,
                "idempotency_key": idempotency_key,
            },
            commit=True,
        )

        try:
            decision = self._decision_service.evaluate_portfolio_decision(
                portfolio_id,
                as_of_date=decision_date,
            )
            self._record_event(
                event_type="decision_computed",
                status="completed",
                portfolio_id=portfolio_id,
                run_id=resolved_run_id,
                event_message="Deterministic decision result computed from canonical facts.",
                payload_json={
                    "policy_id": decision.policy_id,
                    "final_decision": decision.final_decision,
                    "action_count": decision.action_count,
                },
                commit=False,
            )

            decision_run = self._decision_run_repo.append(
                portfolio_id=portfolio_id,
                policy_id=decision.policy_id,
                decision_date=decision_date,
                summary=decision.summary,
                final_decision=decision.final_decision,
                trigger_source=trigger_source,
                actions_json=decision.to_dict()["actions"],
                decision_summary_json=decision.to_dict(),
                created_by_agent=DECISION_ENGINE_NAME,
                confidence_score=decision.confidence_score,
                run_id=resolved_run_id,
                workflow_name=WORKFLOW_NAME,
            )

            self._record_event(
                event_type="decision_persisted",
                status="completed",
                portfolio_id=portfolio_id,
                run_id=resolved_run_id,
                event_message="Daily decision artifact persisted.",
                payload_json={"decision_run_id": decision_run.id},
                commit=False,
            )
            self._record_event(
                event_type="workflow_completed",
                status="completed",
                portfolio_id=portfolio_id,
                run_id=resolved_run_id,
                event_message="Daily decision workflow completed successfully.",
                payload_json={
                    "decision_run_id": decision_run.id,
                    "final_decision": decision.final_decision,
                    "created_by": created_by,
                    "idempotency_key": idempotency_key,
                },
                commit=False,
            )
            self._session.commit()
        except Exception as exc:
            self._session.rollback()
            self._record_failure_event(
                portfolio_id=portfolio_id,
                run_id=resolved_run_id,
                decision_date=decision_date,
                trigger_source=trigger_source,
                created_by=created_by,
                idempotency_key=idempotency_key,
                error=exc,
            )
            raise

        return DailyDecisionWorkflowResult(
            run_id=resolved_run_id,
            workflow_name=WORKFLOW_NAME,
            portfolio_id=portfolio_id,
            decision_date=decision_date,
            decision_run_record_id=decision_run.id,
            decision=decision,
        )

    def _record_event(
        self,
        *,
        event_type: str,
        status: str,
        portfolio_id: int | None,
        run_id: str,
        event_message: str,
        payload_json: dict[str, Any],
        commit: bool,
    ) -> None:
        self._system_event_log_repo.append(
            event_type=event_type,
            status=status,
            portfolio_id=portfolio_id,
            run_id=run_id,
            workflow_name=WORKFLOW_NAME,
            event_message=event_message,
            payload_json=serialize_for_json(payload_json),
        )
        if commit:
            self._session.commit()

    def _record_failure_event(
        self,
        *,
        portfolio_id: int,
        run_id: str,
        decision_date: date,
        trigger_source: str,
        created_by: str | None,
        idempotency_key: str | None,
        error: Exception,
    ) -> None:
        try:
            self._record_event(
                event_type="workflow_failed",
                status="failed",
                portfolio_id=portfolio_id,
                run_id=run_id,
                event_message=f"{type(error).__name__}: {error}",
                payload_json={
                    "decision_date": decision_date,
                    "trigger_source": trigger_source,
                    "created_by": created_by,
                    "idempotency_key": idempotency_key,
                    "error_type": type(error).__name__,
                },
                commit=True,
            )
        except Exception:
            self._session.rollback()


def build_daily_decision_run_id(decision_date: date) -> str:
    """Generate a traceable run identifier for one daily decision execution."""
    return f"daily-decision-{decision_date:%Y%m%d}-{uuid4().hex[:8]}"


def run_daily_decision(
    session: Session,
    *,
    portfolio_id: int,
    decision_date: date,
    trigger_source: str = "manual",
) -> DailyDecisionWorkflowResult:
    """Convenience wrapper for running the deterministic daily decision workflow."""
    workflow = DailyDecisionWorkflow(session)
    return workflow.run(
        portfolio_id=portfolio_id,
        decision_date=decision_date,
        trigger_source=trigger_source,
    )


__all__ = [
    "WORKFLOW_NAME",
    "DailyDecisionWorkflow",
    "DailyDecisionWorkflowResult",
    "build_daily_decision_run_id",
    "run_daily_decision",
]
