"""Bootstrap importer for opening holdings snapshots.

The v1 importer seeds append-only ``position_lot`` rows so a portfolio can be
bootstrapped before full transaction history is available. Mutable master data
such as ``portfolio`` and ``fund_master`` are reused or updated in place, while
the imported lot snapshots are always appended.
"""

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
from fund_manager.storage.repo import (
    FundMasterRepository,
    PortfolioRepository,
    PositionLotRepository,
)

UNITS_QUANTIZER = Decimal("0.000001")
AVG_COST_QUANTIZER = Decimal("0.00000001")
TOTAL_COST_QUANTIZER = Decimal("0.0001")
_REQUIRED_HEADERS = frozenset({"fund_code", "fund_name", "units"})
_HEADER_PORTFOLIO_NAME = "portfolio_name"
_HEADER_AVG_COST = "avg_cost"
_HEADER_TOTAL_COST = "total_cost"


@dataclass(frozen=True)
class ImportValidationIssue:
    """A specific row-level or file-level validation issue."""

    line_number: int
    field_name: str
    message: str

    def __str__(self) -> str:
        return f"line {self.line_number}, field '{self.field_name}': {self.message}"


class HoldingsImportError(ValueError):
    """Base exception for holdings import failures."""


class HoldingsImportValidationError(HoldingsImportError):
    """Raised when the CSV file cannot be safely normalized."""

    def __init__(self, issues: Sequence[ImportValidationIssue]) -> None:
        self.issues = tuple(issues)
        message = "Holdings import validation failed:\n" + "\n".join(
            f"- {issue}" for issue in self.issues
        )
        super().__init__(message)


@dataclass(frozen=True)
class ImportedHoldingRow:
    """One validated holding row after numeric normalization."""

    line_number: int
    fund_code: str
    fund_name: str
    units: Decimal
    average_cost_per_unit: Decimal
    total_cost_amount: Decimal
    portfolio_name: str


@dataclass(frozen=True)
class AggregatedHoldingRow:
    """One import-time aggregate written as a single opening lot."""

    fund_code: str
    fund_name: str
    portfolio_name: str
    units: Decimal
    average_cost_per_unit: Decimal
    total_cost_amount: Decimal
    source_line_numbers: tuple[int, ...]


@dataclass(frozen=True)
class PortfolioImportSummary:
    """Per-portfolio summary of imported opening lots."""

    portfolio_name: str
    position_count: int
    total_units: Decimal
    total_cost_amount: Decimal


