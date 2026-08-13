# DB engine/session setup shared by the loader and api services.
# Expected env var: DATABASE_URL

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from shared.models import Base

DEFAULT_DATABASE_URL = "postgresql+psycopg2://salim:salim@postgres:5432/salim"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


# pool_pre_ping: Supabase drops idle connections; without it a long-idle worker
# wakes up onto a dead socket and the first query of the run fails.
engine = create_engine(database_url(), pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    """Create any missing tables. Safe to call on every service start."""
    Base.metadata.create_all(engine)


def get_session() -> Session:
    return SessionLocal()
