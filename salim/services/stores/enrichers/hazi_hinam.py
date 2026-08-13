"""Hazi Hinam — public JSON API, no auth.

The site is an Angular application, so the branch list is not in the HTML. The
endpoint was found inside the app's own bundle, which ships its configuration
in clear text::

    apiBaseUrl: "https://shop.hazi-hinam.co.il/proxy/"
    apiSuffix:  "api/"

giving ``GET /proxy/api/branches``. That is the technique to reuse for the two
chains still unsolved: fetch the JS bundle, search it for the API base.

The response is unusually complete — it carries every field the Stores file
lacks, including coordinates, which no other chain publishes at all. Worth
knowing: its ``OpenningTimeFrame {From, To}`` matches issue #23's
``openningTimeFrame (from, to)`` letter for letter, misspelling included, and
every other field in the issue maps onto this response too. The requested data
model appears to have been written from this API.
"""
from __future__ import annotations

import logging

import requests

from enrichers.base import Enricher, LocatorRecord, day_name, flatten_hours

log = logging.getLogger("salim.stores.enrich.hazi_hinam")

API_URL = "https://shop.hazi-hinam.co.il/proxy/api/branches"
HEADERS = {
    "User-Agent": "salim-crawler/1.0 (+https://github.com/ShakedZrihen/data-pipeline-2026)",
    "Accept": "application/json",
}


def _clock(part: dict | None) -> str | None:
    if not isinstance(part, dict) or part.get("Hour") is None:
        return None
    return f"{int(part['Hour']):02d}:{int(part.get('Minute') or 0):02d}"


def _city_from(address: str | None) -> str | None:
    """Last comma-separated segment, e.g. "הרקון 2, הוד השרון" -> "הוד השרון"."""
    if not address or "," not in address:
        return None
    return address.rsplit(",", 1)[-1].strip() or None


class HaziHinamEnricher(Enricher):
    name = "hazi_hinam"

    def fetch(self) -> list[LocatorRecord]:
        resp = requests.get(API_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("IsOK"):
            raise RuntimeError(f"locator API reported failure: {payload.get('Message')!r}")

        branches = payload["Results"]["Branches"]
        records: list[LocatorRecord] = []

        for branch in branches:
            hours: dict[str, dict | None] = {}
            for index in range(1, 8):
                day = branch.get(f"Day_{index}") or {}
                frame = day.get("OpenningTimeFrame") or {}
                start, end = _clock(frame.get("From")), _clock(frame.get("To"))
                # A day the branch is shut is recorded as null rather than
                # omitted, so "closed" stays distinguishable from "unknown".
                hours[day_name(index)] = (
                    {"from": start, "to": end} if day.get("IsActive") and start and end else None
                )

            opening_from, opening_to = flatten_hours(hours)
            address = branch.get("Address")
            records.append(
                LocatorRecord(
                    external_id=str(branch["Code"]),
                    address=address,
                    name=branch.get("Name"),
                    city=_city_from(address),
                    phone=branch.get("Phone"),
                    latitude=branch.get("Latitude"),
                    longitude=branch.get("Longitude"),
                    opening_hours=hours,
                    opening_from=opening_from,
                    opening_to=opening_to,
                )
            )

        log.info("fetched %d branch(es) from the locator API", len(records))
        return records
