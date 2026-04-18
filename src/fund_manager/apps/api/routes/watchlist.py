"""Watchlist API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from fund_manager.apps.api.dependencies import get_db
from fund_manager.core.serialization import serialize_for_json
from fund_manager.core.watchlist import FundWatchlistService

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


class WatchlistItemResponse(BaseModel):
    watchlist_item_id: int
    fund_id: int
    fund_code: str
    fund_name: str
    category: str | None = None
    style_tags: list[str] = Field(default_factory=list)
    risk_level: str | None = None
    note: str | None = None
    source_name: str | None = None
    created_at: datetime
    updated_at: datetime
    removed_at: datetime | None = None


class WatchlistListResponse(BaseModel):
    items: list[WatchlistItemResponse] = Field(default_factory=list)


class WatchlistAddRequest(BaseModel):
    fund_code: str
    fund_name: str
    category: str | None = None
    style_tags: list[str] = Field(default_factory=list)
    risk_level: str | None = None
    note: str | None = None
    source_name: str | None = "api"


class WatchlistAddResponse(BaseModel):
    item: WatchlistItemResponse
    fund_created: bool
    fund_updated: bool
    watchlist_created: bool
    watchlist_updated: bool
    message: str


class WatchlistRemoveResponse(BaseModel):
    item: WatchlistItemResponse
    message: str


@router.get("", response_model=WatchlistListResponse)
def list_watchlist_items(
    session: Annotated[Session, Depends(get_db)],
    include_removed: Annotated[bool, Query()] = False,
) -> WatchlistListResponse:
    service = FundWatchlistService(session)
    items = service.list_items(include_removed=include_removed)
    return WatchlistListResponse.model_validate({"items": serialize_for_json(items)})


@router.post(
    "/items",
    response_model=WatchlistAddResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_watchlist_item(
    request: WatchlistAddRequest,
    session: Annotated[Session, Depends(get_db)],
) -> WatchlistAddResponse:
    service = FundWatchlistService(session)
    try:
        result = service.add_item(
            fund_code=request.fund_code,
            fund_name=request.fund_name,
            category=request.category,
            style_tags=tuple(request.style_tags),
            risk_level=request.risk_level,
            note=request.note,
            source_name=request.source_name,
        )
    except ValueError as exc:
        raise _translate_watchlist_error(exc) from exc
    return WatchlistAddResponse.model_validate(
        serialize_for_json(
            {
                "item": result.item,
                "fund_created": result.fund_created,
                "fund_updated": result.fund_updated,
                "watchlist_created": result.watchlist_created,
                "watchlist_updated": result.watchlist_updated,
                "message": f"Fund {result.item.fund_code} is in the active watchlist.",
            }
        )
    )


@router.delete("/items/{fund_code}", response_model=WatchlistRemoveResponse)
def remove_watchlist_item(
    fund_code: str,
    session: Annotated[Session, Depends(get_db)],
) -> WatchlistRemoveResponse:
    service = FundWatchlistService(session)
    try:
        item = service.remove_item(fund_code=fund_code)
    except ValueError as exc:
        raise _translate_watchlist_error(exc) from exc
    return WatchlistRemoveResponse.model_validate(
        serialize_for_json(
            {
                "item": item,
                "message": f"Fund {item.fund_code} was removed from the active watchlist.",
            }
        )
    )


def _translate_watchlist_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    normalized = message.lower()
    if "fund '" in normalized and "was not found" in normalized:
        return HTTPException(status_code=404, detail="Fund not found")
    if "not in the active watchlist" in normalized:
        return HTTPException(status_code=404, detail="Watchlist item not found")
    return HTTPException(status_code=400, detail=message)


__all__ = ["router"]
