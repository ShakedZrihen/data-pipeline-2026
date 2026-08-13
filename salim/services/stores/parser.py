"""Parser for the mandated ``Stores`` XML file.

All four chains publish under the same price-transparency law, but not to the
same schema. Differences seen in the live files (2026-08-08):

    root element   Yohananof / Rami Levi / Hazi Hinam use <Root>,
                   Shufersal uses <Chain>
    field casing   Rami Levi writes <ZipCode>, everyone else <ZIPCode>
    nesting        stores sit under SubChains/SubChain/Stores/Store, but the
                   depth is not worth relying on

So this parser makes no assumption about the root tag or the nesting depth: it
walks every element named ``Store`` (case-insensitively) and reads that
element's children into a case-insensitive dict. Adding a fifth chain should
not require touching this file.
"""
from __future__ import annotations

import gzip
import io
import logging
import xml.etree.ElementTree as ET

from base import StoreRecord

log = logging.getLogger("salim.stores.parser")


def _decompress(blob: bytes) -> bytes:
    """Stores files arrive as plain .xml or gzipped .gz depending on the chain."""
    if blob[:2] == b"\x1f\x8b":
        return gzip.decompress(blob)
    return blob


def _fields(element: ET.Element) -> dict[str, str]:
    """Child tag -> text, lowercased keys so ZIPCode and ZipCode both resolve."""
    out: dict[str, str] = {}
    for child in element:
        text = (child.text or "").strip()
        if text:
            out[child.tag.lower()] = text
    return out


def _first(fields: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = fields.get(name.lower())
        if value:
            return value
    return None


def parse_stores_xml(blob: bytes, provider: str, source_file: str | None = None) -> list[StoreRecord]:
    """Parse a raw (optionally gzipped) Stores file into normalized records."""
    root = ET.parse(io.BytesIO(_decompress(blob))).getroot()

    # ChainID lives at the top of the document, not on each store.
    chain_id = None
    for element in root.iter():
        if element.tag.lower() == "chainid" and (element.text or "").strip():
            chain_id = element.text.strip()
            break

    records: list[StoreRecord] = []
    for element in root.iter():
        if element.tag.lower() != "store":
            continue
        fields = _fields(element)
        store_id = _first(fields, "StoreID", "StoreId", "StoreNumber")
        if not store_id:
            continue  # a <Store> wrapper with no id is not a record
        records.append(
            StoreRecord(
                provider=provider,
                store_id=store_id,
                name=_first(fields, "StoreName"),
                address=_first(fields, "Address"),
                # Kept raw: this is a CBS municipality code (e.g. "2530"), not
                # a city name. The locator scrape supplies the real city.
                city_code=_first(fields, "City"),
                store_type=_first(fields, "StoreType"),
                chain_id=chain_id,
                source_file=source_file,
            )
        )

    log.info("parsed %d store record(s) for %s from %s", len(records), provider, source_file)
    return records
