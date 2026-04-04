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

    def update_public_profile(
        self,
        *,
        fund_code: str,
        fund_name: str | None = None,
        fund_type: str | None = None,
        company_name: str | None = None,
        manager_name: str | None = None,
        benchmark_name: str | None = None,
        source_name: str | None = None,
        source_reference: str | None = None,
    ) -> bool:
        """Refresh mutable public profile fields when new values are available."""
        fund = self.get_by_code(fund_code)
        if fund is None:
            msg = f"Fund {fund_code} does not exist."
            raise ValueError(msg)

        updated = False
        updates = {
            "fund_name": fund_name,
            "fund_type": fund_type,
            "company_name": company_name,
            "manager_name": manager_name,
            "benchmark_name": benchmark_name,
            "source_name": source_name,
            "source_reference": source_reference,
        }

        for field_name, field_value in updates.items():
            if field_value is None:
                continue
            if getattr(fund, field_name) == field_value:
                continue
            setattr(fund, field_name, field_value)
            updated = True

        return updated
