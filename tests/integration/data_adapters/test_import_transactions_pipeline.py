"""Integration tests for the transaction import pipeline."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from fund_manager.data_adapters.import_transactions import (
    TransactionsImportValidationError,
    import_transactions_csv,
)
from fund_manager.storage.models import (
    Base,
    FundMaster,
    Portfolio,
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


def write_transactions_csv(tmp_path: Path, content: str) -> Path:
    csv_path = tmp_path / "transactions.csv"
    csv_path.write_text(content, encoding="utf-8")
    return csv_path
