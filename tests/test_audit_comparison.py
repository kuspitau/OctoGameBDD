from __future__ import annotations

import hashlib
import json

import pytest

from octogamedb.audit_comparison import comparison_report
from octogamedb.audit_comparison import main as comparison_main
from octogamedb.db import (
    apply_migrations,
    connect_database,
    record_scalar_observation,
    select_canonical_observation,
)


def _spawn(spawn_key: str, x: float) -> dict[str, object]:
    return {
        "spawn_key": spawn_key,
        "coordinate_space": "zone_percent",
        "zone_id": 1,
        "x": x,
        "y": 20.0,
        "respawn_seconds": None,
    }


@pytest.fixture
def p1_comparison_case(tmp_path):
    db_path = tmp_path / "p1-comparison.sqlite3"
    spawn_a = "creature:1:zone_percent:1:10.000000:20.000000"
    spawn_b = "creature:1:zone_percent:1:11.000000:20.000000"
    spawn_c = "creature:1:zone_percent:1:12.000000:20.000000"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        active_source = int(
            connection.execute(
                """
                INSERT INTO data_sources(source_key, display_name, source_kind)
                VALUES ('active-source', 'Active source', 'fixture')
                """
            ).lastrowid
        )
        comparison_source = int(
            connection.execute(
                """
                INSERT INTO data_sources(source_key, display_name, source_kind)
                VALUES ('pfquest-octo', 'pfQuest Octo', 'fixture')
                """
            ).lastrowid
        )
        active_batch = int(
            connection.execute(
                """
                INSERT INTO import_batches(
                    source_id, source_revision, status, finished_at,
                    rows_read, rows_accepted, rows_inserted
                )
                VALUES (?, 'active-r1', 'succeeded', '2026-08-27T00:00:00Z', 20, 20, 20)
                """,
                (active_source,),
            ).lastrowid
        )
        comparison_batch = int(
            connection.execute(
                """
                INSERT INTO import_batches(
                    source_id, source_revision, status, finished_at,
                    rows_read, rows_accepted, rows_inserted
                )
                VALUES (?, 'octo-r1', 'succeeded', '2026-08-27T00:00:00Z', 8, 8, 8)
                """,
                (comparison_source,),
            ).lastrowid
        )

        def record(
            subject_kind: str,
            subject_key: str | int,
            fact_key: str,
            value: object,
            *,
            comparison: bool = False,
            select: bool = False,
        ) -> int:
            observation_id = record_scalar_observation(
                connection,
                subject_kind=subject_kind,
                subject_key=subject_key,
                fact_key=fact_key,
                import_batch_id=comparison_batch if comparison else active_batch,
                value=value,
                source_record_type="fixture",
                raw_identifier=subject_key,
            )
            if select:
                group_id = int(
                    connection.execute(
                        "SELECT observation_group_id FROM source_observations WHERE id = ?",
                        (observation_id,),
                    ).fetchone()[0]
                )
                select_canonical_observation(
                    connection,
                    observation_group_id=group_id,
                    observation_id=observation_id,
                    selection_policy="fixture-active/v1",
                    selection_reason="Fixture active-side selection.",
                )
            return observation_id

        record("creature", 1, "world_presence", True, select=True)
        record("creature", 1, "world_presence", True, comparison=True)
        record("creature", 1, "faction", 10, select=True)
        record("creature", 1, "faction", 20, comparison=True)
        record("creature", 1, "name", "Active Name", select=True)
        record(
            "creature",
            1,
            "spawn_set",
            [_spawn(spawn_a, 10.0), _spawn(spawn_b, 11.0)],
            select=True,
        )
        record(
            "creature",
            1,
            "spawn_set",
            [_spawn(spawn_a, 10.0), _spawn(spawn_c, 12.0)],
            comparison=True,
        )
        record(
            "creature_spawn",
            spawn_a,
            "position",
            {"coordinate_space": "zone_percent", "zone_id": 1, "x": 10.0, "y": 20.0},
            select=True,
        )
        record(
            "creature_spawn",
            spawn_a,
            "position",
            {"coordinate_space": "zone_percent", "zone_id": 1, "x": 10.0, "y": 20.0},
            comparison=True,
        )
        record("creature_spawn", spawn_a, "respawn_seconds", 60, select=True)
        record("creature_spawn", spawn_a, "respawn_seconds", 90, comparison=True)
        record(
            "creature_spawn",
            spawn_b,
            "position",
            {"coordinate_space": "zone_percent", "zone_id": 1, "x": 11.0, "y": 20.0},
            select=True,
        )
        record("creature_spawn", spawn_b, "respawn_seconds", 60, select=True)
        record(
            "creature_spawn",
            spawn_c,
            "position",
            {"coordinate_space": "zone_percent", "zone_id": 1, "x": 12.0, "y": 20.0},
            comparison=True,
        )
        record("creature_spawn", spawn_c, "respawn_seconds", 60, comparison=True)
        record("creature", 2, "world_presence", True, comparison=True)
        record("creature", 3, "world_presence", True, select=True)
        record("creature", 3, "name", "Active-only creature", select=True)
        record("creature", 3, "world_presence", False, comparison=True)
        record("creature", 4, "world_presence", False, select=True)
        record("creature", 4, "name", "Historical active name", select=True)
        record("creature", 4, "world_presence", True, comparison=True)
        record("creature", 4, "name", "Comparison name", comparison=True)

    return {"db_path": db_path, "spawn_a": spawn_a, "spawn_b": spawn_b, "spawn_c": spawn_c}