@dataclass(frozen=True)
class HoldingsImportSummary:
    """Structured result of a holdings import run."""

    run_id: str
    dry_run: bool
    as_of_date: date
    source_path: str
    input_row_count: int
    normalized_row_count: int
    position_lot_count: int
    created_portfolio_names: tuple[str, ...]
    reused_portfolio_names: tuple[str, ...]
    created_fund_codes: tuple[str, ...]
    updated_fund_codes: tuple[str, ...]
    reused_fund_codes: tuple[str, ...]
    portfolio_summaries: tuple[PortfolioImportSummary, ...]

    def to_text(self) -> str:
        """Render a concise operator-facing summary."""
        action = "would append" if self.dry_run else "appended"
        lines = [
            f"{'DRY RUN' if self.dry_run else 'SUCCESS'} holdings import",
            f"run_id: {self.run_id}",
            f"source: {self.source_path}",
            f"as_of_date: {self.as_of_date.isoformat()}",
            f"input rows: {self.input_row_count}",
            f"normalized rows: {self.normalized_row_count}",
            f"{action} {self.position_lot_count} position lot snapshot(s)",
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
        for portfolio_summary in self.portfolio_summaries:
            lines.append(
                "portfolio "
                f"{portfolio_summary.portfolio_name}: "
                f"{portfolio_summary.position_count} position(s), "
                f"units={portfolio_summary.total_units}, "
                f"total_cost={portfolio_summary.total_cost_amount}"
            )
        return "\n".join(lines)


@dataclass
class HoldingsImporter:
    """Import opening holdings snapshots into the persistence layer."""

    session: Session
    default_portfolio_name: str
    _portfolio_repo: PortfolioRepository
    _fund_repo: FundMasterRepository
    _position_lot_repo: PositionLotRepository

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
        self._position_lot_repo = PositionLotRepository(session)

    def import_csv(
        self,
        csv_path: Path | str,
        *,
        as_of_date: date | None = None,
        dry_run: bool = False,
        run_id: str | None = None,
    ) -> HoldingsImportSummary:
        """Validate a CSV file and import append-only opening lot snapshots."""
        path = Path(csv_path)
        imported_rows = parse_holdings_csv(
            path,
            default_portfolio_name=self.default_portfolio_name,
        )
        aggregated_rows = aggregate_holding_rows(imported_rows)
        effective_as_of_date = as_of_date or date.today()
        effective_run_id = run_id or build_holdings_import_run_id(effective_as_of_date)

        if dry_run:
            return self._build_dry_run_summary(
                csv_path=path,
                imported_rows=imported_rows,
                aggregated_rows=aggregated_rows,
                as_of_date=effective_as_of_date,
                run_id=effective_run_id,
            )

        created_portfolio_names: set[str] = set()
        reused_portfolio_names: set[str] = set()
        created_fund_codes: set[str] = set()
        updated_fund_codes: set[str] = set()
        reused_fund_codes: set[str] = set()

        try:
            for aggregated_row in aggregated_rows:
                portfolio, created_portfolio = self._portfolio_repo.get_or_create(
                    aggregated_row.portfolio_name,
                    default_portfolio_name=self.default_portfolio_name,
                )
                if created_portfolio:
                    created_portfolio_names.add(portfolio.portfolio_name)
                else:
                    reused_portfolio_names.add(portfolio.portfolio_name)

                fund_result = self._fund_repo.upsert(
                    fund_code=aggregated_row.fund_code,
                    fund_name=aggregated_row.fund_name,
                )
                if fund_result.created:
                    created_fund_codes.add(fund_result.fund.fund_code)
                elif fund_result.updated:
                    updated_fund_codes.add(fund_result.fund.fund_code)
                else:
                    reused_fund_codes.add(fund_result.fund.fund_code)

                self._position_lot_repo.append_import_snapshot(
                    portfolio_id=portfolio.id,
                    fund_id=fund_result.fund.id,
                    fund_code=aggregated_row.fund_code,
                    as_of_date=effective_as_of_date,
                    run_id=effective_run_id,
                    remaining_units=aggregated_row.units,
                    average_cost_per_unit=aggregated_row.average_cost_per_unit,
                    total_cost_amount=aggregated_row.total_cost_amount,
                )

            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        return HoldingsImportSummary(
            run_id=effective_run_id,
            dry_run=False,
            as_of_date=effective_as_of_date,
            source_path=str(path),
            input_row_count=len(imported_rows),
            normalized_row_count=len(imported_rows),
            position_lot_count=len(aggregated_rows),
            created_portfolio_names=tuple(sorted(created_portfolio_names)),
            reused_portfolio_names=tuple(sorted(reused_portfolio_names)),
            created_fund_codes=tuple(sorted(created_fund_codes)),
            updated_fund_codes=tuple(sorted(updated_fund_codes)),
            reused_fund_codes=tuple(sorted(reused_fund_codes)),
            portfolio_summaries=build_portfolio_summaries(aggregated_rows),
        )

    def _build_dry_run_summary(
        self,
        *,
        csv_path: Path,
        imported_rows: Sequence[ImportedHoldingRow],
        aggregated_rows: Sequence[AggregatedHoldingRow],
        as_of_date: date,
        run_id: str,
    ) -> HoldingsImportSummary:
        created_portfolio_names: set[str] = set()
        reused_portfolio_names: set[str] = set()
        created_fund_codes: set[str] = set()
        updated_fund_codes: set[str] = set()
        reused_fund_codes: set[str] = set()

        for aggregated_row in aggregated_rows:
            existing_portfolio = self._portfolio_repo.get_by_name(aggregated_row.portfolio_name)
            if existing_portfolio is None:
                created_portfolio_names.add(aggregated_row.portfolio_name)
            else:
                reused_portfolio_names.add(existing_portfolio.portfolio_name)

            existing_fund = self._fund_repo.get_by_code(aggregated_row.fund_code)
            if existing_fund is None:
                created_fund_codes.add(aggregated_row.fund_code)
            elif existing_fund.fund_name != aggregated_row.fund_name:
                updated_fund_codes.add(aggregated_row.fund_code)
            else:
                reused_fund_codes.add(aggregated_row.fund_code)

        return HoldingsImportSummary(
            run_id=run_id,
            dry_run=True,
            as_of_date=as_of_date,
            source_path=str(csv_path),
            input_row_count=len(imported_rows),
            normalized_row_count=len(imported_rows),
            position_lot_count=len(aggregated_rows),
            created_portfolio_names=tuple(sorted(created_portfolio_names)),
            reused_portfolio_names=tuple(sorted(reused_portfolio_names)),
            created_fund_codes=tuple(sorted(created_fund_codes)),
            updated_fund_codes=tuple(sorted(updated_fund_codes)),
            reused_fund_codes=tuple(sorted(reused_fund_codes)),
            portfolio_summaries=build_portfolio_summaries(aggregated_rows),
        )


def build_holdings_import_run_id(as_of_date: date) -> str:
    """Generate a traceable run identifier for one import execution."""
    return f"holdings-import-{as_of_date:%Y%m%d}-{uuid4().hex[:8]}"


def parse_holdings_csv(
    csv_path: Path | str,
    *,
    default_portfolio_name: str,
) -> list[ImportedHoldingRow]:
    """Read and validate a CSV holdings file."""
    path = Path(csv_path)
    issues: list[ImportValidationIssue] = []
    imported_rows: list[ImportedHoldingRow] = []

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            msg = f"{path} does not contain a header row."
            raise HoldingsImportError(msg)

        header_map = _build_header_map(reader.fieldnames)
        missing_headers = sorted(_REQUIRED_HEADERS - header_map.keys())
        if missing_headers:
            raise HoldingsImportValidationError(
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
        raise HoldingsImportValidationError(issues)

    return imported_rows


def aggregate_holding_rows(rows: Sequence[ImportedHoldingRow]) -> list[AggregatedHoldingRow]:
    """Merge duplicate portfolio/fund rows into one opening lot per import."""
    issues: list[ImportValidationIssue] = []
    aggregates: dict[tuple[str, str], AggregatedHoldingRow] = {}
    ordered_keys: list[tuple[str, str]] = []

    for row in rows:
        key = (row.portfolio_name.casefold(), row.fund_code)
        existing = aggregates.get(key)
        if existing is None:
            ordered_keys.append(key)
            aggregates[key] = AggregatedHoldingRow(
                fund_code=row.fund_code,
                fund_name=row.fund_name,
                portfolio_name=row.portfolio_name,
                units=row.units,
                average_cost_per_unit=row.average_cost_per_unit,
                total_cost_amount=row.total_cost_amount,
                source_line_numbers=(row.line_number,),
            )
            continue

        if existing.fund_name.casefold() != row.fund_name.casefold():
            issues.append(
                ImportValidationIssue(
                    line_number=row.line_number,
                    field_name="fund_name",
                    message=(
                        "duplicate portfolio/fund rows must use the same fund_name; "
                        f"first seen on line {existing.source_line_numbers[0]}"
                    ),
                )
            )
            continue

        total_units = quantize_decimal(existing.units + row.units, UNITS_QUANTIZER)
        total_cost_amount = quantize_decimal(
            existing.total_cost_amount + row.total_cost_amount,
            TOTAL_COST_QUANTIZER,
        )
        average_cost_per_unit = quantize_decimal(
            total_cost_amount / total_units,
            AVG_COST_QUANTIZER,
        )
        aggregates[key] = AggregatedHoldingRow(
            fund_code=row.fund_code,
            fund_name=existing.fund_name,
            portfolio_name=existing.portfolio_name,
            units=total_units,
            average_cost_per_unit=average_cost_per_unit,
            total_cost_amount=total_cost_amount,
            source_line_numbers=existing.source_line_numbers + (row.line_number,),
        )

    if issues:
        raise HoldingsImportValidationError(issues)

    return [aggregates[key] for key in ordered_keys]


def build_portfolio_summaries(
    aggregated_rows: Sequence[AggregatedHoldingRow],
) -> tuple[PortfolioImportSummary, ...]:
    """Summarize imported lots per portfolio for CLI and API output."""
    grouped: dict[str, PortfolioImportSummary] = {}

    for aggregated_row in aggregated_rows:
        existing_summary = grouped.get(aggregated_row.portfolio_name)
        if existing_summary is None:
            grouped[aggregated_row.portfolio_name] = PortfolioImportSummary(
                portfolio_name=aggregated_row.portfolio_name,
                position_count=1,
                total_units=aggregated_row.units,
                total_cost_amount=aggregated_row.total_cost_amount,
            )
            continue

        grouped[aggregated_row.portfolio_name] = PortfolioImportSummary(
            portfolio_name=existing_summary.portfolio_name,
            position_count=existing_summary.position_count + 1,
            total_units=quantize_decimal(
                existing_summary.total_units + aggregated_row.units,
                UNITS_QUANTIZER,
            ),
            total_cost_amount=quantize_decimal(
                existing_summary.total_cost_amount + aggregated_row.total_cost_amount,
                TOTAL_COST_QUANTIZER,
            ),
        )

    return tuple(grouped[name] for name in sorted(grouped))


def import_holdings_csv(
    session: Session,
    csv_path: Path | str,
    *,
    as_of_date: date | None = None,
    dry_run: bool = False,
    run_id: str | None = None,
    default_portfolio_name: str | None = None,
) -> HoldingsImportSummary:
    """Convenience function for importing a holdings CSV file."""
    importer = HoldingsImporter(
        session,
        default_portfolio_name=default_portfolio_name,
    )
    return importer.import_csv(
        csv_path,
        as_of_date=as_of_date,
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
) -> tuple[ImportedHoldingRow | None, list[ImportValidationIssue]]:
    issues: list[ImportValidationIssue] = []

    fund_code = _normalize_required_text(
        _row_value(row, header_map, "fund_code"),
        field_name="fund_code",
        line_number=line_number,
        issues=issues,
    )
    fund_name = _normalize_required_text(
        _row_value(row, header_map, "fund_name"),
        field_name="fund_name",
        line_number=line_number,
        issues=issues,
    )
    units = _parse_positive_decimal(
        _row_value(row, header_map, "units"),
        field_name="units",
        line_number=line_number,
        quantizer=UNITS_QUANTIZER,
        issues=issues,
    )
    average_cost_per_unit = _parse_positive_decimal(
        _row_value(row, header_map, _HEADER_AVG_COST),
        field_name=_HEADER_AVG_COST,
        line_number=line_number,
        quantizer=AVG_COST_QUANTIZER,
        issues=issues,
        required=False,
    )
    total_cost_amount = _parse_positive_decimal(
        _row_value(row, header_map, _HEADER_TOTAL_COST),
        field_name=_HEADER_TOTAL_COST,
        line_number=line_number,
        quantizer=TOTAL_COST_QUANTIZER,
        issues=issues,
        required=False,
    )

    portfolio_name_raw = _row_value(row, header_map, _HEADER_PORTFOLIO_NAME)
    portfolio_name = " ".join(portfolio_name_raw.split()) if portfolio_name_raw else ""
    if not portfolio_name:
        portfolio_name = default_portfolio_name

    if units is None or fund_code is None or fund_name is None:
        return None, issues

    if average_cost_per_unit is None and total_cost_amount is None:
        issues.append(
            ImportValidationIssue(
                line_number=line_number,
                field_name="avg_cost,total_cost",
                message="avg_cost or total_cost must be provided",
            )
        )
        return None, issues

    if average_cost_per_unit is None and total_cost_amount is not None:
        average_cost_per_unit = quantize_decimal(
            total_cost_amount / units,
            AVG_COST_QUANTIZER,
        )
    elif average_cost_per_unit is not None and total_cost_amount is None:
        total_cost_amount = quantize_decimal(
            units * average_cost_per_unit,
            TOTAL_COST_QUANTIZER,
        )
    elif average_cost_per_unit is not None and total_cost_amount is not None:
        computed_total = quantize_decimal(
            units * average_cost_per_unit,
            TOTAL_COST_QUANTIZER,
        )
        if computed_total != total_cost_amount:
            issues.append(
                ImportValidationIssue(
                    line_number=line_number,
                    field_name="avg_cost,total_cost",
                    message=(
                        "avg_cost and total_cost are inconsistent after normalization; "
                        f"expected total_cost {computed_total}"
                    ),
                )
            )
            return None, issues

    if average_cost_per_unit is None or total_cost_amount is None:
        msg = "Normalized holding rows must have both average_cost_per_unit and total_cost_amount."
        raise AssertionError(msg)

    return (
        ImportedHoldingRow(
            line_number=line_number,
            fund_code=fund_code,
            fund_name=fund_name,
            units=units,
            average_cost_per_unit=average_cost_per_unit,
            total_cost_amount=total_cost_amount,
            portfolio_name=portfolio_name,
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
    if field_name == "fund_name":
        return " ".join(value.split())
    return value


def _parse_positive_decimal(
    raw_value: str | None,
    *,
    field_name: str,
    line_number: int,
    quantizer: Decimal,
    issues: list[ImportValidationIssue],
    required: bool = True,
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

    if decimal_value <= 0:
        issues.append(
            ImportValidationIssue(
                line_number=line_number,
                field_name=field_name,
                message="value must be greater than zero",
            )
        )
        return None

    normalized_value = quantize_decimal(decimal_value, quantizer)
    if normalized_value <= 0:
        issues.append(
            ImportValidationIssue(
                line_number=line_number,
                field_name=field_name,
                message="value rounds to zero at supported precision",
            )
        )
        return None

    return normalized_value


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
    parser = argparse.ArgumentParser(description="Import opening holdings from CSV.")
    parser.add_argument("csv_path", type=Path, help="Path to the CSV file to import.")
    parser.add_argument(
        "--as-of-date",
        type=date.fromisoformat,
        default=None,
        help="Snapshot date in ISO format. Defaults to today.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and summarize the import without persisting rows.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the holdings importer as a small CLI utility."""
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    session_factory = get_session_factory()
    with session_factory() as session:
        summary = import_holdings_csv(
            session,
            args.csv_path,
            as_of_date=args.as_of_date,
            dry_run=args.dry_run,
        )
    print(summary.to_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AggregatedHoldingRow",
    "HoldingsImportError",
    "HoldingsImportSummary",
    "HoldingsImportValidationError",
    "HoldingsImporter",
    "ImportValidationIssue",
    "ImportedHoldingRow",
    "PortfolioImportSummary",
    "aggregate_holding_rows",
    "build_holdings_import_run_id",
    "build_portfolio_summaries",
    "import_holdings_csv",
    "main",
    "parse_holdings_csv",
    "quantize_decimal",
]
