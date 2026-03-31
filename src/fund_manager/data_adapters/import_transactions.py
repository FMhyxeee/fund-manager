"""CSV importer for normalized personal fund transactions."""

from __future__ import annotations

import argparse
import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from fund_manager.core.config import get_settings
from fund_manager.storage.db import get_session_factory
from fund_manager.storage.models import TransactionType
from fund_manager.storage.repo import (
    FundMasterRepository,
    PortfolioRepository,
    TransactionRepository,
)

UNITS_QUANTIZER = Decimal("0.000001")
AMOUNT_QUANTIZER = Decimal("0.0001")
NAV_QUANTIZER = Decimal("0.00000001")
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


@dataclass(frozen=True)
class ResolvedTransactionRow:
    """One transaction row with all persistence-facing master data resolved."""

    line_number: int
    portfolio_name: str
    fund_code: str
    fund_name: str
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


@dataclass(frozen=True)
class TradeTypeImportSummary:
    """Aggregate import totals for one normalized transaction type."""

    trade_type: TransactionType
    transaction_count: int
    total_units: Decimal
    total_amount: Decimal
    total_fee: Decimal


@dataclass(frozen=True)
class PortfolioTransactionImportSummary:
    """Aggregate import totals for one portfolio."""

    portfolio_name: str
    transaction_count: int
    total_units: Decimal
    total_amount: Decimal
    total_fee: Decimal


@dataclass(frozen=True)
class TransactionsImportSummary:
    """Structured result of one transaction import run."""

    run_id: str
    dry_run: bool
    source_path: str
    input_row_count: int
    normalized_row_count: int
    transaction_count: int
    created_portfolio_names: tuple[str, ...]
    reused_portfolio_names: tuple[str, ...]
    created_fund_codes: tuple[str, ...]
    updated_fund_codes: tuple[str, ...]
    reused_fund_codes: tuple[str, ...]
    trade_type_summaries: tuple[TradeTypeImportSummary, ...]
    portfolio_summaries: tuple[PortfolioTransactionImportSummary, ...]

    def to_text(self) -> str:
        """Render a concise operator-facing summary."""
        action = "would append" if self.dry_run else "appended"
        lines = [
            f"{'DRY RUN' if self.dry_run else 'SUCCESS'} transaction import",
            f"run_id: {self.run_id}",
            f"source: {self.source_path}",
            f"input rows: {self.input_row_count}",
            f"normalized rows: {self.normalized_row_count}",
            f"{action} {self.transaction_count} transaction record(s)",
        ]
        if self.created_portfolio_names:
            lines.append(f"created portfolios: {', '.join(self.created_portfolio_names)}")
        if self.reused_portfolio_names:
            lines.append(f"reused portfolios: {', '.join(self.reused_portfolio_names)}")
        if self.created_fund_codes:
            lines.append(f"created funds: {', '.join(self.created_fund_codes)}")
        if self.updated_fund_codes:
            lines.append(f"updated funds: {', '.join(self.updated_fund_codes)}")
        if self.reused_fund_codes:
            lines.append(f"reused funds: {', '.join(self.reused_fund_codes)}")
        for trade_type_summary in self.trade_type_summaries:
            lines.append(
                "trade_type "
                f"{trade_type_summary.trade_type.value}: "
                f"{trade_type_summary.transaction_count} transaction(s), "
                f"units={trade_type_summary.total_units}, "
                f"amount={trade_type_summary.total_amount}, "
                f"fees={trade_type_summary.total_fee}"
            )
        for portfolio_summary in self.portfolio_summaries:
            lines.append(
                "portfolio "
                f"{portfolio_summary.portfolio_name}: "
                f"{portfolio_summary.transaction_count} transaction(s), "
                f"units={portfolio_summary.total_units}, "
                f"amount={portfolio_summary.total_amount}, "
                f"fees={portfolio_summary.total_fee}"
            )
        return "\n".join(lines)


@dataclass(frozen=True)
class _ResolvedImportPlan:
    resolved_rows: tuple[ResolvedTransactionRow, ...]
    created_portfolio_names: tuple[str, ...]
    reused_portfolio_names: tuple[str, ...]
    created_fund_codes: tuple[str, ...]
    updated_fund_codes: tuple[str, ...]
    reused_fund_codes: tuple[str, ...]


