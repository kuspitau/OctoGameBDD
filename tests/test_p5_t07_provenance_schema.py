from __future__ import annotations

import json
import sqlite3

from octogamedb.audit_spawn_raw_semantics import (
    _persisted_spawn_set_context,
    _persisted_spawn_set_contexts,
)


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE data_sources (
            id INTEGER PRIMARY KEY,
            source_key TEXT NOT NULL UNIQUE
        );
        CREATE TABLE import_batches (
            id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL,
            source_revision TEXT,
            status TEXT NOT NULL,
            importer_version TEXT,
            rows_read INTEGER NOT NULL DEFAULT 0,
            rows_accepted INTEGER NOT NULL DEFAULT 0,
            rows_skipped INTEGER NOT NULL DEFAULT 0,
            rows_inserted INTEGER NOT NULL DEFAULT 0,
            rows_updated INTEGER NOT NULL DEFAULT 0,
            warning_count INTEGER NOT NULL DEFAULT 0,
            error_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE observation_groups (
            id INTEGER PRIMARY KEY,
            subject_kind TEXT NOT NULL,
            subject_key TEXT NOT NULL,
            fact_key TEXT NOT NULL,
            fact_kind TEXT NOT NULL DEFAULT 'json',
            fact_instance_key TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE source_observations (
            id INTEGER PRIMARY KEY,
            observation_group_id INTEGER NOT NULL,
            source_id INTEGER NOT NULL,
            source_revision TEXT NOT NULL DEFAULT '',
            source_record_type TEXT,
            raw_identifier TEXT,
            value_json TEXT NOT NULL,
            confidence REAL,
            authority_tier INTEGER
        );
        CREATE TABLE observation_import_batches (
            observation_id INTEGER NOT NULL,
            import_batch_id INTEGER NOT NULL,
            PRIMARY KEY (observation_id, import_batch_id)
        );
        CREATE TABLE canonical_selections (
            observation_group_id INTEGER PRIMARY KEY,
            observation_id INTEGER,
            selection_policy TEXT,
            selection_reason TEXT
        );
        """
    )
    return connection


def _insert_spawn_set(
    connection: sqlite3.Connection,
    *,
    observation_id: int,
    group_id: int,
    batch_id: int,
    parent_key: str,
    revision: str,
    spawn_key: str,
    batch_status: str = "succeeded",
) -> None:
    payload = [{"spawn_key": spawn_key, "coordinate_space": "zone_percent", "zone_id": 406}]
    connection.execute(
        """
        INSERT INTO import_batches(id, source_id, source_revision, status, importer_version)
        VALUES (?, 1, ?, ?, 'test')
        """,
        (batch_id, revision, batch_status),
    )
    connection.execute(
        """
        INSERT INTO observation_groups(
            id, subject_kind, subject_key, fact_key, fact_kind, fact_instance_key
        ) VALUES (?, 'creature', ?, 'spawn_set', 'json', '')
        """,
        (group_id, parent_key),
    )
    connection.execute(
        """
        INSERT INTO source_observations(
            id, observation_group_id, source_id, source_revision, value_json
        ) VALUES (?, ?, 1, ?, ?)
        """,
        (observation_id, group_id, revision, json.dumps(payload, separators=(",", ":"))),
    )
    connection.execute(
        """
        INSERT INTO observation_import_batches(observation_id, import_batch_id)
        VALUES (?, ?)
        """,
        (observation_id, batch_id),
    )


def test_bulk_persisted_spawn_contexts_use_provenance_link_once_per_source() -> None:
    connection = _connection()
    revision = "sha256:test-revision"
    connection.execute("INSERT INTO data_sources(id, source_key) VALUES (1, 'pfquest-turtle')")
    _insert_spawn_set(
        connection,
        observation_id=13,
        group_id=11,
        batch_id=7,
        parent_key="123",
        revision=revision,
        spawn_key="zone_percent:406:10:20",
    )
    _insert_spawn_set(
        connection,
        observation_id=23,
        group_id=21,
        batch_id=17,
        parent_key="456",
        revision=revision,
        spawn_key="zone_percent:406:30:40",
    )

    try:
        contexts = _persisted_spawn_set_contexts(
            connection,
            source_key="pfquest-turtle",
            source_revision=revision,
            parents={("creature", "123"), ("creature", "456"), ("creature", "999")},
        )
        single = _persisted_spawn_set_context(
            connection,
            source_key="pfquest-turtle",
            source_revision=revision,
            parent_kind="creature",
            parent_key="123",
        )
    finally:
        connection.close()

    assert set(contexts) == {("creature", "123"), ("creature", "456")}
    assert contexts[("creature", "123")]["member_keys"] == {"zone_percent:406:10:20"}
    assert contexts[("creature", "456")]["member_keys"] == {"zone_percent:406:30:40"}
    assert contexts[("creature", "123")]["import_batches"] == [
        {"batch_id": 7, "status": "succeeded"}
    ]
    assert single is not None
    assert single["member_keys"] == {"zone_percent:406:10:20"}
