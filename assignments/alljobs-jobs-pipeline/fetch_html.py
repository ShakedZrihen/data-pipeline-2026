"""Collect the first five AllJobs result pages into a timestamped JSON file."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.alljobs.co.il"
SEARCH_URL = BASE_URL + "/SearchResultsGuest.aspx"
OUTPUT_PATH = Path(__file__).with_name("jobs.json")
PAGE_COUNT = 5
ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
}


def fetch_html(session: requests.Session, page: int) -> str:
    response = session.get(
        SEARCH_URL,
        params={"page": page, "position": 235, "type": "", "city": "", "region": ""},
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def _find_by_class_prefix(tag, prefix):
    return tag.find("div", class_=lambda c: c and any(cl.startswith(prefix) for cl in c.split()))


def _find_by_classes(tag, classes):
    return tag.find(class_=lambda c: c and any(cl in classes for cl in c.split()))


def _text(el):
    return el.get_text(" ", strip=True) if el else None


def _published_timestamp(value: str | None, fetched_at: datetime) -> int:
    text = (value or "").replace("\xa0", " ").strip()
    minute_match = re.search(r"לפני\s+(\d+)\s+דק", text)
    hour_match = re.search(r"לפני\s+(\d+)\s+שע", text)
    day_match = re.search(r"לפני\s+(\d+)\s+ימ", text)
    explicit_date = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)

    if minute_match:
        published_at = fetched_at - timedelta(minutes=int(minute_match.group(1)))
    elif "לפני דקה" in text:
        published_at = fetched_at - timedelta(minutes=1)
    elif "לפני שעתיים" in text:
        published_at = fetched_at - timedelta(hours=2)
    elif "לפני שעה" in text:
        published_at = fetched_at - timedelta(hours=1)
    elif hour_match:
        published_at = fetched_at - timedelta(hours=int(hour_match.group(1)))
    elif "אתמול" in text:
        published_at = fetched_at - timedelta(days=1)
    elif day_match:
        published_at = fetched_at - timedelta(days=int(day_match.group(1)))
    elif explicit_date:
        day, month, year = map(int, explicit_date.groups())
        published_at = datetime(year, month, day, tzinfo=ISRAEL_TZ)
    else:
        published_at = fetched_at

    return int(published_at.timestamp())


def parse_jobs(html: str, page: int, fetched_at: datetime) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict] = []
    for box in soup.find_all("div", class_="job-box"):
        title_el = _find_by_class_prefix(box, "job-content-top-title")
        title_link = title_el.find("a", href=True) if title_el else None
        h2 = title_link.find("h2") if title_link else None
        href = title_link.get("href") if title_link else None
        job_id_match = re.search(r"JobID=(\d+)", href or "", re.IGNORECASE)

        location_el = _find_by_classes(
            box,
            (
                "job-content-top-location-ltr",
                "job-content-top-location",
                "job-regions-content",
            ),
        )
        type_el = _find_by_classes(
            box, ("job-content-top-type", "job-content-top-type-ltr")
        )

        time_text = _text(box.find(class_="job-content-top-date"))
        jobs.append(
            {
                "job_id": int(job_id_match.group(1)) if job_id_match else None,
                "url": urljoin(BASE_URL, href) if href else None,
                "source_page": page,
                "time": _published_timestamp(time_text, fetched_at),
                "time_text": time_text,
                "title": _text(h2),
                "company": _text(box.find(class_="T14")),
                "location": _text(location_el),
                "type": _text(type_el),
                "description": _text(box.find(class_="job-content-top-desc")),
            }
        )

    return jobs


def collect_jobs(page_count: int = PAGE_COUNT) -> list[dict]:
    fetched_at = datetime.now(ISRAEL_TZ)
    jobs_by_key: dict[object, dict] = {}
    with requests.Session() as session:
        for page in range(1, page_count + 1):
            for index, job in enumerate(parse_jobs(fetch_html(session, page), page, fetched_at)):
                key = job["job_id"] or (page, index, job["title"], job["company"])
                jobs_by_key.setdefault(key, job)
    return list(jobs_by_key.values())


def main() -> None:
    jobs = collect_jobs()
    OUTPUT_PATH.write_text(
        json.dumps(jobs, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(jobs)} jobs from {PAGE_COUNT} pages to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
