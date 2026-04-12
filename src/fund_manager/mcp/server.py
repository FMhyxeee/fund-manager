"""Optional MCP transport layer for fund-manager."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from typing import Iterator

from fund_manager.core.config import get_settings
from fund_manager.core.services.polymarket_service import PolymarketService
from fund_manager.data_adapters.polymarket_adapter import PolymarketAdapter
from fund_manager.mcp.service import FundManagerMCPService, ModelAllocation
from fund_manager.storage.db import get_session_factory

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - exercised only when optional dependency is missing.
    FastMCP = None  # type: ignore[assignment]


@contextmanager
def _service_session() -> Iterator[FundManagerMCPService]:
    session = get_session_factory()()
    try:
        yield FundManagerMCPService(session)
    finally:
        session.close()


def create_server() -> "FastMCP":
    """Create the MCP server instance when the optional dependency is installed."""
    if FastMCP is None:
        msg = (
            "The optional 'mcp' dependency is not installed. "
            "Run: pip install -e '.[mcp]'"
        )
        raise RuntimeError(msg)

    settings = get_settings()
    server = FastMCP(
        name=f"{settings.app_name}-mcp",
        instructions=(
            "Read-only data and simulation tools for the fund-manager personal portfolio system."
        ),
    )

    @server.tool()
    def portfolio_list() -> dict:
        with _service_session() as service:
            return service.list_portfolios()

    @server.tool()
    def portfolio_snapshot(
        as_of_date: str,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
    ) -> dict:
        with _service_session() as service:
            return service.get_portfolio_snapshot(
                as_of_date=date.fromisoformat(as_of_date),
                portfolio_id=portfolio_id,
                portfolio_name=portfolio_name,
            )

    @server.tool()
    def portfolio_positions(
        as_of_date: str,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
    ) -> dict:
        with _service_session() as service:
            return service.get_position_breakdown(
                as_of_date=date.fromisoformat(as_of_date),
                portfolio_id=portfolio_id,
                portfolio_name=portfolio_name,
            )

    @server.tool()
    def portfolio_valuation_history(
        end_date: str,
        start_date: str | None = None,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
    ) -> dict:
        with _service_session() as service:
            return service.get_portfolio_valuation_history(
                end_date=date.fromisoformat(end_date),
                start_date=date.fromisoformat(start_date) if start_date is not None else None,
                portfolio_id=portfolio_id,
                portfolio_name=portfolio_name,
            )

    @server.tool()
    def portfolio_metrics(
        as_of_date: str,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
    ) -> dict:
        with _service_session() as service:
            return service.get_portfolio_metrics(
                as_of_date=date.fromisoformat(as_of_date),
                portfolio_id=portfolio_id,
                portfolio_name=portfolio_name,
            )

    @server.tool()
    def fund_profile(fund_code: str) -> dict:
        with _service_session() as service:
            return service.get_fund_profile(fund_code=fund_code)

    @server.tool()
    def fund_nav_history(fund_code: str, start_date: str, end_date: str) -> dict:
        with _service_session() as service:
            return service.get_fund_nav_history(
                fund_code=fund_code,
                start_date=date.fromisoformat(start_date),
                end_date=date.fromisoformat(end_date),
            )

    @server.tool()
    def polymarket_search_events(query: str, limit: int = 10) -> dict:
        """Search Polymarket prediction market events by keyword.

        Returns active events with their sub-markets and current prices.
        """
        with PolymarketService() as svc:
            return {"events": svc.search_events(query, limit=limit)}

    @server.tool()
    def polymarket_estimate_time(slug: str) -> dict:
        """Estimate when a Polymarket event will occur based on its time-ladder markets.

        Given an event slug (e.g. 'microstrategy-sell-any-bitcoin-in-2025'),
        fetches all sub-markets with different deadlines, reads their Yes prices
        as cumulative probabilities, and computes a probability-weighted expected date.

        Returns the event title, time ladder (date + probability), estimated date,
        and the estimation method used.
        """
        with PolymarketService() as svc:
            return svc.estimate_event_time(slug)

    @server.tool()
    def simulate_model_portfolio(
        allocations: list[dict[str, str | int | float]],
        start_date: str,
        end_date: str,
        rebalance: str = "none",
    ) -> dict:
        with _service_session() as service:
            normalized_allocations = tuple(
                ModelAllocation(
                    fund_code=str(allocation["fund_code"]),
                    weight=Decimal(str(allocation["weight"])),
                )
                for allocation in allocations
            )
            return service.simulate_model_portfolio(
                allocations=normalized_allocations,
                start_date=date.fromisoformat(start_date),
                end_date=date.fromisoformat(end_date),
                rebalance=rebalance,  # type: ignore[arg-type]
            )

    return server


def main() -> None:
    """Run the MCP server over the default transport."""
    create_server().run()


__all__ = ["create_server", "main"]
