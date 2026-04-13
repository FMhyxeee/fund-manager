"""Unit tests for manual decision feedback capture and reconciliation."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from fund_manager.core.services import (
    DecisionActionNotFoundError,
    DecisionFeedbackService,
)
from fund_manager.storage.models import (
    Base,
    DecisionFeedbackStatus,
    DecisionRun,
    FundMaster,
    Portfolio,
    TransactionRecord,
    TransactionType,
)


def test_record_feedback_reconciles_existing_matching_transaction(session: Session) -> None:
    portfolio, fund, decision_run, transaction = seed_decision_context(session)

    result = DecisionFeedbackService(session).record_feedback(
        decision_run_id=decision_run.id,
        action_index=0,
        feedback_status=DecisionFeedbackStatus.EXECUTED,
        feedback_date=transaction.trade_date,
        note="executed manually",
        created_by="test",
    )

    assert result.portfolio_id == portfolio.id
    assert result.fund_id == fund.id
    assert result.action_type == "add"
    assert result.feedback_status is DecisionFeedbackStatus.EXECUTED
    assert result.linked_transaction_ids == (transaction.id,)


def test_record_feedback_rejects_missing_action_index(session: Session) -> None:
    _, _, decision_run, _ = seed_decision_context(session)

    with pytest.raises(DecisionActionNotFoundError):
        DecisionFeedbackService(session).record_feedback(
            decision_run_id=decision_run.id,
            action_index=99,
            feedback_status=DecisionFeedbackStatus.SKIPPED,
            feedback_date=date(2026, 3, 15),
        )


def seed_decision_context(
    session: Session,
) -> tuple[Portfolio, FundMaster, DecisionRun, TransactionRecord]:
    portfolio = Portfolio(
        portfolio_code="main",
        portfolio_name="Main",
        is_default=True,
    )
    fund = FundMaster(
        fund_code="000001",
        fund_name="Alpha Fund",
        source_name="test",
    )
    session.add_all([portfolio, fund])
    session.flush()

    decision_run = DecisionRun(
        portfolio_id=portfolio.id,
        decision_date=date(2026, 3, 15),
        summary="Add Alpha Fund.",
        final_decision="rebalance_required",
        trigger_source="manual_test",
        actions_json=[
            {
                "action_type": "add",
                "fund_id": fund.id,
                "fund_code": fund.fund_code,
                "fund_name": fund.fund_name,
            }
        ],
        created_by_agent="DecisionService",
    )
    transaction = TransactionRecord(
        portfolio_id=portfolio.id,
        fund_id=fund.id,
        trade_date=date(2026, 3, 15),
        trade_type=TransactionType.BUY,
        units=Decimal("10.000000"),
        gross_amount=Decimal("12.0000"),
        source_name="manual",
    )
    session.add_all([decision_run, transaction])
    session.commit()
    return portfolio, fund, decision_run, transaction


def _build_session(tmp_path: Path) -> Session:
    database_path = tmp_path / "decision-feedback-service.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return session_factory()


def _dispose_session(session: Session) -> None:
    bind = session.get_bind()
    session.close()
    if bind is not None:
        bind.dispose()


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    db_session = _build_session(tmp_path)
    try:
        yield db_session
    finally:
        _dispose_session(db_session)
