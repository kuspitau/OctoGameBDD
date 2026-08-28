from __future__ import annotations

import hashlib
import json

import pytest

from octogamedb.audit_spawn_attribution import main as spawn_attribution_main
from octogamedb.audit_spawn_attribution import spawn_attribution_report
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
def spawn_attribution_case(tmp_path):
    db_path = tmp_path / "p5-t05.sqlite3"
    with connect_database(db_path) as connection:
        apply_migrations(connection)
        connection.execute("INSERT INTO maps(map_id, name) VALUES (1, 'Azeroth')")
        connection.execute("INSERT INTO maps(map_id, name) VALUES (2, 'Other Map')")
        connection.execute("INSERT INTO zones(zone_id, map_id, name) VALUES (1, 1, 'Zone One')")
        connection.execute("INSERT INTO zones(zone_id, map_id, name) VALUES (2, 1, 'Zone Two')")

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
            policy: str | None = None,
        ) -> int:
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
            if select:
                group_id = int(
                    connection.execute(
                        "SELECT observation_group_id FROM source_observations WHERE id = ?",
                        (observation_id,),
                    ).fetchone()[0]
                )
                selection_policy = policy or (
                    "pfquest-base-effective-world"
                    if source_key == "pfquest"
                    else "pfquest-turtle-effective-world"
                )
                select_canonical_observation(
                    connection,
                    observation_group_id=group_id,
                    observation_id=observation_id,
                    selection_policy=selection_policy,
                    selection_reason="P5-T05 fixture active selection.",
                )
                seen_positions: set[str] = set()
                for spawn in value:
                    spawn_key = str(spawn["spawn_key"])
                    if spawn_key in seen_positions:
                        continue
                    seen_positions.add(spawn_key)
                    position = {
                        key: spawn[key]
                        for key in ("coordinate_space", "zone_id", "map_id", "x", "y", "z")
                        if key in spawn
                    }
                    position_id = record_scalar_observation(
                        connection,
                        subject_kind=f"{kind}_spawn",
                        subject_key=spawn_key,
                        fact_key="position",
                        import_batch_id=batch_ids[source_key],
                        value=position,
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
                        selection_reason="P5-T05 fixture active position selection.",
                    )
            return observation_id

        # Shared-only member: excluded from P5-T05 population.
        c1 = _spawn("creature", 1, zone_id=1, x=1.0, y=1.0)
        record_set("creature", 1, [c1], source_key="pfquest")
        record_set("creature", 1, [c1], source_key="pfquest-turtle", select=True)
        record_set("creature", 1, [c1, c1], source_key="pfquest-octo")

        # B=1 A=1 C=0. Base duplicates must still mean one unique member.
        c2 = _spawn("creature", 2, zone_id=1, x=2.0, y=2.0)
        record_set("creature", 2, [c2, c2], source_key="pfquest")
        record_set("creature", 2, [c2], source_key="pfquest-turtle", select=True)
        record_set("creature", 2, [], source_key="pfquest-octo")

        # B=0 A=1 C=0 with the parent itself absent from the complete base view.
        c3 = _spawn("creature", 3, zone_id=1, x=3.0, y=3.0)
        record_set("creature", 3, [c3], source_key="pfquest-turtle", select=True)
        record_set("creature", 3, [], source_key="pfquest-octo")

        # B=1 A=0 C=1.
        c4 = _spawn("creature", 4, zone_id=1, x=4.0, y=4.0)
        record_set("creature", 4, [c4], source_key="pfquest")
        record_set("creature", 4, [], source_key="pfquest-turtle", select=True)
        record_set("creature", 4, [c4], source_key="pfquest-octo")

        # B=0 A=0 C=1.
        c5 = _spawn("creature", 5, zone_id=1, x=5.0, y=5.0)
        record_set("creature", 5, [], source_key="pfquest")
        record_set("creature", 5, [], source_key="pfquest-turtle", select=True)
        record_set("creature", 5, [c5], source_key="pfquest-octo")

        # Comparison-side possible replacement: base/active old -> comparison new.
        c6_old = _spawn("creature", 6, zone_id=1, x=10.0, y=10.0)
        c6_new = _spawn("creature", 6, zone_id=1, x=10.2, y=10.0)
        record_set("creature", 6, [c6_old], source_key="pfquest")
        record_set("creature", 6, [c6_old], source_key="pfquest-turtle", select=True)
        record_set("creature", 6, [c6_new], source_key="pfquest-octo")

        # Active-side possible replacement with an intentional nearest tie.
        c7_old = _spawn("creature", 7, zone_id=1, x=20.05, y=20.0)
        c7_new_a = _spawn("creature", 7, zone_id=1, x=20.0, y=20.0)
        c7_new_b = _spawn("creature", 7, zone_id=1, x=20.1, y=20.0)
        record_set("creature", 7, [c7_old], source_key="pfquest")
        record_set(
            "creature",
            7,
            [c7_new_a, c7_new_b],
            source_key="pfquest-turtle",
            select=True,
        )
        record_set("creature", 7, [c7_old], source_key="pfquest-octo")

        # Source-local pair shape, but cross-zone: must not be a candidate.
        c8_old = _spawn("creature", 8, zone_id=1, x=30.0, y=30.0)
        c8_new = _spawn("creature", 8, zone_id=2, x=30.1, y=30.0)
        record_set("creature", 8, [c8_old], source_key="pfquest")
        record_set("creature", 8, [c8_old], source_key="pfquest-turtle", select=True)
        record_set("creature", 8, [c8_new], source_key="pfquest-octo")

        # Source-local pair shape, but incompatible coordinate spaces: must not be a candidate.
        c9_old = _spawn("creature", 9, zone_id=1, x=35.0, y=35.0)
        c9_new = _spawn(
            "creature",
            9,
            zone_id=1,
            x=35.0,
            y=35.0,
            coordinate_space="world",
            map_id=1,
        )
        record_set("creature", 9, [c9_old], source_key="pfquest")
        record_set("creature", 9, [c9_old], source_key="pfquest-turtle", select=True)
        record_set("creature", 9, [c9_new], source_key="pfquest-octo")

        # GameObject coverage.
        g10 = _spawn("gameobject", 10, zone_id=1, x=40.0, y=40.0)
        record_set("gameobject", 10, [], source_key="pfquest")
        record_set("gameobject", 10, [g10], source_key="pfquest-turtle", select=True)
        record_set("gameobject", 10, [], source_key="pfquest-octo")

        # Active selected complete set can legitimately remain the base view.
        c11 = _spawn("creature", 11, zone_id=1, x=50.0, y=50.0)
        record_set("creature", 11, [c11], source_key="pfquest", select=True)
        record_set("creature", 11, [], source_key="pfquest-octo")

    return {
        "db_path": db_path,
        "c1": c1["spawn_key"],
        "c2": c2["spawn_key"],
        "c3": c3["spawn_key"],
        "c4": c4["spawn_key"],
        "c5": c5["spawn_key"],
        "c6_old": c6_old["spawn_key"],
        "c6_new": c6_new["spawn_key"],
        "c7_old": c7_old["spawn_key"],
        "c7_new_a": c7_new_a["spawn_key"],
        "c7_new_b": c7_new_b["spawn_key"],
        "c8_old": c8_old["spawn_key"],
        "c8_new": c8_new["spawn_key"],
        "c9_old": c9_old["spawn_key"],
        "c9_new": c9_new["spawn_key"],
        "g10": g10["spawn_key"],
        "c11": c11["spawn_key"],
    }


