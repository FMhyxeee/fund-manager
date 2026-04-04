"""Integration tests for the scheduler layer with real workflows."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from fund_manager.scheduler.engine import SchedulerEngine
from fund_manager.scheduler.jobs import register_default_jobs
from fund_manager.scheduler.logging import SchedulerLogger
from fund_manager.scheduler.registry import SchedulerRegistry
from fund_manager.scheduler.types import (
    JobFrequency,
    JobStatus,
    TriggerSource,
)
from fund_manager.core.services import FundSyncDetailDTO, PortfolioFundSyncResultDTO
from fund_manager.storage.models import (
    Base,
    FundMaster,
    NavSnapshot,
    Portfolio,
    PortfolioSnapshot,
    PositionLot,
    SystemEventLog,
)
from fund_manager.storage.repo import SystemEventLogRepository


def _seed_portfolio(session: Session) -> Portfolio:
    portfolio = Portfolio(
        portfolio_code="main",
        portfolio_name="Main",
    )
    alpha_fund = FundMaster(
        fund_code="000001",
        fund_name="Alpha Fund",
        source_name="test",
    )
    beta_fund = FundMaster(
        fund_code="000002",
        fund_name="Beta Fund",
        source_name="test",
    )
    session.add_all([portfolio, alpha_fund, beta_fund])
    session.flush()

    session.add_all(
        [
            PositionLot(
                portfolio_id=portfolio.id,
                fund_id=alpha_fund.id,
                run_id="rebuild-20260301",
                lot_key="alpha-core",
                opened_on=date(2026, 3, 1),
                as_of_date=date(2026, 3, 1),
                remaining_units=Decimal("10.000000"),
                average_cost_per_unit=Decimal("1.00000000"),
                total_cost_amount=Decimal("10.0000"),
            ),
            PositionLot(
                portfolio_id=portfolio.id,
                fund_id=alpha_fund.id,
                run_id="rebuild-20260310",
                lot_key="alpha-core",
                opened_on=date(2026, 3, 1),
                as_of_date=date(2026, 3, 10),
                remaining_units=Decimal("12.000000"),
                average_cost_per_unit=Decimal("1.00000000"),
                total_cost_amount=Decimal("12.0000"),
            ),
            PositionLot(
                portfolio_id=portfolio.id,
                fund_id=beta_fund.id,
                run_id="rebuild-20260301",
                lot_key="beta-core",
                opened_on=date(2026, 3, 1),
                as_of_date=date(2026, 3, 1),
                remaining_units=Decimal("5.000000"),
                average_cost_per_unit=Decimal("3.00000000"),
                total_cost_amount=Decimal("15.0000"),
            ),
            NavSnapshot(
                fund_id=alpha_fund.id,
                nav_date=date(2026, 3, 1),
                unit_nav_amount=Decimal("1.00000000"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=alpha_fund.id,
                nav_date=date(2026, 3, 10),
                unit_nav_amount=Decimal("1.20000000"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=alpha_fund.id,
                nav_date=date(2026, 3, 14),
                unit_nav_amount=Decimal("1.50000000"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=beta_fund.id,
                nav_date=date(2026, 3, 1),
                unit_nav_amount=Decimal("3.00000000"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=beta_fund.id,
                nav_date=date(2026, 3, 12),
                unit_nav_amount=Decimal("3.20000000"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=beta_fund.id,
                nav_date=date(2026, 3, 14),
                unit_nav_amount=Decimal("3.10000000"),
                source_name="test",
            ),
        ]
    )
    session.commit()
    return portfolio


class TestSchedulerWeeklyReviewIntegration:
    def test_run_weekly_job_produces_report_and_event_log(self, session: Session) -> None:
        portfolio = _seed_portfolio(session)

        registry = SchedulerRegistry()
        event_repo = SystemEventLogRepository(session)
        register_default_jobs(session, registry, as_of_date=date(2026, 3, 15))

        engine = SchedulerEngine(
            registry,
            scheduler_logger=SchedulerLogger(),
            system_event_log_repo=event_repo,
        )

        results = engine.run_all_for_frequency(
            JobFrequency.WEEKLY,
            portfolio_id=portfolio.id,
            trigger_source=TriggerSource.MANUAL,
        )

        assert len(results) == 1
        result = results[0]
        assert result.status == JobStatus.COMPLETED
        assert result.entry_name == "weekly_review"
        assert result.portfolio_id == portfolio.id

        session.commit()

        scheduler_events = list(
            session.execute(
                select(SystemEventLog)
                .where(SystemEventLog.run_id == result.run_id)
                .order_by(SystemEventLog.id.asc())
            ).scalars()
        )
        assert len(scheduler_events) >= 1
        event = scheduler_events[0]
        assert event.event_type == "scheduler_completed"
        assert event.workflow_name == "scheduler"
        assert event.payload_json is not None
        assert event.payload_json["entry_name"] == "weekly_review"


class TestSchedulerDailySnapshotIntegration:
    def test_run_daily_job_produces_snapshot(self, session: Session) -> None:
        portfolio = _seed_portfolio(session)

        class FakeDailySyncService:
            def __init__(self, current_session: Session) -> None:
                self._session = current_session

            def sync_portfolio_funds(
                self,
                portfolio_id: int,
                *,
                as_of_date: date,
            ) -> PortfolioFundSyncResultDTO:
                del portfolio_id
                alpha_fund = session.execute(
                    select(FundMaster).where(FundMaster.fund_code == "000001")
                ).scalar_one()
                beta_fund = session.execute(
                    select(FundMaster).where(FundMaster.fund_code == "000002")
                ).scalar_one()
                self._session.add_all(
                    [
                        NavSnapshot(
                            fund_id=alpha_fund.id,
                            nav_date=as_of_date,
                            unit_nav_amount=Decimal("1.60000000"),
                            daily_return_ratio=Decimal("0.066667"),
                            source_name="fake",
                        ),
                        NavSnapshot(
                            fund_id=beta_fund.id,
                            nav_date=as_of_date,
                            unit_nav_amount=Decimal("3.30000000"),
                            daily_return_ratio=Decimal("0.064516"),
                            source_name="fake",
                        ),
                    ]
                )
                return PortfolioFundSyncResultDTO(
                    portfolio_id=portfolio.id,
                    as_of_date=as_of_date,
                    processed_fund_count=2,
                    profile_updated_count=0,
                    nav_records_inserted=2,
                    failed_fund_codes=(),
                    funds=(
                        FundSyncDetailDTO(
                            fund_id=alpha_fund.id,
                            fund_code=alpha_fund.fund_code,
                            fund_name=alpha_fund.fund_name,
                            profile_updated=False,
                            nav_records_inserted=1,
                            warnings=(),
                            errors=(),
                        ),
                        FundSyncDetailDTO(
                            fund_id=beta_fund.id,
                            fund_code=beta_fund.fund_code,
                            fund_name=beta_fund.fund_name,
                            profile_updated=False,
                            nav_records_inserted=1,
                            warnings=(),
                            errors=(),
                        ),
                    ),
                )

        registry = SchedulerRegistry()
        event_repo = SystemEventLogRepository(session)
        register_default_jobs(
            session,
            registry,
            as_of_date=date(2026, 3, 15),
            fund_data_sync_service_factory=FakeDailySyncService,
        )

        engine = SchedulerEngine(
            registry,
            scheduler_logger=SchedulerLogger(),
            system_event_log_repo=event_repo,
        )

        result = engine.run_job(
            "daily_snapshot",
            JobFrequency.DAILY,
            portfolio_id=portfolio.id,
            trigger_source=TriggerSource.SCHEDULED,
        )

        assert result.status == JobStatus.COMPLETED
        assert result.entry_name == "daily_snapshot"
        assert result.payload["sync"]["nav_records_inserted"] == 2
        assert result.payload["snapshot"]["snapshot_record_id"] is not None
        session.commit()
        persisted_row = session.execute(select(PortfolioSnapshot)).scalar_one()
        assert persisted_row.snapshot_date == date(2026, 3, 15)
        assert persisted_row.total_market_value_amount == Decimal("35.7000")


class TestSchedulerRegistryDefaultJobs:
    def test_register_default_populates_three_frequencies(self, session: Session) -> None:
        registry = SchedulerRegistry()
        register_default_jobs(session, registry, as_of_date=date(2026, 3, 15))

        all_entries = registry.list_all()
        assert len(all_entries) == 3

        frequencies = {e.frequency for e in all_entries}
        assert frequencies == {JobFrequency.DAILY, JobFrequency.WEEKLY, JobFrequency.MONTHLY}

    def test_register_default_does_not_duplicate(self, session: Session) -> None:
        registry = SchedulerRegistry()
        register_default_jobs(session, registry)

        with pytest.raises(ValueError, match="already registered"):
            register_default_jobs(session, registry)


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    database_path = tmp_path / "scheduler-test.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with session_factory() as db_session:
        yield db_session

    engine.dispose()
