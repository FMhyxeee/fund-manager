"""Repository helpers for append-only transaction records."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from fund_manager.storage.models import TransactionRecord, TransactionType


class TransactionRepository:
    """Persist normalized portfolio transactions."""

    def __init__(self, session: Session) -> None:
        self._session = session

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
