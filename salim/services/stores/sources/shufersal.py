"""Shufersal — public HTML index, no login.

The index splits files by category and category 5 is the stores list, so the
Stores file can be requested directly instead of paging the whole listing.
Each row's href is already a fully-signed Azure blob URL (it carries a SAS
token and expires), so it is downloaded immediately rather than stored.
"""
from __future__ import annotations

import logging
import re

import requests

from base import SourceResult, StoreSource
from parser import parse_stores_xml

log = logging.getLogger("salim.stores.shufersal")

INDEX_URL = "https://prices.shufersal.co.il/FileObject/UpdateCategory"
STORES_CATEGORY = 5
HEADERS = {
    "User-Agent": "salim-crawler/1.0 (+https://github.com/ShakedZrihen/data-pipeline-2026)",
}
_HREF_RE = re.compile(r'href="([^"]*Stores[^"]*)"', re.IGNORECASE)


class ShufersalStoreSource(StoreSource):
    name = "shufersal"

    def fetch(self) -> SourceResult:
        session = requests.Session()
        session.headers.update(HEADERS)

        resp = session.get(INDEX_URL, params={"catID": STORES_CATEGORY}, timeout=30)
        resp.raise_for_status()

        links = [m.replace("&amp;", "&") for m in _HREF_RE.findall(resp.text)]
        if not links:
            raise RuntimeError("no Stores link in Shufersal category listing; page may have changed")

        # The listing is newest-first; the file name still carries the date, so
        # pick by name rather than trusting the ordering.
        url = max(links, key=_file_name)
        name = _file_name(url)

        blob = session.get(url, timeout=60)
        blob.raise_for_status()
        records = parse_stores_xml(blob.content, provider=self.name, source_file=name)
        return SourceResult(records=records, source_file=name)


def _file_name(url: str) -> str:
    return url.split("/")[-1].split("?")[0]
