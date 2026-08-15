from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import requests

from crawler import Crawler, DEFAULT_HEADERS

_WANTED_PREFIXES = ("PriceFull", "PromoFull")
_CSRF_RE = re.compile(r'name="csrftoken"\s+content="([^"]+)"')
_DATE_RE = re.compile(r"(\d{8}-\d{6})")  # e.g. Price...-20260731-004031.gz

_PAGE_SIZE = 1000  # rows per listing request; paged via iDisplayStart below


class CerberusCrawler(Crawler):
    """Shared crawler for chains hosted on the Cerberus price-file portal."""

    wanted_prefixes = _WANTED_PREFIXES

    def __init__(self, config):
        super().__init__(config)
        parsed = urlparse(config.source_url)
        self._base_url = f"{parsed.scheme}://{parsed.netloc}"
        self._log = logging.getLogger(f"salim.crawler.{self.name}")

    def _login(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)

        login_page = session.get(self.config.source_url, timeout=30)
        login_page.raise_for_status()
        match = _CSRF_RE.search(login_page.text)
        if not match:
            raise RuntimeError("could not find csrftoken on login page; site markup may have changed")

        resp = session.post(
            f"{self._base_url}/login/user",
            data={
                "username": self.config.user_name or "",
                "password": self.config.password or "",
                "r": "",
                "csrftoken": match.group(1),
            },
            timeout=30,
        )
        resp.raise_for_status()
        if 'id="login-form"' in resp.text:
            raise RuntimeError(f"login failed for user {self.config.user_name!r} (site returned the login form again)")
        self._log.info("logged in as %s", self.config.user_name)
        return session

    def _list_files(self, session: requests.Session) -> list[dict]:
        listing_page = session.get(f"{self._base_url}/file", timeout=30)
        listing_page.raise_for_status()
        match = _CSRF_RE.search(listing_page.text)
        if not match:
            raise RuntimeError("could not find csrftoken on file listing page; site markup may have changed")
        csrftoken = match.group(1)

        rows: list[dict] = []
        start = 0
        while True:
            resp = session.post(
                f"{self._base_url}/file/json/dir",
                data={
                    "csrftoken": csrftoken,
                    "cd": "/",
                    "iDisplayStart": start,
                    "iDisplayLength": _PAGE_SIZE,
                    "sEcho": 1,
                },
                headers={"X-Requested-With": "XMLHttpRequest"},
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()
            page = payload.get("aaData", [])
            rows.extend(page)
            start += len(page)
            if not page or start >= int(payload.get("iTotalRecords", 0)):
                break

        return [row for row in rows if row.get("type") == "file"]

    @staticmethod
    def _file_date(fname: str) -> str | None:
        match = _DATE_RE.search(fname)
        return match.group(1).replace("-", "") if match else None

    def fetch(self) -> tuple[list[str], str | None]:
        session = self._login()
        files = self._list_files(session)

        # Cerberus download URLs require the authenticated cookies from login.
        self._downloader.session = session

        wanted = [f for f in files if f.get("fname", "").startswith(self.wanted_prefixes)]
        links = [f"{self._base_url}/file/d/{f['fname']}" for f in wanted]

        dates = [d for d in (self._file_date(f["fname"]) for f in wanted) if d]
        newest = max(dates) if dates else None
        self._log.info(
            "fetched %d PriceFull/PromoFull file(s) of %d total; newest %s",
            len(links),
            len(files),
            newest,
        )
        return links, newest

    def new_links(self, links: list[str], since_date: str | None) -> list[str]:
        if since_date is None:
            return list(links)
        fresh = [link for link in links if (self._file_date(link.rsplit("/", 1)[-1]) or "") > since_date]
        self._log.info("new_links: %d of %d newer than %s", len(fresh), len(links), since_date)
        return fresh
