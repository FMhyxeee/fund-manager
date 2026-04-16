"""Controlled transaction ledger service for query and append operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

from sqlalchemy.orm import Session

from fund_manager.core.domain.decimal_constants import (
    AMOUNT_QUANTIZER,
    NAV_QUANTIZER,
    UNITS_QUANTIZER,
    ZERO,
)
from fund_manager.core.services.decision_reconciliation_service import (
    DecisionReconciliationService,
)
from fund_manager.core.services.portfolio_read_service import PortfolioReadService
from fund_manager.core.services.transaction_lot_sync_service import (
    TransactionLotSyncResult,
    TransactionLotSyncService,
)
from fund_manager.storage.models import FundMaster, TransactionRecord, TransactionType
from fund_manager.storage.repo import FundMasterRepository, TransactionRepository
from fund_manager.storage.repo.protocols import (
    FundMasterRepositoryProtocol,
    TransactionRepositoryProtocol,
)

_OPENCLAW_MCP_SOURCE = "openclaw_mcp"
_MAX_TRANSACTION_LIMIT = 200


@dataclass(frozen=True)
class TransactionRecordDTO:
    """JSON-safe transaction record contract for tools and transports."""

    transaction_id: int
    portfolio_id: int
    portfolio_code: str
    portfolio_name: str
    fund_id: int
    fund_code: str
    fund_name: str
    trade_date: date
    trade_type: str
    units: Decimal | None
    gross_amount: Decimal | None
    fee_amount: Decimal | None
    nav_per_unit: Decimal | None
    external_reference: str | None
    source_name: str | None
    source_reference: str | None
    note: str | None
    linked_feedback_ids: tuple[int, ...]
    linked_decision_run_ids: tuple[int, ...]
    created_at: datetime


@dataclass(frozen=True)
class TransactionAppendResult:
    """Structured outcome for one controlled transaction append."""

    transaction: TransactionRecordDTO
    lot_sync: TransactionLotSyncResult
    linked_transaction_ids: tuple[int, ...]
    fund_created: bool
    fund_updated: bool


class TransactionService:
    """Query and append authoritative transactions through deterministic services."""

    def __init__(
        self,
        session: Session,
        *,
        portfolio_read_service: PortfolioReadService | None = None,
        fund_repo: FundMasterRepositoryProtocol | None = None,
        transaction_repo: TransactionRepositoryProtocol | None = None,
        transaction_lot_sync_service: TransactionLotSyncService | None = None,
        decision_reconciliation_service: DecisionReconciliationService | None = None,
    ) -> None:
        self._session = session
        self._portfolio_read_service = portfolio_read_service or PortfolioReadService(session)
        self._fund_repo = fund_repo or FundMasterRepository(session)
        self._transaction_repo = transaction_repo or TransactionRepository(session)
        self._transaction_lot_sync_service = (
            transaction_lot_sync_service or TransactionLotSyncService(session)
        )
        self._decision_reconciliation_service = (
            decision_reconciliation_service or DecisionReconciliationService(session)
        )

    def list_transactions(
        self,
        *,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
        fund_code: str | None = None,
        trade_type: TransactionType | str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 50,
    ) -> tuple[TransactionRecordDTO, ...]:
        """List authoritative transaction records by deterministic filters."""
        normalized_limit = self._normalize_limit(limit)
        resolved_portfolio_id: int | None = None
        if portfolio_id is not None or portfolio_name is not None:
            resolved_portfolio = self._portfolio_read_service.resolve_portfolio_summary(
                portfolio_id=portfolio_id,
                portfolio_name=portfolio_name,
            )
            resolved_portfolio_id = resolved_portfolio.portfolio_id

        resolved_fund_id: int | None = None
        if fund_code is not None:
            normalized_fund_code = self._normalize_required_text(
                fund_code,
                field_name="fund_code",
                max_length=32,
            )
            fund = self._fund_repo.get_by_code(normalized_fund_code)
            if fund is None:
                return ()
            resolved_fund_id = fund.id

        resolved_trade_type = self._normalize_trade_type(trade_type)
        if start_date is not None and end_date is not None and start_date > end_date:
            msg = "start_date must be earlier than or equal to end_date."
            raise ValueError(msg)

        transactions = self._transaction_repo.list_recent(
            portfolio_id=resolved_portfolio_id,
            fund_id=resolved_fund_id,
            trade_type=resolved_trade_type,
            start_date=start_date,
            end_date=end_date,
            limit=normalized_limit,
        )
        return tuple(self._to_dto(transaction) for transaction in transactions)

    def get_transaction(self, *, transaction_id: int) -> TransactionRecordDTO:
        """Return one authoritative transaction by id."""
        transaction = self._transaction_repo.get_by_id(transaction_id)
        if transaction is None:
            msg = f"Transaction {transaction_id} was not found."
            raise ValueError(msg)
        return self._to_dto(transaction)

    def append_transaction(
        self,
        *,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
        fund_code: str,
        fund_name: str | None = None,
        trade_date: date,
        trade_type: TransactionType | str,
        units: Decimal | None = None,
        gross_amount: Decimal | None = None,
        fee_amount: Decimal | None = None,
        nav_per_unit: Decimal | None = None,
        external_reference: str | None = None,
        source_name: str | None = _OPENCLAW_MCP_SOURCE,
        source_reference: str | None = None,
        note: str | None = None,
    ) -> TransactionAppendResult:
        """Append one transaction and rebuild deterministic lot state."""
        portfolio = self._portfolio_read_service.resolve_portfolio_summary(
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
        )
        normalized_source_name = self._normalize_optional_text(
            source_name,
            field_name="source_name",
            max_length=64,
        ) or _OPENCLAW_MCP_SOURCE
        fund, fund_created, fund_updated = self._resolve_fund(
            fund_code=fund_code,
            fund_name=fund_name,
            source_name=normalized_source_name,
        )
        normalized_trade_type = self._normalize_required_trade_type(trade_type)
        normalized_units = self._normalize_optional_decimal(
            units,
            field_name="units",
            quantizer=UNITS_QUANTIZER,
        )
        normalized_gross_amount = self._normalize_optional_decimal(
            gross_amount,
            field_name="gross_amount",
            quantizer=AMOUNT_QUANTIZER,
        )
        normalized_fee_amount = self._normalize_optional_decimal(
            fee_amount,
            field_name="fee_amount",
            quantizer=AMOUNT_QUANTIZER,
            minimum=ZERO,
        )
        normalized_nav_per_unit = self._normalize_optional_decimal(
            nav_per_unit,
            field_name="nav_per_unit",
            quantizer=NAV_QUANTIZER,
            minimum=NAV_QUANTIZER,
        )
        self._validate_measurements(
            trade_type=normalized_trade_type,
            units=normalized_units,
            gross_amount=normalized_gross_amount,
        )

        transaction = self._transaction_repo.append_import_record(
            portfolio_id=portfolio.portfolio_id,
            fund_id=fund.id,
            external_reference=self._normalize_optional_text(
                external_reference,
                field_name="external_reference",
                max_length=128,
            ),
            trade_date=trade_date,
            trade_type=normalized_trade_type,
            units=normalized_units,
            gross_amount=normalized_gross_amount,
            fee_amount=normalized_fee_amount,
            nav_per_unit=normalized_nav_per_unit,
            source_name=normalized_source_name,
            source_reference=self._normalize_optional_text(
                source_reference,
                field_name="source_reference",
                max_length=128,
            ),
            note=self._normalize_optional_text(note, field_name="note"),
        )
        self._session.flush()

        sync_run_id = self._build_sync_run_id(portfolio.portfolio_id, trade_date)
        lot_sync = self._transaction_lot_sync_service.sync_portfolio(
            portfolio_id=portfolio.portfolio_id,
            run_id=sync_run_id,
        )
        linked_transaction_ids = self._decision_reconciliation_service.reconcile_transactions(
            (transaction,),
            match_source="transaction_mcp",
        )
        self._session.flush()

        if transaction.id is None:
            msg = "Appended transaction did not receive a primary key after flush."
            raise RuntimeError(msg)
        persisted_transaction = self._transaction_repo.get_by_id(transaction.id)
        if persisted_transaction is None:
            msg = f"Transaction {transaction.id} was not found after append."
            raise RuntimeError(msg)

        return TransactionAppendResult(
            transaction=self._to_dto(persisted_transaction),
            lot_sync=lot_sync,
            linked_transaction_ids=linked_transaction_ids,
            fund_created=fund_created,
            fund_updated=fund_updated,
        )

    def _resolve_fund(
        self,
        *,
        fund_code: str,
        fund_name: str | None,
        source_name: str,
    ) -> tuple[FundMaster, bool, bool]:
        normalized_fund_code = self._normalize_required_text(
            fund_code,
            field_name="fund_code",
            max_length=32,
        )
        normalized_fund_name = self._normalize_optional_text(
            fund_name,
            field_name="fund_name",
            max_length=255,
        )
        existing_fund = self._fund_repo.get_by_code(normalized_fund_code)
        if existing_fund is None and normalized_fund_name is None:
            msg = (
                f"Fund '{normalized_fund_code}' was not found; provide fund_name to create "
                "a new fund master record explicitly."
            )
            raise ValueError(msg)

        if normalized_fund_name is None:
            assert existing_fund is not None
            return existing_fund, False, False

        upsert_result = self._fund_repo.upsert(
            fund_code=normalized_fund_code,
            fund_name=normalized_fund_name,
            source_name=source_name,
        )
        return upsert_result.fund, upsert_result.created, upsert_result.updated

    def _to_dto(self, transaction: TransactionRecord) -> TransactionRecordDTO:
        linked_feedback_ids = tuple(
            sorted(transaction_link.feedback_id for transaction_link in transaction.decision_links)
        )
        linked_decision_run_ids = tuple(
            sorted(
                {
                    transaction_link.feedback.decision_run_id
                    for transaction_link in transaction.decision_links
                    if transaction_link.feedback is not None
                }
            )
        )
        return TransactionRecordDTO(
            transaction_id=transaction.id,
            portfolio_id=transaction.portfolio_id,
            portfolio_code=transaction.portfolio.portfolio_code,
            portfolio_name=transaction.portfolio.portfolio_name,
            fund_id=transaction.fund_id,
            fund_code=transaction.fund.fund_code,
            fund_name=transaction.fund.fund_name,
            trade_date=transaction.trade_date,
            trade_type=transaction.trade_type.value,
            units=transaction.units,
            gross_amount=transaction.gross_amount,
            fee_amount=transaction.fee_amount,
            nav_per_unit=transaction.nav_per_unit,
            external_reference=transaction.external_reference,
            source_name=transaction.source_name,
            source_reference=transaction.source_reference,
            note=transaction.note,
            linked_feedback_ids=linked_feedback_ids,
            linked_decision_run_ids=linked_decision_run_ids,
            created_at=transaction.created_at,
        )

    def _normalize_trade_type(
        self,
        trade_type: TransactionType | str | None,
    ) -> TransactionType | None:
        if trade_type is None:
            return None
        if isinstance(trade_type, TransactionType):
            return trade_type
        value = trade_type.strip().casefold()
        if not value:
            msg = "trade_type cannot be blank."
            raise ValueError(msg)
        try:
            return TransactionType(value)
        except ValueError as exc:
            supported = ", ".join(transaction_type.value for transaction_type in TransactionType)
            msg = f"trade_type must be one of: {supported}."
            raise ValueError(msg) from exc

    def _normalize_required_trade_type(
        self,
        trade_type: TransactionType | str,
    ) -> TransactionType:
        normalized_trade_type = self._normalize_trade_type(trade_type)
        if normalized_trade_type is None:
            msg = "trade_type is required."
            raise ValueError(msg)
        return normalized_trade_type

    def _normalize_optional_decimal(
        self,
        value: Decimal | None,
        *,
        field_name: str,
        quantizer: Decimal,
        minimum: Decimal | None = None,
    ) -> Decimal | None:
        if value is None:
            return None
        if not value.is_finite():
            msg = f"{field_name} must be finite."
            raise ValueError(msg)
        normalized_value = value.quantize(quantizer, rounding=ROUND_HALF_UP)
        if minimum is not None and normalized_value < minimum:
            msg = f"{field_name} must be greater than or equal to {minimum}."
            raise ValueError(msg)
        return normalized_value

    def _validate_measurements(
        self,
        *,
        trade_type: TransactionType,
        units: Decimal | None,
        gross_amount: Decimal | None,
    ) -> None:
        if trade_type in {
            TransactionType.BUY,
            TransactionType.SELL,
            TransactionType.CONVERT_IN,
            TransactionType.CONVERT_OUT,
        }:
            self._require_positive(units, field_name="units", trade_type=trade_type)
            self._require_positive(
                gross_amount,
                field_name="gross_amount",
                trade_type=trade_type,
            )
            return

        if trade_type is TransactionType.DIVIDEND:
            self._reject_negative(units, field_name="units", trade_type=trade_type)
            self._reject_negative(
                gross_amount,
                field_name="gross_amount",
                trade_type=trade_type,
            )
            positive_units = units is not None and units > ZERO
            positive_amount = gross_amount is not None and gross_amount > ZERO
            if not positive_units and not positive_amount:
                msg = (
                    "dividend transactions must include positive units or gross_amount; "
                    "use units for reinvested dividends or gross_amount for cash dividends."
                )
                raise ValueError(msg)
            return

        if trade_type is TransactionType.ADJUST:
            non_zero_units = units is not None and units != ZERO
            non_zero_amount = gross_amount is not None and gross_amount != ZERO
            if not non_zero_units and not non_zero_amount:
                msg = "adjust transactions must include non-zero units or gross_amount."
                raise ValueError(msg)
            return

        msg = f"Unsupported transaction type: {trade_type.value}."
        raise ValueError(msg)

    def _require_positive(
        self,
        value: Decimal | None,
        *,
        field_name: str,
        trade_type: TransactionType,
    ) -> None:
        if value is None or value <= ZERO:
            msg = f"{field_name} must be greater than zero for {trade_type.value} transactions."
            raise ValueError(msg)

    def _reject_negative(
        self,
        value: Decimal | None,
        *,
        field_name: str,
        trade_type: TransactionType,
    ) -> None:
        if value is not None and value < ZERO:
            msg = f"{field_name} cannot be negative for {trade_type.value} transactions."
            raise ValueError(msg)

    def _normalize_limit(self, limit: int) -> int:
        if limit < 1:
            msg = "limit must be greater than zero."
            raise ValueError(msg)
        if limit > _MAX_TRANSACTION_LIMIT:
            msg = f"limit cannot exceed {_MAX_TRANSACTION_LIMIT}."
            raise ValueError(msg)
        return limit

    def _normalize_required_text(
        self,
        value: str,
        *,
        field_name: str,
        max_length: int,
    ) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            msg = f"{field_name} cannot be blank."
            raise ValueError(msg)
        if len(normalized_value) > max_length:
            msg = f"{field_name} cannot exceed {max_length} characters."
            raise ValueError(msg)
        return normalized_value

    def _normalize_optional_text(
        self,
        value: str | None,
        *,
        field_name: str,
        max_length: int | None = None,
    ) -> str | None:
        if value is None:
            return None
        normalized_value = value.strip()
        if not normalized_value:
            return None
        if max_length is not None and len(normalized_value) > max_length:
            msg = f"{field_name} cannot exceed {max_length} characters."
            raise ValueError(msg)
        return normalized_value

    def _build_sync_run_id(self, portfolio_id: int, trade_date: date) -> str:
        return f"transaction-append-{trade_date:%Y%m%d}-{uuid4().hex[:8]}:txnagg:{portfolio_id}"


__all__ = [
    "TransactionAppendResult",
    "TransactionRecordDTO",
    "TransactionService",
]
