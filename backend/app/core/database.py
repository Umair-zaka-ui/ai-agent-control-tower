"""Database engine, session factory and declarative base."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

# ``pool_pre_ping`` transparently recovers connections dropped by the DB server.
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a request-scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