def test_comparison_report_distinguishes_all_required_states(p1_comparison_case):
    with connect_database(p1_comparison_case["db_path"]) as connection:
        report = comparison_report(connection, source_key="pfquest-octo", limit=100)

    assert report["scope"] == "p1-world-selected-vs-comparison-source"
    assert report["comparison_source"]["source_revision"] == "octo-r1"
    assert report["comparison_source"]["group_count"] == 11
    assert report["comparison_source"]["observation_count"] == 11
    assert report["comparison_source"]["unselected_group_count"] == 3
    assert report["state_counts"] == {
        "comparison_only": 4,
        "active_only": 3,
        "same_value": 2,
        "different_value": 5,
        "not_directly_comparable": 1,
    }
    assert report["record_count"] == 15
    assert report["returned_record_count"] == 15

    presence_pattern = report["template_presence_patterns"][0]
    assert presence_pattern == {
        "template_kind": "creature",
        "parent_count": 4,
        "directly_comparable_parent_count": 3,
        "shared_subject_count": 1,
        "comparison_only_subject_count": 1,
        "active_only_subject_count": 1,
        "absent_both_subject_count": 0,
        "unknown_subject_count": 1,
    }

    spawn_pattern = report["spawn_membership_patterns"][0]
    assert spawn_pattern == {
        "template_kind": "creature",
        "parent_count": 1,
        "active_member_count": 2,
        "comparison_member_count": 2,
        "shared_member_count": 1,
        "comparison_only_member_count": 1,
        "active_only_member_count": 1,
    }


def test_comparison_report_uses_complete_sets_for_spawn_only_states(p1_comparison_case):
    with connect_database(p1_comparison_case["db_path"]) as connection:
        active_only = comparison_report(
            connection,
            source_key="pfquest-octo",
            subject_kind="creature_spawn",
            state="active_only",
            limit=10,
        )
        comparison_only = comparison_report(
            connection,
            source_key="pfquest-octo",
            subject_kind="creature_spawn",
            state="comparison_only",
            limit=10,
        )

    assert active_only["record_count"] == 2
    assert {record["subject_key"] for record in active_only["records"]} == {
        p1_comparison_case["spawn_b"]
    }
    assert all(
        record["complete_set_context"]["membership_state"] == "active_only"
        for record in active_only["records"]
    )
    assert comparison_only["record_count"] == 2
    assert {record["subject_key"] for record in comparison_only["records"]} == {
        p1_comparison_case["spawn_c"]
    }
    assert all(
        record["complete_set_context"]["membership_state"] == "comparison_only"
        for record in comparison_only["records"]
    )

    with connect_database(p1_comparison_case["db_path"]) as connection:
        template_active_only = comparison_report(
            connection,
            source_key="pfquest-octo",
            subject_kind="creature",
            subject_key=3,
            state="active_only",
            limit=10,
        )
    assert template_active_only["record_count"] == 1
    assert template_active_only["records"][0]["fact_key"] == "name"
    assert template_active_only["records"][0]["world_presence_context"]["membership_state"] == (
        "active_only"
    )

    with connect_database(p1_comparison_case["db_path"]) as connection:
        stale_scalar = comparison_report(
            connection,
            source_key="pfquest-octo",
            subject_kind="creature",
            subject_key=4,
            fact_key="name",
            limit=10,
        )
    assert stale_scalar["record_count"] == 1
    assert stale_scalar["records"][0]["state"] == "comparison_only"
    assert stale_scalar["records"][0]["active"]["value"] == "Historical active name"
    assert stale_scalar["records"][0]["world_presence_context"]["membership_state"] == (
        "comparison_only"
    )


def test_comparison_report_filters_and_summary_are_deterministic(p1_comparison_case):
    with connect_database(p1_comparison_case["db_path"]) as connection:
        first = comparison_report(connection, source_key="pfquest-octo", limit=0)
        second = comparison_report(connection, source_key="pfquest-octo", limit=0)
        fact = comparison_report(
            connection,
            source_key="pfquest-octo",
            subject_kind="creature",
            subject_key=1,
            fact_key="faction",
            state="different_value",
            limit=5,
        )
        with pytest.raises(ValueError, match="limit must be non-negative"):
            comparison_report(connection, source_key="pfquest-octo", limit=-1)
        with pytest.raises(ValueError, match="bounded to source pfquest-octo"):
            comparison_report(connection, source_key="active-source", limit=0)

    assert first == second
    assert first["returned_record_count"] == 0
    assert first["records"] == []
    assert first["details_truncated"] is True
    assert fact["record_count"] == 1
    assert fact["records"][0]["active"]["value"] == 10
    assert fact["records"][0]["comparison"]["observations"][0]["value"] == 20


def test_comparison_cli_is_read_only_and_machine_readable(p1_comparison_case, capsys):
    db_path = p1_comparison_case["db_path"]
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    assert (
        comparison_main(
            [
                "pfquest-octo",
                "--state",
                "active_only",
                "--limit",
                "0",
                "--db",
                str(db_path),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    after = hashlib.sha256(db_path.read_bytes()).hexdigest()

    assert payload["state_counts"]["active_only"] == 3
    assert payload["returned_record_count"] == 0
    assert before == after
