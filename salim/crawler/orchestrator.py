from __future__ import annotations

import logging
import os

from crawler import Config, Crawler, InfraConfig, load_infra_config
from concrete_crawlers.shufersal import ShufersalCrawler
from concrete_crawlers.yohananof import YohananofCrawler
from concrete_crawlers.wolt import WoltCrawler
from concrete_crawlers.hazi_hinam import HaziHinamCrawler
from concrete_crawlers.victory import VictoryCrawler
from concrete_crawlers.super_pharm import SuperPharmCrawler
from concrete_crawlers.tiv_taam import TivTaamCrawler

log = logging.getLogger("salim.crawler.orchestrator")


# To add a new chain: import its class above, add it to CRAWLERS below, and
# add its settings to CRAWLER_CONFIGS keyed by the same name as its `.name`.
CRAWLERS: list[type[Crawler]] = [
    YohananofCrawler,
    HaziHinamCrawler,
    ShufersalCrawler,
    WoltCrawler,
    VictoryCrawler,
    SuperPharmCrawler,
    TivTaamCrawler,
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
    return Config(
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
        name=name
    )


def run(crawlers: list[type[Crawler]] | None = None) -> dict[str, list[str]]:
    """Run every registered crawler once.

    One crawler failing (e.g. a source changed its login page) is logged and
    skipped rather than aborting the rest. Returns each crawler's uploaded S3
    keys, keyed by crawler name.
    """
    infra = load_infra_config()
    results: dict[str, list[str]] = {}
    for crawler_cls in crawlers or CRAWLERS:
        name = getattr(crawler_cls, "name", crawler_cls.__name__)
        try:
            settings = CRAWLER_CONFIGS[name]
            cfg = _build_config(name, settings, infra)
            results[name] = crawler_cls(cfg).run()
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
