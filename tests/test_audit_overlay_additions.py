from __future__ import annotations

import hashlib
import json

import pytest

from octogamedb.audit_overlay_additions import main as overlay_additions_main
from octogamedb.audit_overlay_additions import overlay_addition_report
from octogamedb.db import (
    apply_migrations,
    connect_database,
    record_scalar_observation,
    select_canonical_observation,
)


def _spawn(
    kind: str,
    parent_id: int,
    *,
    zone_id: int,
    x: float,
    y: float,
) -> dict[str, object]:
    spawn_key = f"{kind}:{parent_id}:zone_percent:{zone_id}:{x:.6f}:{y:.6f}"
    return {
        "spawn_key": spawn_key,
        "coordinate_space": "zone_percent",
        "zone_id": zone_id,
        "x": x,
        "y": y,
        "respawn_seconds": None,
    }


@pytest.fixture
def overlay_addition_case(tmp_path):
    db_path = tmp_path / "p5-t06.sqlite3"
    with connect_database(db_path) as connection:
        apply_migrations(connection)
        connection.execute("INSERT INTO maps(map_id, name) VALUES (1, 'Azeroth')")
        for zone_id, name in ((1, "Active Zone"), (2, "Comparison Zone"), (3, "Shared Zone")):
            connection.execute(
                "INSERT INTO zones(zone_id, map_id, name) VALUES (?, 1, ?)",
                (zone_id, name),
            )

        source_ids: dict[str, int] = {}
        batch_ids: dict[str, int] = {}
        revisions = {
            "pfquest": "base-r1",
            "pfquest-turtle": "turtle-r1",
            "pfquest-octo": "octo-r1",
        }
        for source_key, revision in revisions.items():
            source_ids[source_key] = int(
                connection.execute(
                    """
                    INSERT INTO data_sources(source_key, display_name, source_kind)
                    VALUES (?, ?, 'fixture')
                    """,
                    (source_key, source_key),
                ).lastrowid
            )
            batch_ids[source_key] = int(
                connection.execute(
                    """
                    INSERT INTO import_batches(
                        source_id, source_revision, status, importer_version, finished_at,
                        rows_read, rows_accepted, rows_inserted
                    )
                    VALUES (?, ?, 'succeeded', ?, '2026-08-28T00:00:00Z', 100, 100, 100)
                    """,
                    (
                        source_ids[source_key],
                        revision,
                        (
                            "pfquest-overlay-reconcile/1-base-evidence"
                            if source_key == "pfquest"
                            else "fixture-overlay"
                        ),
                    ),
                ).lastrowid
            )

        def record_set(
            kind: str,
            parent_id: int,
            value: list[dict[str, object]],
            *,
            source_key: str,
            select: bool = False,
        ) -> None:
            if source_key == "pfquest":
                record_scalar_observation(
                    connection,
                    subject_kind=kind,
                    subject_key=parent_id,
                    fact_key="world_presence",
                    import_batch_id=batch_ids[source_key],
                    value=True,
                    source_record_type="fixture-world-presence",
                    raw_identifier=str(parent_id),
                )
            observation_id = record_scalar_observation(
                connection,
                subject_kind=kind,
                subject_key=parent_id,
                fact_key="spawn_set",
                import_batch_id=batch_ids[source_key],
                value=value,
                source_record_type="fixture-spawn-set",
                raw_identifier=str(parent_id),
            )
            if not select:
                return
            group_id = int(
                connection.execute(
                    "SELECT observation_group_id FROM source_observations WHERE id = ?",
                    (observation_id,),
                ).fetchone()[0]
            )
            selection_policy = (
                "pfquest-base-effective-world"
                if source_key == "pfquest"
                else "pfquest-turtle-effective-world"
            )
            select_canonical_observation(
                connection,
                observation_group_id=group_id,
                observation_id=observation_id,
                selection_policy=selection_policy,
                selection_reason="P5-T06 fixture active selection.",
            )
            for spawn in value:
                spawn_key = str(spawn["spawn_key"])
                position_id = record_scalar_observation(
                    connection,
                    subject_kind=f"{kind}_spawn",
                    subject_key=spawn_key,
                    fact_key="position",
                    import_batch_id=batch_ids[source_key],
                    value={
                        "coordinate_space": spawn["coordinate_space"],
                        "zone_id": spawn["zone_id"],
                        "x": spawn["x"],
                        "y": spawn["y"],
                    },
                    source_record_type="fixture-position",
                    raw_identifier=spawn_key,
                )
                position_group_id = int(
                    connection.execute(
                        "SELECT observation_group_id FROM source_observations WHERE id = ?",
                        (position_id,),
                    ).fetchone()[0]
                )
                select_canonical_observation(
                    connection,
                    observation_group_id=position_group_id,
                    observation_id=position_id,
                    selection_policy=selection_policy,
                    selection_reason="P5-T06 fixture active position selection.",
                )

        # Parent absent from base: active-side whole-content addition in zone 1.
        c100 = _spawn("creature", 100, zone_id=1, x=10.0, y=10.0)
        record_set("creature", 100, [c100], source_key="pfquest-turtle", select=True)
        record_set("creature", 100, [], source_key="pfquest-octo")

        # Parent absent from base: comparison-side whole-content addition in zone 2.
        c101 = _spawn("creature", 101, zone_id=2, x=11.0, y=11.0)
        record_set("creature", 101, [], source_key="pfquest-turtle", select=True)
        record_set("creature", 101, [c101], source_key="pfquest-octo")

        # Base-present parent: active adds one extra spawn in zone 1.
        c102_base = _spawn("creature", 102, zone_id=1, x=12.0, y=12.0)
        c102_add = _spawn("creature", 102, zone_id=1, x=12.5, y=12.5)
        record_set("creature", 102, [c102_base], source_key="pfquest")
        record_set(
            "creature",
            102,
            [c102_base, c102_add],
            source_key="pfquest-turtle",
            select=True,
        )
        record_set("creature", 102, [c102_base], source_key="pfquest-octo")

        # Base-present GameObject parent: comparison adds one extra spawn in zone 2.
        g200_base = _spawn("gameobject", 200, zone_id=2, x=20.0, y=20.0)
        g200_add = _spawn("gameobject", 200, zone_id=2, x=20.5, y=20.5)
        record_set("gameobject", 200, [g200_base], source_key="pfquest")
        record_set("gameobject", 200, [g200_base], source_key="pfquest-turtle", select=True)
        record_set("gameobject", 200, [g200_base, g200_add], source_key="pfquest-octo")

        # Both overlays add distinct members under the same base-present parent and zone.
        c103_base = _spawn("creature", 103, zone_id=3, x=30.0, y=30.0)
        c103_active = _spawn("creature", 103, zone_id=3, x=30.5, y=30.0)
        c103_comparison = _spawn("creature", 103, zone_id=3, x=29.5, y=30.0)
        record_set("creature", 103, [c103_base], source_key="pfquest")
        record_set(
            "creature",
            103,
            [c103_base, c103_active],
            source_key="pfquest-turtle",
            select=True,
        )
        record_set(
            "creature",
            103,
            [c103_base, c103_comparison],
            source_key="pfquest-octo",
        )

    return {
        "db_path": db_path,
        "source_ids": source_ids,
        "c100": c100["spawn_key"],
        "c101": c101["spawn_key"],
        "c102_add": c102_add["spawn_key"],
        "g200_add": g200_add["spawn_key"],
        "c103_active": c103_active["spawn_key"],
        "c103_comparison": c103_comparison["spawn_key"],
    }


