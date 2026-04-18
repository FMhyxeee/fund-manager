"""Repository helpers for append-only transaction records."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from fund_manager.storage.models import TransactionRecord, TransactionType


class TransactionRepository:
    """Persist normalized portfolio transactions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, transaction_id: int) -> TransactionRecord | None:
        """Return one transaction with related display and link metadata."""
        statement = (
            select(TransactionRecord)
            .options(
                selectinload(TransactionRecord.portfolio),
                selectinload(TransactionRecord.fund),
            )
            .where(TransactionRecord.id == transaction_id)
            .limit(1)
        )
        return self._session.execute(statement).scalars().first()

    def list_recent(
        self,
        *,
        portfolio_id: int | None = None,
        fund_id: int | None = None,
        trade_type: TransactionType | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 50,
    ) -> tuple[TransactionRecord, ...]:
        """Return transaction records in reverse chronological order."""
        statement = select(TransactionRecord).options(
            selectinload(TransactionRecord.portfolio),
            selectinload(TransactionRecord.fund),
        )
        if portfolio_id is not None:
            statement = statement.where(TransactionRecord.portfolio_id == portfolio_id)
        if fund_id is not None:
            statement = statement.where(TransactionRecord.fund_id == fund_id)
        if trade_type is not None:
            statement = statement.where(TransactionRecord.trade_type == trade_type)
        if start_date is not None:
            statement = statement.where(TransactionRecord.trade_date >= start_date)
        if end_date is not None:
            statement = statement.where(TransactionRecord.trade_date <= end_date)

        statement = statement.order_by(
            TransactionRecord.trade_date.desc(),
            TransactionRecord.id.desc(),
        ).limit(limit)
        return tuple(self._session.execute(statement).scalars().all())

    def append_import_record(
        self,
        *,
        portfolio_id: int,
        fund_id: int,
        external_reference: str | None,
        trade_date: date,
        trade_type: TransactionType,
        units: Decimal | None,
        gross_amount: Decimal | None,
        fee_amount: Decimal | None,
        nav_per_unit: Decimal | None,
        source_name: str | None,
        source_reference: str | None,
        note: str | None,
    ) -> TransactionRecord:
        """Append one imported transaction without mutating prior history."""
        transaction = TransactionRecord(
            portfolio_id=portfolio_id,
            fund_id=fund_id,
            external_reference=external_reference,
            trade_date=trade_date,
            trade_type=trade_type,
            units=units,
            gross_amount=gross_amount,
            fee_amount=fee_amount,
            nav_per_unit=nav_per_unit,
            source_name=source_name,
            source_reference=source_reference,
            note=note,
        )
        self._session.add(transaction)
        return transaction
