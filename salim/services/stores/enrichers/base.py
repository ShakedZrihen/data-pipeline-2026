"""Abstract base for a branch-locator source — the second half of a store row.

The mandated Stores file gives identity (who and where). It carries no phone,
no coordinates and no opening hours, so those come from each chain's own
branch-locator page, and that is what an ``Enricher`` fetches.

Writing one for a new chain means implementing ``fetch`` and nothing else:
return a list of ``LocatorRecord``. Matching them to store rows, deciding which
fields are safe to write, and the DB work are all shared.

    class ShufersalEnricher(Enricher):
        name = "shufersal"

        def fetch(self) -> list[LocatorRecord]:
            ...

The hard part of a new chain is never this class — it is finding where the
chain's site actually gets its branch list. Two of the four publish plain
responses; the other two are JS applications that fetch it over XHR, and for
those the endpoint has to be found in the page's own JavaScript bundle. That is
how Hazi Hinam's was found: its Angular bundle carries its own config, naming
``apiBaseUrl`` and ``apiSuffix`` in clear text.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LocatorRecord:
    """One branch as the chain's own site describes it.

    ``external_id`` is the locator's id for the branch. It is kept for
    provenance only — it does **not** correspond to the ``StoreID`` in the
    official file, so it must never be used to join. See ``matching.py``.
    """

    external_id: str
    address: str | None

    name: str | None = None
    city: str | None = None
    phone: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    # {"sunday": {"from": "07:00", "to": "22:00"}, "saturday": None}
    opening_hours: dict | None = None
    # Widest regular-weekday window, for the issue's flat from/to.
    opening_from: str | None = None
    opening_to: str | None = None
    # Chains publish hours as prose at least as often as as data; keeping the
    # original means a later reader can re-interpret without re-scraping.
    opening_hours_raw: str | None = None


class Enricher(ABC):
    """A chain's branch locator. Subclasses implement ``fetch`` only."""

    #: must equal the matching StoreSource's name (it keys `stores.provider`)
    name: str

    @abstractmethod
    def fetch(self) -> list[LocatorRecord]:
        """Return every branch the chain's locator publishes."""


# --- helpers shared by concrete enrichers --- #

_DAYS = ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday")


def day_name(index: int) -> str:
    """1-based day index (1 = Sunday, as Israeli sites count) -> English name."""
    return _DAYS[(index - 1) % 7]


def flatten_hours(opening_hours: dict | None) -> tuple[str | None, str | None]:
    """Collapse a weekly schedule into one ``(from, to)`` pair.

    The issue asks for a single ``openningTimeFrame (from, to)``, but a branch
    keeps different hours on Friday and Saturday. This takes the widest window
    across the regular week (Sunday-Thursday) and ignores the rest, which is
    the least misleading way to answer a question that assumes one window.
    """
    if not opening_hours:
        return None, None

    windows = [
        (value["from"], value["to"])
        for day, value in opening_hours.items()
        if day in _DAYS[:5] and isinstance(value, dict) and value.get("from") and value.get("to")
    ]
    if not windows:
        return None, None
    return min(w[0] for w in windows), max(w[1] for w in windows)
