"""SQLAlchemy engine/session — SQLite now, Postgres later."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from tearsheet import config
from tearsheet.store.models import Base

_engine = None
_SessionLocal: sessionmaker[Session] | None = None


from sqlalchemy import create_engine, event

def get_engine():
    """Return the shared SQLAlchemy engine."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            config.database_url(),
            echo=False,
            future=True,
        )
        if _engine.name == "sqlite":
            @event.listens_for(_engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.close()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the shared session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
    return _SessionLocal


def init_db() -> None:
    """Create all tables."""
    Base.metadata.create_all(get_engine())


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
