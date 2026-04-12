"""Repository helpers for append-only deterministic decision runs."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from fund_manager.storage.models import DecisionRun


class DecisionRunRepository:
    """Persist deterministic daily decision artifacts without mutating history."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, decision_run_id: int) -> DecisionRun | None:
        """Fetch one deterministic decision run by primary key."""
        return self._session.get(DecisionRun, decision_run_id)

    def get_detail_by_id(self, decision_run_id: int) -> DecisionRun | None:
        """Fetch one decision run with portfolio and policy metadata loaded."""
        statement = (
            select(DecisionRun)
            .options(
                joinedload(DecisionRun.portfolio),
                joinedload(DecisionRun.policy),
            )
            .where(DecisionRun.id == decision_run_id)
        )
        return self._session.execute(statement).scalars().first()

    def get_detail_by_run_id(self, run_id: str) -> DecisionRun | None:
        """Fetch one decision run by run ID with portfolio and policy metadata loaded."""
        statement = (
            select(DecisionRun)
            .options(
                joinedload(DecisionRun.portfolio),
                joinedload(DecisionRun.policy),
            )
            .where(DecisionRun.run_id == run_id)
            .limit(1)
        )
        return self._session.execute(statement).scalars().first()

    def list_recent(
        self,
        *,
        portfolio_id: int | None = None,
        decision_date: date | None = None,
        limit: int = 20,
    ) -> Sequence[DecisionRun]:
        """List recent decision runs in reverse chronological order."""
        statement = (
            select(DecisionRun)
            .options(
                joinedload(DecisionRun.portfolio),
                joinedload(DecisionRun.policy),
            )
            .order_by(DecisionRun.decision_date.desc(), DecisionRun.id.desc())
            .limit(limit)
        )
        if portfolio_id is not None:
            statement = statement.where(DecisionRun.portfolio_id == portfolio_id)
        if decision_date is not None:
            statement = statement.where(DecisionRun.decision_date == decision_date)
        return tuple(self._session.execute(statement).scalars().all())

    def append(
        self,
        *,
        portfolio_id: int,
        decision_date: date,
        summary: str,
        final_decision: str,
        trigger_source: str | None,
        actions_json: list[dict[str, Any]] | dict[str, Any] | None,
        decision_summary_json: dict[str, Any] | list[Any] | None,
        created_by_agent: str | None,
        policy_id: int | None = None,
        confidence_score: Decimal | None = None,
        run_id: str | None = None,
        workflow_name: str | None = None,
    ) -> DecisionRun:
        """Append one persisted deterministic decision run artifact."""
        decision_run = DecisionRun(
            portfolio_id=portfolio_id,
            policy_id=policy_id,
            run_id=run_id,
            workflow_name=workflow_name,
            decision_date=decision_date,
            trigger_source=trigger_source,
            summary=summary,
            final_decision=final_decision,
            confidence_score=confidence_score,
            actions_json=actions_json,
            decision_summary_json=decision_summary_json,
            created_by_agent=created_by_agent,
        )
        self._session.add(decision_run)
        self._session.flush()
        return decision_run


__all__ = ["DecisionRunRepository"]
