"""Polymarket prediction market service — event discovery and time estimation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fund_manager.data_adapters.polymarket_adapter import PolymarketAdapter


class PolymarketService:
    """High-level service for Polymarket queries and time predictions."""

    def __init__(self, adapter: PolymarketAdapter | None = None) -> None:
        self._adapter = adapter or PolymarketAdapter()

    def close(self) -> None:
        self._adapter.close()

    def __enter__(self) -> PolymarketService:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ---- Search ----

    def search_events(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search active events matching a keyword."""
        raw = self._adapter.search_events(query, active=True, closed=False, limit=limit)
        return [self._format_event(e) for e in raw]

    def search_markets(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search active markets matching a keyword."""
        raw = self._adapter.search_markets(query, active=True, closed=False, limit=limit)
        return [self._format_market(m) for m in raw]

    def get_event(self, slug: str) -> dict[str, Any] | None:
        """Get a single event with all its sub-markets."""
        raw = self._adapter.get_event_by_slug(slug)
        if raw is None:
            return None
        return self._format_event(raw)

    # ---- Time Prediction ----

    def estimate_event_time(self, slug: str) -> dict[str, Any]:
        """
        Estimate when an event will occur based on its time-ladder markets.

        An event on Polymarket often has multiple sub-markets of the form
        "Will X happen by [date]?", each with a different deadline and price.
        We treat the Yes price as P(X happens by date) and compute a
        probability-weighted expected time.

        Returns:
            dict with event info, time ladder, and estimated date.
        """
        raw = self._adapter.get_event_by_slug(slug)
        if raw is None:
            return {"error": f"Event not found: {slug}"}

        markets = raw.get("markets", [])
        if not markets:
            return {"error": "No markets found for this event"}

        # Build time ladder: [(end_date, p_yes)]
        ladder: list[dict[str, Any]] = []
        for m in markets:
            end_str = m.get("endDate") or m.get("endDateIso")
            if not end_str:
                continue
            try:
                end_dt = self._parse_dt(end_str)
            except (ValueError, TypeError):
                continue

            prices = m.get("outcomePrices")
            p_yes = self._parse_yes_price(prices)
            if p_yes is None:
                continue

            ladder.append({
                "question": m.get("question", ""),
                "group": m.get("groupItemTitle", ""),
                "end_date": end_dt.isoformat(),
                "p_yes": round(p_yes, 4),
            })

        if not ladder:
            return {
                "event": raw.get("title", ""),
                "error": "No markets with parseable dates and prices",
            }

        # Sort by end date
        ladder.sort(key=lambda x: x["end_date"])

        # Compute probability-weighted expected time
        # P(happens in period i) = P(happens by date_i) - P(happens by date_{i-1})
        # E[time] = sum(P_i * mid_date_i)
        now = datetime.now(timezone.utc)

        # Filter out resolved (p_yes ≈ 0 or ≈ 1) for estimation, but keep all in ladder
        active_rungs = [r for r in ladder if 0.001 < r["p_yes"] < 0.999]

        estimated_date = None
        method = ""

        if len(active_rungs) >= 2:
            # Multi-rung estimation
            estimated_date = self._weighted_estimate(active_rungs, now)
            method = "probability-weighted (multi-rung)"
        elif len(active_rungs) == 1:
            # Single rung: if p_yes is significant, estimate proportion of remaining time
            rung = active_rungs[0]
            end_dt = datetime.fromisoformat(rung["end_date"])
            remaining = (end_dt - now).total_seconds()
            p = rung["p_yes"]
            # Simple model: expected time = now + remaining * f(p)
            # where f(p) is a calibrated factor. Use inverse CDF of exponential dist.
            # For P(T < t_end) = p => lambda = -ln(1-p) / t_end
            # E[T] = 1/lambda => E[T] = t_end / -ln(1-p)
            import math
            if p > 0.99:
                frac = 0.3  # very likely soon
            elif p < 0.01:
                frac = 0.9  # unlikely, assume late
            else:
                # expected fraction of remaining time
                frac = -math.log(1 - p) / (-math.log(1 - p) + 1)
                frac = min(frac, 0.95)
            est_seconds = remaining * frac
            estimated_date = (now.timestamp() + est_seconds)
            estimated_date = datetime.fromtimestamp(estimated_date, tz=timezone.utc).isoformat()
            method = f"single-rung exponential (p={p:.2f})"
        else:
            # All resolved or no active rungs
            if any(r["p_yes"] > 0.99 for r in ladder):
                method = "already occurred (p≈1 in at least one rung)"
                # Find earliest rung with p≈1
                for r in ladder:
                    if r["p_yes"] > 0.99:
                        estimated_date = r["end_date"]
                        break
            else:
                method = "unlikely in all timeframes (all p≈0)"

        return {
            "event": raw.get("title", ""),
            "slug": slug,
            "ladder": ladder,
            "estimated_date": estimated_date,
            "method": method,
        }

    def _weighted_estimate(
        self, rungs: list[dict[str, Any]], now: datetime
    ) -> str | None:
        """Compute probability-weighted expected date from multiple rungs."""
        import math

        # Compute incremental probabilities
        deltas: list[tuple[float, float]] = []  # (p_incremental, mid_timestamp)
        prev_p = 0.0

        for rung in rungs:
            p = rung["p_yes"]
            end_dt = datetime.fromisoformat(rung["end_date"])
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)

            dp = max(p - prev_p, 0)
            if dp > 0:
                # Midpoint of the time interval
                # Use the rung end date as the representative time for this increment
                # (conservative: assume event happens near deadline)
                mid_ts = end_dt.timestamp()
                deltas.append((dp, mid_ts))

            prev_p = p

        if not deltas:
            return None

        # Remaining probability assigned to "beyond last rung"
        total_p = sum(d[0] for d in deltas)
        if total_p < 0.01:
            return None

        # Normalize
        est_ts = sum(p * ts for p, ts in deltas) / total_p
        return datetime.fromtimestamp(est_ts, tz=timezone.utc).isoformat()

    # ---- Formatting helpers ----

    @staticmethod
    def _parse_dt(s: str) -> datetime:
        """Parse a datetime string, normalizing to UTC."""
        s = s.strip()
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s[:26], fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        # Try ISO format directly
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _parse_yes_price(prices: str | list | None) -> float | None:
        """Extract the Yes price (first outcome) from outcomePrices."""
        if prices is None:
            return None
        if isinstance(prices, list):
            if not prices:
                return None
            try:
                return float(prices[0])
            except (ValueError, TypeError):
                return None
        # JSON string like "[\"0.525\", \"0.475\"]"
        import json
        try:
            parsed = json.loads(prices)
            return float(parsed[0])
        except (json.JSONDecodeError, ValueError, TypeError, IndexError):
            return None

    @staticmethod
    def _format_market(m: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": m.get("id"),
            "question": m.get("question"),
            "slug": m.get("slug"),
            "end_date": m.get("endDate") or m.get("endDateIso"),
            "outcome_prices": m.get("outcomePrices"),
            "volume": m.get("volumeNum") or m.get("volume"),
            "active": m.get("active"),
            "closed": m.get("closed"),
        }

    @staticmethod
    def _format_event(e: dict[str, Any]) -> dict[str, Any]:
        markets = [
            PolymarketService._format_market(m)
            for m in e.get("markets", [])
        ]
        return {
            "id": e.get("id"),
            "title": e.get("title"),
            "slug": e.get("slug"),
            "markets": markets,
        }
