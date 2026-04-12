"""CSV parsing entrypoints for normalized transaction imports."""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from pathlib import Path

from fund_manager.core.domain.decimal_constants import ZERO
from fund_manager.data_adapters.csv.validator import (
    AMOUNT_QUANTIZER,
    NAV_QUANTIZER,
    UNITS_QUANTIZER,
    ImportValidationIssue,
    ImportedTransactionRow,
    TransactionsImportError,
    TransactionsImportValidationError,
    _HEADER_AMOUNT,
    _HEADER_EXTERNAL_REFERENCE,
    _HEADER_FEE,
    _HEADER_FUND_NAME,
    _HEADER_NAV_AT_TRADE,
    _HEADER_NOTE,
    _HEADER_PORTFOLIO_NAME,
    _HEADER_SOURCE,
    _HEADER_SOURCE_REFERENCE,
    _HEADER_UNITS,
    _REQUIRED_HEADERS,
    normalize_optional_text,
    normalize_required_text,
    parse_decimal_value,
    parse_trade_date,
    parse_trade_type,
    validate_transaction_measurements,
)


def parse_transactions_csv(
    csv_path: Path | str,
    *,
    default_portfolio_name: str,
) -> list[ImportedTransactionRow]:
    """Read and validate a CSV transactions file."""
    path = Path(csv_path)
    issues: list[ImportValidationIssue] = []
    imported_rows: list[ImportedTransactionRow] = []

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            msg = f"{path} does not contain a header row."
            raise TransactionsImportError(msg)

        header_map = build_header_map(reader.fieldnames)
        missing_headers = sorted(_REQUIRED_HEADERS - header_map.keys())
        if missing_headers:
            raise TransactionsImportValidationError(
                [
                    ImportValidationIssue(
                        line_number=1,
                        field_name="header",
                        message=f"missing required column(s): {', '.join(missing_headers)}",
                    )
                ]
            )

        for line_number, row in enumerate(reader, start=2):
            imported_row, row_issues = normalize_import_row(
                row,
                header_map=header_map,
                line_number=line_number,
                default_portfolio_name=default_portfolio_name,
            )
            issues.extend(row_issues)
            if imported_row is not None:
                imported_rows.append(imported_row)

    if issues:
        raise TransactionsImportValidationError(issues)

    return imported_rows


def build_header_map(fieldnames: Sequence[str | None]) -> dict[str, str]:
    """Build a normalized header lookup without losing original keys."""
    header_map: dict[str, str] = {}
    for fieldname in fieldnames:
        if fieldname is None:
            continue
        normalized_header = fieldname.strip()
        if normalized_header:
            header_map[normalized_header] = fieldname
    return header_map


def normalize_import_row(
    row: Mapping[str, str | None],
    *,
    header_map: Mapping[str, str],
    line_number: int,
    default_portfolio_name: str,
) -> tuple[ImportedTransactionRow | None, list[ImportValidationIssue]]:
    """Normalize one CSV row into a validated transaction DTO."""
    issues: list[ImportValidationIssue] = []

    fund_code = normalize_required_text(
        row_value(row, header_map, "fund_code"),
        field_name="fund_code",
        line_number=line_number,
        issues=issues,
    )
    fund_name = normalize_optional_text(row_value(row, header_map, _HEADER_FUND_NAME))
    trade_date = parse_trade_date(
        row_value(row, header_map, "trade_date"),
        line_number=line_number,
        issues=issues,
    )
    trade_type = parse_trade_type(
        row_value(row, header_map, "trade_type"),
        line_number=line_number,
        issues=issues,
    )
    units = parse_decimal_value(
        row_value(row, header_map, _HEADER_UNITS),
        field_name=_HEADER_UNITS,
        line_number=line_number,
        quantizer=UNITS_QUANTIZER,
        issues=issues,
        required=False,
    )
    amount = parse_decimal_value(
        row_value(row, header_map, _HEADER_AMOUNT),
        field_name=_HEADER_AMOUNT,
        line_number=line_number,
        quantizer=AMOUNT_QUANTIZER,
        issues=issues,
        required=False,
    )
    fee = parse_decimal_value(
        row_value(row, header_map, _HEADER_FEE),
        field_name=_HEADER_FEE,
        line_number=line_number,
        quantizer=AMOUNT_QUANTIZER,
        issues=issues,
        required=False,
        minimum=ZERO,
    )
    nav_at_trade = parse_decimal_value(
        row_value(row, header_map, _HEADER_NAV_AT_TRADE),
        field_name=_HEADER_NAV_AT_TRADE,
        line_number=line_number,
        quantizer=NAV_QUANTIZER,
        issues=issues,
        required=False,
        minimum=NAV_QUANTIZER,
    )

    portfolio_name = normalize_optional_text(row_value(row, header_map, _HEADER_PORTFOLIO_NAME))
    if portfolio_name is None:
        portfolio_name = default_portfolio_name

    if fund_code is None or trade_date is None or trade_type is None:
        return None, issues

    validate_transaction_measurements(
        trade_type=trade_type,
        units=units,
        amount=amount,
        line_number=line_number,
        issues=issues,
    )

    if issues:
        return None, issues

    return (
        ImportedTransactionRow(
            line_number=line_number,
            portfolio_name=portfolio_name,
            fund_code=fund_code,
            fund_name=fund_name,
            trade_date=trade_date,
            trade_type=trade_type,
            units=units,
            amount=amount,
            fee=fee,
            nav_at_trade=nav_at_trade,
            source_name=normalize_optional_text(row_value(row, header_map, _HEADER_SOURCE)),
            source_reference=normalize_optional_text(
                row_value(row, header_map, _HEADER_SOURCE_REFERENCE)
            ),
            external_reference=normalize_optional_text(
                row_value(row, header_map, _HEADER_EXTERNAL_REFERENCE)
            ),
            note=normalize_optional_text(row_value(row, header_map, _HEADER_NOTE)),
        ),
        issues,
    )


def row_value(
    row: Mapping[str, str | None],
    header_map: Mapping[str, str],
    key: str,
) -> str | None:
    """Read a row value through the normalized header map."""
    source_key = header_map.get(key)
    if source_key is None:
        return None
    return row.get(source_key)


__all__ = [
    "build_header_map",
    "normalize_import_row",
    "parse_transactions_csv",
    "row_value",
]
