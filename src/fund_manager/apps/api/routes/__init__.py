"""API route registration."""

from fastapi import APIRouter

from fund_manager.apps.api.routes.funds import router as funds_router
from fund_manager.apps.api.routes.health import router as health_router
from fund_manager.apps.api.routes.imports import router as imports_router
from fund_manager.apps.api.routes.portfolios import router as portfolios_router
from fund_manager.apps.api.routes.reports import router as reports_router
from fund_manager.apps.api.routes.workflows import router as workflows_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(portfolios_router)
api_router.include_router(funds_router)
api_router.include_router(reports_router)
api_router.include_router(imports_router)
api_router.include_router(workflows_router)