def _report(case, **kwargs):
    with connect_database(case["db_path"]) as connection:
        return overlay_addition_report(
            connection,
            base_source_revision="base-r1",
            comparison_source_revision="octo-r1",
            **kwargs,
        )


def test_overlay_additions_classify_both_base_parent_modes_and_reconcile(overlay_addition_case):
    report = _report(overlay_addition_case, limit=100, top=20)

    assert report["scope"] == "p5-t06-overlay-addition-coverage"
    assert report["included_member_count"] == 6
    assert report["pattern_counts"] == {
        "active_only_vs_base": 3,
        "comparison_only_vs_base": 3,
    }
    assert report["addition_parent_class_counts"] == {
        "parent_absent_from_base": 2,
        "spawn_added_to_base_present_parent": 4,
    }
    assert sum(report["pattern_counts"].values()) == 6
    assert sum(report["addition_parent_class_counts"].values()) == 6

    members = {row["spawn_key"]: row for row in report["members"]}
    assert members[overlay_addition_case["c100"]]["addition_parent_class"] == (
        "parent_absent_from_base"
    )
    assert members[overlay_addition_case["c101"]]["addition_parent_class"] == (
        "parent_absent_from_base"
    )
    assert members[overlay_addition_case["c102_add"]]["addition_parent_class"] == (
        "spawn_added_to_base_present_parent"
    )
    assert members[overlay_addition_case["g200_add"]]["addition_parent_class"] == (
        "spawn_added_to_base_present_parent"
    )
    assert members[overlay_addition_case["g200_add"]]["subject_kind"] == "gameobject_spawn"
    assert all(row["base_contains"] is False for row in members.values())
    assert all(row["base_import_batches"] for row in members.values())
    assert all(row["comparison_import_batches"] for row in members.values())
    assert all("coordinates" in row for row in members.values())


