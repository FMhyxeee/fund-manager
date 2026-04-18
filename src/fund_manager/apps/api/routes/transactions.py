"""Transaction ledger API routes."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from fund_manager.apps.api.dependencies import get_db
from fund_manager.core.serialization import serialize_for_json
from fund_manager.core.services import TransactionService

router = APIRouter(prefix="/transactions", tags=["transactions"])

TradeTypeLiteral = Literal["buy", "sell", "dividend", "convert_in", "convert_out", "adjust"]


class TransactionResponse(BaseModel):
    transaction_id: int
    portfolio_id: int
    portfolio_code: str
    portfolio_name: str
    fund_id: int
    fund_code: str
    fund_name: str
    trade_date: date
    trade_type: str
    units: Decimal | None = None
    gross_amount: Decimal | None = None
    fee_amount: Decimal | None = None
    nav_per_unit: Decimal | None = None
    external_reference: str | None = None
    source_name: str | None = None
    source_reference: str | None = None
    note: str | None = None
    created_at: datetime


class TransactionListResponse(BaseModel):
    transactions: list[TransactionResponse]


class TransactionAppendRequest(BaseModel):
    portfolio_id: int | None = None
    portfolio_name: str | None = None
    fund_code: str
    fund_name: str | None = None
    trade_date: date
    trade_type: TradeTypeLiteral
    units: Decimal | None = None
    gross_amount: Decimal | None = None
    fee_amount: Decimal | None = None
    nav_per_unit: Decimal | None = None
    external_reference: str | None = None
    source_name: str | None = "api"
    source_reference: str | None = None
    note: str | None = None


class TransactionAppendResponse(BaseModel):
    transaction: TransactionResponse
    lot_sync: dict[str, object]
    fund_created: bool
    fund_updated: bool
    message: str


@router.get("", response_model=TransactionListResponse)
def list_transactions(
    session: Annotated[Session, Depends(get_db)],
    portfolio_id: Annotated[int | None, Query()] = None,
    portfolio_name: Annotated[str | None, Query()] = None,
    fund_code: Annotated[str | None, Query()] = None,
    trade_type: Annotated[TradeTypeLiteral | None, Query()] = None,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> TransactionListResponse:
    service = TransactionService(session)
    try:
        transactions = service.list_transactions(
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
            fund_code=fund_code,
            trade_type=trade_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
    except ValueError as exc:
        raise _translate_transaction_error(exc) from exc
    return TransactionListResponse.model_validate(
        {"transactions": serialize_for_json(transactions)}
    )


@router.get("/{transaction_id}", response_model=TransactionResponse)
def get_transaction(
    transaction_id: int,
    session: Annotated[Session, Depends(get_db)],
) -> TransactionResponse:
    service = TransactionService(session)
    try:
        transaction = service.get_transaction(transaction_id=transaction_id)
    except ValueError as exc:
        raise _translate_transaction_error(exc) from exc
    return TransactionResponse.model_validate(serialize_for_json(transaction))


@router.post(
    "",
    response_model=TransactionAppendResponse,
    status_code=status.HTTP_201_CREATED,
)
def append_transaction(
    request: TransactionAppendRequest,
    session: Annotated[Session, Depends(get_db)],
) -> TransactionAppendResponse:
    service = TransactionService(session)
    try:
        result = service.append_transaction(**request.model_dump())
    except ValueError as exc:
        raise _translate_transaction_error(exc) from exc
    return TransactionAppendResponse.model_validate(
        serialize_for_json(
            {
                "transaction": result.transaction,
                "lot_sync": result.lot_sync,
                "fund_created": result.fund_created,
                "fund_updated": result.fund_updated,
                "message": (
                    "Appended authoritative transaction "
                    f"{result.transaction.transaction_id} and rebuilt ledger lots."
                ),
            }
        )
    )


def _translate_transaction_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    normalized = message.lower()
    if "portfolio" in normalized and "was not found" in normalized:
        return HTTPException(status_code=404, detail="Portfolio not found")
    if "transaction" in normalized and "was not found" in normalized:
        return HTTPException(status_code=404, detail="Transaction not found")
    if "fund '" in normalized and "was not found" in normalized:
        return HTTPException(status_code=404, detail="Fund not found")
    return HTTPException(status_code=400, detail=message)


__all__ = ["router"]
