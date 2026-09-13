"""DB engine/session setup and schema migration shared by every service.

Expected env var: DATABASE_URL. The schema is owned by the Alembic history in
``shared/migrations``; services call ``migrate()`` at startup, and a model
change without a matching migration fails the drift test in ``shared/tests``.
See docs/decisions/0002-schema-migrations.md.
"""
from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg2://salim:salim@postgres:5432/salim"
ALEMBIC_INI = Path(__file__).with_name("alembic.ini")
# One key for the whole schema: services that start together migrate in turn.
SCHEMA_LOCK_KEY = 0x53414C494D


def database_url() -> str:
    # GitHub secrets copied from dashboards occasionally include a leading space
    # or trailing newline. Neither is part of a valid SQLAlchemy URL.
    value = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL).strip()
    if not value:
        raise RuntimeError("DATABASE_URL is empty")
    return _escape_unencoded_password_at(value)


def _escape_unencoded_password_at(value: str) -> str:
    """Encode extra ``@`` characters in URL credentials without exposing them.

    Supabase passwords may contain ``@``. The final ``@`` in the authority is
    the user-info/host delimiter; any earlier ones belong to the password.
    Already encoded ``%40`` values are left unchanged.
    """
    scheme_end = value.find("://")
    if scheme_end < 0:
        return value
    authority_start = scheme_end + 3
    authority_end = len(value)
    for separator in ("/", "?", "#"):
        index = value.find(separator, authority_start)
        if index >= 0:
            authority_end = min(authority_end, index)
    authority = value[authority_start:authority_end]
    if authority.count("@") <= 1:
        return value
    credentials, delimiter, host = authority.rpartition("@")
    normalized_authority = f"{credentials.replace('@', '%40')}{delimiter}{host}"
    return f"{value[:authority_start]}{normalized_authority}{value[authority_end:]}"


def make_engine(url: str | None = None) -> Engine:
    value = _escape_unencoded_password_at(url.strip()) if url is not None else database_url()
    try:
        parsed = make_url(value)
    except ArgumentError as exc:
        raise RuntimeError(
            "DATABASE_URL is not a valid SQLAlchemy connection URL; expected "
            "postgresql+psycopg2://USER:PASSWORD@HOST:PORT/DATABASE"
        ) from exc
    if parsed.get_backend_name() != "postgresql":
        raise RuntimeError("DATABASE_URL must use PostgreSQL")
    return create_engine(parsed, pool_pre_ping=True, future=True)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def migrate(engine: Engine, revision: str = "head") -> None:
    """Bring the schema up to *revision*, serialized across concurrent starters.

    The transaction-scoped advisory lock means two services booting at once
    do not both try to run the same migration; the second waits and finds
    nothing left to do.
    """
    _run_alembic(engine, command.upgrade, revision)


def downgrade(engine: Engine, revision: str = "base") -> None:
    """Walk the schema back to *revision*. Tests use it to start from nothing."""
    _run_alembic(engine, command.downgrade, revision)


def _run_alembic(engine: Engine, run, revision: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SCHEMA_LOCK_KEY})
        run(_alembic_config(connection), revision)


def _alembic_config(connection) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["connection"] = connection
    return config
