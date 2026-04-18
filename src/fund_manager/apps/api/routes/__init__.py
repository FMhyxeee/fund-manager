"""API route registration for the simplified core."""

from fastapi import APIRouter

from fund_manager.apps.api.routes.funds import router as funds_router
from fund_manager.apps.api.routes.health import router as health_router
from fund_manager.apps.api.routes.portfolios import router as portfolios_router
from fund_manager.apps.api.routes.transactions import router as transactions_router
from fund_manager.apps.api.routes.watchlist import router as watchlist_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(portfolios_router)
api_router.include_router(funds_router)
api_router.include_router(transactions_router)
api_router.include_router(watchlist_router)
