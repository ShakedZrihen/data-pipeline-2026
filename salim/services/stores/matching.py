"""Matching a locator record to a row in the `stores` table.

The obvious join — locator id to ``StoreID`` — does not work. Measured on Hazi
Hinam, whose official file numbers branches 201-219 while its locator API
numbers them 100-108: **zero overlap**. The two sides simply keep separate
registries, and there is no reason to expect any chain to differ.

What was measured on the same 12 branches:

    by branch name      7/12, and it produces false pairs (the definite article
                        breaks "כישור" against "הכישור", while loose token
                        overlap happily marries two unrelated branches)
    by street address   11/12

So addresses are the key: a house number plus a street token is far more
discriminating than a nickname, and both sides publish it.

**The mapping is many-to-one, not one-to-one.** A chain may run a supermarket
and a produce store at one address, each with its own ``StoreID``, while the
consumer-facing locator lists the site once — for Hazi Hinam that collapses 12
branches onto 8 records. ``match_stores`` reports that rather than hiding it, so
the caller can decide which fields are safe to copy; see
``repository.apply_enrichment``.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

log = logging.getLogger("salim.stores.matching")

# Words that appear on one side but not the other and carry no location meaning.
_NOISE = re.compile(r"\b(ישראל|רחוב|פינת|קומה|מרכז מסחרי|ת\.ד)\b")
_PUNCT = re.compile(r"[\"'׳״,\-–־.()\[\]/]")


def address_key(address: str | None) -> tuple[str | None, frozenset[str]]:
    """``(house number, street tokens)`` — the part both sides agree on.

    The leading ``ה`` is stripped from every token because the official file
    and the locator disagree about it constantly ("כישור" vs "הכישור").
    """
    text = unicodedata.normalize("NFKC", address or "")
    text = _PUNCT.sub(" ", text)
    text = _NOISE.sub(" ", text)

    numbers = re.findall(r"\b(\d{1,4})\b", text)
    tokens = frozenset(
        re.sub(r"^ה", "", token)
        for token in text.split()
        if not token.isdigit() and len(token) > 2
    )
    return (numbers[0] if numbers else None), tokens


def _is_match(left: tuple[str | None, frozenset[str]], right: tuple[str | None, frozenset[str]]) -> bool:
    """Compare two address keys.

    A house number is the strongest signal available, so when both sides have
    one it must agree and a single shared street token is then enough.

    Plenty of branches have no house number at all — "צומת גוש עציון",
    "א.ת באר טוביה", "מרכז מסחרי מטה בנימין". Refusing to match those loses
    real branches, so they fall back to token overlap, but at a higher bar: two
    shared tokens rather than one, since without a number a single common word
    like "מרכז" or "קניון" says almost nothing.

    A number on one side only is treated as no match: it usually means the two
    are different addresses, and guessing here is how false pairs get made.
    """
    left_number, left_tokens = left
    right_number, right_tokens = right
    shared = left_tokens & right_tokens

    if left_number and right_number:
        return left_number == right_number and bool(shared)
    if not left_number and not right_number:
        return len(shared) >= 2
    return False


_NAME_NOISE = re.compile(
    r"\b(כל בו|סניף|מרכול|קניון|מרכז מסחרי|החדש|הישן|שופרסל|רמי לוי|חצי חינם|יוחננוף)\b"
)


def name_key(name: str | None) -> str:
    """Normalized branch name, for the fallback pass."""
    text = unicodedata.normalize("NFKC", name or "")
    text = _PUNCT.sub(" ", text)
    text = _NAME_NOISE.sub(" ", text)
    text = " ".join(re.sub(r"^ה", "", t) for t in text.split() if len(t) > 1)
    return re.sub(r"\s+", " ", text).strip()


def _match_by_name(stores, locator_records) -> dict[str, Match]:
    """Second pass for rows the address could not resolve.

    Which key is reliable turns out to be a per-chain property, not a general
    one. Hazi Hinam names its branches with nicknames ("שרונים" against the
    official "כל בו חצי חינם שרונים") and its addresses line up, so addresses
    win there. Rami Levi is the reverse: its two sides disagree about house
    numbers ("היהלומים 8" against "היהלומים 9"), about spelling ("בוליטמור"
    against "בולטימור") and sometimes publish no address at all — while the
    branch names agree almost exactly.

    Only unambiguous names are used: a name is accepted just when it appears
    once on each side. Anything repeated is left unmatched rather than guessed,
    since a wrong pair silently writes one branch's phone onto another.
    """
    store_names: dict[str, list] = {}
    for store in stores:
        key = name_key(store.name)
        if key:
            store_names.setdefault(key, []).append(store)

    record_names: dict[str, list] = {}
    for record in locator_records:
        key = name_key(record.name)
        if key:
            record_names.setdefault(key, []).append(record)

    matches: dict[str, Match] = {}
    for key, candidates in store_names.items():
        records = record_names.get(key, [])
        if len(candidates) != 1 or len(records) != 1:
            continue
        matches[candidates[0].store_id] = Match(
            external_id=records[0].external_id, store_ids=[candidates[0].store_id]
        )
    return matches


@dataclass
class Match:
    """One locator record and every store row it resolves to."""

    external_id: str
    store_ids: list[str]

    @property
    def is_unique(self) -> bool:
        return len(self.store_ids) == 1


def match_stores(stores, locator_records) -> tuple[dict[str, Match], list[str]]:
    """Resolve locator records against store rows by address.

    ``stores`` and ``locator_records`` both need ``.store_id``/``.external_id``
    and ``.address``. Returns ``{store_id: Match}`` plus the ids of locator
    records that matched nothing.
    """
    indexed = [(s, address_key(s.address)) for s in stores]

    matches: dict[str, Match] = {}
    unmatched: list[str] = []

    for record in locator_records:
        number, tokens = address_key(record.address)
        if not tokens:
            unmatched.append(record.external_id)
            continue

        hits = [
            store
            for store, key in indexed
            if _is_match((number, tokens), key)
        ]
        if not hits:
            unmatched.append(record.external_id)
            continue

        match = Match(external_id=record.external_id, store_ids=[s.store_id for s in hits])
        for store in hits:
            matches[store.store_id] = match

    # Second pass: names, for rows the address could not resolve.
    resolved = set(matches)
    by_name = _match_by_name([s for s in stores if s.store_id not in resolved], locator_records)
    used = {m.external_id for m in matches.values()}
    for store_id, match in by_name.items():
        if match.external_id in used:  # already spoken for by a stronger key
            continue
        matches[store_id] = match
    if by_name:
        log.info("name fallback resolved %d additional row(s)", len(matches) - len(resolved))

    matched_ids = {m.external_id for m in matches.values()}
    unmatched = [external_id for external_id in unmatched if external_id not in matched_ids]

    ambiguous = {m.external_id for m in matches.values() if not m.is_unique}
    log.info(
        "matched %d store row(s) to %d locator record(s); %d ambiguous, %d unmatched",
        len(matches),
        len({m.external_id for m in matches.values()}),
        len(ambiguous),
        len(unmatched),
    )
    return matches, unmatched
