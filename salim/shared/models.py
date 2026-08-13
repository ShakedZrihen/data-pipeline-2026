# SQLAlchemy models shared by the loader and api services.
# TODO: define Product and Price tables here.

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Store(Base):
    """One physical branch of one supermarket chain.

    Identity is ``(provider, store_id)``: chains number their own branches from
    001, so a store id is only unique within its chain. That pair is the
    primary key, which also makes the loader's upsert a plain
    ``ON CONFLICT (provider, store_id)``.

    Columns come from two different kinds of source, which is why so many are
    nullable:

    - The chain's mandated ``Stores`` file (price-transparency law) supplies
      ``store_id``, ``name``, ``address``, ``city_code``, ``store_type``.
      It carries no phone, no coordinates and no opening hours.
    - The chain's own branch-locator page supplies ``phone``,
      ``opening_hours``, ``city`` and — where published — ``latitude`` /
      ``longitude``.

    A row therefore appears as soon as the Stores file lists it, and fills in
    over time as the locator scrape reaches it.
    """

    __tablename__ = "stores"

    # --- identity --- #
    provider = Column(String(32), primary_key=True)
    store_id = Column(String(16), primary_key=True)

    # --- lifecycle --- #
    # Set from presence in the newest Stores file: a branch that stops being
    # listed is flagged inactive rather than deleted, so price rows that
    # reference it keep resolving.
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))

    # --- from the Stores file --- #
    name = Column(String(256))
    address = Column(String(512))
    city_code = Column(String(16))  # CBS municipality code, NOT a city name
    store_type = Column(String(8))
    chain_id = Column(String(32))

    # --- from the chain's branch locator --- #
    city = Column(String(128))
    phone = Column(String(64))
    latitude = Column(Numeric(9, 6))
    longitude = Column(Numeric(9, 6))

    # Full weekly schedule, e.g.
    # {"sunday": {"from": "07:00", "to": "23:00"}, "saturday": null}
    opening_hours = Column(JSONB)
    # Flat summary of the above (the issue's `openningTimeFrame (from, to)`):
    # the widest window the branch is open on a regular weekday.
    opening_from = Column(String(5))
    opening_to = Column(String(5))
    # Chains publish hours as prose at least as often as as data — Rami Levi
    # has branches that "open an hour after Shabbat ends", which is not a clock
    # time. Keeping the original text means the structure above can be
    # re-derived later without re-scraping.
    opening_hours_raw = Column(String(1024))

    # --- provenance --- #
    source_file = Column(String(256))

    # Which locator record filled the enrichment columns, e.g.
    # "hazi_hinam_api:106". Null while a branch is unenriched.
    enrichment_source = Column(String(128))
    # "unique"    — exactly one branch matched this locator record
    # "ambiguous" — several branches share it (a chain running two formats at
    #               one address), so only the address-intrinsic fields were
    #               taken and opening_hours was left alone
    enrichment_match = Column(String(16))
    enriched_at = Column(DateTime(timezone=True))
    first_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True))
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_stores_provider_active", "provider", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<Store {self.provider}/{self.store_id} {self.name!r}>"
