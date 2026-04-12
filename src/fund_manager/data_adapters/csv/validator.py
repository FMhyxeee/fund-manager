"""Validation helpers and normalized row types for transaction CSV imports."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fund_manager.core.domain.decimal_constants import (
    AMOUNT_QUANTIZER,
    NAV_QUANTIZER,
    UNITS_QUANTIZER,
    ZERO,
)
from fund_manager.storage.models import TransactionType

_REQUIRED_HEADERS = frozenset({"fund_code", "trade_date", "trade_type"})
_SUPPORTED_TRADE_TYPES = tuple(transaction_type.value for transaction_type in TransactionType)
_HEADER_FUND_NAME = "fund_name"
_HEADER_PORTFOLIO_NAME = "portfolio_name"
_HEADER_UNITS = "units"
_HEADER_AMOUNT = "amount"
_HEADER_FEE = "fee"
_HEADER_NAV_AT_TRADE = "nav_at_trade"
_HEADER_SOURCE = "source"
_HEADER_SOURCE_REFERENCE = "source_reference"
_HEADER_EXTERNAL_REFERENCE = "external_reference"
_HEADER_NOTE = "note"


@dataclass(frozen=True)
class ImportValidationIssue:
    """A specific row-level or file-level validation issue."""

    line_number: int
    field_name: str
    message: str

    def __str__(self) -> str:
        return f"line {self.line_number}, field '{self.field_name}': {self.message}"


class TransactionsImportError(ValueError):
    """Base exception for transaction import failures."""


class TransactionsImportValidationError(TransactionsImportError):
    """Raised when the CSV file cannot be safely normalized or resolved."""

    def __init__(self, issues: Sequence[ImportValidationIssue]) -> None:
        self.issues = tuple(issues)
        message = "Transaction import validation failed:\n" + "\n".join(
            f"- {issue}" for issue in self.issues
        )
        super().__init__(message)


@dataclass(frozen=True)
class ImportedTransactionRow:
    """One validated transaction row after CSV normalization."""

    line_number: int
    portfolio_name: str
    fund_code: str
    fund_name: str | None
    trade_date: date
    trade_type: TransactionType
    units: Decimal | None
    amount: Decimal | None
    fee: Decimal | None
    nav_at_trade: Decimal | None
    source_name: str | None
    source_reference: str | None
    external_reference: str | None
    note: str | None


def quantize_decimal(value: Decimal, quantizer: Decimal) -> Decimal:
    """Normalize a decimal value to storage precision."""
    return value.quantize(quantizer, rounding=ROUND_HALF_UP)


def normalize_required_text(
    raw_value: str | None,
    *,
    field_name: str,
    line_number: int,
    issues: list[ImportValidationIssue],
) -> str | None:
    value = raw_value.strip() if raw_value is not None else ""
    if not value:
        issues.append(
            ImportValidationIssue(
                line_number=line_number,
                field_name=field_name,
                message="value is required",
            )
        )
        return None
    return value


def normalize_optional_text(raw_value: str | None) -> str | None:
    """Trim optional text fields and collapse blanks to None."""
    if raw_value is None:
        return None
    value = raw_value.strip()
    return value or None


def parse_trade_date(
    raw_value: str | None,
    *,
    line_number: int,
    issues: list[ImportValidationIssue],
) -> date | None:
    """Parse one ISO-format trade date field."""
    value = raw_value.strip() if raw_value is not None else ""
    if not value:
        issues.append(
            ImportValidationIssue(
                line_number=line_number,
                field_name="trade_date",
                message="value is required",
            )
        )
        return None

    try:
        return date.fromisoformat(value)
    except ValueError:
        issues.append(
            ImportValidationIssue(
                line_number=line_number,
                field_name="trade_date",
                message=f"'{value}' is not a valid ISO date; expected YYYY-MM-DD",
            )
        )
        return None


def parse_trade_type(
    raw_value: str | None,
    *,
    line_number: int,
    issues: list[ImportValidationIssue],
) -> TransactionType | None:
    """Parse and validate one trade type value."""
    value = raw_value.strip().casefold() if raw_value is not None else ""
    if not value:
        issues.append(
            ImportValidationIssue(
                line_number=line_number,
                field_name="trade_type",
                message="value is required",
            )
        )
        return None

    try:
        return TransactionType(value)
    except ValueError:
        issues.append(
            ImportValidationIssue(
                line_number=line_number,
                field_name="trade_type",
                message=(
                    f"'{value}' is not supported; expected one of: "
                    f"{', '.join(_SUPPORTED_TRADE_TYPES)}"
                ),
            )
        )
        return None


def parse_decimal_value(
    raw_value: str | None,
    *,
    field_name: str,
    line_number: int,
    quantizer: Decimal,
    issues: list[ImportValidationIssue],
    required: bool,
    minimum: Decimal | None = None,
) -> Decimal | None:
    """Parse one decimal field and normalize it to storage precision."""
    value = raw_value.strip() if raw_value is not None else ""
    if not value:
        if required:
            issues.append(
                ImportValidationIssue(
                    line_number=line_number,
                    field_name=field_name,
                    message="value is required",
                )
            )
        return None

    try:
        decimal_value = Decimal(value)
    except InvalidOperation:
        issues.append(
            ImportValidationIssue(
                line_number=line_number,
                field_name=field_name,
                message=f"'{value}' is not a valid decimal number",
            )
        )
        return None

    if not decimal_value.is_finite():
        issues.append(
            ImportValidationIssue(
                line_number=line_number,
                field_name=field_name,
                message="value must be finite",
            )
        )
        return None

    normalized_value = quantize_decimal(decimal_value, quantizer)
    if minimum is not None and normalized_value < minimum:
        comparator = "greater than or equal to" if minimum == ZERO else "greater than"
        issues.append(
            ImportValidationIssue(
                line_number=line_number,
                field_name=field_name,
                message=f"value must be {comparator} {minimum}",
            )
        )
        return None

    return normalized_value


def validate_transaction_measurements(
    *,
    trade_type: TransactionType,
    units: Decimal | None,
    amount: Decimal | None,
    line_number: int,
    issues: list[ImportValidationIssue],
) -> None:
    """Validate measurement rules that depend on the normalized trade type."""
    if trade_type in {
        TransactionType.BUY,
        TransactionType.SELL,
        TransactionType.CONVERT_IN,
        TransactionType.CONVERT_OUT,
    }:
        _require_positive_value(
            units,
            field_name=_HEADER_UNITS,
            line_number=line_number,
            issues=issues,
        )
        _require_positive_value(
            amount,
            field_name=_HEADER_AMOUNT,
            line_number=line_number,
            issues=issues,
        )
        return

    if trade_type is TransactionType.DIVIDEND:
        _reject_negative_value(
            units,
            field_name=_HEADER_UNITS,
            line_number=line_number,
            issues=issues,
        )
        _reject_negative_value(
            amount,
            field_name=_HEADER_AMOUNT,
            line_number=line_number,
            issues=issues,
        )
        positive_units = units is not None and units > ZERO
        positive_amount = amount is not None and amount > ZERO
        if not positive_units and not positive_amount:
            issues.append(
                ImportValidationIssue(
                    line_number=line_number,
                    field_name="units,amount",
                    message=(
                        "dividend rows must include a positive units or amount value; "
                        "use units for reinvested dividends or amount for cash dividends"
                    ),
                )
            )
        return

    if trade_type is TransactionType.ADJUST:
        non_zero_units = units is not None and units != ZERO
        non_zero_amount = amount is not None and amount != ZERO
        if not non_zero_units and not non_zero_amount:
            issues.append(
                ImportValidationIssue(
                    line_number=line_number,
                    field_name="units,amount",
                    message="adjust rows must include a non-zero units or amount value",
                )
            )
        return

    msg = f"Unsupported transaction type encountered during validation: {trade_type.value}"
    raise AssertionError(msg)


def _require_positive_value(
    value: Decimal | None,
    *,
    field_name: str,
    line_number: int,
    issues: list[ImportValidationIssue],
) -> None:
    if value is None:
        issues.append(
            ImportValidationIssue(
                line_number=line_number,
                field_name=field_name,
                message="value is required for this trade_type",
            )
        )
        return

    if value <= ZERO:
        issues.append(
            ImportValidationIssue(
                line_number=line_number,
                field_name=field_name,
                message="value must be greater than zero for this trade_type",
            )
        )


def _reject_negative_value(
    value: Decimal | None,
    *,
    field_name: str,
    line_number: int,
    issues: list[ImportValidationIssue],
) -> None:
    if value is not None and value < ZERO:
        issues.append(
            ImportValidationIssue(
                line_number=line_number,
                field_name=field_name,
                message="value cannot be negative for this trade_type",
            )
        )


__all__ = [
    "AMOUNT_QUANTIZER",
    "ImportValidationIssue",
    "ImportedTransactionRow",
    "NAV_QUANTIZER",
    "TransactionsImportError",
    "TransactionsImportValidationError",
    "UNITS_QUANTIZER",
    "_HEADER_AMOUNT",
    "_HEADER_EXTERNAL_REFERENCE",
    "_HEADER_FEE",
    "_HEADER_FUND_NAME",
    "_HEADER_NAV_AT_TRADE",
    "_HEADER_NOTE",
    "_HEADER_PORTFOLIO_NAME",
    "_HEADER_SOURCE",
    "_HEADER_SOURCE_REFERENCE",
    "_HEADER_UNITS",
    "_REQUIRED_HEADERS",
    "normalize_optional_text",
    "normalize_required_text",
    "parse_decimal_value",
    "parse_trade_date",
    "parse_trade_type",
    "quantize_decimal",
    "validate_transaction_measurements",
]
