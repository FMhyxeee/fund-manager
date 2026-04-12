"""Repository helpers for append-only feedback-to-transaction links."""

from __future__ import annotations

from sqlalchemy.orm import Session

from fund_manager.storage.models import DecisionTransactionLink


class DecisionTransactionLinkRepository:
    """Persist links between manual feedback and authoritative transactions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self,
        *,
        feedback_id: int,
        transaction_id: int,
        match_source: str | None = None,
        match_reason: str | None = None,
    ) -> DecisionTransactionLink:
        """Append one feedback-to-transaction link."""
        link = DecisionTransactionLink(
            feedback_id=feedback_id,
            transaction_id=transaction_id,
            match_source=match_source,
            match_reason=match_reason,
        )
        self._session.add(link)
        self._session.flush()
        return link


__all__ = ["DecisionTransactionLinkRepository"]
