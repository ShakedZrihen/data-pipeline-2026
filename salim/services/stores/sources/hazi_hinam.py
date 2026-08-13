"""Hazi Hinam — public HTML index, no login.

Two quirks relative to the other three chains:

- the file is named ``StoresFull...`` rather than ``Stores...``, so a
  ``Stores*`` match that anchors on the exact prefix misses it;
- the index has no category filter, so the Stores entry has to be found by
  walking pages (it was on page 2 at the time of writing, and moves as new
  price files are published).

Page walking is capped so a markup change can't turn this into an open-ended
crawl of the site.
"""
from __future__ import annotations

import logging
import re

import requests

from base import SourceResult, StoreSource
from parser import parse_stores_xml

log = logging.getLogger("salim.stores.hazi_hinam")

INDEX_URL = "https://shop.hazi-hinam.co.il/Prices"
HEADERS = {
    "User-Agent": "salim-crawler/1.0 (+https://github.com/ShakedZrihen/data-pipeline-2026)",
}
_STORES_RE = re.compile(r'https?://[^"\']*StoresFull[^"\']*\.gz', re.IGNORECASE)
_MAX_PAGES = 15


class HaziHinamStoreSource(StoreSource):
    name = "hazi_hinam"

    def fetch(self) -> SourceResult:
        session = requests.Session()
        session.headers.update(HEADERS)

        found: list[str] = []
        for page in range(1, _MAX_PAGES + 1):
            resp = session.get(
                INDEX_URL,
                params={"p": page, "s": "", "f": "", "t": "", "d": ""},
                timeout=30,
            )
            resp.raise_for_status()
            found = _STORES_RE.findall(resp.text)
            if found:
                log.info("found Stores file on page %d", page)
                break
        else:
            raise RuntimeError(f"no StoresFull link in the first {_MAX_PAGES} index pages")

        url = max(found, key=_file_name)
        name = _file_name(url)

        blob = session.get(url, timeout=60)
        blob.raise_for_status()
        records = parse_stores_xml(blob.content, provider=self.name, source_file=name)
        return SourceResult(records=records, source_file=name)


def _file_name(url: str) -> str:
    return url.split("/")[-1].split("?")[0]
