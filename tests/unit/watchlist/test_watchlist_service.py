from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from fund_manager.core.watchlist.service import FundWatchlistService
from fund_manager.storage.models import Base, FundMaster, WatchlistItem


def make_session() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    return factory()


def test_add_item_creates_fund_and_watchlist_entry() -> None:
    session = make_session()
    service = FundWatchlistService(session)

    result = service.add_item(
        fund_code="000001",
        fund_name="Alpha Fund",
        category="broad_index",
        style_tags=("index", "index", "broad"),
        risk_level="medium",
        note="observe",
    )
    session.commit()

    assert result.fund_created is True
    assert result.watchlist_created is True
    assert result.item.fund_code == "000001"
    assert result.item.style_tags == ("index", "broad")
    assert session.query(FundMaster).count() == 1
    assert session.query(WatchlistItem).count() == 1


def test_add_item_reactivates_removed_entry() -> None:
    session = make_session()
    service = FundWatchlistService(session)
    service.add_item(fund_code="000001", fund_name="Alpha Fund")
    session.commit()
    service.remove_item(fund_code="000001")
    session.commit()

    result = service.add_item(fund_code="000001", fund_name="Alpha Fund", category="healthcare")
    session.commit()

    assert result.fund_created is False
    assert result.watchlist_created is False
    assert result.watchlist_updated is True
    assert result.item.removed_at is None
    assert result.item.category == "healthcare"


def test_remove_item_hides_entry_from_active_list() -> None:
    session = make_session()
    service = FundWatchlistService(session)
    service.add_item(fund_code="000001", fund_name="Alpha Fund")
    session.commit()

    removed = service.remove_item(fund_code="000001")
    session.commit()

    assert removed.removed_at is not None
    assert service.list_items() == ()
    assert len(service.list_items(include_removed=True)) == 1

