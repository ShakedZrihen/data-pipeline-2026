"""DB engine/session setup shared by the loader and api services.

Expected env var: DATABASE_URL. Schema is created with ``create_all`` on
service startup; there is no migration tool yet, so changing a column on a
live database is a manual job (see README).
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from shared.models import Base

DEFAULT_DATABASE_URL = "postgresql+psycopg2://salim:salim@postgres:5432/salim"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def make_engine(url: str | None = None) -> Engine:
    return create_engine(url or database_url(), pool_pre_ping=True, future=True)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)
