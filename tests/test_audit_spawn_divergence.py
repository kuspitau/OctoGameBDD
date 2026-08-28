from __future__ import annotations

import hashlib
import json

import pytest

from octogamedb.audit_spawn_divergence import main as spawn_divergence_main
from octogamedb.audit_spawn_divergence import spawn_divergence_report
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
    coordinate_space: str = "zone_percent",
    map_id: int | None = None,
) -> dict[str, object]:
    context = zone_id if coordinate_space == "zone_percent" else (map_id or 1)
    spawn_key = f"{kind}:{parent_id}:{coordinate_space}:{context}:{x:.6f}:{y:.6f}"
    value: dict[str, object] = {
        "spawn_key": spawn_key,
        "coordinate_space": coordinate_space,
        "x": x,
        "y": y,
        "respawn_seconds": None,
    }
    if coordinate_space == "zone_percent":
        value["zone_id"] = zone_id
    else:
        value["map_id"] = map_id or 1
    return value


@pytest.fixture
def spawn_divergence_case(tmp_path):
    db_path = tmp_path / "p5-t04.sqlite3"
    with connect_database(db_path) as connection:
        apply_migrations(connection)
        connection.execute("INSERT INTO maps(map_id, name) VALUES (1, 'Azeroth')")
        connection.execute("INSERT INTO maps(map_id, name) VALUES (2, 'Other Map')")
        connection.execute("INSERT INTO zones(zone_id, map_id, name) VALUES (1, 1, 'Zone One')")
        connection.execute("INSERT INTO zones(zone_id, map_id, name) VALUES (2, 1, 'Zone Two')")

        source_ids: dict[str, int] = {}
        batch_ids: dict[str, int] = {}
        for source_key, revision in (
            ("active-source", "active-r1"),
            ("alternate-active", "alternate-r1"),
            ("pfquest-octo", "octo-r1"),
        ):
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
                        source_id, source_revision, status, finished_at,
                        rows_read, rows_accepted, rows_inserted
                    )
                    VALUES (?, ?, 'succeeded', '2026-08-28T00:00:00Z', 100, 100, 100)
                    """,
                    (source_ids[source_key], revision),
                ).lastrowid
            )

        def record_set(
            kind: str,
            parent_id: int,
            value: list[dict[str, object]],
            *,
            source_key: str,
            select: bool,
            policy: str = "fixture-active/v1",
        ) -> None:
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
                    selection_policy=policy,
                    selection_reason="P5-T04 fixture active selection.",
                )
                for spawn in value:
                    position = {
                        key: spawn[key]
                        for key in ("coordinate_space", "zone_id", "map_id", "x", "y", "z")
                        if key in spawn
                    }
                    position_id = record_scalar_observation(
                        connection,
                        subject_kind=f"{kind}_spawn",
                        subject_key=str(spawn["spawn_key"]),
                        fact_key="position",
                        import_batch_id=batch_ids[source_key],
                        value=position,
                        source_record_type="fixture-position",
                        raw_identifier=str(spawn["spawn_key"]),
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
                        selection_policy=policy,
                        selection_reason="P5-T04 fixture active position selection.",
                    )

        # 1: shared-only.
        c1 = _spawn("creature", 1, zone_id=1, x=1.0, y=1.0)
        record_set("creature", 1, [c1], source_key="active-source", select=True)
        # Complete-set membership is set-like. Real source lists may repeat an
        # identical coordinate row, so duplicate spawn_key values must collapse.
        record_set("creature", 1, [c1, c1], source_key="pfquest-octo", select=False)

        # 2: true active-only.
        c2 = _spawn("creature", 2, zone_id=1, x=2.0, y=2.0)
        record_set("creature", 2, [c2], source_key="active-source", select=True)
        record_set("creature", 2, [], source_key="pfquest-octo", select=False)

        # 3: true comparison-only.
        c3 = _spawn("creature", 3, zone_id=1, x=3.0, y=3.0)
        record_set("creature", 3, [], source_key="active-source", select=True)
        record_set("creature", 3, [c3], source_key="pfquest-octo", select=False)

        # 4: mixed and ambiguous. Both active spawns are 0.05 percentage points from comparison.
        c4a = _spawn("creature", 4, zone_id=1, x=10.00, y=10.0)
        c4b = _spawn("creature", 4, zone_id=1, x=10.10, y=10.0)
        c4c = _spawn("creature", 4, zone_id=1, x=10.05, y=10.0)
        record_set("creature", 4, [c4a, c4b], source_key="active-source", select=True)
        record_set("creature", 4, [c4c], source_key="pfquest-octo", select=False)

        # 5: mixed but cross-zone; it must not create relocation candidates.
        c5a = _spawn("creature", 5, zone_id=1, x=20.0, y=20.0)
        c5b = _spawn("creature", 5, zone_id=2, x=20.1, y=20.0)
        record_set("creature", 5, [c5a], source_key="active-source", select=True)
        record_set("creature", 5, [c5b], source_key="pfquest-octo", select=False)

        # 6: mixed but incompatible coordinate spaces; no match.
        c6a = _spawn("creature", 6, zone_id=1, x=30.0, y=30.0)
        c6b = _spawn(
            "creature",
            6,
            zone_id=1,
            x=30.0,
            y=30.0,
            coordinate_space="world",
            map_id=1,
        )
        record_set(
            "creature",
            6,
            [c6a],
            source_key="alternate-active",
            select=True,
            policy="alt/v2",
        )
        record_set("creature", 6, [c6b], source_key="pfquest-octo", select=False)

        # 10: gameobject mixed close pair, for both-kind coverage.
        g10a = _spawn("gameobject", 10, zone_id=1, x=40.0, y=40.0)
        g10b = _spawn("gameobject", 10, zone_id=1, x=40.2, y=40.0)
        record_set("gameobject", 10, [g10a], source_key="active-source", select=True)
        record_set("gameobject", 10, [g10b], source_key="pfquest-octo", select=False)

    return {
        "db_path": db_path,
        "c2": c2["spawn_key"],
        "c3": c3["spawn_key"],
        "c4a": c4a["spawn_key"],
        "c4b": c4b["spawn_key"],
        "c4c": c4c["spawn_key"],
        "c5a": c5a["spawn_key"],
        "c5b": c5b["spawn_key"],
        "c6a": c6a["spawn_key"],
        "c6b": c6b["spawn_key"],
        "g10a": g10a["spawn_key"],
        "g10b": g10b["spawn_key"],
    }


def test_spawn_divergence_report_classifies_unique_members_and_parents(spawn_divergence_case):
    with connect_database(spawn_divergence_case["db_path"]) as connection:
        report = spawn_divergence_report(connection, limit=100, top=20)

    assert report["scope"] == "p5-t04-pfquest-octo-spawn-membership-divergence"
    assert report["comparison_source"]["source_revision"] == "octo-r1"
    assert report["membership_baseline"] == {
        "by_subject_kind": [
            {
                "subject_kind": "creature_spawn",
                "parent_count": 6,
                "shared_member_count": 1,
                "active_only_member_count": 5,
                "comparison_only_member_count": 4,
            },
            {
                "subject_kind": "gameobject_spawn",
                "parent_count": 1,
                "shared_member_count": 0,
                "active_only_member_count": 1,
                "comparison_only_member_count": 1,
            },
        ],
        "shared_member_count": 1,
        "active_only_member_count": 6,
        "comparison_only_member_count": 5,
        "one_sided_member_count": 11,
    }
    assert report["parent_topology"]["class_counts"] == {
        "shared_only": 1,
        "active_only_members": 1,
        "comparison_only_members": 1,
        "mixed_one_sided_members": 4,
    }
    assert sum(
        row["parent_count"]
        for row in report["parent_topology"]["one_sided_member_count_distribution"]
    ) == 7
    assert report["filtered_one_sided_member_count"] == 11
    assert len({member["spawn_key"] for member in report["members"]}) == 11


def test_spawn_divergence_report_preserves_ambiguity_and_context_boundaries(spawn_divergence_case):
    with connect_database(spawn_divergence_case["db_path"]) as connection:
        report = spawn_divergence_report(connection, limit=100, top=20)

    members = {member["spawn_key"]: member for member in report["members"]}
    assert members[spawn_divergence_case["c4a"]]["nearest_candidate_count"] == 1
    assert members[spawn_divergence_case["c4b"]]["nearest_candidate_count"] == 1
    assert members[spawn_divergence_case["c4c"]]["nearest_candidate_count"] == 2
    assert members[spawn_divergence_case["c4c"]]["nearest_candidate_distance_band"] == "(0,0.1]"

    assert members[spawn_divergence_case["c5a"]]["nearest_candidate_count"] == 0
    assert members[spawn_divergence_case["c5b"]]["nearest_candidate_count"] == 0
    assert members[spawn_divergence_case["c6a"]]["nearest_candidate_count"] == 0
    assert members[spawn_divergence_case["c6b"]]["nearest_candidate_count"] == 0

    analysis = report["relocation_candidate_analysis"]
    assert analysis["member_candidate_cardinality"] == {"zero": 6, "one": 4, "multiple": 1}
    assert analysis["members_without_compatible_opposite_count"] == 6
    assert analysis["compatible_candidate_pair_count"] == 3
    assert analysis["unique_nearest_candidate_pair_count"] == 3
    assert analysis["member_nearest_tie_cardinality"] == {"zero": 6, "one": 4, "multiple": 1}
    pairs = {
        (row["active_spawn_key"], row["comparison_spawn_key"]): row
        for row in report["candidate_pairs"]
    }
    assert pairs[(spawn_divergence_case["c4a"], spawn_divergence_case["c4c"])][
        "nearest_for_comparison"
    ] is True
    assert pairs[(spawn_divergence_case["c4b"], spawn_divergence_case["c4c"])][
        "nearest_for_comparison"
    ] is True
    assert (spawn_divergence_case["g10a"], spawn_divergence_case["g10b"]) in pairs


def test_spawn_divergence_report_aggregates_provenance_geography_and_filters(spawn_divergence_case):
    with connect_database(spawn_divergence_case["db_path"]) as connection:
        report = spawn_divergence_report(connection, limit=100, top=20)
        filtered = spawn_divergence_report(
            connection,
            subject_kind="creature_spawn",
            direction="active_only",
            zone_id=1,
            limit=100,
            top=20,
        )
        ambiguous = spawn_divergence_report(
            connection,
            candidate_cardinality="multiple",
            limit=100,
            top=20,
        )

    contexts = {
        (row["source_key"], row["source_revision"], row["selection_policy"]): row
        for row in report["active_membership_contexts"]
    }
    assert contexts[("active-source", "active-r1", "fixture-active/v1")][
        "one_sided_member_count"
    ] == 9
    assert contexts[("alternate-active", "alternate-r1", "alt/v2")][
        "one_sided_member_count"
    ] == 2
    position_contexts = {
        (row["source_key"], row["source_revision"], row["selection_policy"]): row["member_count"]
        for row in report["active_only_selected_position_contexts"]
    }
    assert position_contexts[("active-source", "active-r1", "fixture-active/v1")] == 5
    assert position_contexts[("alternate-active", "alternate-r1", "alt/v2")] == 1

    zone_rows = report["top_zone_map_concentrations"]
    assert any(
        row["zone_id"] == 1 and row["zone_name"] == "Zone One" and row["map_name"] == "Azeroth"
        for row in zone_rows
    )
    assert filtered["filtered_one_sided_member_count"] == 5
    assert all(member["subject_kind"] == "creature_spawn" for member in filtered["members"])
    assert all(member["direction"] == "active_only" for member in filtered["members"])
    assert all(member["zone_id"] == 1 for member in filtered["members"])
    assert filtered["membership_baseline"] == report["membership_baseline"]
    assert ambiguous["filtered_one_sided_member_count"] == 1
    assert ambiguous["members"][0]["spawn_key"] == spawn_divergence_case["c4c"]

    members = {member["spawn_key"]: member for member in report["members"]}
    assert members[spawn_divergence_case["c6a"]]["active_position_source_key"] == "alternate-active"
    assert members[spawn_divergence_case["c6a"]]["active_position_selection_policy"] == "alt/v2"
    assert members[spawn_divergence_case["c2"]]["comparison_import_batches"]


def test_spawn_divergence_report_is_deterministic_and_cli_is_read_only(
    spawn_divergence_case, capsys
):
    db_path = spawn_divergence_case["db_path"]
    with connect_database(db_path) as connection:
        first = spawn_divergence_report(connection, limit=0, top=3)
        second = spawn_divergence_report(connection, limit=0, top=3)
        with pytest.raises(ValueError, match="bounded to comparison source pfquest-octo"):
            spawn_divergence_report(connection, source_key="active-source")
        with pytest.raises(ValueError, match="limit and top must be non-negative"):
            spawn_divergence_report(connection, limit=-1)

    assert first == second
    assert first["members"] == []
    assert first["candidate_pairs"] == []
    assert first["members_truncated"] is True

    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert (
        spawn_divergence_main(
            [
                "pfquest-octo",
                "--parent-key",
                "4",
                "--limit",
                "5",
                "--db",
                str(db_path),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert payload["filtered_one_sided_member_count"] == 3
    assert payload["comparison_source"]["source_revision"] == "octo-r1"
    assert before == after