@dataclass
class TransactionsImporter:
    """Import normalized transaction CSV files into the persistence layer."""

    session: Session
    default_portfolio_name: str
    _portfolio_repo: PortfolioRepository
    _fund_repo: FundMasterRepository
    _transaction_repo: TransactionRepository

    def __init__(
        self,
        session: Session,
        *,
        default_portfolio_name: str | None = None,
    ) -> None:
        settings = get_settings()
        self.session = session
        self.default_portfolio_name = default_portfolio_name or settings.default_portfolio_name
        self._portfolio_repo = PortfolioRepository(session)
        self._fund_repo = FundMasterRepository(session)
        self._transaction_repo = TransactionRepository(session)

    def import_csv(
        self,
        csv_path: Path | str,
        *,
        dry_run: bool = False,
        run_id: str | None = None,
    ) -> TransactionsImportSummary:
        """Validate and import a transaction CSV file."""
        path = Path(csv_path)
        imported_rows = parse_transactions_csv(
            path,
            default_portfolio_name=self.default_portfolio_name,
        )
        effective_run_id = run_id or build_transactions_import_run_id(date.today())
        import_plan = self._resolve_import_plan(imported_rows)

        if dry_run:
            return self._build_summary(
                csv_path=path,
                imported_rows=imported_rows,
                import_plan=import_plan,
                dry_run=True,
                run_id=effective_run_id,
            )

        try:
            for resolved_row in import_plan.resolved_rows:
                portfolio, _ = self._portfolio_repo.get_or_create(
                    resolved_row.portfolio_name,
                    default_portfolio_name=self.default_portfolio_name,
                )
                fund_result = self._fund_repo.upsert(
                    fund_code=resolved_row.fund_code,
                    fund_name=resolved_row.fund_name,
                    source_name="transaction_import",
                )
                self._transaction_repo.append_import_record(
                    portfolio_id=portfolio.id,
                    fund_id=fund_result.fund.id,
                    external_reference=resolved_row.external_reference,
                    trade_date=resolved_row.trade_date,
                    trade_type=resolved_row.trade_type,
                    units=resolved_row.units,
                    gross_amount=resolved_row.amount,
                    fee_amount=resolved_row.fee,
                    nav_per_unit=resolved_row.nav_at_trade,
                    source_name=resolved_row.source_name,
                    source_reference=resolved_row.source_reference,
                    note=resolved_row.note,
                )

            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        return self._build_summary(
            csv_path=path,
            imported_rows=imported_rows,
            import_plan=import_plan,
            dry_run=False,
            run_id=effective_run_id,
        )

    def _resolve_import_plan(
        self,
        imported_rows: Sequence[ImportedTransactionRow],
    ) -> _ResolvedImportPlan:
        issues: list[ImportValidationIssue] = []
        resolved_rows: list[ResolvedTransactionRow] = []
        created_portfolio_names: set[str] = set()
        reused_portfolio_names: set[str] = set()
        created_fund_codes: set[str] = set()
        updated_fund_codes: set[str] = set()
        reused_fund_codes: set[str] = set()
        portfolio_exists_cache: dict[str, bool] = {}
        existing_fund_name_by_code: dict[str, str | None] = {}
        planned_fund_name_by_code: dict[str, str] = {}
        planned_fund_name_line_by_code: dict[str, int] = {}

        for row in imported_rows:
            portfolio_key = row.portfolio_name.casefold()
            if portfolio_key not in portfolio_exists_cache:
                existing_portfolio = self._portfolio_repo.get_by_name(row.portfolio_name)
                portfolio_exists_cache[portfolio_key] = existing_portfolio is not None
                if existing_portfolio is None:
                    created_portfolio_names.add(row.portfolio_name)
                else:
                    reused_portfolio_names.add(existing_portfolio.portfolio_name)

            existing_fund = self._fund_repo.get_by_code(row.fund_code)
            if row.fund_code not in existing_fund_name_by_code:
                existing_fund_name_by_code[row.fund_code] = (
                    existing_fund.fund_name if existing_fund is not None else None
                )

            existing_fund_name = existing_fund_name_by_code[row.fund_code]
            planned_fund_name = planned_fund_name_by_code.get(row.fund_code)
            resolved_fund_name = self._resolve_fund_name(
                row=row,
                existing_fund_name=existing_fund_name,
                planned_fund_name=planned_fund_name,
                planned_fund_line=planned_fund_name_line_by_code.get(row.fund_code),
                issues=issues,
            )
            if resolved_fund_name is None:
                continue

            if existing_fund_name is None:
                created_fund_codes.add(row.fund_code)
            elif (
                row.fund_name is not None
                and row.fund_name.casefold() != existing_fund_name.casefold()
            ):
                updated_fund_codes.add(row.fund_code)
            else:
                reused_fund_codes.add(row.fund_code)

            if (
                planned_fund_name is None
                or planned_fund_name.casefold() != resolved_fund_name.casefold()
            ):
                planned_fund_name_by_code[row.fund_code] = resolved_fund_name
                planned_fund_name_line_by_code[row.fund_code] = row.line_number

            resolved_rows.append(
                ResolvedTransactionRow(
                    line_number=row.line_number,
                    portfolio_name=row.portfolio_name,
                    fund_code=row.fund_code,
                    fund_name=resolved_fund_name,
                    trade_date=row.trade_date,
                    trade_type=row.trade_type,
                    units=row.units,
                    amount=row.amount,
                    fee=row.fee,
                    nav_at_trade=row.nav_at_trade,
                    source_name=row.source_name,
                    source_reference=row.source_reference,
                    external_reference=row.external_reference,
                    note=row.note,
                )
            )

        if issues:
            raise TransactionsImportValidationError(issues)

        reused_fund_codes -= created_fund_codes
        reused_fund_codes -= updated_fund_codes

        return _ResolvedImportPlan(
            resolved_rows=tuple(resolved_rows),
            created_portfolio_names=tuple(sorted(created_portfolio_names)),
            reused_portfolio_names=tuple(sorted(reused_portfolio_names)),
            created_fund_codes=tuple(sorted(created_fund_codes)),
            updated_fund_codes=tuple(sorted(updated_fund_codes)),
            reused_fund_codes=tuple(sorted(reused_fund_codes)),
        )

    def _resolve_fund_name(
        self,
        *,
        row: ImportedTransactionRow,
        existing_fund_name: str | None,
        planned_fund_name: str | None,
        planned_fund_line: int | None,
        issues: list[ImportValidationIssue],
    ) -> str | None:
        if existing_fund_name is None and planned_fund_name is None:
            if row.fund_name is None:
                issues.append(
                    ImportValidationIssue(
                        line_number=row.line_number,
                        field_name="fund_name",
                        message=(
                            f"fund_code '{row.fund_code}' does not exist yet; add a fund_name "
                            "column for new funds or import the fund master data first"
                        ),
                    )
                )
                return None
            return row.fund_name

        current_fund_name = planned_fund_name or existing_fund_name
        if current_fund_name is None:
            msg = "Resolved fund names must be available before persistence."
            raise AssertionError(msg)

        if row.fund_name is None:
            return current_fund_name

        if row.fund_name.casefold() == current_fund_name.casefold():
            return current_fund_name

        if existing_fund_name is not None and planned_fund_name is None:
            return row.fund_name

        issues.append(
            ImportValidationIssue(
                line_number=row.line_number,
                field_name="fund_name",
                message=(
                    "conflicting fund_name for the same fund_code; "
                    f"expected '{current_fund_name}' from line {planned_fund_line}"
                ),
            )
        )
        return None

    def _build_summary(
        self,
        *,
        csv_path: Path,
        imported_rows: Sequence[ImportedTransactionRow],
        import_plan: _ResolvedImportPlan,
        dry_run: bool,
        run_id: str,
    ) -> TransactionsImportSummary:
        return TransactionsImportSummary(
            run_id=run_id,
            dry_run=dry_run,
            source_path=str(csv_path),
            input_row_count=len(imported_rows),
            normalized_row_count=len(imported_rows),
            transaction_count=len(import_plan.resolved_rows),
            created_portfolio_names=import_plan.created_portfolio_names,
            reused_portfolio_names=import_plan.reused_portfolio_names,
            created_fund_codes=import_plan.created_fund_codes,
            updated_fund_codes=import_plan.updated_fund_codes,
            reused_fund_codes=import_plan.reused_fund_codes,
            trade_type_summaries=build_trade_type_summaries(import_plan.resolved_rows),
            portfolio_summaries=build_portfolio_summaries(import_plan.resolved_rows),
        )


