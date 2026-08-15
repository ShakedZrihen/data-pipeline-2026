from __future__ import annotations

import logging
import os
from dataclasses import dataclass

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


# To add a new chain: add a registration below and add its settings to
# CRAWLER_CONFIGS keyed by the same registration name.
CRAWLERS: list[CrawlerRegistration | type[Crawler]] = [
    CrawlerRegistration(name="yohananof", crawler_cls=CerberusCrawler),
    CrawlerRegistration(name="rami_levi", crawler_cls=CerberusCrawler),
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


def run(crawlers: list[CrawlerRegistration | type[Crawler]] | None = None) -> dict[str, list[str]]:
    """Run every registered crawler once.

    One crawler failing (e.g. a source changed its login page) is logged and
    skipped rather than aborting the rest. Returns each crawler's uploaded S3
    keys, keyed by crawler name.
    """
    infra = load_infra_config()
    results: dict[str, list[str]] = {}
    for crawler in crawlers or CRAWLERS:
        registration = _registration_for(crawler)
        name = registration.name
        try:
            settings = CRAWLER_CONFIGS[name]
            cfg = _build_config(name, settings, infra)
            results[name] = registration.crawler_cls(cfg).run()
        except Exception:
            log.exception("crawler '%s' failed", name)
            results[name] = []
    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run()
