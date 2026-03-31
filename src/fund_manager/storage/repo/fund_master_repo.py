"""Repository helpers for fund master records."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_manager.storage.models import FundMaster


@dataclass(frozen=True)
class FundUpsertResult:
    """Outcome of a fund master upsert."""

    fund: FundMaster
    created: bool
    updated: bool


class FundMasterRepository:
    """Read and mutate fund master records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_code(self, fund_code: str) -> FundMaster | None:
        """Return a fund master record for a code when present."""
        statement = select(FundMaster).where(FundMaster.fund_code == fund_code).limit(1)
        return self._session.execute(statement).scalars().first()

    def upsert(
        self,
        *,
        fund_code: str,
        fund_name: str,
        source_name: str = "holdings_import",
    ) -> FundUpsertResult:
        """Create a new fund or refresh mutable display fields."""
        existing_fund = self.get_by_code(fund_code)
        if existing_fund is None:
            fund = FundMaster(
                fund_code=fund_code,
                fund_name=fund_name,
                source_name=source_name,
            )
            self._session.add(fund)
            self._session.flush()
            return FundUpsertResult(fund=fund, created=True, updated=False)

        updated = False
        if existing_fund.fund_name != fund_name:
            existing_fund.fund_name = fund_name
            updated = True
        if existing_fund.source_name is None:
            existing_fund.source_name = source_name
            updated = True

        return FundUpsertResult(fund=existing_fund, created=False, updated=updated)
