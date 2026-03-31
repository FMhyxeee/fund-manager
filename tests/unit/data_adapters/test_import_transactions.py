"""Unit tests for transaction import normalization."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from fund_manager.data_adapters.import_transactions import (
    ImportedTransactionRow,
    TransactionsImportValidationError,
    parse_transactions_csv,
)
from fund_manager.storage.models import TransactionType


def test_parse_transactions_csv_normalizes_values_and_preserves_metadata(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "transactions.csv"
    csv_path.write_text(
        "fund_code,fund_name,portfolio_name,trade_date,trade_type,units,amount,fee,"
        "nav_at_trade,source,source_reference,external_reference,note\n"
        "000001,Alpha Fund,,2026-03-01,BUY,10.1234567,120.34567,0.0,1.203456789,"
        "manual,ledger.csv,txn-001, first buy \n"
        "000001,,main,2026-03-10,dividend,5.2,0.0,0.0,,manual,ledger.csv,,reinvested\n"
        "000001,,main,2026-03-11,adjust,-1.25,,0.0,,manual,,,manual correction\n",
        encoding="utf-8",
    )

    rows = parse_transactions_csv(csv_path, default_portfolio_name="main")

    assert rows == [
        ImportedTransactionRow(
            line_number=2,
            portfolio_name="main",
            fund_code="000001",
            fund_name="Alpha Fund",
            trade_date=date(2026, 3, 1),
            trade_type=TransactionType.BUY,
            units=Decimal("10.123457"),
            amount=Decimal("120.3457"),
            fee=Decimal("0.0000"),
            nav_at_trade=Decimal("1.20345679"),
            source_name="manual",
            source_reference="ledger.csv",
            external_reference="txn-001",
            note="first buy",
        ),
        ImportedTransactionRow(
            line_number=3,
            portfolio_name="main",
            fund_code="000001",
            fund_name=None,
            trade_date=date(2026, 3, 10),
            trade_type=TransactionType.DIVIDEND,
            units=Decimal("5.200000"),
            amount=Decimal("0.0000"),
            fee=Decimal("0.0000"),
            nav_at_trade=None,
            source_name="manual",
            source_reference="ledger.csv",
            external_reference=None,
            note="reinvested",
        ),
        ImportedTransactionRow(
            line_number=4,
            portfolio_name="main",
            fund_code="000001",
            fund_name=None,
            trade_date=date(2026, 3, 11),
            trade_type=TransactionType.ADJUST,
            units=Decimal("-1.250000"),
            amount=None,
            fee=Decimal("0.0000"),
            nav_at_trade=None,
            source_name="manual",
            source_reference=None,
            external_reference=None,
            note="manual correction",
        ),
    ]


def test_parse_transactions_csv_rejects_invalid_trade_type_and_date(tmp_path: Path) -> None:
    csv_path = tmp_path / "transactions.csv"
    csv_path.write_text(
        "fund_code,trade_date,trade_type,units,amount\n000001,2026/03/01,swap,10,12\n",
        encoding="utf-8",
    )

    with pytest.raises(TransactionsImportValidationError) as exc_info:
        parse_transactions_csv(csv_path, default_portfolio_name="main")

    message = str(exc_info.value)
    assert "is not a valid ISO date; expected YYYY-MM-DD" in message
    assert (
        "is not supported; expected one of: buy, sell, dividend, convert_in, convert_out, adjust"
        in message
    )


def test_parse_transactions_csv_rejects_buy_without_positive_amount(tmp_path: Path) -> None:
    csv_path = tmp_path / "transactions.csv"
    csv_path.write_text(
        "fund_code,trade_date,trade_type,units,amount\n000001,2026-03-01,buy,10,0\n",
        encoding="utf-8",
    )

    with pytest.raises(TransactionsImportValidationError) as exc_info:
        parse_transactions_csv(csv_path, default_portfolio_name="main")

    assert "field 'amount': value must be greater than zero for this trade_type" in str(
        exc_info.value
    )
