"""Unit tests for holdings import normalization."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from fund_manager.data_adapters.import_holdings import (
    HoldingsImportValidationError,
    ImportedHoldingRow,
    aggregate_holding_rows,
    parse_holdings_csv,
)


def test_parse_holdings_csv_normalizes_precision_and_default_portfolio(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "holdings.csv"
    csv_path.write_text(
        "fund_code,fund_name,units,avg_cost,total_cost,portfolio_name\n"
        "000001,Alpha Fund,10.1234567,1.2,,\n",
        encoding="utf-8",
    )

    rows = parse_holdings_csv(csv_path, default_portfolio_name="main")

    assert rows == [
        ImportedHoldingRow(
            line_number=2,
            fund_code="000001",
            fund_name="Alpha Fund",
            units=Decimal("10.123457"),
            average_cost_per_unit=Decimal("1.20000000"),
            total_cost_amount=Decimal("12.1481"),
            portfolio_name="main",
        )
    ]


def test_parse_holdings_csv_requires_avg_cost_or_total_cost(tmp_path: Path) -> None:
    csv_path = tmp_path / "holdings.csv"
    csv_path.write_text(
        "fund_code,fund_name,units,avg_cost,total_cost,portfolio_name\n"
        "000001,Alpha Fund,10,,,main\n",
        encoding="utf-8",
    )

    with pytest.raises(HoldingsImportValidationError) as exc_info:
        parse_holdings_csv(csv_path, default_portfolio_name="main")

    assert "avg_cost or total_cost must be provided" in str(exc_info.value)


def test_parse_holdings_csv_rejects_inconsistent_cost_values(tmp_path: Path) -> None:
    csv_path = tmp_path / "holdings.csv"
    csv_path.write_text(
        "fund_code,fund_name,units,avg_cost,total_cost,portfolio_name\n"
        "000001,Alpha Fund,10,1,11,main\n",
        encoding="utf-8",
    )

    with pytest.raises(HoldingsImportValidationError) as exc_info:
        parse_holdings_csv(csv_path, default_portfolio_name="main")

    assert "expected total_cost 10.0000" in str(exc_info.value)


def test_aggregate_holding_rows_merges_duplicate_funds() -> None:
    rows = [
        ImportedHoldingRow(
            line_number=2,
            fund_code="000001",
            fund_name="Alpha Fund",
            units=Decimal("10.000000"),
            average_cost_per_unit=Decimal("1.00000000"),
            total_cost_amount=Decimal("10.0000"),
            portfolio_name="main",
        ),
        ImportedHoldingRow(
            line_number=3,
            fund_code="000001",
            fund_name="Alpha Fund",
            units=Decimal("20.000000"),
            average_cost_per_unit=Decimal("2.00000000"),
            total_cost_amount=Decimal("40.0000"),
            portfolio_name="main",
        ),
    ]

    aggregated_rows = aggregate_holding_rows(rows)

    assert len(aggregated_rows) == 1
    assert aggregated_rows[0].units == Decimal("30.000000")
    assert aggregated_rows[0].total_cost_amount == Decimal("50.0000")
    assert aggregated_rows[0].average_cost_per_unit == Decimal("1.66666667")
    assert aggregated_rows[0].source_line_numbers == (2, 3)
