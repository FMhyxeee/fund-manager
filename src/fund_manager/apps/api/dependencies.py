"""FastAPI dependency injection helpers."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from fund_manager.core.config import Settings, get_settings
from fund_manager.storage.db import get_session_factory


def get_db() -> Generator[Session, None, None]:
    """Yield a database session per request."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