def _report(case, **kwargs):
    with connect_database(case["db_path"]) as connection:
        return spawn_attribution_report(
            connection,
            base_source_revision="base-r1",
            comparison_source_revision="octo-r1",
            **kwargs,
        )


def test_spawn_attribution_partitions_all_four_patterns_and_excludes_shared(spawn_attribution_case):
    report = _report(spawn_attribution_case, limit=100, top=20)

    assert report["scope"] == "p5-t05-three-way-base-active-octo-spawn-attribution"
    assert report["base_source"]["source_revision"] == "base-r1"
    assert report["comparison_source"]["source_revision"] == "octo-r1"
    counts = {row["pattern"]: row["member_count"] for row in report["patterns"]}
    assert counts == {
        "base_active_not_comparison": 5,
        "active_only_vs_base": 4,
        "base_comparison_not_active": 2,
        "comparison_only_vs_base": 4,
    }
    assert report["one_sided_member_count"] == 15
    assert report["active_only_member_count"] == 9
    assert report["comparison_only_member_count"] == 6
    assert sum(counts.values()) == 15

    members = {row["spawn_key"]: row for row in report["members"]}
    assert spawn_attribution_case["c1"] not in members
    assert members[spawn_attribution_case["c2"]]["three_way_pattern"] == (
        "base_active_not_comparison"
    )
    assert members[spawn_attribution_case["c3"]]["three_way_pattern"] == "active_only_vs_base"
    assert members[spawn_attribution_case["c3"]]["base_membership_evidence"] == (
        "absent_from_complete_base_view"
    )
    assert members[spawn_attribution_case["c4"]]["three_way_pattern"] == (
        "base_comparison_not_active"
    )
    assert members[spawn_attribution_case["c5"]]["three_way_pattern"] == (
        "comparison_only_vs_base"
    )
    assert members[spawn_attribution_case["g10"]]["subject_kind"] == "gameobject_spawn"
    assert members[spawn_attribution_case["c2"]]["base_import_batches"]
    assert members[spawn_attribution_case["c2"]]["base_membership_evidence"] == (
        "spawn_set_observation"
    )