def build_transactions_import_run_id(import_date: date) -> str:
    """Generate a traceable run identifier for one import execution."""
    return f"transactions-import-{import_date:%Y%m%d}-{uuid4().hex[:8]}"


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

        header_map = _build_header_map(reader.fieldnames)
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
            imported_row, row_issues = _normalize_import_row(
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


def build_trade_type_summaries(
    rows: Sequence[ResolvedTransactionRow],
) -> tuple[TradeTypeImportSummary, ...]:
    """Summarize imported transactions by trade type."""
    grouped: dict[TransactionType, TradeTypeImportSummary] = {}

    for row in rows:
        existing_summary = grouped.get(row.trade_type)
        if existing_summary is None:
            grouped[row.trade_type] = TradeTypeImportSummary(
                trade_type=row.trade_type,
                transaction_count=1,
                total_units=row.units or Decimal("0"),
                total_amount=row.amount or Decimal("0"),
                total_fee=row.fee or Decimal("0"),
            )
            continue

        grouped[row.trade_type] = TradeTypeImportSummary(
            trade_type=existing_summary.trade_type,
            transaction_count=existing_summary.transaction_count + 1,
            total_units=quantize_decimal(
                existing_summary.total_units + (row.units or Decimal("0")),
                UNITS_QUANTIZER,
            ),
            total_amount=quantize_decimal(
                existing_summary.total_amount + (row.amount or Decimal("0")),
                AMOUNT_QUANTIZER,
            ),
            total_fee=quantize_decimal(
                existing_summary.total_fee + (row.fee or Decimal("0")),
                AMOUNT_QUANTIZER,
            ),
        )

    return tuple(grouped[trade_type] for trade_type in TransactionType if trade_type in grouped)


def build_portfolio_summaries(
    rows: Sequence[ResolvedTransactionRow],
) -> tuple[PortfolioTransactionImportSummary, ...]:
    """Summarize imported transactions per portfolio."""
    grouped: dict[str, PortfolioTransactionImportSummary] = {}

    for row in rows:
        existing_summary = grouped.get(row.portfolio_name)
        if existing_summary is None:
            grouped[row.portfolio_name] = PortfolioTransactionImportSummary(
                portfolio_name=row.portfolio_name,
                transaction_count=1,
                total_units=row.units or Decimal("0"),
                total_amount=row.amount or Decimal("0"),
                total_fee=row.fee or Decimal("0"),
            )
            continue

        grouped[row.portfolio_name] = PortfolioTransactionImportSummary(
            portfolio_name=existing_summary.portfolio_name,
            transaction_count=existing_summary.transaction_count + 1,
            total_units=quantize_decimal(
                existing_summary.total_units + (row.units or Decimal("0")),
                UNITS_QUANTIZER,
            ),
            total_amount=quantize_decimal(
                existing_summary.total_amount + (row.amount or Decimal("0")),
                AMOUNT_QUANTIZER,
            ),
            total_fee=quantize_decimal(
                existing_summary.total_fee + (row.fee or Decimal("0")),
                AMOUNT_QUANTIZER,
            ),
        )

    return tuple(grouped[name] for name in sorted(grouped))


def import_transactions_csv(
    session: Session,
    csv_path: Path | str,
    *,
    dry_run: bool = False,
    run_id: str | None = None,
    default_portfolio_name: str | None = None,
) -> TransactionsImportSummary:
    """Convenience function for importing a transactions CSV file."""
    importer = TransactionsImporter(
        session,
        default_portfolio_name=default_portfolio_name,
    )
    return importer.import_csv(
        csv_path,
        dry_run=dry_run,
        run_id=run_id,
    )


def quantize_decimal(value: Decimal, quantizer: Decimal) -> Decimal:
    """Normalize a decimal value to storage precision."""
    return value.quantize(quantizer, rounding=ROUND_HALF_UP)


def _build_header_map(fieldnames: Sequence[str | None]) -> dict[str, str]:
    header_map: dict[str, str] = {}
    for fieldname in fieldnames:
        if fieldname is None:
            continue
        normalized_header = fieldname.strip()
        if normalized_header:
            header_map[normalized_header] = fieldname
    return header_map


def _normalize_import_row(
    row: Mapping[str, str | None],
    *,
    header_map: Mapping[str, str],
    line_number: int,
    default_portfolio_name: str,
) -> tuple[ImportedTransactionRow | None, list[ImportValidationIssue]]:
    issues: list[ImportValidationIssue] = []

    fund_code = _normalize_required_text(
        _row_value(row, header_map, "fund_code"),
        field_name="fund_code",
        line_number=line_number,
        issues=issues,
    )
    fund_name = _normalize_optional_text(_row_value(row, header_map, _HEADER_FUND_NAME))
    trade_date = _parse_trade_date(
        _row_value(row, header_map, "trade_date"),
        line_number=line_number,
        issues=issues,
    )
    trade_type = _parse_trade_type(
        _row_value(row, header_map, "trade_type"),
        line_number=line_number,
        issues=issues,
    )
    units = _parse_decimal(
        _row_value(row, header_map, _HEADER_UNITS),
        field_name=_HEADER_UNITS,
        line_number=line_number,
        quantizer=UNITS_QUANTIZER,
        issues=issues,
        required=False,
    )
    amount = _parse_decimal(
        _row_value(row, header_map, _HEADER_AMOUNT),
        field_name=_HEADER_AMOUNT,
        line_number=line_number,
        quantizer=AMOUNT_QUANTIZER,
        issues=issues,
        required=False,
    )
    fee = _parse_decimal(
        _row_value(row, header_map, _HEADER_FEE),
        field_name=_HEADER_FEE,
        line_number=line_number,
        quantizer=AMOUNT_QUANTIZER,
        issues=issues,
        required=False,
        minimum=Decimal("0"),
    )
    nav_at_trade = _parse_decimal(
        _row_value(row, header_map, _HEADER_NAV_AT_TRADE),
        field_name=_HEADER_NAV_AT_TRADE,
        line_number=line_number,
        quantizer=NAV_QUANTIZER,
        issues=issues,
        required=False,
        minimum=Decimal("0.00000001"),
    )

    portfolio_name = _normalize_optional_text(_row_value(row, header_map, _HEADER_PORTFOLIO_NAME))
    if portfolio_name is None:
        portfolio_name = default_portfolio_name

    if fund_code is None or trade_date is None or trade_type is None:
        return None, issues

    _validate_transaction_measurements(
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
            source_name=_normalize_optional_text(_row_value(row, header_map, _HEADER_SOURCE)),
            source_reference=_normalize_optional_text(
                _row_value(row, header_map, _HEADER_SOURCE_REFERENCE)
            ),
            external_reference=_normalize_optional_text(
                _row_value(row, header_map, _HEADER_EXTERNAL_REFERENCE)
            ),
            note=_normalize_optional_text(_row_value(row, header_map, _HEADER_NOTE)),
        ),
        issues,
    )


