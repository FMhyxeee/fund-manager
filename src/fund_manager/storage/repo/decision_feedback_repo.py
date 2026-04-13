"""Repository helpers for append-only manual decision feedback."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from fund_manager.storage.models import DecisionFeedback, DecisionFeedbackStatus


class DecisionFeedbackRepository:
    """Persist manual decision feedback records without mutating prior history."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, feedback_id: int) -> DecisionFeedback | None:
        """Fetch one manual decision feedback row by primary key."""
        return self._session.get(DecisionFeedback, feedback_id)

    def list_for_decision_run(self, decision_run_id: int) -> Sequence[DecisionFeedback]:
        """Return append-only feedback history for one decision run."""
        statement = (
            select(DecisionFeedback)
            .options(
                joinedload(DecisionFeedback.fund),
                selectinload(DecisionFeedback.transaction_links),
            )
            .where(DecisionFeedback.decision_run_id == decision_run_id)
            .order_by(DecisionFeedback.id.asc())
        )
        return tuple(self._session.execute(statement).scalars().all())

    def append(
        self,
        *,
        decision_run_id: int,
        portfolio_id: int,
        fund_id: int | None,
        action_index: int,
        action_type: str,
        feedback_status: DecisionFeedbackStatus,
        feedback_date: date,
        note: str | None = None,
        created_by: str | None = None,
    ) -> DecisionFeedback:
        """Append one manual feedback record for a deterministic action."""
        feedback = DecisionFeedback(
            decision_run_id=decision_run_id,
            portfolio_id=portfolio_id,
            fund_id=fund_id,
            action_index=action_index,
            action_type=action_type,
            feedback_status=feedback_status,
            feedback_date=feedback_date,
            note=note,
            created_by=created_by,
        )
        self._session.add(feedback)
        self._session.flush()
        return feedback


__all__ = ["DecisionFeedbackRepository"]
