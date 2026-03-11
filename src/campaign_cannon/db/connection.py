"""Database connection management for Campaign Cannon.

Provides SQLite with WAL mode, busy_timeout, connection pooling,
and a session context manager with automatic commit/rollback.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine, event, create_engine
from sqlalchemy.orm import Session, sessionmaker

from campaign_cannon.config.settings import get_settings
from campaign_cannon.db.models import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _enable_wal(dbapi_conn, connection_record) -> None:  # noqa: ANN001
    """Enable WAL mode and set busy_timeout on every new SQLite connection."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def get_engine() -> Engine:
    """Return the singleton SQLAlchemy engine (creates it on first call)."""
    global _engine
    if _engine is None:
        settings = get_settings()
        url = f"sqlite:///{settings.db_path}"
        _engine = create_engine(
            url,
            pool_pre_ping=True,
            echo=False,
        )
        event.listen(_engine, "connect", _enable_wal)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the singleton session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
        )
    return _session_factory


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Yield a transactional session that auto-commits on success, rolls back on error."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create all tables (useful for tests and first-run without Alembic)."""
    Base.metadata.create_all(get_engine())


def reset_engine() -> None:
    """Dispose the engine and clear singletons (useful for tests)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
