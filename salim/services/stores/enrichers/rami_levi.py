"""Rami Levi — server-rendered HTML, no auth.

Unlike the other three chains the branch list is in the page itself (a Nuxt
app that renders on the server), so no API hunt is needed. Each branch is one
accordion block::

    <button class="store-btn ...">
      <h2 class="title-list">אומן<small>האומן 15, ירושלים</small></h2>
    </button>
    <div class="... content-stores ...">
      <h4>שעות פתיחה</h4> <div class="mb-2"><p>ימים א'-ה': 8:00-22:00</p>…</div>
      <h4>טלפון</h4>       <div class="mb-2">02-6331231</div>
      <h4>פקס</h4>         <div class="mb-2">02-6797432</div>
    </div>

Two things this source does not give:

- **No coordinates.** Rami Levi publishes none, and neither does any chain here
  except Hazi Hinam, so ``latitude``/``longitude`` need geocoding regardless.
- **No stable branch id.** ``external_id`` is synthesized from the address,
  which costs nothing: the join is on address anyway, since locator ids do not
  correspond to the official ``StoreID`` (see ``matching.py``).

Opening hours are prose, not data — the page publishes lines like
``מוצאי שבת: הסניף יפתח שעה לאחר צאת השבת ועד לשעה 23:00``, which has no fixed
clock time at all. ``_parse_hours`` reads the regular weekday line and gives up
honestly on the rest; the untouched text is always kept in
``opening_hours_raw`` so a later reader can do better without re-scraping.
"""
from __future__ import annotations

import html
import logging
import re

import requests

from enrichers.base import Enricher, LocatorRecord, flatten_hours

log = logging.getLogger("salim.stores.enrich.rami_levi")

PAGE_URL = "https://www.rami-levy.co.il/he/stores"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
}

_BLOCK_RE = re.compile(
    r'<button[^>]*class="[^"]*store-btn.*?</button>\s*<div[^>]*content-stores.*?(?=<div class="my-1 position-relative|</main|\Z)',
    re.DOTALL,
)
_TITLE_RE = re.compile(r'<h2[^>]*title-list[^>]*>(.*?)</h2>', re.DOTALL)
_SMALL_RE = re.compile(r"<small[^>]*>(.*?)</small>", re.DOTALL)
_SECTION_RE = re.compile(
    r"<h4[^>]*>\s*([^<]+?)\s*</h4>\s*<div[^>]*class=\"mb-2\"[^>]*>(.*?)</div>", re.DOTALL
)
_PHONE_RE = re.compile(r"(0\d{1,2}-?\d{7}|\*\d{3,5})")

# Hebrew day letters, in week order starting Sunday.
_DAY_LETTERS = "אבגדהוש"
_DAY_NAMES = ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday")
_RANGE_RE = re.compile(
    r"([" + _DAY_LETTERS + r"])['׳]?\s*[-–]\s*([" + _DAY_LETTERS + r"])['׳]?"
    r"[^0-9]{0,20}(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})"
)
_SINGLE_RE = re.compile(
    r"(?:יום\s*)?([" + _DAY_LETTERS + r"])['׳]?[^0-9]{0,20}(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})"
)


def _text(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment or "")).replace("\xa0", " ").strip()


def _pad(clock: str) -> str:
    hour, minute = clock.split(":")
    return f"{int(hour):02d}:{minute}"


def _parse_hours(raw: str) -> dict[str, dict | None]:
    """Best effort over free text. Days it cannot read are simply absent."""
    hours: dict[str, dict | None] = {}

    for start, end, opens, closes in _RANGE_RE.findall(raw):
        first, last = _DAY_LETTERS.index(start), _DAY_LETTERS.index(end)
        if first > last:  # a range that wraps the week is not worth guessing at
            continue
        for index in range(first, last + 1):
            hours[_DAY_NAMES[index]] = {"from": _pad(opens), "to": _pad(closes)}

    for day, opens, closes in _SINGLE_RE.findall(raw):
        hours.setdefault(_DAY_NAMES[_DAY_LETTERS.index(day)], {"from": _pad(opens), "to": _pad(closes)})

    return hours


class RamiLeviEnricher(Enricher):
    name = "rami_levi"

    def fetch(self) -> list[LocatorRecord]:
        resp = requests.get(PAGE_URL, headers=HEADERS, timeout=45)
        resp.raise_for_status()

        records: list[LocatorRecord] = []
        for block in _BLOCK_RE.findall(resp.text):
            title = _TITLE_RE.search(block)
            if not title:
                continue
            small = _SMALL_RE.search(title.group(1))
            address = _text(small.group(1)) if small else None
            name = _text(_SMALL_RE.sub("", title.group(1)))
            if not address:
                continue

            phone = None
            raw_hours = None
            for label, body in _SECTION_RE.findall(block):
                value = _text(body)
                if "שעות" in label:
                    raw_hours = value
                elif "טלפון" in label:  # the block also carries a fax; only take the phone
                    match = _PHONE_RE.search(value)
                    phone = match.group(1) if match else None

            hours = _parse_hours(raw_hours) if raw_hours else {}
            opening_from, opening_to = flatten_hours(hours)

            records.append(
                LocatorRecord(
                    external_id=re.sub(r"\s+", "-", address)[:64],
                    address=address,
                    name=name or None,
                    city=address.rsplit(",", 1)[-1].strip() if "," in address else None,
                    phone=phone,
                    opening_hours=hours or None,
                    opening_from=opening_from,
                    opening_to=opening_to,
                    opening_hours_raw=raw_hours,
                )
            )

        log.info("parsed %d branch(es) from the locator page", len(records))
        return records
