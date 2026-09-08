from __future__ import annotations

import json
import sqlite3

from octogamedb.world_entity_search import (
    _selected_quest_relation_index,
    _selected_quest_role_rows,
)


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE data_sources (
            id INTEGER PRIMARY KEY,
            source_key TEXT NOT NULL
        );
        CREATE TABLE observation_groups (
            id INTEGER PRIMARY KEY,
            subject_kind TEXT NOT NULL,
            subject_key TEXT NOT NULL,
            fact_key TEXT NOT NULL,
            fact_instance_key TEXT NOT NULL
        );
        CREATE TABLE source_observations (
            id INTEGER PRIMARY KEY,
            observation_group_id INTEGER NOT NULL,
            source_id INTEGER NOT NULL,
            source_revision TEXT NOT NULL,
            source_record_type TEXT,
            raw_identifier TEXT,
            authority_tier INTEGER,
            value_json TEXT NOT NULL
        );
        CREATE TABLE canonical_selections (
            observation_group_id INTEGER PRIMARY KEY,
            observation_id INTEGER NOT NULL,
            selection_policy TEXT,
            selection_reason TEXT NOT NULL
        );
        """
    )
    connection.execute("INSERT INTO data_sources(id, source_key) VALUES (1, 'fixture')")
    return connection


def _selected_relation(
    connection: sqlite3.Connection,
    *,
    group_id: int,
    quest_id: int,
    fact_key: str,
    instance_key: str,
    value: dict[str, object],
) -> None:
    connection.execute(
        """
        INSERT INTO observation_groups(
            id, subject_kind, subject_key, fact_key, fact_instance_key
        ) VALUES (?, 'quest', ?, ?, ?)
        """,
        (group_id, str(quest_id), fact_key, instance_key),
    )
    connection.execute(
        """
        INSERT INTO source_observations(
            id, observation_group_id, source_id, source_revision,
            source_record_type, raw_identifier, authority_tier, value_json
        ) VALUES (?, ?, 1, 'fixture-r1', 'quest', ?, 100, ?)
        """,
        (group_id, group_id, f"quest:{quest_id}", json.dumps(value, sort_keys=True)),
    )
    connection.execute(
        """
        INSERT INTO canonical_selections(
            observation_group_id, observation_id, selection_policy, selection_reason
        ) VALUES (?, ?, 'fixture-policy', 'fixture selected relation')
        """,
        (group_id, group_id),
    )


def _seed(connection: sqlite3.Connection) -> None:
    _selected_relation(
        connection,
        group_id=1,
        quest_id=100,
        fact_key="endpoint",
        instance_key="giver:creature:10",
        value={
            "target": {"kind": "creature", "key": "10"},
            "attributes": {"endpoint_kind": "giver"},
        },
    )
    _selected_relation(
        connection,
        group_id=2,
        quest_id=101,
        fact_key="endpoint",
        instance_key="finisher:creature:10",
        value={
            "target": {"kind": "creature", "key": "10"},
            "attributes": {"endpoint_kind": "finisher"},
        },
    )
    _selected_relation(
        connection,
        group_id=3,
        quest_id=102,
        fact_key="objective_creature",
        instance_key="10",
        value={"target": {"kind": "creature", "key": "10"}, "attributes": {}},
    )
    _selected_relation(
        connection,
        group_id=4,
        quest_id=103,
        fact_key="endpoint",
        instance_key="giver:creature:11",
        value={
            "target": {"kind": "creature", "key": "11"},
            "attributes": {"endpoint_kind": "giver"},
        },
    )
    _selected_relation(
        connection,
        group_id=5,
        quest_id=104,
        fact_key="objective_gameobject",
        instance_key="10",
        value={"target": {"kind": "gameobject", "key": "10"}, "attributes": {}},
    )
    connection.commit()


def test_batched_selected_quest_roles_equal_legacy_lookup() -> None:
    connection = _connection()
    _seed(connection)

    legacy = _selected_quest_role_rows(connection, entity_kind="creature", entity_id=10)
    index = _selected_quest_relation_index(connection)
    batched = _selected_quest_role_rows(
        connection,
        entity_kind="creature",
        entity_id=10,
        selected_relation_index=index,
    )

    assert batched == legacy
    assert [(row["quest_id"], row["role"]) for row in batched] == [
        (100, "giver"),
        (101, "finisher"),
        (102, "objective"),
    ]


def test_batched_role_lookup_performs_no_per_entity_relation_sql() -> None:
    connection = _connection()
    _seed(connection)
    index = _selected_quest_relation_index(connection)
    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    try:
        result = _selected_quest_role_rows(
            connection,
            entity_kind="gameobject",
            entity_id=10,
            selected_relation_index=index,
        )
    finally:
        connection.set_trace_callback(None)

    assert [(row["quest_id"], row["role"]) for row in result] == [(104, "objective")]
    assert statements == []
