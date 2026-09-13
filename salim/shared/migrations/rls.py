"""Row-level security is part of every table's definition, not a post-step.

Supabase exposes the public schema through its Data API. A table with RLS
enabled and no policies is closed to the anon/authenticated roles, which is
what every table here wants: the services write through the privileged
Postgres connection. Call this from the migration that creates a table so the
table is never exposed, even briefly, and the RLS guard test stays green.
"""
from alembic import op


def enable_row_level_security(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
