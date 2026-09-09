"""Give branches the columns a store row needs (PR #63).

``IF NOT EXISTS`` because issue #65 published this as hand-written SQL, and a
database where someone already ran it must migrate cleanly too.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

COLUMNS = (
    sa.Column("phone", sa.String(64)),
    sa.Column("city_code", sa.String(16)),
    sa.Column("store_type", sa.String(8)),
    sa.Column("source_file", sa.String(256)),
    sa.Column("enrichment_source", sa.String(128)),
    sa.Column("enrichment_match", sa.String(16)),
    sa.Column("enriched_at", sa.DateTime(timezone=True)),
    sa.Column("fields_not_provided", postgresql.JSONB()),
    sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    sa.Column("last_seen_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column("branches", column, if_not_exists=True)


def downgrade() -> None:
    for column in reversed(COLUMNS):
        op.drop_column("branches", column.name)
