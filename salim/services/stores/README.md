# stores — store database service

Keeps the `stores` table in sync with what each supermarket chain publishes
about its own branches.

One cycle, per chain:

```
locate newest Stores file  ->  parse  ->  upsert  ->  deactivate the missing
```

Each chain is committed separately, and a chain that fails is logged and
skipped rather than aborting the run.

## Where the data comes from

Israel's price-transparency law requires every chain to publish a `Stores`
file alongside its price files. That file is the backbone of this table.

| Chain | Portal | Auth | File |
|---|---|---|---|
| Yohananof | `url.publishedprices.co.il` | login, blank password | `Stores<chain>-000-<date>.xml` |
| Rami Levi | `url.publishedprices.co.il` | login, blank password | `Stores<chain>-000-<date>.xml` |
| Shufersal | `prices.shufersal.co.il` | none | `Stores<chain>-000-<date>.gz` |
| Hazi Hinam | `shop.hazi-hinam.co.il` | none | `StoresFull<chain>-000-<date>.gz` |

Yohananof and Rami Levi share one portal (Cerberus), so their login, listing
and download live once in `sources/cerberus.py`; their own modules supply only
an account name.

## What that file does and does not contain

It carries `StoreID`, `StoreName`, `Address`, `City`, `ZIPCode`, `StoreType`.
It carries **no phone, no coordinates and no opening hours** — those columns are
filled by a separate enrichment step against each chain's branch-locator page,
and stay `NULL` until it runs.

`City` is a CBS municipality code (`"2530"`), not a city name, so it is stored
as `city_code` and the human-readable `city` is left to the enrichment step.
The `address` from this file is a street only — geocoding it without a city
would be ambiguous.

## Source quirks this code handles

Four chains, one law, four dialects. Each of these was found in a live file and
each one silently breaks a naive implementation:

- **Rami Levi's listing is capped at 1000 rows.** Its Stores file sorts past
  the cap, so an un-paged request returns nothing and looks exactly like a chain
  that publishes no store list. `_list_files` pages to `iTotalRecords`.
- **The root element differs.** `<Root>` for three chains, `<Chain>` for
  Shufersal. The parser keys off the `Store` elements, not the document root.
- **Field casing differs.** Rami Levi writes `<ZipCode>`, everyone else
  `<ZIPCode>`. Field lookup is case-insensitive.
- **Hazi Hinam names the file `StoresFull`,** not `Stores`.
- **Not every record is a branch.** `StoreType` `1` is physical; other values
  are logical entities such as Hazi Hinam's "חצי חינם משלוחים", whose `Address`
  holds a URL. Those are filtered out before writing.

## Enrichment: phone, hours, coordinates

Those come from each chain's own branch locator, one `Enricher` per chain in
`enrichers/`. Two of the four are implemented:

| Chain | Locator | Status |
|---|---|---|
| Hazi Hinam | public JSON API, `/proxy/api/branches` | implemented |
| Rami Levi | server-rendered HTML at `/he/stores` | implemented |
| Yohananof | Next.js; branches arrive over XHR | **endpoint not found yet** |
| Shufersal | empty JS shell — 400KB whose only text is "Shufersal" | **endpoint not found yet** |

For the two unsolved chains the work is finding *where* the site gets its
branch list, not writing the enricher. The technique that worked for Hazi Hinam
is to fetch the page's own JavaScript bundle and search it for the API base —
its Angular bundle names `apiBaseUrl` and `apiSuffix` in clear text. Once an
endpoint is found, adding the chain means one subclass of `Enricher`; nothing
else changes.

Three findings worth keeping regardless of how the rest is scraped:

- **Only Hazi Hinam publishes coordinates.** Rami Levi, the most open of the
  other three, publishes none. `latitude`/`longitude` will need geocoding for
  most chains — and geocoding needs a city, which the Stores file gives only as
  a CBS code.
- **Opening hours are prose as often as data.** Rami Levi publishes lines like
  `מוצאי שבת: הסניף יפתח שעה לאחר צאת השבת ועד לשעה 23:00` — "opens an hour
  after Shabbat ends", which has no clock time at all. `opening_hours` is a
  best-effort reading and `opening_hours_raw` keeps the original text so a
  later reader can do better without re-scraping.
- **Hazi Hinam's API returns `OpenningTimeFrame {From, To}`** — matching this
  issue's `openningTimeFrame (from, to)` letter for letter, misspelling
  included, as does every other field it asks for. The requested data model
  appears to have been written from this API.

### Matching locator records to store rows

The obvious join does not exist: locator ids bear no relation to `StoreID`
(Hazi Hinam numbers branches 201-219 officially and 100-108 on its locator —
zero overlap). `matching.py` therefore matches on content, in two passes.

**Which key is reliable is a per-chain property**, which is why both passes are
needed:

| | Hazi Hinam | Rami Levi |
|---|---|---|
| Names | nicknames — "שרונים" vs "כל בו חצי חינם שרונים" | agree almost exactly |
| Addresses | agree | disagree on house numbers ("היהלומים 8" vs `9`), spelling ("בוליטמור" vs "בולטימור"), and some are blank |
| Best key | **address** | **name** |

So: address first (house number plus a street token; branches with no house
number fall back to two shared tokens), then names for whatever is left — and
only names that appear exactly once on each side, since a wrong pair silently
writes one branch's phone onto another.

Measured coverage: Hazi Hinam 11/12, Rami Levi 56/98. The Rami Levi remainder
is genuine disagreement between the chain's own two publications, not a parser
bug.

**The mapping is many-to-one.** A chain may run a supermarket and a produce
store at one address, each with its own `StoreID`, while the locator lists the
site once — 12 Hazi Hinam branches collapse onto 8 records. When that happens
`apply_enrichment` writes only what stays true for both (coordinates, city, the
chain's phone) and leaves `opening_hours` alone, because a produce counter does
not keep the supermarket's hours. `enrichment_match` records which case a row
was: `unique` or `ambiguous`.

## Table

`stores`, keyed on `(provider, store_id)` — chains number their branches from
`001`, so a store id is only unique within its chain.

`is_active` is derived from presence in the newest file: a branch that stops
being listed is flagged inactive rather than deleted, so price rows that
reference it keep resolving. Deactivation runs only after a chain's fetch
succeeded and returned records — otherwise one network error would mark a whole
chain closed.

The upsert writes only the columns the Stores file owns, so re-running it never
blanks out enrichment data already in the row.

## Running

Whole stack:

```bash
docker compose up --build stores
```

One chain, for development:

```bash
STORES_PROVIDERS=shufersal python main.py
```

Environment: `DATABASE_URL`, optionally `STORES_PROVIDERS` (comma-separated).
