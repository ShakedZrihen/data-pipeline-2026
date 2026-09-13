"""Alembic environment.

Two entry points share this file. Services call ``shared.db.migrate()``, which
hands in an open connection through ``config.attributes`` and has already
configured logging. The ``alembic`` CLI (``docker compose run --rm migrate``)
hands in nothing, so a connection is opened from ``DATABASE_URL`` and logging
comes from alembic.ini.
"""
from logging.config import fileConfig

from alembic import context

from shared.db import database_url, make_engine
from shared.models import Base

config = context.config
target_metadata = Base.metadata

# Server defaults and types are compared so a changed default or widened
# column shows up in autogenerate and in the drift test.
COMPARE_OPTIONS = {"compare_type": True, "compare_server_default": True}


def run_migrations_offline() -> None:
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True, **COMPARE_OPTIONS)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    if config.config_file_name:
        fileConfig(config.config_file_name)
    with make_engine().connect() as connection:
        _run(connection)
        connection.commit()


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, **COMPARE_OPTIONS)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