def test_spawn_attribution_preserves_provenance_geography_and_parent_topology(
    spawn_attribution_case,
):
    report = _report(spawn_attribution_case, limit=100, top=20)
    members = {row["spawn_key"]: row for row in report["members"]}

    turtle = members[spawn_attribution_case["c2"]]
    assert turtle["active_selected_source_key"] == "pfquest-turtle"
    assert turtle["active_selected_source_revision"] == "turtle-r1"
    assert turtle["active_selected_selection_policy"] == "pfquest-turtle-effective-world"
    assert turtle["zone_name"] == "Zone One"
    assert turtle["map_name"] == "Azeroth"

    base = members[spawn_attribution_case["c11"]]
    assert base["active_selected_source_key"] == "pfquest"
    assert base["active_selected_source_revision"] == "base-r1"
    assert base["active_selected_selection_policy"] == "pfquest-base-effective-world"

    contexts = {
        (row["source_key"], row["source_revision"]): row
        for row in report["active_selected_contexts"]
    }
    assert contexts[("pfquest", "base-r1")]["member_count"] == 1
    assert contexts[("pfquest-turtle", "turtle-r1")]["member_count"] == 14
    assert any(
        row["zone_id"] == 1 and row["member_count"] > 0
        for row in report["zone_map_pattern_counts"]
    )
    assert all(
        row["parent_topology_class"]
        in {
            "active_only_members",
            "comparison_only_members",
            "mixed_one_sided_members",
        }
        for row in report["top_parent_concentrations"]
    )


def test_source_local_replacement_analysis_is_pattern_specific_and_preserves_ties(
    spawn_attribution_case,
):
    report = _report(spawn_attribution_case, limit=100, top=20)
    classes = {
        row["pair_class"]: row
        for row in report["source_local_replacement_analysis"]["pair_classes"]
    }

    comparison = classes["comparison_side_possible_replacement"]
    assert comparison["compatible_candidate_pair_count"] == 1
    assert comparison["unique_nearest_candidate_pair_count"] == 1
    assert comparison["mutual_nearest_candidate_pair_count"] == 1

    active = classes["active_side_possible_replacement"]
    assert active["compatible_candidate_pair_count"] == 2
    assert active["unique_nearest_candidate_pair_count"] == 2
    assert active["mutual_nearest_candidate_pair_count"] == 2
    assert active["member_nearest_tie_cardinality"]["multiple"] == 1

    pairs = {
        (row["active_spawn_key"], row["comparison_spawn_key"]): row
        for row in report["candidate_pairs"]
    }
    assert (
        spawn_attribution_case["c6_old"],
        spawn_attribution_case["c6_new"],
    ) in pairs
    assert pairs[(spawn_attribution_case["c7_new_a"], spawn_attribution_case["c7_old"])][
        "mutual_nearest"
    ] is True
    assert pairs[(spawn_attribution_case["c7_new_b"], spawn_attribution_case["c7_old"])][
        "mutual_nearest"
    ] is True
    assert (spawn_attribution_case["c8_old"], spawn_attribution_case["c8_new"]) not in pairs
    assert (spawn_attribution_case["c9_old"], spawn_attribution_case["c9_new"]) not in pairs


def test_spawn_attribution_filters_are_deterministic_and_cli_is_read_only(
    spawn_attribution_case, capsys
):
    first = _report(spawn_attribution_case, limit=0, top=3)
    second = _report(spawn_attribution_case, limit=0, top=3)
    filtered = _report(
        spawn_attribution_case,
        pattern="active_only_vs_base",
        subject_kind="creature_spawn",
        zone_id=1,
        limit=100,
        top=20,
    )
    assert first == second
    assert first["members"] == []
    assert first["candidate_pairs"] == []
    assert first["members_truncated"] is True
    assert filtered["filtered_one_sided_member_count"] == 3
    assert all(row["three_way_pattern"] == "active_only_vs_base" for row in filtered["members"])
    assert all(row["subject_kind"] == "creature_spawn" for row in filtered["members"])
    assert all(row["zone_id"] == 1 for row in filtered["members"])

    db_path = spawn_attribution_case["db_path"]
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert (
        spawn_attribution_main(
            [
                "--base-source-revision",
                "base-r1",
                "--comparison-source-revision",
                "octo-r1",
                "--pattern",
                "comparison_only_vs_base",
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
    assert payload["filtered_one_sided_member_count"] == 4
    assert before == after


def test_spawn_attribution_fails_closed_when_base_complete_set_is_missing(spawn_attribution_case):
    with connect_database(spawn_attribution_case["db_path"]) as connection:
        source_id = int(
            connection.execute(
                "SELECT id FROM data_sources WHERE source_key = 'pfquest'"
            ).fetchone()[0]
        )
        group_id = int(
            connection.execute(
                """
                SELECT og.id
                FROM observation_groups AS og
                JOIN source_observations AS so ON so.observation_group_id = og.id
                WHERE so.source_id = ?
                  AND og.subject_kind = 'creature'
                  AND og.subject_key = '2'
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
            spawn_attribution_report(
                connection,
                base_source_revision="base-r1",
                comparison_source_revision="octo-r1",
                limit=0,
            )
