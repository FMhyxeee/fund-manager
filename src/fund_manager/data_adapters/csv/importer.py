"""Importer orchestration for normalized transaction CSV files."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from fund_manager.core.config import get_settings
from fund_manager.core.domain.decimal_constants import AMOUNT_QUANTIZER, UNITS_QUANTIZER, ZERO
from fund_manager.core.services.decision_reconciliation_service import (
    DecisionReconciliationService,
)
from fund_manager.core.services.transaction_lot_sync_service import TransactionLotSyncService
from fund_manager.data_adapters.csv.parser import parse_transactions_csv
from fund_manager.data_adapters.csv.validator import (
    ImportValidationIssue,
    ImportedTransactionRow,
    TransactionsImportValidationError,
    quantize_decimal,
)
from fund_manager.storage.db import get_session_factory
from fund_manager.storage.models import TransactionType
from fund_manager.storage.repo import (
    FundMasterRepository,
    PortfolioRepository,
    TransactionRepository,
)
from fund_manager.storage.repo.protocols import (
    FundMasterRepositoryProtocol,
    PortfolioRepositoryProtocol,
    TransactionRepositoryProtocol,
)


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
    _portfolio_repo: PortfolioRepositoryProtocol
    _fund_repo: FundMasterRepositoryProtocol
    _transaction_repo: TransactionRepositoryProtocol

    def __init__(
        self,
        session: Session,
        *,
        default_portfolio_name: str | None = None,
        portfolio_repo: PortfolioRepositoryProtocol | None = None,
        fund_repo: FundMasterRepositoryProtocol | None = None,
        transaction_repo: TransactionRepositoryProtocol | None = None,
    ) -> None:
        settings = get_settings()
        self.session = session
        self.default_portfolio_name = default_portfolio_name or settings.default_portfolio_name
        self._portfolio_repo = portfolio_repo or PortfolioRepository(session)
        self._fund_repo = fund_repo or FundMasterRepository(session)
        self._transaction_repo = transaction_repo or TransactionRepository(session)

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
            affected_portfolio_ids: set[int] = set()
            appended_transactions = []
            for resolved_row in import_plan.resolved_rows:
                portfolio, _ = self._portfolio_repo.get_or_create(
                    resolved_row.portfolio_name,
                    default_portfolio_name=self.default_portfolio_name,
                )
                affected_portfolio_ids.add(portfolio.id)
                fund_result = self._fund_repo.upsert(
                    fund_code=resolved_row.fund_code,
                    fund_name=resolved_row.fund_name,
                    source_name="transaction_import",
                )
                transaction = self._transaction_repo.append_import_record(
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
                appended_transactions.append(transaction)

            # The importer runs under sessions with autoflush disabled in tests
            # and production, so the rebuild must flush pending transaction rows
            # before it queries the ledger back through SQLAlchemy.
            self.session.flush()
            transaction_lot_sync_service = TransactionLotSyncService(self.session)
            for portfolio_id in sorted(affected_portfolio_ids):
                transaction_lot_sync_service.sync_portfolio(
                    portfolio_id=portfolio_id,
                    run_id=f"{effective_run_id}:txnagg:{portfolio_id}",
                )
            DecisionReconciliationService(self.session).reconcile_transactions(appended_transactions)

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
                total_units=row.units or ZERO,
                total_amount=row.amount or ZERO,
                total_fee=row.fee or ZERO,
            )
            continue

        grouped[row.trade_type] = TradeTypeImportSummary(
            trade_type=existing_summary.trade_type,
            transaction_count=existing_summary.transaction_count + 1,
            total_units=quantize_decimal(
                existing_summary.total_units + (row.units or ZERO),
                UNITS_QUANTIZER,
            ),
            total_amount=quantize_decimal(
                existing_summary.total_amount + (row.amount or ZERO),
                AMOUNT_QUANTIZER,
            ),
            total_fee=quantize_decimal(
                existing_summary.total_fee + (row.fee or ZERO),
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
                total_units=row.units or ZERO,
                total_amount=row.amount or ZERO,
                total_fee=row.fee or ZERO,
            )
            continue

        grouped[row.portfolio_name] = PortfolioTransactionImportSummary(
            portfolio_name=existing_summary.portfolio_name,
            transaction_count=existing_summary.transaction_count + 1,
            total_units=quantize_decimal(
                existing_summary.total_units + (row.units or ZERO),
                UNITS_QUANTIZER,
            ),
            total_amount=quantize_decimal(
                existing_summary.total_amount + (row.amount or ZERO),
                AMOUNT_QUANTIZER,
            ),
            total_fee=quantize_decimal(
                existing_summary.total_fee + (row.fee or ZERO),
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


__all__ = [
    "ImportValidationIssue",
    "ImportedTransactionRow",
    "PortfolioTransactionImportSummary",
    "ResolvedTransactionRow",
    "TradeTypeImportSummary",
    "TransactionsImportSummary",
    "TransactionsImporter",
    "build_argument_parser",
    "build_portfolio_summaries",
    "build_trade_type_summaries",
    "build_transactions_import_run_id",
    "import_transactions_csv",
    "main",
]
