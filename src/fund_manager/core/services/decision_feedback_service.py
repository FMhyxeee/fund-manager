"""Capture manual feedback for deterministic decision actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from fund_manager.core.services.decision_reconciliation_service import (
    DecisionReconciliationService,
)
from fund_manager.storage.models import DecisionFeedbackStatus
from fund_manager.storage.repo import DecisionFeedbackRepository, DecisionRunRepository
from fund_manager.storage.repo.protocols import (
    DecisionFeedbackRepositoryProtocol,
    DecisionRunRepositoryProtocol,
)


class DecisionFeedbackError(Exception):
    """Base error for manual decision feedback operations."""


class DecisionRunNotFoundError(DecisionFeedbackError):
    """Raised when a feedback request references a missing decision run."""


class DecisionActionNotFoundError(DecisionFeedbackError):
    """Raised when a feedback request references a missing action index."""


@dataclass(frozen=True)
class DecisionFeedbackRecordResult:
    """Structured result returned after recording manual feedback."""

    feedback_id: int
    decision_run_id: int
    portfolio_id: int
    fund_id: int | None
    action_index: int
    action_type: str
    feedback_status: DecisionFeedbackStatus
    feedback_date: date
    linked_transaction_ids: tuple[int, ...]


class DecisionFeedbackService:
    """Validate and persist manual feedback against deterministic decision actions."""

    def __init__(
        self,
        session: Session,
        *,
        decision_run_repo: DecisionRunRepositoryProtocol | None = None,
        decision_feedback_repo: DecisionFeedbackRepositoryProtocol | None = None,
        reconciliation_service: DecisionReconciliationService | None = None,
    ) -> None:
        self._decision_run_repo = decision_run_repo or DecisionRunRepository(session)
        self._decision_feedback_repo = decision_feedback_repo or DecisionFeedbackRepository(session)
        self._reconciliation_service = reconciliation_service or DecisionReconciliationService(session)

    def record_feedback(
        self,
        *,
        decision_run_id: int,
        action_index: int,
        feedback_status: DecisionFeedbackStatus,
        feedback_date: date | None = None,
        note: str | None = None,
        created_by: str | None = None,
        reconcile_existing_transactions: bool = True,
    ) -> DecisionFeedbackRecordResult:
        """Append one manual feedback row for a deterministic action."""
        decision_run = self._decision_run_repo.get_by_id(decision_run_id)
        if decision_run is None:
            raise DecisionRunNotFoundError(f"Decision run {decision_run_id} was not found.")

        action = self._resolve_action_payload(
            actions_json=decision_run.actions_json,
            action_index=action_index,
        )
        action_type = str(action.get("action_type") or "").strip()
        if not action_type:
            raise DecisionActionNotFoundError(
                f"Action {action_index} on decision run {decision_run_id} has no action_type."
            )

        fund_id = self._coerce_optional_int(action.get("fund_id"))
        feedback = self._decision_feedback_repo.append(
            decision_run_id=decision_run.id,
            portfolio_id=decision_run.portfolio_id,
            fund_id=fund_id,
            action_index=action_index,
            action_type=action_type,
            feedback_status=feedback_status,
            feedback_date=feedback_date or date.today(),
            note=note,
            created_by=created_by,
        )

        linked_transaction_ids: tuple[int, ...] = ()
        if reconcile_existing_transactions:
            linked_transaction_ids = self._reconciliation_service.reconcile_feedback(feedback.id)

        return DecisionFeedbackRecordResult(
            feedback_id=feedback.id,
            decision_run_id=decision_run.id,
            portfolio_id=decision_run.portfolio_id,
            fund_id=fund_id,
            action_index=action_index,
            action_type=action_type,
            feedback_status=feedback.feedback_status,
            feedback_date=feedback.feedback_date,
            linked_transaction_ids=linked_transaction_ids,
        )

    def _resolve_action_payload(
        self,
        *,
        actions_json: list[dict[str, Any]] | dict[str, Any] | None,
        action_index: int,
    ) -> dict[str, Any]:
        if action_index < 0:
            raise DecisionActionNotFoundError("action_index must be zero or greater.")

        if isinstance(actions_json, list):
            if action_index >= len(actions_json):
                raise DecisionActionNotFoundError(
                    f"Action index {action_index} is out of range for this decision run."
                )
            action = actions_json[action_index]
            if not isinstance(action, dict):
                raise DecisionActionNotFoundError(
                    f"Action index {action_index} does not contain an object payload."
                )
            return action

        if isinstance(actions_json, dict) and action_index == 0:
            return actions_json

        raise DecisionActionNotFoundError(
            f"Decision run does not contain an action payload at index {action_index}."
        )

    @staticmethod
    def _coerce_optional_int(raw_value: Any) -> int | None:
        if raw_value is None or raw_value == "":
            return None
        return int(raw_value)


__all__ = [
    "DecisionActionNotFoundError",
    "DecisionFeedbackError",
    "DecisionFeedbackRecordResult",
    "DecisionFeedbackService",
    "DecisionRunNotFoundError",
]
