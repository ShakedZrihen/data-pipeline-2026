"""Baseline: the schema as PR #57 left it.

Every statement is ``IF NOT EXISTS`` on purpose. Databases created before
Alembic (Supabase, and any local volume from ``create_all``) already hold
these tables with no version history; running this on them changes nothing
except recording the version, so the same script serves a fresh database and
an adopted one. See docs/decisions/0002-schema-migrations.md.

Revision ID: 0001
Revises:
Create Date: 2026-09-09
"""
from alembic import op
import sqlalchemy as sa

from shared.migrations.rls import enable_row_level_security

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Creation order respects foreign keys; downgrade walks it in reverse.
TABLES = (
    "chains",
    "branches",
    "branch_opening_hours",
    "branch_opening_exceptions",
    "catalog_products",
    "product_aliases",
    "products",
    "prices",
    "price_history",
    "promotions",
    "promotion_items",
    "promotion_history",
    "promotion_item_history",
    "manufacturers",
)

INDEXES = (
    ("ix_branches_city", "branches", ["city"], False),
    ("ix_catalog_products_slug", "catalog_products", ["slug"], True),
    ("ix_product_aliases_product_id", "product_aliases", ["product_id"], False),
    ("ix_products_catalog_product_id", "products", ["catalog_product_id"], False),
    ("ix_products_manufacturer_status", "products", ["manufacturer_status"], False),
    ("ix_price_history_item_time", "price_history", ["item_code", "update_time"], False),
    ("ix_price_history_branch_time", "price_history", ["provider", "store_id", "update_time"], False),
    ("ix_promotions_provider_store_end", "promotions", ["provider", "store_id", "end_time"], False),
    ("ix_promotion_items_item", "promotion_items", ["provider", "item_code"], False),
    ("ix_promotion_history_branch_time", "promotion_history", ["provider", "store_id", "update_time"], False),
    ("ix_promotion_item_history_item", "promotion_item_history", ["provider", "item_code", "update_time"], False),
)


def _timestamp(name: str, **kw) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), **kw)


def _now(name: str, nullable: bool = True) -> sa.Column:
    return _timestamp(name, server_default=sa.text("now()"), nullable=nullable)


def _deal_terms() -> list[sa.Column]:
    return [
        sa.Column("discount_type", sa.Integer()),
        sa.Column("min_qty", sa.Numeric(12, 3)),
        sa.Column("max_qty", sa.Numeric(12, 3)),
        sa.Column("discount_price", sa.Numeric(12, 2)),
        sa.Column("discounted_price_per_mida", sa.Numeric(12, 2)),
    ]