def _normalize_required_text(
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


def _normalize_optional_text(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    value = raw_value.strip()
    return value or None


def _parse_trade_date(
    raw_value: str | None,
    *,
    line_number: int,
    issues: list[ImportValidationIssue],
) -> date | None:
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


def _parse_trade_type(
    raw_value: str | None,
    *,
    line_number: int,
    issues: list[ImportValidationIssue],
) -> TransactionType | None:
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


def _parse_decimal(
    raw_value: str | None,
    *,
    field_name: str,
    line_number: int,
    quantizer: Decimal,
    issues: list[ImportValidationIssue],
    required: bool,
    minimum: Decimal | None = None,
) -> Decimal | None:
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
        comparator = "greater than or equal to" if minimum == 0 else "greater than"
        issues.append(
            ImportValidationIssue(
                line_number=line_number,
                field_name=field_name,
                message=f"value must be {comparator} {minimum}",
            )
        )
        return None

    return normalized_value


def _validate_transaction_measurements(
    *,
    trade_type: TransactionType,
    units: Decimal | None,
    amount: Decimal | None,
    line_number: int,
    issues: list[ImportValidationIssue],
) -> None:
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
        positive_units = units is not None and units > 0
        positive_amount = amount is not None and amount > 0
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
        non_zero_units = units is not None and units != 0
        non_zero_amount = amount is not None and amount != 0
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

    if value <= 0:
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
    if value is not None and value < 0:
        issues.append(
            ImportValidationIssue(
                line_number=line_number,
                field_name=field_name,
                message="value cannot be negative for this trade_type",
            )
        )


def _row_value(
    row: Mapping[str, str | None],
    header_map: Mapping[str, str],
    key: str,
) -> str | None:
    source_key = header_map.get(key)
    if source_key is None:
        return None
    return row.get(source_key)


def build_argument_parser() -> argparse.ArgumentParser:
    """Create the CLI parser for module execution."""
    parser = argparse.ArgumentParser(description="Import normalized transactions from CSV.")
    parser.add_argument("csv_path", type=Path, help="Path to the CSV file to import.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and summarize the import without persisting rows.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the transaction importer as a small CLI utility."""
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    session_factory = get_session_factory()
    with session_factory() as session:
        summary = import_transactions_csv(
            session,
            args.csv_path,
            dry_run=args.dry_run,
        )
    print(summary.to_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ImportValidationIssue",
    "ImportedTransactionRow",
    "PortfolioTransactionImportSummary",
    "TradeTypeImportSummary",
    "TransactionsImportError",
    "TransactionsImporter",
    "TransactionsImportSummary",
    "TransactionsImportValidationError",
    "build_portfolio_summaries",
    "build_trade_type_summaries",
    "build_transactions_import_run_id",
    "import_transactions_csv",
    "main",
    "parse_transactions_csv",
    "quantize_decimal",
]
