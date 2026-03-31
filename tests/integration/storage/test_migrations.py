"""Smoke tests for the Alembic migration path."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def build_alembic_config(database_url: str) -> Config:
    """Create an Alembic config pointed at a temporary database."""
    repository_root = Path(__file__).resolve().parents[3]
    config = Config(str(repository_root / "alembic.ini"))
    config.set_main_option(
        "script_location", str(repository_root / "src/fund_manager/storage/migrations")
    )
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_alembic_upgrade_creates_v1_schema(tmp_path: Path) -> None:
    """Running the initial migration should create the full schema."""
    database_path = tmp_path / "migration_smoke.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"

    command.upgrade(build_alembic_config(database_url), "head")

    engine = create_engine(database_url)
    inspector = inspect(engine)

    assert {
        "agent_debate_log",
        "alembic_version",
        "fund_master",
        "nav_snapshot",
        "portfolio",
        "portfolio_snapshot",
        "position_lot",
        "review_report",
        "strategy_proposal",
        "system_event_log",
        "transaction",
    } <= set(inspector.get_table_names())

    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    assert revision == "20260331_0001"
