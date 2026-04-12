"""Reconcile manual decision feedback against authoritative transactions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_manager.storage.models import (
    DecisionFeedback,
    DecisionFeedbackStatus,
    DecisionTransactionLink,
    TransactionRecord,
    TransactionType,
)
from fund_manager.storage.repo import (
    DecisionFeedbackRepository,
    DecisionTransactionLinkRepository,
)
from fund_manager.storage.repo.protocols import (
    DecisionFeedbackRepositoryProtocol,
    DecisionTransactionLinkRepositoryProtocol,
)

MATCH_WINDOW_DAYS = 14
ACTION_TO_TRADE_TYPES: dict[str, tuple[TransactionType, ...]] = {
    "add": (TransactionType.BUY, TransactionType.CONVERT_IN),
    "trim": (TransactionType.SELL, TransactionType.CONVERT_OUT),
}
TRADE_TYPE_TO_ACTION = {
    TransactionType.BUY: "add",
    TransactionType.CONVERT_IN: "add",
    TransactionType.SELL: "trim",
    TransactionType.CONVERT_OUT: "trim",
}


class DecisionReconciliationService:
    """Link manual decision feedback to imported authoritative transactions."""

    def __init__(
        self,
        session: Session,
        *,
        feedback_repo: DecisionFeedbackRepositoryProtocol | None = None,
        decision_transaction_link_repo: DecisionTransactionLinkRepositoryProtocol | None = None,
    ) -> None:
        self._session = session
        self._feedback_repo = feedback_repo or DecisionFeedbackRepository(session)
        self._decision_transaction_link_repo = (
            decision_transaction_link_repo or DecisionTransactionLinkRepository(session)
        )

    def reconcile_feedback(
        self,
        feedback_id: int,
        *,
        match_source: str = "feedback_recorded",
    ) -> tuple[int, ...]:
        """Link an executed feedback row to already-imported matching transactions."""
        feedback = self._feedback_repo.get_by_id(feedback_id)
        if feedback is None:
            return ()

        trade_types = ACTION_TO_TRADE_TYPES.get(feedback.action_type)
        if (
            feedback.feedback_status is not DecisionFeedbackStatus.EXECUTED
            or feedback.fund_id is None
            or not trade_types
        ):
            return ()

        window_end = feedback.feedback_date + timedelta(days=MATCH_WINDOW_DAYS)
        matching_transactions = self._session.execute(
            select(TransactionRecord)
            .outerjoin(
                DecisionTransactionLink,
                DecisionTransactionLink.transaction_id == TransactionRecord.id,
            )
            .where(
                TransactionRecord.portfolio_id == feedback.portfolio_id,
                TransactionRecord.fund_id == feedback.fund_id,
                TransactionRecord.trade_type.in_(trade_types),
                TransactionRecord.trade_date >= feedback.feedback_date,
                TransactionRecord.trade_date <= window_end,
                DecisionTransactionLink.transaction_id.is_(None),
            )
            .order_by(TransactionRecord.trade_date.asc(), TransactionRecord.id.asc())
        ).scalars().all()

        linked_transaction_ids: list[int] = []
        for transaction in matching_transactions:
            link = self._link_transaction(
                feedback=feedback,
                transaction=transaction,
                match_source=match_source,
            )
            if link is not None:
                linked_transaction_ids.append(transaction.id)
        return tuple(linked_transaction_ids)

    def reconcile_transactions(
        self,
        transactions: Sequence[TransactionRecord],
        *,
        match_source: str = "transaction_import",
    ) -> tuple[int, ...]:
        """Link newly imported transactions back to the latest matching executed feedback."""
        linked_transaction_ids: list[int] = []
        for transaction in sorted(
            (row for row in transactions if row.id is not None),
            key=lambda row: (row.trade_date, row.id),
        ):
            if self._transaction_already_linked(transaction.id):
                continue

            feedback = self._find_matching_feedback(transaction)
            if feedback is None:
                continue

            link = self._link_transaction(
                feedback=feedback,
                transaction=transaction,
                match_source=match_source,
            )
            if link is not None:
                linked_transaction_ids.append(transaction.id)
        return tuple(linked_transaction_ids)

    def _find_matching_feedback(self, transaction: TransactionRecord) -> DecisionFeedback | None:
        action_type = TRADE_TYPE_TO_ACTION.get(transaction.trade_type)
        if action_type is None:
            return None

        window_start = transaction.trade_date - timedelta(days=MATCH_WINDOW_DAYS)
        return self._session.execute(
            select(DecisionFeedback)
            .where(
                DecisionFeedback.portfolio_id == transaction.portfolio_id,
                DecisionFeedback.fund_id == transaction.fund_id,
                DecisionFeedback.action_type == action_type,
                DecisionFeedback.feedback_status == DecisionFeedbackStatus.EXECUTED,
                DecisionFeedback.feedback_date >= window_start,
                DecisionFeedback.feedback_date <= transaction.trade_date,
            )
            .order_by(DecisionFeedback.feedback_date.desc(), DecisionFeedback.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def _transaction_already_linked(self, transaction_id: int) -> bool:
        return (
            self._session.execute(
                select(DecisionTransactionLink.id)
                .where(DecisionTransactionLink.transaction_id == transaction_id)
                .limit(1)
            ).scalar_one_or_none()
            is not None
        )

    def _link_transaction(
        self,
        *,
        feedback: DecisionFeedback,
        transaction: TransactionRecord,
        match_source: str,
    ) -> DecisionTransactionLink | None:
        if transaction.id is None or self._transaction_already_linked(transaction.id):
            return None

        return self._decision_transaction_link_repo.append(
            feedback_id=feedback.id,
            transaction_id=transaction.id,
            match_source=match_source,
            match_reason=(
                "Matched on portfolio, fund, trade direction, and decision/transaction date window."
            ),
        )


__all__ = [
    "ACTION_TO_TRADE_TYPES",
    "DecisionReconciliationService",
    "MATCH_WINDOW_DAYS",
    "TRADE_TYPE_TO_ACTION",
]
