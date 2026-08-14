"""Tiv Taam price-transparency crawler.

Tiv Taam publishes its files through the same Cerberus portal used by
Yohananof. Authentication, pagination, report filtering and checkpoint date
parsing are therefore shared; only the crawler identity and credentials differ.
"""
from __future__ import annotations

from concrete_crawlers.yohananof import YohananofCrawler


class TivTaamCrawler(YohananofCrawler):
    """Fetch Tiv Taam ``PriceFull`` and ``PromoFull`` files."""

    name = "tiv_taam"
