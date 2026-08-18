"""Manufacturer extraction: the free tiers, and the shared name normalization.

Order is raw -> cache -> dictionary. Anything that gets through all three is
left ``pending`` for the LLM sweeper (``enrich.py``); the consumer itself never
makes a network call.
"""
from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

# Values chains put in ManufactureName when they have nothing to say.
# Compared with all whitespace/punctuation removed, so "לא ידוע", "לא-ידוע" and "N/A" all hit.
_JUNK_MANUFACTURERS = frozenset(
    {"", "0", "na", "none", "null", "unknown", "לאידוע", "כללי", "אחר", "יצרן", "ללא"}
)

_STRIP = re.compile(r"[^\w%\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")


def normalize_name(name: str | None) -> str:
    """Whitespace-collapsed, lower-cased, punctuation-free key for one item name."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKC", name).lower()
    text = _STRIP.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def is_junk_manufacturer(raw: str | None) -> bool:
    return normalize_name(raw).replace(" ", "") in _JUNK_MANUFACTURERS


class BrandDictionary:
    """Known brands, matched as whole tokens; a name naming two brands is ambiguous."""

    def __init__(self, brands: dict[str, str]):
        # normalized token tuple -> canonical manufacturer
        self._brands = {tuple(normalize_name(k).split()): v for k, v in brands.items() if normalize_name(k)}
        self._max_len = max((len(k) for k in self._brands), default=0)

    def match(self, name: str | None) -> str | None:
        tokens = normalize_name(name).split()
        found: set[str] = set()
        for n in range(1, self._max_len + 1):
            for i in range(len(tokens) - n + 1):
                hit = self._brands.get(tuple(tokens[i : i + n]))
                if hit is not None:
                    found.add(hit)
        return found.pop() if len(found) == 1 else None


class Resolution(NamedTuple):
    """One answer about a name; ``manufacturer=None`` means "looked, there is none"."""

    manufacturer: str | None
    source: str


def resolve_free(
    item_name: str | None,
    manufacturer_raw: str | None,
    cache: dict[str, str | None],
    brands: BrandDictionary,
) -> Resolution | None:
    """The answer from the tiers that cost nothing, or None to defer to the LLM.

    A cached ``None`` is a real answer and comes back as ``Resolution(None, "cache")``
    so the product is marked unknown, not pending.
    """
    if not is_junk_manufacturer(manufacturer_raw):
        return Resolution(manufacturer_raw.strip(), "raw")
    key = normalize_name(item_name)
    if key in cache:
        return Resolution(cache[key], "cache")
    brand = brands.match(item_name)
    if brand:
        return Resolution(brand, "dictionary")
    return None
