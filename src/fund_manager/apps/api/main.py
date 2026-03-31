"""Minimal FastAPI application bootstrap."""

from fastapi import FastAPI

from fund_manager.apps.api.routes import api_router
from fund_manager.core.config import get_settings


def create_app() -> FastAPI:
    """Create the FastAPI application instance."""
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url=f"{settings.api_prefix}/docs",
        openapi_url=f"{settings.api_prefix}/openapi.json",
    )
    application.include_router(api_router, prefix=settings.api_prefix)
    return application


app = create_app()


def run() -> None:
    """Run the local development server."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "fund_manager.apps.api.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_env == "local",
    )
