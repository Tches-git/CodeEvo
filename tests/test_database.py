import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, inspect

from codeevo.database import normalize_database_url, upgrade_database
from codeevo.postgres_store import PostgresTaskStore
from codeevo.repository import TaskRepository, create_repository


class DatabaseMigrationTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        os.unlink(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_baseline_migration_is_complete_and_idempotent(self):
        url = "sqlite+pysqlite:///" + self.path

        upgrade_database(url)
        upgrade_database(url)

        engine = create_engine(url)
        try:
            tables = set(inspect(engine).get_table_names())
        finally:
            engine.dispose()
        self.assertIn("alembic_version", tables)
        self.assertIn("tasks", tables)
        self.assertIn("agent_memories", tables)
        self.assertIn("release_observations", tables)
        self.assertIn("annotation_cases", tables)
        self.assertIn("annotation_submissions", tables)
        self.assertIn("annotation_adjudications", tables)
        self.assertIn("annotation_exports", tables)
        self.assertEqual(26, len(tables))

    def test_repository_selection_is_explicit(self):
        repository = create_repository("", self.path)

        self.assertIsInstance(repository, TaskRepository)
        self.assertEqual("sqlite", repository.backend)
        with self.assertRaisesRegex(ValueError, "PostgreSQL URL"):
            create_repository("mysql://localhost/codeevo", self.path)

    def test_postgresql_url_uses_psycopg_v3_dialect(self):
        self.assertEqual(
            "postgresql+psycopg://user:pass@db/codeevo",
            normalize_database_url("postgresql://user:pass@db/codeevo"),
        )
        self.assertEqual(
            "postgresql+psycopg://user:pass@db/codeevo",
            normalize_database_url("postgres://user:pass@db/codeevo"),
        )

    @patch("codeevo.postgres_store.create_database_engine")
    def test_postgres_row_factory_is_scoped_to_repository_operations(self, create_engine_mock):
        driver_connection = MagicMock()
        original_row_factory = object()
        driver_connection.row_factory = original_row_factory
        connection = MagicMock(driver_connection=driver_connection)
        engine = MagicMock()
        engine.raw_connection.return_value = connection
        create_engine_mock.return_value = engine

        repository = PostgresTaskStore(
            "postgresql://user:pass@db/codeevo",
            auto_migrate=False,
        )

        create_engine_mock.assert_called_once_with("postgresql://user:pass@db/codeevo")
        with repository._connect():
            self.assertIs(driver_connection.row_factory, repository._row_factory)
        self.assertIs(driver_connection.row_factory, original_row_factory)
        connection.commit.assert_called_once_with()
        connection.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
