"""Database bootstrap helpers for the future persistence layer."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from fund_manager.core.config import get_settings


class Base(DeclarativeBase):
    """Base class for future ORM models."""


@lru_cache
def get_engine() -> Engine:
    """Create the shared SQLAlchemy engine."""
    settings = get_settings()
    connect_args = (
        {"check_same_thread": False}
        if settings.database_url.startswith("sqlite")
        else {}
    )
    return create_engine(settings.database_url, connect_args=connect_args)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Create the shared session factory."""
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
