"""Import API routes for holdings and transactions."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from fund_manager.apps.api.dependencies import get_db
from fund_manager.data_adapters.import_holdings import import_holdings_csv
from fund_manager.data_adapters.import_transactions import import_transactions_csv

router = APIRouter(prefix="/imports", tags=["imports"])


class ImportResponse(BaseModel):
    run_id: str
    imported_count: int
    input_row_count: int
    normalized_row_count: int
    dry_run: bool
    message: str


@router.post("/holdings", response_model=ImportResponse)
async def import_holdings(
    file: UploadFile,
    portfolio_name: str | None = None,
    dry_run: bool = False,
    session: Annotated[Session, Depends(get_db)] = None,
) -> ImportResponse:
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="wb") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        result = import_holdings_csv(
            session,
            tmp_path,
            dry_run=dry_run,
            default_portfolio_name=portfolio_name,
        )
        if not dry_run:
            session.commit()
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return ImportResponse(
        run_id=result.run_id,
        imported_count=result.position_lot_count,
        input_row_count=result.input_row_count,
        normalized_row_count=result.normalized_row_count,
        dry_run=result.dry_run,
        message=f"Imported {result.position_lot_count} position lots ({'dry run' if dry_run else 'committed'}).",
    )


@router.post("/transactions", response_model=ImportResponse)
async def import_transactions(
    file: UploadFile,
    portfolio_name: str | None = None,
    dry_run: bool = False,
    session: Annotated[Session, Depends(get_db)] = None,
) -> ImportResponse:
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="wb") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        result = import_transactions_csv(
            session,
            tmp_path,
            dry_run=dry_run,
            default_portfolio_name=portfolio_name,
        )
        if not dry_run:
            session.commit()
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return ImportResponse(
        run_id=result.run_id,
        imported_count=result.transaction_count,
        input_row_count=result.input_row_count,
        normalized_row_count=result.normalized_row_count,
        dry_run=result.dry_run,
        message=f"Imported {result.transaction_count} transactions ({'dry run' if dry_run else 'committed'}).",
    )
