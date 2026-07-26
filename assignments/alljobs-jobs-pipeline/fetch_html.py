import json
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import dateparser
import requests
from bs4 import BeautifulSoup

BASE_URL = (
    "https://www.alljobs.co.il/SearchResultsGuest.aspx"
    "?page={page}&position=235&type=&city=&region="
)
PAGES = 5
# Fixed delay between page requests so we don't hammer the live site.
REQUEST_DELAY_SECONDS = 2
RAW_HTML_DIR = Path("data/raw")
OUTPUT_PATH = Path("jobs.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

SITE_TZ = ZoneInfo("Asia/Jerusalem")

# Pin the language so autodetection can't attribute a Hebrew string with Latin
# digits to another locale. DATE_ORDER matters for the DD/MM/YYYY form: 05/06
# is ambiguous and the site means 5 June.
DATEPARSER_SETTINGS = {"DATE_ORDER": "DMY", "PREFER_DATES_FROM": "past"}


def _meta_path(html_path: Path) -> Path:
    return html_path.with_suffix(".meta.json")


def fetch_html(url: str, output_path: Path) -> datetime:
    """Fetch `url` to `output_path` and return the time it was fetched.

    The site reports posting dates relatively ("2 days ago"), so the fetch time
    is the reference point they're relative to. It's written to a sidecar file
    next to the HTML: without it, re-parsing saved HTML later would silently
    shift every timestamp forward.
    """
    response = requests.get(url, headers=HEADERS, timeout=10)
    response.raise_for_status()
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(response.text, encoding="utf-8")
    _meta_path(output_path).write_text(
        json.dumps({"url": url, "fetched_at": fetched_at.isoformat()}, indent=2),
        encoding="utf-8",
    )
    return fetched_at


def load_fetched_at(html_path: Path) -> datetime:
    meta = json.loads(_meta_path(html_path).read_text(encoding="utf-8"))
    return datetime.fromisoformat(meta["fetched_at"])


def parse_posted_at(raw: str | None, fetched_at: datetime) -> str | None:
    """Turn a rendered date string into an ISO-8601 Israeli wall-clock time. """
    if not raw:
        return None

    base = fetched_at.astimezone(SITE_TZ).replace(tzinfo=None)
    parsed = dateparser.parse(
        raw,
        languages=["he"],
        settings={**DATEPARSER_SETTINGS, "RELATIVE_BASE": base},
    )
    if parsed is None:
        return None

    return parsed.replace(tzinfo=SITE_TZ).isoformat()


def _find_by_class_prefix(tag, prefix):
    return tag.find("div", class_=lambda c: c and any(cl.startswith(prefix) for cl in c.split()))


def _find_by_classes(tag, classes):
    return tag.find(class_=lambda c: c and any(cl in classes for cl in c.split()))


def _text(el):
    return el.get_text(" ", strip=True) if el else None


def parse_jobs(html_path: Path, fetched_at: datetime | None = None) -> list[dict]:
    if fetched_at is None:
        fetched_at = load_fetched_at(html_path)
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")

    jobs = []
    for box in soup.find_all("div", class_="job-box"):
        title_el = _find_by_class_prefix(box, "job-content-top-title")
        h2 = title_el.find("h2") if title_el else None

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

        time_raw = _text(box.find(class_="job-content-top-date"))
        posted_at = parse_posted_at(time_raw, fetched_at)
        if time_raw and posted_at is None:
            print(f"warning: unrecognised date format {time_raw!r}")

        jobs.append(
            {
                "time": posted_at,
                "title": _text(h2),
                "company": _text(box.find(class_="T14")),
                "location": _text(location_el),
                "type": _text(type_el),
                "description": _text(box.find(class_="job-content-top-desc")),
            }
        )

    return jobs


def crawl(pages: int = PAGES, output_path: Path = OUTPUT_PATH) -> list[dict]:
    jobs = []

    for page in range(1, pages + 1):
        html_path = RAW_HTML_DIR / f"alljobs_page{page}.html"
        fetched_at = fetch_html(BASE_URL.format(page=page), html_path)
        page_jobs = parse_jobs(html_path, fetched_at)
        jobs.extend(page_jobs)
        print(f"page {page}: {len(page_jobs)} jobs")

        if page < pages:
            time.sleep(REQUEST_DELAY_SECONDS)

    output_path.write_text(
        json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n{len(jobs)} jobs written to {output_path}")
    return jobs


if __name__ == "__main__":
    crawl()
