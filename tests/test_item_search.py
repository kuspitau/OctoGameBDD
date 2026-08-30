from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from octogamedb.item_query_cli import main as item_query_main
from octogamedb.item_search import (
    COVERAGE_MATERIALIZED,
    COVERAGE_UNKNOWN,
    MATCH_KNOWN,
    MATCH_UNKNOWN,
    NON_MATCH_KNOWN,
    QUERY_STATES,
    STAT_COVERAGE_COMPLETE,
    item_query_page_to_dict,
    query_item_templates,
    query_items,
)


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY);

        CREATE TABLE items (
            item_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );

        CREATE TABLE item_templates (
            item_id INTEGER PRIMARY KEY,
            class_id INTEGER NOT NULL,
            subclass_id INTEGER NOT NULL,
            quality INTEGER NOT NULL,
            inventory_type INTEGER NOT NULL,
            item_level INTEGER NOT NULL,
            required_level INTEGER NOT NULL,
            allowable_class_mask INTEGER NOT NULL,
            allowable_race_mask INTEGER NOT NULL,
            required_skill_id INTEGER NOT NULL,
            required_skill_rank INTEGER NOT NULL,
            required_spell_id INTEGER NOT NULL,
            required_reputation_faction_id INTEGER NOT NULL,
            required_reputation_rank INTEGER NOT NULL,
            armor INTEGER NOT NULL,
            holy_resistance INTEGER NOT NULL,
            fire_resistance INTEGER NOT NULL,
            nature_resistance INTEGER NOT NULL,
            frost_resistance INTEGER NOT NULL,
            shadow_resistance INTEGER NOT NULL,
            arcane_resistance INTEGER NOT NULL,
            max_durability INTEGER NOT NULL
        );

        CREATE TABLE item_stat_modifiers (
            item_id INTEGER NOT NULL,
            slot_index INTEGER NOT NULL,
            stat_type INTEGER NOT NULL,
            stat_value INTEGER NOT NULL,
            PRIMARY KEY (item_id, slot_index)
        );

        CREATE TABLE data_sources (
            id INTEGER PRIMARY KEY,
            source_key TEXT NOT NULL,
            display_name TEXT NOT NULL,
            source_kind TEXT NOT NULL
        );

        CREATE TABLE observation_groups (
            id INTEGER PRIMARY KEY,
            subject_kind TEXT NOT NULL,
            subject_key TEXT NOT NULL,
            fact_key TEXT NOT NULL
        );

        CREATE TABLE source_observations (
            id INTEGER PRIMARY KEY,
            observation_group_id INTEGER NOT NULL,
            source_id INTEGER NOT NULL,
            source_revision TEXT NOT NULL,
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


def _seed(connection: sqlite3.Connection) -> None:
    connection.execute("INSERT INTO schema_migrations(version) VALUES (14)")
    connection.executemany(
        "INSERT INTO items(item_id, name) VALUES (?, ?)",
        (
            (1, "Known Match"),
            (2, "Known Nonmatch"),
            (3, "Unknown Template"),
            (4, "Other Mystery"),
        ),
    )
    connection.executemany(
        """
        INSERT INTO item_templates(
            item_id, class_id, subclass_id, quality, inventory_type,
            item_level, required_level,
            allowable_class_mask, allowable_race_mask,
            required_skill_id, required_skill_rank, required_spell_id,
            required_reputation_faction_id, required_reputation_rank,
            armor, holy_resistance, fire_resistance, nature_resistance,
            frost_resistance, shadow_resistance, arcane_resistance,
            max_durability
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, -1, -1, 0, 0, 0, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (1, 4, 2, 3, 5, 40, 30, 120, 0, 10, 5, 0, 0, 0, 80),
            (2, 4, 2, 2, 5, 45, 35, 60, 0, 0, 0, 0, 0, 0, 40),
        ),
    )
    connection.executemany(
        "INSERT INTO item_stat_modifiers(item_id, slot_index, stat_type, stat_value) "
        "VALUES (?, ?, ?, ?)",
        (
            (1, 0, 3, 12),
            (1, 1, 7, 8),
            (2, 0, 3, 4),
        ),
    )
    connection.execute(
        "INSERT INTO data_sources(id, source_key, display_name, source_kind) "
        "VALUES (1, 'octo-itemcache', 'Octo item cache', 'client-cache')"
    )
    for group_id, fact_key, value in (
        (1, "template.quality", 3),
        (
            2,
            "template.stat_slots",
            [
                {"slot_index": 0, "stat_type": 3, "stat_value": 12},
                {"slot_index": 1, "stat_type": 7, "stat_value": 8},
            ],
        ),
    ):
        connection.execute(
            "INSERT INTO observation_groups(id, subject_kind, subject_key, fact_key) "
            "VALUES (?, 'item', '1', ?)",
            (group_id, fact_key),
        )
        connection.execute(
            """
            INSERT INTO source_observations(
                id, observation_group_id, source_id, source_revision, value_json
            ) VALUES (?, ?, 1, 'sha256:fixture', ?)
            """,
            (group_id, group_id, json.dumps(value, sort_keys=True)),
        )
        connection.execute(
            """
            INSERT INTO canonical_selections(
                observation_group_id, observation_id, selection_policy, selection_reason
            ) VALUES (?, ?, 'p6-item-template/octo-itemcache', 'Fixture selection.')
            """,
            (group_id, group_id),
        )
    connection.commit()


def _memory_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    _create_schema(connection)
    _seed(connection)
    return connection


def _file_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        _create_schema(connection)
        _seed(connection)
    finally:
        connection.close()


def test_query_items_distinguishes_match_nonmatch_and_unknown():
    connection = _memory_connection()
    try:
        page = query_items(
            connection,
            max_required_level=32,
            min_armor=100,
            min_fire_resistance=5,
            min_stats={3: 10},
            include_states=QUERY_STATES,
            sort_by="item_id",
        )
    finally:
        connection.close()

    assert page.summary.total_item_identities == 4
    assert page.summary.materialized_templates == 2
    assert page.summary.unknown_templates == 2
    assert page.summary.known_match_count == 1
    assert page.summary.known_non_match_count == 1
    assert page.summary.unknown_count == 2
    assert [result.match_state for result in page.results] == [
        MATCH_KNOWN,
        NON_MATCH_KNOWN,
        MATCH_UNKNOWN,
        MATCH_UNKNOWN,
    ]

    match, nonmatch, unknown, _ = page.results
    assert match.coverage.template == COVERAGE_MATERIALIZED
    assert match.coverage.stat_slots == STAT_COVERAGE_COMPLETE
    assert match.fire_resistance == 10
    assert match.stats == ((0, 3, 12), (1, 7, 8))
    assert [fact.fact_key for fact in match.trace] == [
        "template.quality",
        "template.stat_slots",
    ]
    assert nonmatch.coverage.template == COVERAGE_MATERIALIZED
    assert unknown.coverage.template == COVERAGE_UNKNOWN
    assert unknown.required_level is None
    assert unknown.stats == ()
    assert unknown.trace == ()


def test_missing_stat_type_is_known_nonmatch_only_for_materialized_template():
    connection = _memory_connection()
    try:
        page = query_items(
            connection,
            min_stats={99: 1},
            include_states=QUERY_STATES,
            sort_by="item_id",
        )
    finally:
        connection.close()

    assert [result.match_state for result in page.results] == [
        NON_MATCH_KNOWN,
        NON_MATCH_KNOWN,
        MATCH_UNKNOWN,
        MATCH_UNKNOWN,
    ]
    assert page.results[0].predicates[0].actual == ()
    assert page.results[2].predicates[0].actual is None


def test_known_false_predicate_dominates_unknown_in_conjunction():
    connection = _memory_connection()
    try:
        page = query_items(
            connection,
            name_contains="known",
            min_armor=1,
            include_states=QUERY_STATES,
            sort_by="item_id",
        )
    finally:
        connection.close()

    states = {result.item_id: result.match_state for result in page.results}
    assert states[1] == MATCH_KNOWN
    assert states[2] == MATCH_KNOWN
    assert states[3] == MATCH_UNKNOWN
    assert states[4] == NON_MATCH_KNOWN


def test_sorting_is_deterministic_and_unknown_values_stay_last():
    connection = _memory_connection()
    try:
        page = query_items(
            connection,
            include_states=(MATCH_KNOWN,),
            sort_by="required_level",
            descending=True,
            limit=3,
        )
    finally:
        connection.close()

    assert [result.item_id for result in page.results] == [2, 1, 3]
    assert page.summary.returned_count == 3


def test_json_contract_exposes_coverage_predicates_stats_and_trace():
    connection = _memory_connection()
    try:
        page = query_items(
            connection,
            item_id=1,
            min_stats={3: 10},
            include_states=(MATCH_KNOWN,),
        )
        payload = item_query_page_to_dict(page)
    finally:
        connection.close()

    result = payload["results"][0]
    assert result["match_state"] == MATCH_KNOWN
    assert result["coverage"] == {
        "template": COVERAGE_MATERIALIZED,
        "stat_slots": STAT_COVERAGE_COMPLETE,
    }
    assert result["template"]["quality"] == 3
    assert result["stats"] == [
        {"slot_index": 0, "stat_type": 3, "stat_value": 12},
        {"slot_index": 1, "stat_type": 7, "stat_value": 8},
    ]
    assert result["predicates"][1]["state"] == MATCH_KNOWN
    assert result["trace"][0]["source_key"] == "octo-itemcache"


def test_p6_query_compatibility_surface_is_preserved():
    connection = _memory_connection()
    try:
        results = query_item_templates(
            connection,
            max_required_level=32,
            inventory_type=5,
            min_stats={3: 10},
        )
    finally:
        connection.close()

    assert [result.item_id for result in results] == [1]
    assert results[0].stats == ((0, 3, 12), (1, 7, 8))
    assert results[0].trace[0].fact_key == "template.quality"


def test_validation_rejects_invalid_ranges_states_and_limits():
    connection = _memory_connection()
    try:
        with pytest.raises(ValueError, match="must not exceed"):
            query_items(connection, min_required_level=40, max_required_level=20)
        with pytest.raises(ValueError, match="unsupported query state"):
            query_items(connection, include_states=("bad",))
        with pytest.raises(TypeError, match="sequence"):
            query_items(connection, include_states=MATCH_KNOWN)
        with pytest.raises(ValueError, match="between 1 and 1000"):
            query_items(connection, limit=0)
    finally:
        connection.close()


def test_cli_json_is_read_only_and_exposes_unknown_coverage(tmp_path, capsys):
    db_path = tmp_path / "items.sqlite3"
    _file_database(db_path)
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    assert (
        item_query_main(
            [
                "--db",
                str(db_path),
                "--quality",
                "3",
                "--include-unknown",
                "--sort-by",
                "item_id",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    after = hashlib.sha256(db_path.read_bytes()).hexdigest()

    assert before == after
    assert payload["summary"]["known_match_count"] == 1
    assert payload["summary"]["known_non_match_count"] == 1
    assert payload["summary"]["unknown_count"] == 2
    assert [result["item_id"] for result in payload["results"]] == [1, 3, 4]
    assert payload["results"][1]["coverage"]["template"] == COVERAGE_UNKNOWN

def test_level2_validator_core_is_read_only_on_synthetic_database(tmp_path):
    db_path = tmp_path / "canonical.sqlite3"
    _file_database(db_path)
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    validator_path = Path(__file__).parents[1] / "scripts" / "validate_p7_t01.py"
    spec = importlib.util.spec_from_file_location("validate_p7_t01", validator_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    result = module.validate(db_path, expected_sha256=before)

    after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert result["schema_version"] == 14
    assert result["item_identities"] == 4
    assert result["materialized_templates"] == 2
    assert result["unknown_templates"] == 2
    assert result["canonical_db_unchanged"] is True
    assert before == after