def upgrade() -> None:
    op.create_table(
        "chains",
        sa.Column("chain_id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("slug", sa.String(64), unique=True),
        if_not_exists=True,
    )
    op.create_table(
        "branches",
        sa.Column("chain_id", sa.String(32), primary_key=True),
        sa.Column("branch_id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(256)),
        sa.Column("city", sa.String(128)),
        sa.Column("address", sa.String(512)),
        sa.Column("latitude", sa.Float()),
        sa.Column("longitude", sa.Float()),
        sa.Column("timezone", sa.String(64), server_default=sa.text("'Asia/Jerusalem'"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _timestamp("metadata_updated_at"),
        sa.ForeignKeyConstraint(["chain_id"], ["chains.chain_id"]),
        if_not_exists=True,
    )
    op.create_table(
        "branch_opening_hours",
        sa.Column("chain_id", sa.String(32), primary_key=True),
        sa.Column("branch_id", sa.String(32), primary_key=True),
        sa.Column("weekday", sa.Integer(), primary_key=True),
        sa.Column("interval_index", sa.Integer(), primary_key=True, server_default=sa.text("0")),
        sa.Column("opens_at", sa.Time(), nullable=False),
        sa.Column("closes_at", sa.Time(), nullable=False),
        sa.ForeignKeyConstraint(["chain_id", "branch_id"], ["branches.chain_id", "branches.branch_id"], ondelete="CASCADE"),
        if_not_exists=True,
    )
    op.create_table(
        "branch_opening_exceptions",
        sa.Column("chain_id", sa.String(32), primary_key=True),
        sa.Column("branch_id", sa.String(32), primary_key=True),
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("interval_index", sa.Integer(), primary_key=True, server_default=sa.text("0")),
        sa.Column("is_closed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("opens_at", sa.Time()),
        sa.Column("closes_at", sa.Time()),
        sa.Column("reason", sa.String(256)),
        sa.ForeignKeyConstraint(["chain_id", "branch_id"], ["branches.chain_id", "branches.branch_id"], ondelete="CASCADE"),
        if_not_exists=True,
    )
    op.create_table(
        "catalog_products",
        sa.Column("product_id", sa.String(160), primary_key=True),
        sa.Column("gtin", sa.String(32), unique=True),
        sa.Column("slug", sa.String(160)),
        sa.Column("display_name", sa.String(512)),
        sa.Column("manufacturer", sa.String(256)),
        _timestamp("source_update_time"),
        _now("created_at", nullable=False),
        _now("updated_at", nullable=False),
        if_not_exists=True,
    )
    op.create_table(
        "product_aliases",
        sa.Column("alias", sa.String(160), primary_key=True),
        sa.Column("product_id", sa.String(160), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["catalog_products.product_id"], ondelete="CASCADE"),
        if_not_exists=True,
    )
    op.create_table(
        "products",
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("item_code", sa.String(32), primary_key=True),
        sa.Column("catalog_product_id", sa.String(160), nullable=False),
        sa.Column("item_name", sa.String(512)),
        sa.Column("item_type", sa.Integer()),
        sa.Column("unit_quantity", sa.String(64)),
        sa.Column("unit_of_measure", sa.String(64)),
        sa.Column("quantity", sa.Numeric(12, 3)),
        sa.Column("weighted", sa.Boolean()),
        sa.Column("in_package", sa.Numeric(12, 3)),
        sa.Column("manufacturer", sa.String(256)),
        sa.Column("manufacturer_raw", sa.String(256)),
        sa.Column("manufacturer_status", sa.String(16), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("manufacturer_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        _timestamp("manufacturer_checked_at"),
        _timestamp("source_update_time"),
        _now("updated_at"),
        sa.ForeignKeyConstraint(["catalog_product_id"], ["catalog_products.product_id"]),
        if_not_exists=True,
    )
    op.create_table(
        "prices",
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("store_id", sa.String(32), primary_key=True),
        sa.Column("item_code", sa.String(32), primary_key=True),
        sa.Column("price", sa.Numeric(12, 2)),
        _timestamp("update_time"),
        _now("updated_at"),
        sa.ForeignKeyConstraint(["provider", "item_code"], ["products.provider", "products.item_code"]),
        if_not_exists=True,
    )
    op.create_table(
        "price_history",
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("store_id", sa.String(32), primary_key=True),
        sa.Column("item_code", sa.String(32), primary_key=True),
        _timestamp("update_time", primary_key=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        _now("ingested_at", nullable=False),
        sa.ForeignKeyConstraint(["provider", "item_code"], ["products.provider", "products.item_code"]),
        if_not_exists=True,
    )
    op.create_table(
        "promotions",
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("store_id", sa.String(32), primary_key=True),
        sa.Column("promotion_id", sa.String(32), primary_key=True),
        sa.Column("description", sa.String(1024)),
        _timestamp("start_time"),
        _timestamp("end_time"),
        _timestamp("update_time"),
        _now("updated_at"),
        if_not_exists=True,
    )
    op.create_table(
        "promotion_items",
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("store_id", sa.String(32), primary_key=True),
        sa.Column("promotion_id", sa.String(32), primary_key=True),
        sa.Column("item_code", sa.String(32), primary_key=True),
        *_deal_terms(),
        sa.ForeignKeyConstraint(
            ["provider", "store_id", "promotion_id"],
            ["promotions.provider", "promotions.store_id", "promotions.promotion_id"],
            ondelete="CASCADE",
        ),
        if_not_exists=True,
    )
    op.create_table(
        "promotion_history",
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("store_id", sa.String(32), primary_key=True),
        sa.Column("promotion_id", sa.String(32), primary_key=True),
        _timestamp("update_time", primary_key=True),
        sa.Column("description", sa.String(1024)),
        _timestamp("start_time"),
        _timestamp("end_time"),
        _now("ingested_at", nullable=False),
        if_not_exists=True,
    )
    op.create_table(
        "promotion_item_history",
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("store_id", sa.String(32), primary_key=True),
        sa.Column("promotion_id", sa.String(32), primary_key=True),
        _timestamp("update_time", primary_key=True),
        sa.Column("item_code", sa.String(32), primary_key=True),
        *_deal_terms(),
        sa.ForeignKeyConstraint(
            ["provider", "store_id", "promotion_id", "update_time"],
            [
                "promotion_history.provider",
                "promotion_history.store_id",
                "promotion_history.promotion_id",
                "promotion_history.update_time",
            ],
            ondelete="CASCADE",
        ),
        if_not_exists=True,
    )
    op.create_table(
        "manufacturers",
        sa.Column("normalized_name", sa.String(512), primary_key=True),
        sa.Column("manufacturer", sa.String(256)),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("model", sa.String(64)),
        _now("resolved_at"),
        if_not_exists=True,
    )
    for name, table, columns, unique in INDEXES:
        op.create_index(name, table, columns, unique=unique, if_not_exists=True)
    for table in TABLES:
        enable_row_level_security(table)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table, if_exists=True)
