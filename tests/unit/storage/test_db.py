"""Tests for database bootstrap helpers."""

from __future__ import annotations

from sqlalchemy import text

from fund_manager.core.config import get_settings
from fund_manager.storage.db import get_engine, get_session_factory


def test_sqlite_engine_enables_foreign_keys(monkeypatch, tmp_path) -> None:
    """SQLite connections should enforce foreign keys by default."""
    database_path = tmp_path / "fk-check.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    get_engine.cache_clear()

    try:
        engine = get_engine()
        with engine.connect() as connection:
            foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
    finally:
        get_settings.cache_clear()
        get_session_factory.cache_clear()
        get_engine.cache_clear()

    assert foreign_keys == 1
