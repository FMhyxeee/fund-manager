"""API tests for the simplified FastAPI surface."""

from __future__ import annotations

from collections.abc import Generator
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from fund_manager.apps.api.dependencies import get_db
from fund_manager.apps.api.main import app
from fund_manager.storage.models import (
    Base,
    FundMaster,
    NavSnapshot,
    Portfolio,
    PositionLot,
    TransactionRecord,
    TransactionType,
    WatchlistItem,
)


@pytest.fixture()
def engine() -> Engine:
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine: Engine) -> Generator[Session, None, None]:
    sess = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)()
    yield sess
    sess.close()


@pytest.fixture()
def client(engine: Engine) -> Generator[TestClient, None, None]:
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    def _override_get_db() -> Generator[Session, None, None]:
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def seed_portfolio_with_fund(session: Session) -> tuple[Portfolio, FundMaster]:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio")
    fund = FundMaster(fund_code="000001", fund_name="Test Fund", source_name="test")
    session.add_all([portfolio, fund])
    session.flush()
    session.add(
        PositionLot(
            portfolio_id=portfolio.id,
            fund_id=fund.id,
            run_id="test-run",
            lot_key="test-lot",
            opened_on=date(2026, 3, 1),
            as_of_date=date(2026, 3, 15),
            remaining_units=Decimal("100.000000"),
            average_cost_per_unit=Decimal("1.00000000"),
            total_cost_amount=Decimal("100.0000"),
        )
    )
    session.commit()
    return portfolio, fund


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_list_portfolios_with_data(client: TestClient, session: Session) -> None:
    seed_portfolio_with_fund(session)

    response = client.get("/api/v1/portfolios")

    assert response.status_code == 200
    assert response.json()[0]["portfolio_code"] == "main"


def test_get_portfolio_snapshot(client: TestClient, session: Session) -> None:
    portfolio, _ = seed_portfolio_with_fund(session)

    response = client.get(f"/api/v1/portfolios/{portfolio.id}/snapshot?as_of_date=2026-03-15")

    assert response.status_code == 200
    data = response.json()
    assert data["portfolio_code"] == "main"
    assert data["positions"][0]["fund_code"] == "000001"


def test_get_portfolio_metrics(client: TestClient, session: Session) -> None:
    portfolio, fund = seed_portfolio_with_fund(session)
    session.add(
        NavSnapshot(
            fund_id=fund.id,
            nav_date=date(2026, 3, 15),
            unit_nav_amount=Decimal("1.25000000"),
            source_name="test",
        )
    )
    session.commit()

    response = client.get(f"/api/v1/portfolios/{portfolio.id}/metrics?as_of_date=2026-03-15")

    assert response.status_code == 200
    data = response.json()
    assert data["metrics"]["position_count"] == 1
    assert data["metrics"]["top_positions"][0]["fund_code"] == "000001"


def test_get_fund_profile_and_nav_history(client: TestClient, session: Session) -> None:
    _, fund = seed_portfolio_with_fund(session)
    session.add(
        NavSnapshot(
            fund_id=fund.id,
            nav_date=date(2026, 3, 15),
            unit_nav_amount=Decimal("1.25000000"),
            source_name="test",
        )
    )
    session.commit()

    profile_response = client.get("/api/v1/funds/000001")
    nav_response = client.get(
        "/api/v1/funds/000001/nav-history?start_date=2026-03-01&end_date=2026-03-31"
    )

    assert profile_response.status_code == 200
    assert profile_response.json()["fund_name"] == "Test Fund"
    assert nav_response.status_code == 200
    assert nav_response.json()["points"][0]["nav_date"] == "2026-03-15"


def test_append_transaction_creates_fund_and_lot_snapshot(
    client: TestClient,
    session: Session,
) -> None:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio")
    session.add(portfolio)
    session.commit()

    response = client.post(
        "/api/v1/transactions",
        json={
            "portfolio_id": portfolio.id,
            "fund_code": "000002",
            "fund_name": "New Fund",
            "trade_date": "2026-03-16",
            "trade_type": "buy",
            "units": "10.000000",
            "gross_amount": "12.0000",
            "nav_per_unit": "1.20000000",
            "source_name": "api-test",
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["fund_created"] is True
    assert data["transaction"]["fund_code"] == "000002"
    assert session.query(TransactionRecord).count() == 1
    assert session.query(PositionLot).count() == 1


def test_list_and_get_transactions(client: TestClient, session: Session) -> None:
    portfolio, fund = seed_portfolio_with_fund(session)
    transaction = TransactionRecord(
        portfolio_id=portfolio.id,
        fund_id=fund.id,
        trade_date=date(2026, 3, 16),
        trade_type=TransactionType.BUY,
        units=Decimal("10.000000"),
        gross_amount=Decimal("12.0000"),
        source_name="test",
    )
    session.add(transaction)
    session.commit()

    list_response = client.get(f"/api/v1/transactions?portfolio_id={portfolio.id}")
    get_response = client.get(f"/api/v1/transactions/{transaction.id}")

    assert list_response.status_code == 200
    assert list_response.json()["transactions"][0]["transaction_id"] == transaction.id
    assert get_response.status_code == 200
    assert get_response.json()["fund_code"] == "000001"


def test_watchlist_crud(client: TestClient, session: Session) -> None:
    response = client.post(
        "/api/v1/watchlist/items",
        json={
            "fund_code": "000003",
            "fund_name": "Watch Fund",
            "category": "broad_index",
            "style_tags": ["index", "broad"],
            "risk_level": "medium",
            "note": "observe",
        },
    )

    assert response.status_code == 201
    assert response.json()["watchlist_created"] is True
    assert session.query(WatchlistItem).count() == 1

    list_response = client.get("/api/v1/watchlist")
    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["fund_code"] == "000003"

    delete_response = client.delete("/api/v1/watchlist/items/000003")
    assert delete_response.status_code == 200
    assert delete_response.json()["item"]["removed_at"] is not None

    active_response = client.get("/api/v1/watchlist")
    assert active_response.json()["items"] == []


def test_removed_routes_are_not_public(client: TestClient) -> None:
    assert client.get("/api/v1/decisions").status_code == 404
    assert client.get("/api/v1/reports").status_code == 404
    assert client.post("/api/v1/workflows/daily-decision/run", json={}).status_code == 404
