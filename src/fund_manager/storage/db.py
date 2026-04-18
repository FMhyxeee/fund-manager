"""Database bootstrap helpers for the persistence layer."""

from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from fund_manager.core.config import get_settings


class Base(DeclarativeBase):
    """Base class for ORM models with stable constraint naming."""

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s__%(column_0_N_name)s",
            "uq": "uq_%(table_name)s__%(column_0_N_name)s",
            "ck": "ck_%(table_name)s__%(constraint_name)s",
            "fk": "fk_%(table_name)s__%(column_0_name)s__%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


@lru_cache
def get_engine() -> Engine:
    """Create the shared SQLAlchemy engine."""
    settings = get_settings()
    if settings.database_url.startswith("sqlite:///./"):
        database_path = Path(settings.database_url.removeprefix("sqlite:///./"))
        database_path.parent.mkdir(parents=True, exist_ok=True)
    connect_args = (
        {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    )
    engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
    if settings.database_url.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Create the shared session factory."""
    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
    """Keep SQLite foreign key constraints enforced for every connection."""
    previous_autocommit = getattr(dbapi_connection, "autocommit", None)
    if previous_autocommit is not None:
        dbapi_connection.autocommit = True
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()
        if previous_autocommit is not None:
            dbapi_connection.autocommit = previous_autocommit
