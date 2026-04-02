"""Repository helpers for append-only strategy proposals."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from fund_manager.storage.models import StrategyProposal


class StrategyProposalRepository:
    """Persist final strategy proposal artifacts without rewriting history."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self,
        *,
        portfolio_id: int,
        proposal_date: date,
        thesis: str,
        evidence_json: dict[str, Any] | list[Any] | None,
        recommended_actions_json: list[dict[str, Any]] | dict[str, Any] | None,
        risk_notes: str | None,
        counterarguments: str | None,
        final_decision: str | None,
        confidence_score: Decimal | None,
        created_by_agent: str | None,
        run_id: str | None = None,
        workflow_name: str | None = None,
    ) -> StrategyProposal:
        """Append one persisted strategy proposal artifact."""
        strategy_proposal = StrategyProposal(
            portfolio_id=portfolio_id,
            run_id=run_id,
            workflow_name=workflow_name,
            proposal_date=proposal_date,
            thesis=thesis,
            evidence_json=evidence_json,
            recommended_actions_json=recommended_actions_json,
            risk_notes=risk_notes,
            counterarguments=counterarguments,
            final_decision=final_decision,
            confidence_score=confidence_score,
            created_by_agent=created_by_agent,
        )
        self._session.add(strategy_proposal)
        self._session.flush()
        return strategy_proposal
