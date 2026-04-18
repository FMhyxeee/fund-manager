"""Stable API error envelope helpers."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from fund_manager.core.serialization import serialize_for_json


class ErrorBody(BaseModel):
    """Stable machine-readable API error payload."""

    code: str
    message: str
    details: dict[str, Any] | list[Any] | None = None


class ErrorResponse(BaseModel):
    """Stable top-level API error envelope."""

    detail: str
    error: ErrorBody


def install_exception_handlers(application: FastAPI) -> None:
    """Register stable error handlers for API callers."""

    @application.exception_handler(HTTPException)
    async def _http_exception_handler(
        request: Request,
        exc: HTTPException,
    ) -> JSONResponse:
        del request
        message = _extract_error_message(exc.detail)
        response = ErrorResponse(
            detail=message,
            error=ErrorBody(
                code=_infer_error_code(exc.status_code, message),
                message=message,
                details=_extract_error_details(exc.detail),
            ),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=serialize_for_json(response.model_dump()),
        )

    @application.exception_handler(RequestValidationError)
    async def _validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        del request
        response = ErrorResponse(
            detail="Request validation failed",
            error=ErrorBody(
                code="validation_error",
                message="Request validation failed",
                details=list(exc.errors()),
            ),
        )
        return JSONResponse(
            status_code=422,
            content=serialize_for_json(response.model_dump()),
        )

    @application.exception_handler(Exception)
    async def _unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        del request
        response = ErrorResponse(
            detail="Internal server error",
            error=ErrorBody(
                code="internal_error",
                message="Internal server error",
                details={"error_type": type(exc).__name__},
            ),
        )
        return JSONResponse(
            status_code=500,
            content=serialize_for_json(response.model_dump()),
        )


def _extract_error_message(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str) and message:
            return message
    return "Request failed"


def _extract_error_details(detail: Any) -> dict[str, Any] | list[Any] | None:
    if isinstance(detail, dict):
        details = detail.get("details")
        if isinstance(details, (dict, list)):
            return details
        return detail
    return None


def _infer_error_code(status_code: int, message: str) -> str:
    normalized = message.strip().lower()
    if status_code == 404:
        if "portfolio not found" in normalized:
            return "portfolio_not_found"
        if "transaction not found" in normalized:
            return "transaction_not_found"
        if "watchlist item not found" in normalized:
            return "watchlist_item_not_found"
        if "fund not found" in normalized:
            return "fund_not_found"
        return "not_found"

    if status_code == 409:
        if "missing nav" in normalized or "incomplete portfolio snapshot" in normalized:
            return "snapshot_incomplete"
        return "conflict"

    if status_code == 400:
        if "fund '" in normalized and "was not found" in normalized:
            return "fund_not_found"
        return "invalid_request"

    return f"http_{status_code}"


__all__ = ["ErrorBody", "ErrorResponse", "install_exception_handlers"]
