from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field

from crawler import Config, Crawler, InfraConfig, load_infra_config
from concrete_crawlers.cerberus import CerberusCrawler
from concrete_crawlers.hazi_hinam import HaziHinamCrawler
from concrete_crawlers.shufersal import ShufersalCrawler
from concrete_crawlers.super_pharm import SuperPharmCrawler
from concrete_crawlers.victory import VictoryCrawler
from concrete_crawlers.wolt import WoltCrawler

log = logging.getLogger("salim.crawler.orchestrator")


@dataclass(frozen=True)
class CrawlerRegistration:
    name: str
    crawler_cls: type[Crawler]


@dataclass(frozen=True)
class RunReport:
    """Outcome of one orchestrator cycle.

    A crawler that ran to completion is in ``uploaded`` even when it found
    nothing new; a crawler that raised is only in ``failed``. The two must stay
    apart: an empty list is a quiet day at the source, a failure is not, and
    folding them together is how three chains failed on every scheduled run
    for three weeks while the job stayed green.
    """

    uploaded: dict[str, list[str]] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


# To add a new chain: add a registration below and add its settings to
# CRAWLER_CONFIGS keyed by the same registration name.
CRAWLERS: list[CrawlerRegistration | type[Crawler]] = [
    CrawlerRegistration(name="yohananof", crawler_cls=CerberusCrawler),
    CrawlerRegistration(name="rami_levi", crawler_cls=CerberusCrawler),
    CrawlerRegistration(name="tiv_taam", crawler_cls=CerberusCrawler),
    HaziHinamCrawler,
    ShufersalCrawler,
    WoltCrawler,
    VictoryCrawler,
    SuperPharmCrawler,
]

# crawler name -> source-specific settings, merged with the shared
# InfraConfig to build that crawler's Config. Non-secret (url/username) since
# these are public gov.il price-transparency info; a real secret can still be
# supplied via CRAWLER_<NAME>_PASSWORD without touching this dict.
CRAWLER_CONFIGS: dict[str, dict] = {
    "yohananof": {
        "source_url": "https://url.publishedprices.co.il/login",
        "user_name": "yohananof",
        "password": "",
    },
    "rami_levi": {
        "source_url": "https://url.publishedprices.co.il/login",
        "user_name": "RamiLevi",
        "password": "",
    },
    "shufersal": {
        "source_url": "https://prices.shufersal.co.il/",
        "user_name": None,  # public listing, no login
        "password": "",
    },
    # Wolt Market publishes a public HTML price index (no auth).
    "wolt": {
        "source_url": "https://wm-gateway.wolt.com/isr-prices/public/v1/index.html",
    },
    "hazi_hinam": {
        "source_url": "https://shop.hazi-hinam.co.il/Prices",
    },
    "victory": {
        "source_url": "https://laibcatalog.co.il/victory/index.html",
    },
    "super_pharm": {
        "source_url": "http://prices.super-pharm.co.il/",
    },
    "tiv_taam": {
        "source_url": "https://url.publishedprices.co.il/login",
        "user_name": "TivTaam",
        "password": "",
    },
}


def _build_config(name: str, settings: dict, infra: InfraConfig) -> Config:
    password = os.environ.get(f"CRAWLER_{name.upper()}_PASSWORD", settings.get("password"))
    start_date = os.environ.get(f"CRAWLER_{name.upper()}_START_DATE", settings.get("start_date"))
    return Config(
        name=name,
        source_url=settings["source_url"],
        bucket=infra.bucket,
        s3_endpoint=infra.s3_endpoint,
        s3_access_key=infra.s3_access_key,
        s3_secret_key=infra.s3_secret_key,
        s3_region=infra.s3_region,
        download_dir=infra.download_dir / name,
        link_suffixes=settings.get("link_suffixes"),
        user_name=settings.get("user_name"),
        password=password,
        start_date=start_date,
    )


def _registration_for(crawler: CrawlerRegistration | type[Crawler]) -> CrawlerRegistration:
    if isinstance(crawler, CrawlerRegistration):
        return crawler

    name = getattr(crawler, "name", None)
    if not name:
        raise ValueError(f"crawler class {crawler.__name__} is missing a registration name")
    return CrawlerRegistration(name=name, crawler_cls=crawler)


def selected_crawlers() -> list[CrawlerRegistration | type[Crawler]]:
    """The crawlers this runner should attempt, from ``CRAWLER_PROVIDERS``.

    Which chains are reachable depends on where the runner is, not on the code:
    three of the sources below refuse GitHub's datacenter IP ranges outright,
    while the same commit collects all of them from an Israeli IP. So the
    hosted schedule narrows the set with this variable and a self-hosted runner
    leaves it unset.

    It is an allowlist rather than a skip-list on purpose. The workflow env
    then reads as "what GitHub can actually reach", and a chain added upstream
    later stays off the hosted schedule until someone confirms it works there —
    which matters because one of the three failures is a page that parses to
    zero links and reports success.

    Unset or empty means every registered crawler; an unset Actions variable
    arrives as "" rather than absent, so both have to mean the same thing.
    """
    wanted = os.environ.get("CRAWLER_PROVIDERS", "").strip()
    if not wanted:
        return CRAWLERS

    names = [n.strip() for n in wanted.split(",") if n.strip()]
    known = {_registration_for(c).name: c for c in CRAWLERS}
    unknown = [n for n in names if n not in known]
    if unknown:
        # Skipping a misspelled name silently would drop a chain from the
        # schedule while the job still reported success.
        raise ValueError(
            f"CRAWLER_PROVIDERS names unknown crawler(s): {', '.join(sorted(unknown))}. "
            f"Known: {', '.join(sorted(known))}"
        )

    selected = set(names)
    # Registration order, not the order they were listed in the variable.
    return [c for c in CRAWLERS if _registration_for(c).name in selected]


def run(crawlers: list[CrawlerRegistration | type[Crawler]] | None = None) -> RunReport:
    """Run every registered crawler once.

    One crawler failing (e.g. a source changed its login page) is logged and
    the rest still run; the failure is recorded in the report rather than
    swallowed.
    """
    infra = load_infra_config()
    report = RunReport()
    for crawler in crawlers if crawlers is not None else selected_crawlers():
        registration = _registration_for(crawler)
        name = registration.name
        try:
            settings = CRAWLER_CONFIGS[name]
            cfg = _build_config(name, settings, infra)
            report.uploaded[name] = registration.crawler_cls(cfg).run()
        except Exception:
            log.exception("crawler '%s' failed", name)
            report.failed.append(name)
    return report


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    report = run()
    files = sum(len(keys) for keys in report.uploaded.values())
    log.info(
        "run complete: %d crawler(s) ok, %d failed, %d file(s) uploaded",
        len(report.uploaded), len(report.failed), files,
    )
    if not report.ok:
        # The exit code is all a scheduled job reports; a failure that does
        # not reach it is invisible from the Actions tab.
        log.error("failed crawler(s): %s", ", ".join(report.failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
