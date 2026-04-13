"""Integration tests for the transaction import pipeline."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from fund_manager.core.services import PortfolioService
from fund_manager.core.services import DecisionFeedbackService
from fund_manager.data_adapters.import_transactions import (
    TransactionsImportValidationError,
    import_transactions_csv,
)
from fund_manager.storage.models import (
    Base,
    DecisionFeedbackStatus,
    DecisionRun,
    DecisionTransactionLink,
    FundMaster,
    Portfolio,
    PositionLot,
    TransactionRecord,
    TransactionType,
)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with session_factory() as db_session:
        yield db_session


def test_import_transactions_creates_master_data_and_preserves_metadata(
    session: Session,
    tmp_path: Path,
) -> None:
    csv_path = write_transactions_csv(
        tmp_path,
        "fund_code,fund_name,portfolio_name,trade_date,trade_type,units,amount,fee,"
        "nav_at_trade,source,source_reference,external_reference,note\n"
        "000001,Alpha Fund,,2026-03-01,buy,10,12.3456,0.1000,1.23456789,manual,"
        "ledger.csv,txn-001,initial buy\n"
        "000001,,main,2026-03-10,dividend,0.5,0,0,,manual,ledger.csv,txn-002,reinvested dividend\n"
        "000002,Beta Fund,retirement,2026-03-11,convert_in,3,6.3,0,2.1,broker,"
        "broker.csv,txn-003,broker transfer\n",
    )

    summary = import_transactions_csv(session, csv_path)

    assert summary.dry_run is False
    assert summary.transaction_count == 3
    assert summary.created_portfolio_names == ("main", "retirement")
    assert summary.created_fund_codes == ("000001", "000002")
    assert session.scalar(select(func.count()).select_from(Portfolio)) == 2
    assert session.scalar(select(func.count()).select_from(FundMaster)) == 2
    assert session.scalar(select(func.count()).select_from(TransactionRecord)) == 3
    assert session.scalar(select(func.count()).select_from(PositionLot)) == 2

    dividend_row = session.execute(
        select(TransactionRecord)
        .join(FundMaster, TransactionRecord.fund_id == FundMaster.id)
        .where(
            FundMaster.fund_code == "000001",
            TransactionRecord.trade_type == TransactionType.DIVIDEND,
        )
    ).scalar_one()
    assert dividend_row.gross_amount == Decimal("0.0000")
    assert dividend_row.units == Decimal("0.500000")
    assert dividend_row.source_name == "manual"
    assert dividend_row.source_reference == "ledger.csv"
    assert dividend_row.external_reference == "txn-002"
    assert dividend_row.note == "reinvested dividend"

    main_lot = session.execute(
        select(PositionLot)
        .join(FundMaster, PositionLot.fund_id == FundMaster.id)
        .where(
            FundMaster.fund_code == "000001",
            PositionLot.lot_key == "txnagg:000001",
        )
    ).scalar_one()
    assert main_lot.remaining_units == Decimal("10.500000")
    assert main_lot.total_cost_amount == Decimal("12.4456")

    main_portfolio = session.execute(
        select(Portfolio).where(Portfolio.portfolio_code == "main")
    ).scalar_one()
    snapshot = PortfolioService(session).get_portfolio_snapshot(
        main_portfolio.id,
        as_of_date=main_lot.as_of_date,
    )
    assert snapshot.position_count == 1
    assert snapshot.positions[0].fund_code == "000001"
    assert snapshot.positions[0].units == Decimal("10.500000")


def test_import_transactions_dry_run_does_not_write(session: Session, tmp_path: Path) -> None:
    csv_path = write_transactions_csv(
        tmp_path,
        "fund_code,fund_name,trade_date,trade_type,units,amount\n"
        "000001,Alpha Fund,2026-03-01,buy,10,12\n",
    )

    summary = import_transactions_csv(session, csv_path, dry_run=True)

    assert summary.dry_run is True
    assert summary.transaction_count == 1
    assert session.scalar(select(func.count()).select_from(Portfolio)) == 0
    assert session.scalar(select(func.count()).select_from(FundMaster)) == 0
    assert session.scalar(select(func.count()).select_from(TransactionRecord)) == 0
    assert session.scalar(select(func.count()).select_from(PositionLot)) == 0


def test_import_transactions_requires_fund_name_for_new_fund(
    session: Session,
    tmp_path: Path,
) -> None:
    csv_path = write_transactions_csv(
        tmp_path,
        "fund_code,trade_date,trade_type,units,amount\n999999,2026-03-01,buy,10,12\n",
    )

    with pytest.raises(TransactionsImportValidationError) as exc_info:
        import_transactions_csv(session, csv_path)

    assert "add a fund_name column for new funds or import the fund master data first" in str(
        exc_info.value
    )
    assert session.scalar(select(func.count()).select_from(Portfolio)) == 0
    assert session.scalar(select(func.count()).select_from(FundMaster)) == 0
    assert session.scalar(select(func.count()).select_from(TransactionRecord)) == 0


def test_import_transactions_rebuilds_transaction_backed_snapshot_after_sell(
    session: Session,
    tmp_path: Path,
) -> None:
    csv_path = write_transactions_csv(
        tmp_path,
        "fund_code,fund_name,portfolio_name,trade_date,trade_type,units,amount,fee,nav_at_trade\n"
        "000001,Alpha Fund,main,2026-03-01,buy,10,10,0,1\n"
        "000001,,main,2026-03-05,sell,4,4.8,0,1.2\n",
    )

    summary = import_transactions_csv(session, csv_path)

    assert summary.transaction_count == 2
    transaction_lot = session.execute(
        select(PositionLot).where(PositionLot.lot_key == "txnagg:000001")
    ).scalar_one()
    assert transaction_lot.remaining_units == Decimal("6.000000")
    assert transaction_lot.total_cost_amount == Decimal("6.0000")


def test_import_transactions_links_new_transaction_back_to_executed_feedback(
    session: Session,
    tmp_path: Path,
) -> None:
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
        trigger_source="test",
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
    session.add(decision_run)
    session.commit()

    feedback = DecisionFeedbackService(session).record_feedback(
        decision_run_id=decision_run.id,
        action_index=0,
        feedback_status=DecisionFeedbackStatus.EXECUTED,
        feedback_date=date(2026, 3, 15),
        created_by="test",
    )
    session.commit()

    csv_path = write_transactions_csv(
        tmp_path,
        "fund_code,fund_name,portfolio_name,trade_date,trade_type,units,amount,fee,nav_at_trade\n"
        "000001,,main,2026-03-16,buy,10,12,0,1.2\n",
    )

    summary = import_transactions_csv(session, csv_path)

    assert summary.transaction_count == 1
    link = session.execute(select(DecisionTransactionLink)).scalar_one()
    assert link.feedback_id == feedback.feedback_id
    assert link.match_source == "transaction_import"
    linked_transaction = session.get(TransactionRecord, link.transaction_id)
    assert linked_transaction is not None
    assert linked_transaction.trade_type is TransactionType.BUY


def write_transactions_csv(tmp_path: Path, content: str) -> Path:
    csv_path = tmp_path / "transactions.csv"
    csv_path.write_text(content, encoding="utf-8")
    return csv_path
