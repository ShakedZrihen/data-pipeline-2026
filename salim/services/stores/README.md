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

## Locator endpoints — Shufersal and Yochananof

`enrichers/base.py` says the hard part of a new chain is finding where its site
gets its branch list. Both remaining chains are solved; the endpoints and their
traps are recorded here so nobody has to re-derive them.

### Yochananof — GraphQL

The consumer site is **`yochananof.co.il`** — spelled with a `ch`, unlike the
crawler's `yohananof` provider name. Two traps before the data:

- `www.yochananof.co.il` **fails TLS verification**: the Let's Encrypt cert is
  issued for the apex `yochananof.co.il` only, with no `www` SAN. Request the
  apex and verification passes — do **not** reach for `verify=False`.
- The branch page is a Next.js app that renders nothing server-side. The data
  comes from an Apollo GraphQL endpoint named in the JS bundle:
  **`https://api.yochananof.co.il/graphql`**. Introspection is enabled.

```graphql
{ externalStores { storeNumber storeName address customerServicePhone locationMapUrl
    openingHours { defaultByWeekday { weekday standard { from to } daylightSaving { from to } } } } }
```

Measured 2 Sept 2026 — **52 branches**: `storeNumber`/`storeName`/`address`
52/52, `locationMapUrl` 47/52, `openingHours` 47/52, and
**`customerServicePhone` 0/52 — Yochananof publishes no branch phone numbers
here**, so that column stays null for this chain no matter how the matching goes.

Two shape notes: hours are **minutes from midnight** (450 = 07:30, 1260 = 21:00)
on a **0-based weekday** (0 = Sunday), so `day_name()` needs `weekday + 1`;
Saturday arrives as `standard: []`, meaning closed rather than unknown. Summer
hours are a separate `daylightSaving` range, present only where they differ.
Coordinates are not their own fields — they are embedded in `locationMapUrl`, a
Google Maps embed, as `!2d<longitude>!3d<latitude>`.

### Shufersal — Wix Data collection

The locator is **not** on the shop domain. `www.shufersal.co.il` links to it as
`javascript:toggleBranchesModal()`, and the real page is
`window.miglog.branchesLink` = **`https://www.shufersal.co.il/corp/branches`** —
a Wix site, whose records live in a public Wix Data collection called
`Branches` (`permissions.read: anyone`).

Fetching it takes two requests: `GET /corp/_api/v1/access-tokens`, then the
`instance` token of app **`675bbcef-18d8-41f5-800e-131ec9e08762`** (wix-data) as
the `Authorization` header on
`POST /corp/_api/cloud-data/v2/items/query`, body
`{"dataCollectionId": "Branches", "query": {"paging": {"limit": 200, "offset": N}}}`.
The page caps at 200, so it has to be paged.

Measured 2 Sept 2026 — **1,001 rows**, and that count is the thing to be careful
about. The mandated Stores file lists **417** Shufersal branches; this collection
covers **15 sub-networks**, most of which are not Shufersal-branded retail:
שופרסל דיל 227, **מחסנים (warehouses) 209**, Be 158, אקספרס 138, שלי 114,
יש חסד 45, יוניברס 42, דן דיל 25, and smaller. Enriching against all 1,001
invites false address matches; filter on `companyNetwork` first.

Field coverage is partial and **absent values arrive as the *string* `"undefined"`,
not null** — `latitude`/`longitude` 519/1001, `branchPhone` 564/1001,
`branchAddress` 637/1001, `city` 772/1001. Any parser that trusts truthiness will
happily store `"undefined"` as a coordinate.

### Measured end to end — 3 Sept 2026

Full run against a freshly created database (`docker compose down -v` first, so
this also proves `create_all` builds the right schema from nothing), counted
from `branches` and `branch_opening_hours` rather than from the run summary.

**576 branches, 389 enriched uniquely + 25 with address-only data, 525 opening-hour rows.**

| chain | branches | phone | coords | city | hours | the source does not provide |
|---|---|---|---|---|---|---|
| שופרסל | 416 | 308 | 315 | 320 | — | **opening_hours** |
| רמי לוי | 98 | 53 | — | 56 | 333 rows | **latitude, longitude** |
| יוחננוף | 50 | — | 27 | 15 | 162 rows | **phone** |
| חצי חינם | 12 | 11 | 11 | 9 | 30 rows | *nothing — the only complete one* |

A dash is **not a scrape that failed**. Those sources carry no such field at
all, and each row records that in `branches.fields_not_provided`, so a null
column can be told apart from one nobody has looked up yet:

| what is true | how the row shows it |
|---|---|
| nobody has looked this branch up | `enriched_at IS NULL` |
| the source has no such field | field listed in `fields_not_provided` |
| the source has the field, blank here | enriched, not listed, column still null |

The declarations behind that column are measured against live responses, not
read off documentation — see `provides` on each enricher.

#### Why hours are normalized

`branch_opening_hours` holds one row per branch per weekday, ISO-numbered
(Monday 1 … Sunday 7). A real Yochananof week, straight from the table:

```
 weekday | opens_at | closes_at
       1 | 07:30    | 21:00
       2 | 07:30    | 22:00
       3 | 07:30    | 22:30
       4 | 07:30    | 23:00
       5 | 06:00    | 13:30     <- short Friday
       7 | 07:30    | 21:00
                               <- weekday 6 absent: closed Saturday
```

A single `from`/`to` pair cannot express that. #28's `flatten_hours` took the
widest window across Sunday–Thursday, which for this branch stores
`07:30–23:00` and claims it is open on Friday evening and all day Saturday.

Two things the live data corrected, found by running the conversion over all
four locators rather than reasoning about it:

- **"Open until midnight" is spelled both `00:00` and `24:00`** — one Rami Levi
  branch uses each on different days of the same week. `24:00` is not a valid
  time and `00:00` read literally sorts before every opening time, so both are
  recognised before parsing and stored as `23:59:59`.
- **An inverted window skips its day rather than failing the branch.** Two Rami
  Levi branches publish a Friday as `13:30–06:30`, from and to swapped at the
  source. One unusable day is not an unusable branch.

### Applying this to a database that already has `branches`

Nothing to do by hand.
The service runs the Alembic history at startup, and migration `0002_branch_store_metadata` adds these columns to a `branches` table the loader created earlier.
See [Changing the schema](../../README.md#changing-the-schema).
So the first run against Supabase (#35) needs no preparation: whichever of the loader or this service starts first migrates it.
