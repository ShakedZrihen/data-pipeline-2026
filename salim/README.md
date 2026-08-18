# Salim — Supermarket Price Pipeline

Fetches supermarket price publications, pipes them through a queue, and
serves the normalized data over an API.

[מאגר מחירי סופרים ממשלתי](https://www.gov.il/he/pages/cpfta_prices_regulations)

## Architecture

```
crawler (cron) --> Supabase Storage bucket (zip files)
                        |
                        v
              extractor worker (pull zip, unzip, XML/CSV -> JSON)
                        |
                        v
                  RabbitMQ (CloudAMQP)
                        |
                        v
              loader worker (format, upsert into DB)
                        |
                        v
                Supabase Postgres
                        |
                        v
                  FastAPI (api service)
```

| Stage       | Local dev (docker-compose) | Production            |
|-------------|-----------------------------|------------------------|
| Object store | MinIO (S3-compatible)      | Supabase Storage       |
| Queue        | RabbitMQ                   | CloudAMQP              |
| Database     | Postgres                   | Supabase Postgres      |
| Compute      | docker-compose services     | Render.com services    |

Each service reads its object store / queue / DB connection details from
environment variables, so the same code runs locally against MinIO/RabbitMQ/Postgres
and in production against Supabase Storage/CloudAMQP/Supabase Postgres —
only the `.env` values change.

## Folder structure

```
salim/
  docker-compose.yml       # full local stack: infra + all 4 services
  .env.example             # copy to .env and fill in
  shared/                  # code shared by loader + api (DB models, engine)
  crawler/                 # scrapes source site, zips output, uploads to bucket
  services/
    extractor/             # pulls zip from bucket, extracts, converts to JSON, publishes to queue
    loader/                # consumes queue, formats, writes to DB
  api/                     # FastAPI read API over the stored data
```

## Running locally

```bash
cd salim
cp .env.example .env
docker compose up --build
```

- MinIO console: http://localhost:9001 (user/pass from `.env`)
- RabbitMQ management UI: http://localhost:15672
- API docs: http://localhost:8000/docs

## Services

- **crawler** — runs on an internal schedule (`CRON_SCHEDULE` env, cron syntax),
  scrapes/downloads source price files, zips them, and uploads the zip to the
  `raw-prices` bucket.
- **extractor** — polls the bucket for new zip files, extracts them, converts each
  price file (XML/CSV) to JSON, and publishes one message per record to the
  `raw-prices` queue in RabbitMQ.
- **loader** - consumes the `raw-prices` queue in batches, upserts price items into
  `products` + `prices` and promotions into `promotions` + `promotion_items`, and
  fills in each product's manufacturer. See [Loader and enricher](#loader-and-enricher).
- **api** — FastAPI service exposing read endpoints over the `prices` data.

## Loader and enricher

The loader (`services/loader/`) is the queue consumer.
Both extractor outputs land on the same `raw-prices` queue, so each message is dispatched by shape:
a `promotionId` means a promotion, `itemCode` + `price` means a price item, anything else is poison.

**Tables.**
They are created with `create_all()` at startup.
There is no migration tool yet, so a column change on a live database is a manual `ALTER`.

| Table | Key | Holds |
|---|---|---|
| `chains` | `chain_id` | ChainId → display name, seeded from `chains.py` |
| `products` | `(provider, item_code)` | name, unit fields, and the manufacturer with its `manufacturer_status` (`pending` / `resolved` / `unknown`) |
| `prices` | `(provider, store_id, item_code)` | current price and the source `update_time` |
| `promotions` | `(provider, store_id, promotion_id)` | description and validity window |
| `promotion_items` | `(…, item_code)` | per-item deal terms; replaced wholesale when the promotion is upserted |
| `manufacturers` | normalized item name | resolution cache and audit log (`source` is `dictionary`, `llm` or `manual`) |

`provider` is the numeric `ChainId` from the XML, everywhere.
Every write is an idempotent upsert, and a row's `update_time` never goes backwards, so redelivered or out-of-order messages are harmless.
Poison messages are copied to `raw-prices.dlq` (with an `x-reason` header) and acked; anything else that fails nacks the whole batch back for redelivery.

**Manufacturer enrichment** runs in two tiers.
The consumer only does what costs nothing, in order: the XML's own `ManufactureName` (unless it is a placeholder like `לא ידוע`) → the `manufacturers` cache → a whole-token match against the seed brand dictionary (`brands.py`; a name mentioning two brands is treated as ambiguous).
Whatever falls through stays `pending`.
The consumer reloads the cache every `LOADER_CACHE_REFRESH_SECONDS` (default 10 minutes) to pick up what the sweeper resolved.
The sweeper, `enrich.py --backfill`, then sends pending names to `claude-haiku-4-5` in batches of 50 with a structured-output schema, marks each product `resolved` or `unknown`, and caches the answer so the same name is never asked twice, on any chain.
It exits immediately when nothing is pending, and a failed request charges every name in that batch one attempt and ends the run (`ENRICHER_MAX_ATTEMPTS`, default 3), so an outage costs one request per run.

```bash
docker compose run --rm loader-enrich                       # resolve pending products
docker compose run --rm loader-enrich python enrich.py --reset-attempts   # retry exhausted names
docker compose run --rm loader-enrich python enrich.py --reset-unknown    # re-ask "no manufacturer" answers
```

Set `ANTHROPIC_API_KEY` in `.env`; the model is `ENRICHER_MODEL`.
In production run the same command on a schedule (hourly is plenty).

The LLM is deliberately a thin seam.
`enrich.py` builds one `anthropic.Anthropic()` client and calls `messages.create` with a system prompt, a JSON list of `{id, name}` and a JSON schema for the answer; nothing else about the pipeline knows a model exists.
To change the model, set `ENRICHER_MODEL`.
To point at another endpoint that speaks the Anthropic Messages API (a proxy, or a local server that emulates it), set `ANTHROPIC_BASE_URL`; the SDK reads it without code changes.
To swap providers entirely, implement the two-line `Resolver` protocol in `enrich.py` (`model` attribute plus `resolve(batch) -> {id: manufacturer | None}`) and hand it to `run_backfill`; the tests use exactly that hook with a fake.
The API is billed from Console credits, separately from a claude.ai subscription; the key alone is not enough.

## Deploying to production

Each of `crawler/`, `services/extractor/`, `services/loader/`, and `api/` has its
own `Dockerfile` and is meant to be deployed as an independent Render.com service
(background worker for crawler/extractor/loader, web service for api), pointed at
the real Supabase Storage bucket, CloudAMQP instance, and Supabase Postgres
connection string via environment variables — no code changes needed.
