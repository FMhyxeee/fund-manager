"""Repository helpers for portfolio master records."""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fund_manager.storage.models import Portfolio

_PORTFOLIO_CODE_FALLBACK = "portfolio"


def normalize_portfolio_name(portfolio_name: str) -> str:
    """Collapse whitespace so portfolio matching stays stable."""
    normalized_name = " ".join(portfolio_name.split())
    if not normalized_name:
        msg = "Portfolio name cannot be blank."
        raise ValueError(msg)
    return normalized_name


def build_portfolio_code_seed(portfolio_name: str) -> str:
    """Create a stable code seed from a human portfolio name."""
    normalized_name = normalize_portfolio_name(portfolio_name).casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized_name).strip("-")
    return slug or _PORTFOLIO_CODE_FALLBACK


class PortfolioRepository:
    """Read and mutate mutable portfolio master data."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_name(self, portfolio_name: str) -> Portfolio | None:
        """Return a portfolio by case-insensitive name match."""
        normalized_name = normalize_portfolio_name(portfolio_name)
        statement = (
            select(Portfolio)
            .where(func.lower(Portfolio.portfolio_name) == normalized_name.lower())
            .order_by(Portfolio.id.asc())
            .limit(1)
        )
        return self._session.execute(statement).scalars().first()

    def get_or_create(
        self,
        portfolio_name: str,
        *,
        default_portfolio_name: str,
    ) -> tuple[Portfolio, bool]:
        """Create a portfolio when it does not exist yet."""
        normalized_name = normalize_portfolio_name(portfolio_name)
        existing_portfolio = self.get_by_name(normalized_name)
        if existing_portfolio is not None:
            if (
                not existing_portfolio.is_default
                and normalized_name.casefold() == default_portfolio_name.casefold()
            ):
                existing_portfolio.is_default = True
            return existing_portfolio, False

        portfolio_code = self._allocate_unique_code(normalized_name)
        portfolio = Portfolio(
            portfolio_code=portfolio_code,
            portfolio_name=normalized_name,
            is_default=normalized_name.casefold() == default_portfolio_name.casefold(),
        )
        self._session.add(portfolio)
        self._session.flush()
        return portfolio, True

    def _allocate_unique_code(self, portfolio_name: str) -> str:
        """Allocate a unique stable code for a portfolio name."""
        code_seed = build_portfolio_code_seed(portfolio_name)
        candidate_code = code_seed
        suffix = 2

        while self._code_exists(candidate_code):
            candidate_code = f"{code_seed}-{suffix}"
            suffix += 1

        return candidate_code

    def _code_exists(self, portfolio_code: str) -> bool:
        statement = select(Portfolio.id).where(Portfolio.portfolio_code == portfolio_code).limit(1)
        return self._session.execute(statement).first() is not None
