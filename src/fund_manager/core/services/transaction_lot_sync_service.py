"""Rebuild transaction-backed position lot snapshots from the transaction ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fund_manager.core.domain.decimal_constants import (
    AVG_COST_QUANTIZER,
    TOTAL_COST_QUANTIZER,
    UNITS_QUANTIZER,
    ZERO,
)
from fund_manager.core.domain.metrics import quantize_money
from fund_manager.storage.models import FundMaster, PositionLot, TransactionRecord, TransactionType

TRANSACTION_AGGREGATE_LOT_PREFIX = "txnagg:"

_INCREASE_TYPES = {
    TransactionType.BUY,
    TransactionType.CONVERT_IN,
    TransactionType.DIVIDEND,
}
_DECREASE_TYPES = {
    TransactionType.SELL,
    TransactionType.CONVERT_OUT,
}


@dataclass(frozen=True)
class TransactionLotSyncResult:
    """Structured summary for one transaction-to-lot sync run."""

    portfolio_id: int
    as_of_date: date
    run_id: str
    snapshot_count: int
    fund_codes: tuple[str, ...]


@dataclass
class _FundLedgerState:
    portfolio_id: int
    fund_id: int
    fund_code: str
    opened_on: date
    units: Decimal
    total_cost_amount: Decimal
    source_transaction_id: int


class TransactionLotSyncService:
    """Materialize current transaction-backed position state into position_lot rows."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def sync_portfolio(
        self,
        *,
        portfolio_id: int,
        as_of_date: date | None = None,
        run_id: str | None = None,
    ) -> TransactionLotSyncResult:
        effective_as_of_date = as_of_date or self._get_latest_trade_date(portfolio_id)
        if effective_as_of_date is None:
            return TransactionLotSyncResult(
                portfolio_id=portfolio_id,
                as_of_date=date.today(),
                run_id=run_id or self._build_run_id(),
                snapshot_count=0,
                fund_codes=(),
            )

        effective_run_id = run_id or self._build_run_id()
        ledger_state = self._build_ledger_state(
            portfolio_id=portfolio_id,
            as_of_date=effective_as_of_date,
        )
        for state in ledger_state.values():
            self._append_snapshot_row(
                state,
                as_of_date=effective_as_of_date,
                run_id=effective_run_id,
            )

        return TransactionLotSyncResult(
            portfolio_id=portfolio_id,
            as_of_date=effective_as_of_date,
            run_id=effective_run_id,
            snapshot_count=len(ledger_state),
            fund_codes=tuple(sorted(ledger_state)),
        )

    def _get_latest_trade_date(self, portfolio_id: int) -> date | None:
        return self._session.scalar(
            select(func.max(TransactionRecord.trade_date)).where(
                TransactionRecord.portfolio_id == portfolio_id
            )
        )

    def _build_ledger_state(
        self,
        *,
        portfolio_id: int,
        as_of_date: date,
    ) -> dict[str, _FundLedgerState]:
        rows = self._session.execute(
            select(TransactionRecord, FundMaster.fund_code)
            .join(FundMaster, FundMaster.id == TransactionRecord.fund_id)
            .where(
                TransactionRecord.portfolio_id == portfolio_id,
                TransactionRecord.trade_date <= as_of_date,
            )
            .order_by(TransactionRecord.trade_date.asc(), TransactionRecord.id.asc())
        ).all()

        state_by_fund_code: dict[str, _FundLedgerState] = {}
        for transaction, fund_code in rows:
            units = self._normalize_units(transaction.units)
            if transaction.trade_type in _INCREASE_TYPES:
                if units <= ZERO:
                    continue
                self._apply_increase(
                    state_by_fund_code,
                    fund_code=fund_code,
                    transaction=transaction,
                    units=units,
                )
                continue
            if transaction.trade_type in _DECREASE_TYPES:
                if units <= ZERO:
                    continue
                self._apply_decrease(
                    state_by_fund_code,
                    fund_code=fund_code,
                    transaction=transaction,
                    units=units,
                )
                continue
            if transaction.trade_type == TransactionType.ADJUST:
                if units > ZERO:
                    self._apply_increase(
                        state_by_fund_code,
                        fund_code=fund_code,
                        transaction=transaction,
                        units=units,
                    )
                elif units < ZERO:
                    self._apply_decrease(
                        state_by_fund_code,
                        fund_code=fund_code,
                        transaction=transaction,
                        units=self._normalize_units(-units),
                    )

        return state_by_fund_code

    def _apply_increase(
        self,
        state_by_fund_code: dict[str, _FundLedgerState],
        *,
        fund_code: str,
        transaction: TransactionRecord,
        units: Decimal,
    ) -> None:
        cost_increment = self._resolve_cost_increment(transaction=transaction, units=units)
        state = state_by_fund_code.get(fund_code)
        if state is None:
            state_by_fund_code[fund_code] = _FundLedgerState(
                portfolio_id=transaction.portfolio_id,
                fund_id=transaction.fund_id,
                fund_code=fund_code,
                opened_on=transaction.trade_date,
                units=units,
                total_cost_amount=cost_increment,
                source_transaction_id=transaction.id,
            )
            return

        state.units = self._normalize_units(state.units + units)
        state.total_cost_amount = quantize_money(state.total_cost_amount + cost_increment)

    def _apply_decrease(
        self,
        state_by_fund_code: dict[str, _FundLedgerState],
        *,
        fund_code: str,
        transaction: TransactionRecord,
        units: Decimal,
    ) -> None:
        state = state_by_fund_code.get(fund_code)
        if state is None or state.units <= ZERO:
            msg = (
                f"Cannot reduce transaction-backed position for fund {fund_code} "
                "because no positive holdings exist in the ledger state."
            )
            raise ValueError(msg)
        if units > state.units:
            msg = (
                f"Cannot reduce {units} units for fund {fund_code}; "
                f"only {state.units} units are available."
            )
            raise ValueError(msg)

        average_cost = state.total_cost_amount / state.units if state.units > ZERO else ZERO
        next_units = self._normalize_units(state.units - units)
        if next_units == ZERO:
            state.units = ZERO
            state.total_cost_amount = ZERO
            return

        reduced_cost = average_cost * units
        state.units = next_units
        state.total_cost_amount = quantize_money(state.total_cost_amount - reduced_cost)

    def _resolve_cost_increment(
        self,
        *,
        transaction: TransactionRecord,
        units: Decimal,
    ) -> Decimal:
        gross_amount = transaction.gross_amount or ZERO
        fee_amount = transaction.fee_amount or ZERO
        if gross_amount > ZERO:
            return quantize_money(gross_amount + fee_amount)
        if transaction.nav_per_unit is not None:
            return quantize_money(units * transaction.nav_per_unit + fee_amount)
        return quantize_money(fee_amount)

    def _append_snapshot_row(
        self,
        state: _FundLedgerState,
        *,
        as_of_date: date,
        run_id: str,
    ) -> None:
        average_cost = (
            (state.total_cost_amount / state.units).quantize(
                AVG_COST_QUANTIZER,
                rounding=ROUND_HALF_UP,
            )
            if state.units > ZERO
            else ZERO.quantize(AVG_COST_QUANTIZER, rounding=ROUND_HALF_UP)
        )
        self._session.add(
            PositionLot(
                portfolio_id=state.portfolio_id,
                fund_id=state.fund_id,
                source_transaction_id=state.source_transaction_id,
                run_id=run_id,
                lot_key=f"{TRANSACTION_AGGREGATE_LOT_PREFIX}{state.fund_code}",
                opened_on=state.opened_on,
                as_of_date=as_of_date,
                remaining_units=state.units.quantize(UNITS_QUANTIZER, rounding=ROUND_HALF_UP),
                average_cost_per_unit=average_cost,
                total_cost_amount=state.total_cost_amount.quantize(
                    TOTAL_COST_QUANTIZER,
                    rounding=ROUND_HALF_UP,
                ),
            )
        )

    def _build_run_id(self) -> str:
        return f"txnagg-sync-{uuid4().hex[:12]}"

    def _normalize_units(self, value: Decimal | None) -> Decimal:
        return (value or ZERO).quantize(UNITS_QUANTIZER, rounding=ROUND_HALF_UP)


__all__ = [
    "TRANSACTION_AGGREGATE_LOT_PREFIX",
    "TransactionLotSyncResult",
    "TransactionLotSyncService",
]
