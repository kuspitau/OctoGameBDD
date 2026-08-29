from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from octogamedb.db import record_scalar_observation, select_canonical_observation
from octogamedb.importers.octo_itemcache import (
    ItemCacheParseError,
    compute_itemcache_slice_revision,
    import_octo_itemcache_slice,
    parse_itemcache_wdb,
)

FIXTURE = Path(__file__).parent / "fixtures" / "p6_t01" / "itemcache.wdb"
MIGRATION = (
    Path(__file__).parents[1]
    / "src"
    / "octogamedb"
    / "db"
    / "migrations"
    / "0014_item_template_facts.sql"
)

BASE_SCHEMA = """
CREATE TABLE data_sources (
 id INTEGER PRIMARY KEY, source_key TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
 source_kind TEXT NOT NULL, source_url TEXT, source_path TEXT, updated_at TEXT DEFAULT '', created_at TEXT DEFAULT ''
);
CREATE TABLE import_batches (
 id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES data_sources(id), source_revision TEXT,
 started_at TEXT DEFAULT '', finished_at TEXT, status TEXT NOT NULL, importer_version TEXT,
 rows_read INTEGER NOT NULL DEFAULT 0, rows_accepted INTEGER NOT NULL DEFAULT 0,
 rows_skipped INTEGER NOT NULL DEFAULT 0, rows_inserted INTEGER NOT NULL DEFAULT 0,
 rows_updated INTEGER NOT NULL DEFAULT 0, warning_count INTEGER NOT NULL DEFAULT 0,
 error_count INTEGER NOT NULL DEFAULT 0, details_json TEXT
);
CREATE TABLE observation_groups (
 id INTEGER PRIMARY KEY, subject_kind TEXT NOT NULL, subject_key TEXT NOT NULL, fact_key TEXT NOT NULL,
 fact_kind TEXT NOT NULL, fact_instance_key TEXT NOT NULL DEFAULT '', UNIQUE(subject_kind,subject_key,fact_key,fact_instance_key)
);
CREATE TABLE source_observations (
 id INTEGER PRIMARY KEY, observation_group_id INTEGER NOT NULL REFERENCES observation_groups(id),
 source_id INTEGER NOT NULL REFERENCES data_sources(id), source_revision TEXT NOT NULL DEFAULT '',
 source_record_type TEXT, raw_identifier TEXT, value_json TEXT NOT NULL, confidence REAL, authority_tier INTEGER
);
CREATE UNIQUE INDEX uq_source_observations_identity ON source_observations(
 observation_group_id,source_id,source_revision,COALESCE(source_record_type,''),COALESCE(raw_identifier,''),value_json
);
CREATE TABLE observation_import_batches (
 observation_id INTEGER NOT NULL REFERENCES source_observations(id), import_batch_id INTEGER NOT NULL REFERENCES import_batches(id),
 PRIMARY KEY(observation_id, import_batch_id)
);
CREATE TABLE canonical_selections (
 observation_group_id INTEGER PRIMARY KEY REFERENCES observation_groups(id), observation_id INTEGER NOT NULL,
 selection_policy TEXT, selection_reason TEXT NOT NULL,
 selected_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TABLE items (item_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
"""


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(BASE_SCHEMA)
    connection.executescript(MIGRATION.read_text(encoding="utf-8"))
    connection.executemany(
        "INSERT INTO items(item_id, name) VALUES (?, ?)",
        [(1001, "Fixture Sword"), (1002, "Fixture Chest")],
    )
    return connection


def add_fallback_observation(
    connection: sqlite3.Connection, *, item_id: int, field: str, value: int, policy: str
) -> None:
    connection.execute(
        "INSERT INTO data_sources(source_key,display_name,source_kind) VALUES ('tortoise-world-sql','Tortoise','sql')"
        " ON CONFLICT(source_key) DO NOTHING"
    )
    source_id = int(connection.execute("SELECT id FROM data_sources WHERE source_key='tortoise-world-sql'").fetchone()[0])
    cursor = connection.execute(
        "INSERT INTO import_batches(source_id,source_revision,status,finished_at) VALUES (?, 'fixture', 'succeeded', 'fixture')",
        (source_id,),
    )
    observation_id = record_scalar_observation(
        connection,
        subject_kind="item",
        subject_key=item_id,
        fact_key=f"template.{field}",
        import_batch_id=int(cursor.lastrowid),
        value=value,
        source_record_type="item_template",
        raw_identifier=str(item_id),
        authority_tier=20,
    )
    group_id = int(connection.execute("SELECT observation_group_id FROM source_observations WHERE id=?", (observation_id,)).fetchone()[0])
    select_canonical_observation(
        connection,
        observation_group_id=group_id,
        observation_id=observation_id,
        selection_policy=policy,
        selection_reason="fixture fallback",
    )


def test_parse_vanilla_itemcache_fields_and_stats():
    snapshot = parse_itemcache_wdb(FIXTURE)
    assert snapshot.header.signature == "BDIW"
    assert snapshot.header.client_version == 5875
    assert snapshot.header.locale == "enUS"
    assert [record.item_id for record in snapshot.records] == [1001, 1002, 900001]

    sword = snapshot.by_id[1001]
    assert sword.name == "Fixture Sword"
    assert (sword.class_id, sword.subclass_id, sword.quality) == (2, 7, 2)
    assert sword.item_level == 25
    assert sword.required_level == 20
    assert sword.allowable_class_mask == -1
    assert sword.max_durability == 65
    assert [(slot.stat_type, slot.stat_value) for slot in sword.stat_slots[:3]] == [
        (3, 5),
        (4, 7),
        (0, 0),
    ]


