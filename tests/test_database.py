from __future__ import annotations

import sqlite3

import pytest

import octogamedb.db.migrations as migration_module
from octogamedb.db import Migration, apply_migrations, connect_database, get_applied_migrations


def test_fresh_initialization_creates_foundation_schema(tmp_path):
    db_path = tmp_path / "nested" / "octogamedb.sqlite3"

    with connect_database(db_path) as connection:
        applied = apply_migrations(connection)

        assert [migration.version for migration in applied] == [1]
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert db_path.exists()
    assert {"schema_migrations", "data_sources", "import_batches"} <= tables


def test_repeat_initialization_is_idempotent(tmp_path):
    db_path = tmp_path / "octogamedb.sqlite3"

    with connect_database(db_path) as connection:
        assert len(apply_migrations(connection)) == 1
        assert apply_migrations(connection) == ()
        assert get_applied_migrations(connection) == ((1, "0001_import_metadata.sql"),)


def test_foreign_keys_are_enforced(tmp_path):
    db_path = tmp_path / "octogamedb.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)

        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO import_batches(source_id, status)
                VALUES (9999, 'running')
                """
            )


def test_source_and_import_batch_constraints(tmp_path):
    db_path = tmp_path / "octogamedb.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        cursor = connection.execute(
            """
            INSERT INTO data_sources(source_key, display_name, source_kind)
            VALUES ('pfquest', 'pfQuest', 'lua')
            """
        )
        source_id = cursor.lastrowid

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO data_sources(source_key, display_name, source_kind)
                VALUES ('pfquest', 'Duplicate', 'lua')
                """
            )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO import_batches(
                    source_id, status, rows_read, rows_accepted, rows_skipped
                )
                VALUES (?, 'running', 1, 1, 1)
                """,
                (source_id,),
            )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO import_batches(source_id, status, finished_at)
                VALUES (?, 'running', '2026-08-24T00:00:00Z')
                """,
                (source_id,),
            )

        connection.execute(
            """
            INSERT INTO import_batches(
                source_id,
                source_revision,
                status,
                importer_version,
                rows_read,
                rows_accepted
            )
            VALUES (?, 'rev-1', 'running', 'test-importer/1', 3, 3)
            """,
            (source_id,),
        )


def test_failed_transaction_is_rolled_back(tmp_path):
    db_path = tmp_path / "octogamedb.sqlite3"

    with pytest.raises(RuntimeError), connect_database(db_path) as connection:
        apply_migrations(connection)
        connection.execute(
            """
            INSERT INTO data_sources(source_key, display_name, source_kind)
            VALUES ('temp', 'Temporary', 'test')
            """
        )
        raise RuntimeError("force rollback")

    with connect_database(db_path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM data_sources WHERE source_key = 'temp'"
            ).fetchone()[0]
            == 0
        )


def test_failed_migration_is_not_recorded(tmp_path, monkeypatch):
    db_path = tmp_path / "failed-migration.sqlite3"
    bad_migration = Migration(
        version=1,
        name="0001_broken.sql",
        sql="CREATE TABLE partial_table(id INTEGER PRIMARY KEY); INVALID SQL;",
    )
    monkeypatch.setattr(migration_module, "discover_migrations", lambda: (bad_migration,))

    with connect_database(db_path) as connection:
        with pytest.raises(sqlite3.OperationalError):
            apply_migrations(connection)

        recorded = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 1"
        ).fetchone()[0]
        partial_table = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'partial_table'"
        ).fetchone()[0]

        assert recorded == 0
        assert partial_table == 0
