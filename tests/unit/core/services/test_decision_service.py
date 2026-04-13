"""Unit tests for the deterministic decision service."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from fund_manager.core.services import DecisionService
from fund_manager.storage.models import Base, FundMaster, NavSnapshot, Portfolio, PositionLot
from fund_manager.storage.repo import PortfolioPolicyRepository, PortfolioPolicyTargetCreate


def test_decision_service_returns_no_policy_action_when_no_active_policy(session: Session) -> None:
    portfolio, *_ = seed_portfolio(session)

    result = DecisionService(session).evaluate_portfolio_decision(
        portfolio.id,
        as_of_date=date(2026, 3, 15),
    )

    assert result.final_decision == "no_active_policy"
    assert result.action_count == 1
    assert result.actions[0].action_type == "set_policy"


def test_decision_service_generates_add_and_trim_actions_from_policy_bands(session: Session) -> None:
    portfolio, alpha_fund, beta_fund = seed_portfolio(session)
    PortfolioPolicyRepository(session).append(
        portfolio_id=portfolio.id,
        policy_name="core-balance",
        effective_from=date(2026, 3, 1),
        rebalance_threshold_ratio=Decimal("0.050000"),
        targets=(
            PortfolioPolicyTargetCreate(
                fund_id=alpha_fund.id,
                target_weight_ratio=Decimal("0.500000"),
            ),
            PortfolioPolicyTargetCreate(
                fund_id=beta_fund.id,
                target_weight_ratio=Decimal("0.500000"),
            ),
        ),
        max_single_position_weight_ratio=Decimal("0.650000"),
        created_by="test",
    )
    session.commit()

    result = DecisionService(session).evaluate_portfolio_decision(
        portfolio.id,
        as_of_date=date(2026, 3, 15),
    )

    assert result.final_decision == "rebalance_required"
    assert result.action_count == 2
    assert [action.action_type for action in result.actions] == ["add", "trim"]
    assert result.actions[0].fund_code == "000002"
    assert result.actions[0].delta_weight_ratio == Decimal("0.100000")
    assert result.actions[0].suggested_amount == Decimal("2.5000")
    assert result.actions[1].fund_code == "000001"
    assert result.actions[1].delta_weight_ratio == Decimal("0.100000")
    assert result.actions[1].suggested_amount == Decimal("2.5000")


def test_decision_service_defers_when_nav_is_missing(session: Session) -> None:
    portfolio, alpha_fund, beta_fund = seed_portfolio(session, include_beta_nav=False)
    PortfolioPolicyRepository(session).append(
        portfolio_id=portfolio.id,
        policy_name="core-balance",
        effective_from=date(2026, 3, 1),
        rebalance_threshold_ratio=Decimal("0.050000"),
        targets=(
            PortfolioPolicyTargetCreate(
                fund_id=alpha_fund.id,
                target_weight_ratio=Decimal("0.500000"),
            ),
            PortfolioPolicyTargetCreate(
                fund_id=beta_fund.id,
                target_weight_ratio=Decimal("0.500000"),
            ),
        ),
        created_by="test",
    )
    session.commit()

    result = DecisionService(session).evaluate_portfolio_decision(
        portfolio.id,
        as_of_date=date(2026, 3, 15),
    )

    assert result.final_decision == "defer_until_complete_data"
    assert result.missing_nav_fund_codes == ("000002",)
    assert result.action_count == 1
    assert result.actions[0].action_type == "refresh_data"
    assert result.actions[0].fund_code == "000002"


def seed_portfolio(
    session: Session,
    *,
    include_beta_nav: bool = True,
) -> tuple[Portfolio, FundMaster, FundMaster]:
    portfolio = Portfolio(
        portfolio_code="main",
        portfolio_name="Main",
        is_default=True,
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
                run_id="rebuild-20260310",
                lot_key="beta-core",
                opened_on=date(2026, 3, 1),
                as_of_date=date(2026, 3, 10),
                remaining_units=Decimal("5.000000"),
                average_cost_per_unit=Decimal("2.00000000"),
                total_cost_amount=Decimal("10.0000"),
            ),
            NavSnapshot(
                fund_id=alpha_fund.id,
                nav_date=date(2026, 3, 14),
                unit_nav_amount=Decimal("1.25000000"),
                source_name="test",
            ),
        ]
    )
    if include_beta_nav:
        session.add(
            NavSnapshot(
                fund_id=beta_fund.id,
                nav_date=date(2026, 3, 14),
                unit_nav_amount=Decimal("2.00000000"),
                source_name="test",
            )
        )
    session.commit()
    return portfolio, alpha_fund, beta_fund


def _build_session(tmp_path: Path) -> Session:
    database_path = tmp_path / "decision-service.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return session_factory()


def _dispose_session(session: Session) -> None:
    bind = session.get_bind()
    session.close()
    if bind is not None:
        bind.dispose()


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    db_session = _build_session(tmp_path)
    try:
        yield db_session
    finally:
        _dispose_session(db_session)
