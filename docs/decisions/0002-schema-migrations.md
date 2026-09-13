# Schema migrations with Alembic

**Status:** Accepted
**Decision:** The schema is owned by the Alembic history in `salim/shared/migrations`.
Services run `alembic upgrade head` at startup, and CI fails when the models and the history disagree.

## Problem

Every service created its schema with `Base.metadata.create_all()` on startup.
That creates tables that do not exist and does nothing else.
When PR #63 added ten columns to `branches`, a fresh local database was built complete while Supabase, where the loader had already created the table, was left without them.
Nothing caught it before the first production write (#65, #66).
Any column added to any table would have repeated it.

## Design

**One history, in `shared/`.**
`shared/alembic.ini`, `shared/migrations/env.py` and `shared/migrations/versions/` live next to the models.
Every image that talks to the database already copies `shared/`, so migrations ship with each service without Dockerfile changes.

**Services migrate at startup.**
`shared.db.migrate(engine)` replaces `init_db()` one for one in the loader, the enricher and the stores service.
It runs the upgrade on a single connection under a transaction-scoped Postgres advisory lock, so services that start together migrate in turn instead of racing.
The API only reads and never migrates.
There is no separate deploy step to forget: the manual `Load queue into Supabase` workflow migrates production the next time it runs, with no new secret.

**Existing databases are adopted, not stamped.**
Supabase and every local volume already hold the PR #57 tables with no version history, and nobody working from a fork can run `alembic stamp` against Supabase.
So the baseline migration creates every table and index with `IF NOT EXISTS`, and the `branches` migration adds its columns the same way.
On a database that already has the tables it changes nothing except recording the version.
A database that already had the hand-written SQL from #65 applied migrates cleanly too.
Both cases are tests in `shared/tests/test_migrations.py`.

**Row-level security is part of the migration.**
Supabase exposes the public schema through its Data API, so every table is created with RLS enabled and no policies.
`shared/migrations/rls.py` is the one-liner a migration calls after `create_table`, and a test asserts that no table in the metadata is left without it.

**Drift fails CI.**
`test_models_match_migrations` migrates a fresh database and asserts that Alembic's `compare_metadata` finds no difference from `shared.models`.
A model change without a migration fails the loader-tests workflow and names the missing column.

## Working with it

```bash
docker compose run --rm migrate revision --autogenerate --rev-id 0003 -m "add x to y"
docker compose run --rm migrate history
docker compose run --rm migrate check      # models vs database, without writing anything
```

Review the generated script, add `enable_row_level_security()` for any new table, and commit it with the model change.
Revision ids are numbered by hand so the history reads in order.

## Alternatives considered

- **Keep it manual.** Free today and paid per column forever, always discovered in production.
- **A folder of SQL files applied by a script.** Cheaper to introduce than Alembic, but it records nothing about what ran where, which is most of the value.
- **A dedicated migrate workflow instead of startup.** The textbook production shape, but it needs the Supabase secret configured before anything works, and until then the loader starts against a stale schema, which is the failure being removed.
Moving the call out of startup later is one line per service.

## Consequences

- `create_all()` is no longer called anywhere.
Test fixtures provision through `downgrade()` and `migrate()`, so every DB-backed test exercises the real path.
- A local volume from before PR #57 has tables the baseline does not describe.
Reset it with `docker compose down -v` rather than migrating it.
- `alembic_version` is the only table without RLS.
It holds one row and no data.
