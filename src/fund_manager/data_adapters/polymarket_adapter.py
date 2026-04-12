"""Polymarket Gamma API adapter for fetching prediction market data."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx


GAMMA_API_BASE = "https://gamma-api.polymarket.com"


def _get_http_client() -> httpx.Client:
    """Build an httpx client that respects proxy env vars."""
    # httpx auto-detects HTTP_PROXY/HTTPS_PROXY/ALL_PROXY
    return httpx.Client(timeout=20.0)


class PolymarketAdapter:
    """Low-level adapter for the Polymarket Gamma REST API."""

    def __init__(self, base_url: str = GAMMA_API_BASE) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = _get_http_client()

    def close(self) -> None:
        self._client.close()

    # ---- Markets ----

    def get_markets(
        self,
        *,
        active: bool | None = None,
        closed: bool | None = None,
        limit: int = 20,
        offset: int = 0,
        slug: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch a list of markets with optional filters."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if active is not None:
            params["active"] = str(active).lower()
        if closed is not None:
            params["closed"] = str(closed).lower()
        if slug:
            params["slug"] = slug

        resp = self._client.get(f"{self._base_url}/markets", params=params)
        resp.raise_for_status()
        return resp.json()

    # ---- Events (groups of markets) ----

    def get_events(
        self,
        *,
        active: bool | None = None,
        closed: bool | None = None,
        limit: int = 20,
        offset: int = 0,
        slug: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch events, each containing nested markets."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if active is not None:
            params["active"] = str(active).lower()
        if closed is not None:
            params["closed"] = str(closed).lower()
        if slug:
            params["slug"] = slug

        resp = self._client.get(f"{self._base_url}/events", params=params)
        resp.raise_for_status()
        return resp.json()

    def get_event_by_slug(self, slug: str) -> dict[str, Any] | None:
        """Fetch a single event by its slug. Returns None if not found."""
        events = self.get_events(slug=slug, limit=1)
        return events[0] if events else None

    # ---- Search ----

    def search_markets(
        self,
        query: str,
        *,
        active: bool = True,
        closed: bool = False,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search markets by keyword in the question text (client-side filter)."""
        # Gamma API doesn't have full-text search; we fetch and filter.
        results: list[dict[str, Any]] = []
        offset = 0
        batch = 100
        query_lower = query.lower()

        while len(results) < limit:
            markets = self.get_markets(
                active=active, closed=closed, limit=batch, offset=offset
            )
            if not markets:
                break
            for m in markets:
                if query_lower in m.get("question", "").lower():
                    results.append(m)
                    if len(results) >= limit:
                        break
            offset += batch

        return results[:limit]

    def search_events(
        self,
        query: str,
        *,
        active: bool = True,
        closed: bool = False,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search events by keyword in the title (client-side filter)."""
        results: list[dict[str, Any]] = []
        offset = 0
        batch = 100
        query_lower = query.lower()

        while len(results) < limit:
            events = self.get_events(
                active=active, closed=closed, limit=batch, offset=offset
            )
            if not events:
                break
            for e in events:
                if query_lower in e.get("title", "").lower():
                    results.append(e)
                    if len(results) >= limit:
                        break
            offset += batch

        return results[:limit]