def test_slice_revision_ignores_unselected_records():
    snapshot = parse_itemcache_wdb(FIXTURE)
    first = compute_itemcache_slice_revision(snapshot, [1001])
    assert first == compute_itemcache_slice_revision(snapshot, [1001, 1001])
    assert first != compute_itemcache_slice_revision(snapshot, [1001, 1002])


def test_import_is_bounded_provenance_aware_and_idempotent():
    connection = connect()
    add_fallback_observation(
        connection,
        item_id=1001,
        field="item_level",
        value=99,
        policy="p6-item-template/tortoise-fallback",
    )
    add_fallback_observation(
        connection,
        item_id=1002,
        field="quality",
        value=7,
        policy="manual-review",
    )

    first = import_octo_itemcache_slice(
        connection,
        source_path=FIXTURE,
        item_ids=[1001, 1002, 900001, 999999],
    )
    assert first.rows_read == 4
    assert first.rows_accepted == 3
    assert first.rows_skipped == 1
    assert first.warning_count == 2
    assert first.details["missing_cache_item_ids"] == [999999]
    assert first.details["unresolved_canonical_item_ids"] == [900001]

    sword = connection.execute("SELECT * FROM item_templates WHERE item_id=1001").fetchone()
    chest = connection.execute("SELECT * FROM item_templates WHERE item_id=1002").fetchone()
    assert sword["item_level"] == 25  # direct Octo observation supersedes managed fallback
    assert chest["quality"] == 7      # explicit/custom selection remains protected
    assert connection.execute("SELECT 1 FROM items WHERE item_id=900001").fetchone() is None

    stat_rows = connection.execute(
        "SELECT slot_index,stat_type,stat_value FROM item_stat_modifiers WHERE item_id=1001 ORDER BY slot_index"
    ).fetchall()
    assert [tuple(row) for row in stat_rows] == [(0, 3, 5), (1, 4, 7)]

    conflict = connection.execute(
        """
        SELECT COUNT(*)
        FROM source_observations AS so
        JOIN observation_groups AS og ON og.id=so.observation_group_id
        WHERE og.subject_kind='item' AND og.subject_key='1001' AND og.fact_key='template.item_level'
        """
    ).fetchone()[0]
    assert conflict == 2

    domain_before = tuple(connection.execute("SELECT * FROM item_templates ORDER BY item_id").fetchall())
    observation_count_before = connection.execute("SELECT COUNT(*) FROM source_observations").fetchone()[0]
    second = import_octo_itemcache_slice(
        connection,
        source_path=FIXTURE,
        item_ids=[1001, 1002, 900001, 999999],
    )
    assert (second.rows_inserted, second.rows_updated) == (0, 0)
    assert tuple(connection.execute("SELECT * FROM item_templates ORDER BY item_id").fetchall()) == domain_before
    assert connection.execute("SELECT COUNT(*) FROM source_observations").fetchone()[0] == observation_count_before


def test_cache_absence_does_not_delete_existing_materialization():
    connection = connect()
    import_octo_itemcache_slice(connection, source_path=FIXTURE, item_ids=[1001])
    before = dict(connection.execute("SELECT * FROM item_templates WHERE item_id=1001").fetchone())
    result = import_octo_itemcache_slice(connection, source_path=FIXTURE, item_ids=[999999])
    assert result.rows_accepted == 0
    assert dict(connection.execute("SELECT * FROM item_templates WHERE item_id=1001").fetchone()) == before


def test_parser_fails_closed_on_unknown_trailing_shape(tmp_path: Path):
    broken = tmp_path / "itemcache.wdb"
    data = FIXTURE.read_bytes()
    # Extend the first record payload by one byte while keeping all later bytes aligned.
    first_length = int.from_bytes(data[24:28], "little")
    modified = bytearray(data)
    modified[24:28] = (first_length + 1).to_bytes(4, "little")
    insert_at = 28 + first_length
    modified[insert_at:insert_at] = b"X"
    broken.write_bytes(modified)
    with pytest.raises(ItemCacheParseError, match="unsupported layout"):
        parse_itemcache_wdb(broken)


def test_bounded_query_filters_stats_and_exposes_selection_trace():
    from octogamedb.item_search import query_item_templates

    connection = connect()
    import_octo_itemcache_slice(connection, source_path=FIXTURE, item_ids=[1001, 1002])
    results = query_item_templates(
        connection,
        max_required_level=30,
        inventory_type=13,
        min_stats={3: 5, 4: 7},
    )
    assert [result.item_id for result in results] == [1001]
    assert results[0].stats == ((0, 3, 5), (1, 4, 7))
    trace = {fact.fact_key: fact for fact in results[0].trace}
    assert trace["template.item_level"].value == 25
    assert trace["template.item_level"].source_key == "octo-itemcache"
    assert trace["template.item_level"].selection_policy == "p6-item-template/octo-itemcache"
