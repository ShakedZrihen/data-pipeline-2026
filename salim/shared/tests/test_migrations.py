"""The migration history is the schema. These tests keep it honest.

Set TEST_DATABASE_URL to run them, e.g.
    TEST_DATABASE_URL=postgresql+psycopg2://salim:salim@localhost:5432/salim
They are skipped otherwise.
"""
import os
import unittest

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from shared.db import _alembic_config, downgrade, make_engine, migrate
from shared.models import Base

URL = os.environ.get("TEST_DATABASE_URL")

# The SQL issue #65 asked to run by hand on Supabase, verbatim.
ISSUE_65_SQL = """
ALTER TABLE branches ADD COLUMN IF NOT EXISTS phone VARCHAR(64);
ALTER TABLE branches ADD COLUMN IF NOT EXISTS city_code VARCHAR(16);
ALTER TABLE branches ADD COLUMN IF NOT EXISTS store_type VARCHAR(8);
ALTER TABLE branches ADD COLUMN IF NOT EXISTS source_file VARCHAR(256);
ALTER TABLE branches ADD COLUMN IF NOT EXISTS enrichment_source VARCHAR(128);
ALTER TABLE branches ADD COLUMN IF NOT EXISTS enrichment_match VARCHAR(16);
ALTER TABLE branches ADD COLUMN IF NOT EXISTS enriched_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE branches ADD COLUMN IF NOT EXISTS fields_not_provided JSONB;
ALTER TABLE branches ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMP WITH TIME ZONE DEFAULT now();
ALTER TABLE branches ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP WITH TIME ZONE;
"""


@unittest.skipUnless(URL, "TEST_DATABASE_URL not set")
class MigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = make_engine(URL)
        with cls.engine.connect() as connection:
            cls.head = ScriptDirectory.from_config(_alembic_config(connection)).get_current_head()

    def setUp(self):
        downgrade(self.engine)

    def current_revision(self):
        with self.engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()

    def drift(self):
        with self.engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"compare_type": True, "compare_server_default": True}
            )
            return compare_metadata(context, Base.metadata)

    def tables(self):
        with self.engine.connect() as connection:
            return set(inspect(connection).get_table_names())

    def tables_without_rls(self):
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity"
                )
            )
            return {row[0] for row in rows} - {"alembic_version"}

    def execute(self, sql):
        with self.engine.begin() as connection:
            connection.execute(text(sql))

    def test_fresh_database_migrates_to_head(self):
        migrate(self.engine)
        self.assertEqual(self.current_revision(), self.head)
        self.assertEqual(self.tables(), {t.name for t in Base.metadata.sorted_tables} | {"alembic_version"})

    def test_models_match_migrations(self):
        """A model change without a migration fails here, naming the difference."""
        migrate(self.engine)
        self.assertEqual(self.drift(), [])

    def test_every_table_has_row_level_security(self):
        migrate(self.engine)
        self.assertEqual(self.tables_without_rls(), set())

    def test_migrate_is_idempotent(self):
        migrate(self.engine)
        migrate(self.engine)
        self.assertEqual(self.current_revision(), self.head)
        self.assertEqual(self.drift(), [])

    def test_adopts_database_created_before_alembic(self):
        """Supabase: the PR #57 tables exist, no version history, no #65 columns."""
        migrate(self.engine, "0001")
        self.execute("DROP TABLE alembic_version")

        migrate(self.engine)

        self.assertEqual(self.current_revision(), self.head)
        self.assertEqual(self.drift(), [])
        self.assertEqual(self.tables_without_rls(), set())

    def test_adopts_database_where_issue_65_sql_was_run(self):
        migrate(self.engine, "0001")
        self.execute("DROP TABLE alembic_version")
        self.execute(ISSUE_65_SQL)

        migrate(self.engine)

        self.assertEqual(self.current_revision(), self.head)
        self.assertEqual(self.drift(), [])

    def test_downgrade_to_base_leaves_nothing(self):
        migrate(self.engine)
        downgrade(self.engine)
        self.assertEqual(self.tables(), {"alembic_version"})
        self.assertIsNone(self.current_revision())


if __name__ == "__main__":
    unittest.main()
