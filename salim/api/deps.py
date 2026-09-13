"""FastAPI dependency wiring for database access.

Expected env var: DATABASE_URL (see shared/db.py). The API only reads;
the schema is migrated by the services that write (loader, stores).
"""
from __future__ import annotations

from typing import Iterator

from sqlalchemy.orm import Session

from shared.db import make_engine, make_session_factory

_engine = make_engine()
_session_factory = make_session_factory(_engine)


def get_session() -> Iterator[Session]:
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()
