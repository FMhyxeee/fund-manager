"""Daily synchronization of held-fund public data into canonical storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from fund_manager.core.domain.decimal_constants import HUNDRED
from fund_manager.data_adapters.akshare_adapter import (
    AkshareAdapterError,
    AkshareFundDataAdapter,
    FundNavHistory,
    FundProfile,
)
from fund_manager.storage.repo import (
    FundMasterRepository,
    NavSnapshotCreate,
    NavSnapshotRepository,
    PositionLotRepository,
)
from fund_manager.storage.repo.protocols import (
    FundMasterRepositoryProtocol,
    NavSnapshotRepositoryProtocol,
    PositionLotRepositoryProtocol,
)


@dataclass(frozen=True)
class FundSyncDetailDTO:
    """Per-fund synchronization outcome."""

    fund_id: int
    fund_code: str
    fund_name: str
    profile_updated: bool
    nav_records_inserted: int
    warnings: tuple[str, ...]
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "fund_id": self.fund_id,
            "fund_code": self.fund_code,
            "fund_name": self.fund_name,
            "profile_updated": self.profile_updated,
            "nav_records_inserted": self.nav_records_inserted,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class PortfolioFundSyncResultDTO:
    """Structured summary for one portfolio daily sync run."""

    portfolio_id: int
    as_of_date: date
    processed_fund_count: int
    profile_updated_count: int
    nav_records_inserted: int
    failed_fund_codes: tuple[str, ...]
    funds: tuple[FundSyncDetailDTO, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "portfolio_id": self.portfolio_id,
            "as_of_date": self.as_of_date.isoformat(),
            "processed_fund_count": self.processed_fund_count,
            "profile_updated_count": self.profile_updated_count,
            "nav_records_inserted": self.nav_records_inserted,
            "failed_fund_codes": list(self.failed_fund_codes),
            "funds": [detail.to_dict() for detail in self.funds],
        }


class FundDataSyncService:
    """Synchronize currently held funds from AKShare into canonical storage."""

    def __init__(
        self,
        session: Session,
        *,
        adapter: AkshareFundDataAdapter | None = None,
        position_lot_repo: PositionLotRepositoryProtocol | None = None,
        fund_master_repo: FundMasterRepositoryProtocol | None = None,
        nav_snapshot_repo: NavSnapshotRepositoryProtocol | None = None,
    ) -> None:
        self._session = session
        self._adapter = adapter or AkshareFundDataAdapter()
        self._position_lot_repo = position_lot_repo or PositionLotRepository(session)
        self._fund_master_repo = fund_master_repo or FundMasterRepository(session)
        self._nav_snapshot_repo = nav_snapshot_repo or NavSnapshotRepository(session)

    def sync_portfolio_funds(
        self,
        portfolio_id: int,
        *,
        as_of_date: date,
    ) -> PortfolioFundSyncResultDTO:
        """Refresh public profile and NAV data for funds actively held in a portfolio."""
        active_funds = self._position_lot_repo.list_active_funds_for_portfolio_up_to(
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
        )

        details: list[FundSyncDetailDTO] = []
        failed_fund_codes: list[str] = []
        profile_updated_count = 0
        nav_records_inserted_total = 0

        for fund in active_funds:
            warnings: list[str] = []
            errors: list[str] = []
            profile_updated = False
            nav_records_inserted = 0

            try:
                profile = self._adapter.get_fund_profile(fund.fund_code)
            except AkshareAdapterError as exc:
                errors.append(f"profile sync failed: {exc}")
            else:
                if profile is not None:
                    warnings.extend(profile.warnings)
                    profile_updated = self._apply_profile(profile)
                    if profile_updated:
                        profile_updated_count += 1

            latest_nav_date = self._nav_snapshot_repo.get_latest_nav_date(fund_id=fund.fund_id)
            try:
                nav_history = self._adapter.get_fund_nav_history(
                    fund.fund_code,
                    start_date=latest_nav_date,
                    end_date=as_of_date,
                )
            except AkshareAdapterError as exc:
                errors.append(f"NAV sync failed: {exc}")
            else:
                warnings.extend(nav_history.warnings)
                nav_records_inserted, nav_warnings = self._append_nav_history(
                    fund_id=fund.fund_id,
                    nav_history=nav_history,
                    latest_nav_date=latest_nav_date,
                )
                warnings.extend(nav_warnings)
                nav_records_inserted_total += nav_records_inserted

            if errors:
                failed_fund_codes.append(fund.fund_code)

            details.append(
                FundSyncDetailDTO(
                    fund_id=fund.fund_id,
                    fund_code=fund.fund_code,
                    fund_name=fund.fund_name,
                    profile_updated=profile_updated,
                    nav_records_inserted=nav_records_inserted,
                    warnings=tuple(warnings),
                    errors=tuple(errors),
                )
            )

        return PortfolioFundSyncResultDTO(
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
            processed_fund_count=len(active_funds),
            profile_updated_count=profile_updated_count,
            nav_records_inserted=nav_records_inserted_total,
            failed_fund_codes=tuple(sorted(failed_fund_codes)),
            funds=tuple(details),
        )

    def _apply_profile(self, profile: FundProfile) -> bool:
        return self._fund_master_repo.update_public_profile(
            fund_code=profile.fund_code,
            fund_name=profile.fund_name,
            fund_type=profile.fund_type,
            company_name=profile.company_name,
            manager_name=profile.manager_name,
            benchmark_name=profile.benchmark,
            source_name=profile.source,
            source_reference="fund_profile",
        )

    def _append_nav_history(
        self,
        *,
        fund_id: int,
        nav_history: FundNavHistory,
        latest_nav_date: date | None,
    ) -> tuple[int, tuple[str, ...]]:
        warnings: list[str] = []
        snapshots: list[NavSnapshotCreate] = []

        for point in nav_history.points:
            if latest_nav_date is not None and point.nav_date <= latest_nav_date:
                continue
            if point.unit_nav is None:
                warnings.append(
                    f"Skipped {point.nav_date.isoformat()} because the upstream series "
                    "does not expose unit NAV."
                )
                continue

            daily_return_ratio = (
                point.daily_return_pct / HUNDRED
                if point.daily_return_pct is not None
                else None
            )
            snapshots.append(
                NavSnapshotCreate(
                    nav_date=point.nav_date,
                    unit_nav_amount=point.unit_nav,
                    accumulated_nav_amount=point.accumulated_nav,
                    daily_return_ratio=daily_return_ratio,
                    source_name=nav_history.source,
                    source_reference=nav_history.source_endpoint,
                )
            )

        inserted = self._nav_snapshot_repo.append_many(
            fund_id=fund_id,
            snapshots=tuple(snapshots),
        )
        return inserted, tuple(warnings)
