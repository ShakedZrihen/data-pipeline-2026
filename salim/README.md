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
    stores/                # syncs the `stores` table from each chain's published store list
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
- **loader** — consumes the `raw-prices` queue, normalizes/validates each message,
  and upserts it into the `prices` table (plus `stores`/`products` lookup tables).
- **stores** — syncs the `stores` table from each chain's mandated `Stores`
  publication (branch id, name, address) and flags branches that stopped being
  listed as inactive. Runs to completion and exits; see
  [services/stores/README.md](services/stores/README.md).
- **api** — FastAPI service exposing read endpoints over the `prices` data.

## Deploying to production

Each of `crawler/`, `services/extractor/`, `services/loader/`, and `api/` has its
own `Dockerfile` and is meant to be deployed as an independent Render.com service
(background worker for crawler/extractor/loader, web service for api), pointed at
the real Supabase Storage bucket, CloudAMQP instance, and Supabase Postgres
connection string via environment variables — no code changes needed.
