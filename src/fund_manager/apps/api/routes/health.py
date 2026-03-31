"""Health-check routes."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from fund_manager.core.config import Settings, get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Response model for the health endpoint."""

    name: str = Field(..., description="Service name.")
    environment: str = Field(..., description="Runtime environment.")
    status: str = Field(..., description="Health status.")


@router.get("/health", response_model=HealthResponse, summary="Health check")
def read_health(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Return a small service heartbeat response."""
    return HealthResponse(
        name=settings.app_name,
        environment=settings.app_env,
        status="ok",
    )
