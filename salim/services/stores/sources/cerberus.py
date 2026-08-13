"""Shared source for chains hosted on the Cerberus portal (url.publishedprices.co.il).

Yohananof and Rami Levi both publish there, so the login handshake, the file
listing and the download all live here once; the per-chain subclasses supply
nothing but a username.

Two things about this portal are easy to get wrong:

1. **The listing is capped at 1000 rows per request.** Rami Levi currently has
   ``iTotalRecords=1433`` and its Stores file sorts past that cap — a single
   un-paged request returns no Stores file at all and looks exactly like a
   chain that does not publish one. ``_list_files`` pages to the end.
2. **Downloads need the logged-in session.** ``/file/d/<name>`` is behind the
   same cookie as the listing, so the download reuses the session rather than
   a fresh anonymous request.
"""
from __future__ import annotations

import logging
import re

import requests

from base import SourceResult, StoreSource
from parser import parse_stores_xml

log = logging.getLogger("salim.stores.cerberus")

BASE_URL = "https://url.publishedprices.co.il"
HEADERS = {
    "User-Agent": "salim-crawler/1.0 (+https://github.com/ShakedZrihen/data-pipeline-2026)",
}
_CSRF_RE = re.compile(r'name="csrftoken"\s+content="([^"]+)"')
_PAGE_SIZE = 1000


class CerberusStoreSource(StoreSource):
    """Base for any chain on the Cerberus portal."""

    #: portal login name; password is blank for these public accounts
    user_name: str
    password: str = ""

    def _login(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(HEADERS)

        login_page = session.get(f"{BASE_URL}/login", timeout=30)
        login_page.raise_for_status()
        match = _CSRF_RE.search(login_page.text)
        if not match:
            raise RuntimeError("no csrftoken on login page; portal markup may have changed")

        resp = session.post(
            f"{BASE_URL}/login/user",
            data={
                "username": self.user_name,
                "password": self.password,
                "r": "",
                "csrftoken": match.group(1),
            },
            timeout=30,
        )
        resp.raise_for_status()
        if 'id="login-form"' in resp.text:
            raise RuntimeError(f"login failed for {self.user_name!r}")
        log.info("logged in as %s", self.user_name)
        return session

    def _list_files(self, session: requests.Session) -> list[str]:
        """Every file name in the account root, paging past the 1000-row cap."""
        listing = session.get(f"{BASE_URL}/file", timeout=30)
        listing.raise_for_status()
        match = _CSRF_RE.search(listing.text)
        if not match:
            raise RuntimeError("no csrftoken on listing page; portal markup may have changed")
        csrftoken = match.group(1)

        names: list[str] = []
        start = 0
        while True:
            resp = session.post(
                f"{BASE_URL}/file/json/dir",
                data={
                    "csrftoken": csrftoken,
                    "cd": "/",
                    "iDisplayStart": start,
                    "iDisplayLength": _PAGE_SIZE,
                    "sEcho": 1,
                },
                headers={"X-Requested-With": "XMLHttpRequest"},
                timeout=60,
            )
            resp.raise_for_status()
            payload = resp.json()
            page = payload.get("aaData", [])
            names += [row.get("fname", "") for row in page if row.get("type") == "file"]
            start += len(page)
            total = int(payload.get("iTotalRecords", 0))
            if not page or start >= total:
                log.info("listed %d file(s) of %d reported", len(names), total)
                return names

    def fetch(self) -> SourceResult:
        session = self._login()
        names = self._list_files(session)

        # Names carry a timestamp (Stores<chain>-000-YYYYMMDD-HHMMSS.xml), and
        # they share one format per chain, so the lexical max is the newest.
        candidates = [n for n in names if n.lower().startswith("store")]
        if not candidates:
            raise RuntimeError(f"no Stores file found for {self.user_name!r} among {len(names)} files")
        newest = max(candidates)

        resp = session.get(f"{BASE_URL}/file/d/{newest}", timeout=60)
        resp.raise_for_status()
        records = parse_stores_xml(resp.content, provider=self.name, source_file=newest)
        return SourceResult(records=records, source_file=newest)
