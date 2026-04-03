"""Dashboard route serving a single-page HTML overview."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_manager.apps.api.dependencies import get_db
from fund_manager.core.services.portfolio_service import (
    PortfolioNotFoundError,
    PortfolioService,
)
from fund_manager.storage.models import Portfolio, ReviewReport

router = APIRouter(tags=["dashboard"])

_template_dir = Path(__file__).resolve().parent.parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(str(_template_dir)), autoescape=True)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(session: Annotated[Session, Depends(get_db)]) -> HTMLResponse:
    portfolios = (
        session.execute(select(Portfolio).order_by(Portfolio.is_default.desc(), Portfolio.id.asc()))
        .scalars()
        .all()
    )

    portfolio_id: int | None = None
    if portfolios:
        portfolio_id = portfolios[0].id

    snapshot = None
    if portfolio_id is not None:
        service = PortfolioService(session)
        try:
            dto = service.assemble_portfolio_snapshot(
                portfolio_id=portfolio_id,
                as_of_date=date.today(),
            )
            snapshot = {
                "portfolio_id": dto.portfolio_id,
                "portfolio_code": dto.portfolio_code,
                "portfolio_name": dto.portfolio_name,
                "as_of_date": dto.as_of_date.isoformat(),
                "position_count": dto.position_count,
                "total_cost": str(dto.total_cost_amount),
                "total_market_value": str(dto.total_market_value_amount)
                if dto.total_market_value_amount is not None
                else None,
                "unrealized_pnl": str(dto.unrealized_pnl_amount)
                if dto.unrealized_pnl_amount is not None
                else None,
                "daily_return": str(dto.daily_return_ratio)
                if dto.daily_return_ratio is not None
                else None,
                "weekly_return": str(dto.weekly_return_ratio)
                if dto.weekly_return_ratio is not None
                else None,
                "monthly_return": str(dto.monthly_return_ratio)
                if dto.monthly_return_ratio is not None
                else None,
                "period_return": str(dto.period_return_ratio)
                if dto.period_return_ratio is not None
                else None,
                "max_drawdown": str(dto.max_drawdown_ratio)
                if dto.max_drawdown_ratio is not None
                else None,
                "missing_nav_fund_codes": list(dto.missing_nav_fund_codes),
                "positions": [
                    {
                        "fund_code": p.fund_code,
                        "fund_name": p.fund_name,
                        "units": str(p.units),
                        "total_cost": str(p.total_cost_amount),
                        "current_value": str(p.current_value_amount)
                        if p.current_value_amount is not None
                        else "N/A",
                        "weight": str(p.weight_ratio) if p.weight_ratio is not None else "N/A",
                        "unrealized_pnl": str(p.unrealized_pnl_amount)
                        if p.unrealized_pnl_amount is not None
                        else "N/A",
                        "missing_nav": p.missing_nav,
                    }
                    for p in dto.positions
                ],
            }
        except PortfolioNotFoundError:
            snapshot = None

    report_rows = (
        session.execute(select(ReviewReport).order_by(ReviewReport.id.desc()).limit(10))
        .scalars()
        .all()
    )
    reports = [
        {
            "id": r.id,
            "portfolio_id": r.portfolio_id,
            "period_type": r.period_type,
            "period_start": r.period_start.isoformat(),
            "period_end": r.period_end.isoformat(),
            "workflow_name": r.workflow_name,
            "created_by_agent": r.created_by_agent,
        }
        for r in report_rows
    ]

    template = _jinja_env.get_template("dashboard.html")
    html = template.render(
        snapshot=snapshot,
        reports=reports,
        portfolios=[
            {"id": p.id, "code": p.portfolio_code, "name": p.portfolio_name} for p in portfolios
        ],
    )
    return HTMLResponse(content=html)