def test_overlay_additions_measure_parent_and_zone_overlap_without_spawn_merge(
    overlay_addition_case,
):
    report = _report(overlay_addition_case, limit=100, top=20)

    parent_coverage = {
        row["overlay_coverage"]: (row["group_count"], row["member_count"])
        for row in report["parent_overlay_coverage_counts"]
    }
    assert parent_coverage == {
        "active_only": (2, 2),
        "comparison_only": (2, 2),
        "both": (1, 2),
    }

    zone_coverage = {
        row["overlay_coverage"]: (row["group_count"], row["member_count"])
        for row in report["zone_map_overlay_coverage_counts"]
    }
    assert zone_coverage == {
        "active_only": (1, 2),
        "comparison_only": (1, 2),
        "both": (1, 2),
    }

    both_parent = next(
        row for row in report["parent_template_counts"] if row["parent_subject_key"] == "103"
    )
    assert both_parent["overlay_coverage"] == "both"
    assert both_parent["active_addition_count"] == 1
    assert both_parent["comparison_addition_count"] == 1

    both_members = _report(overlay_addition_case, overlay_coverage="both", limit=100)["members"]
    assert {row["spawn_key"] for row in both_members} == {
        overlay_addition_case["c103_active"],
        overlay_addition_case["c103_comparison"],
    }
    zone_active = _report(
        overlay_addition_case,
        overlay_coverage="active_only",
        overlay_coverage_scope="zone",
        limit=100,
    )
    assert zone_active["filters"]["overlay_coverage_scope"] == "zone"
    assert {row["zone_id"] for row in zone_active["members"]} == {1}
    assert zone_active["filtered_member_count"] == 2
    assert overlay_addition_case["c103_active"] != overlay_addition_case["c103_comparison"]


def test_overlay_addition_concentration_is_deterministic_and_cumulative(overlay_addition_case):
    first = _report(overlay_addition_case, limit=0, top=20)
    second = _report(overlay_addition_case, limit=0, top=20)
    assert first == second

    zones = first["zone_map_counts"]
    assert [row["zone_id"] for row in zones] == [1, 2, 3]
    assert [row["total_addition_count"] for row in zones] == [2, 2, 2]
    assert [row["cumulative_addition_count"] for row in zones] == [2, 4, 6]
    assert [row["cumulative_percentage_of_included_total"] for row in zones] == [
        33.333333,
        66.666667,
        100.0,
    ]

    parents = first["parent_template_counts"]
    assert parents[0]["parent_subject_key"] == "103"
    assert parents[0]["total_addition_count"] == 2
    assert parents[-1]["cumulative_addition_count"] == 6
    assert parents[-1]["cumulative_percentage_of_included_total"] == 100.0


def test_overlay_addition_filters_json_and_cli_are_read_only(overlay_addition_case, capsys):
    active = _report(
        overlay_addition_case,
        pattern="active_only_vs_base",
        subject_kind="creature_spawn",
        zone_id=1,
        limit=100,
        top=20,
    )
    assert active["filtered_member_count"] == 2
    assert all(row["three_way_pattern"] == "active_only_vs_base" for row in active["members"])
    assert all(row["zone_id"] == 1 for row in active["members"])

    absent = _report(
        overlay_addition_case,
        addition_parent_class="parent_absent_from_base",
        limit=100,
    )
    assert absent["filtered_member_count"] == 2
    assert all(
        row["addition_parent_class"] == "parent_absent_from_base" for row in absent["members"]
    )

    by_parent = _report(overlay_addition_case, parent_key=103, limit=100)
    assert by_parent["filtered_member_count"] == 2

    db_path = overlay_addition_case["db_path"]
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert (
        overlay_additions_main(
            [
                "--base-source-revision",
                "base-r1",
                "--comparison-source-revision",
                "octo-r1",
                "--overlay-coverage",
                "both",
                "--limit",
                "10",
                "--db",
                str(db_path),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert payload["filtered_member_count"] == 2
    assert payload["filters"]["overlay_coverage_scope"] == "parent"
    assert before == after


def test_overlay_additions_fail_closed_when_base_parent_evidence_is_missing(overlay_addition_case):
    with connect_database(overlay_addition_case["db_path"]) as connection:
        source_id = overlay_addition_case["source_ids"]["pfquest"]
        group_id = int(
            connection.execute(
                """
                SELECT og.id
                FROM observation_groups AS og
                JOIN source_observations AS so ON so.observation_group_id = og.id
                WHERE so.source_id = ?
                  AND og.subject_kind = 'creature'
                  AND og.subject_key = '102'
                  AND og.fact_key = 'spawn_set'
                """,
                (source_id,),
            ).fetchone()[0]
        )
        connection.execute(
            "DELETE FROM observation_import_batches WHERE observation_id IN "
            "(SELECT id FROM source_observations WHERE observation_group_id = ? AND source_id = ?)",
            (group_id, source_id),
        )
        connection.execute(
            "DELETE FROM source_observations WHERE observation_group_id = ? AND source_id = ?",
            (group_id, source_id),
        )
        with pytest.raises(
            ValueError,
            match="could not reconstruct a unique persisted base spawn_set",
        ):
            overlay_addition_report(
                connection,
                base_source_revision="base-r1",
                comparison_source_revision="octo-r1",
                limit=0,
            )
