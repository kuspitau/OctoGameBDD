from __future__ import annotations

import pytest

from octogamedb.audit import (
    conflict_report,
    coverage_report,
    resolution_report,
    source_report,
    trace_report,
    unselected_report,
)
from octogamedb.db import (
    connect_database,
    record_scalar_observation,
    select_canonical_observation,
)


def test_golden_coverage_case(golden_audit_case):
    with connect_database(golden_audit_case["db_path"]) as connection:
        report = coverage_report(connection)
    assert report == golden_audit_case["fixture"]["expected_coverage"]


def test_golden_conflict_case_distinguishes_resolved_and_unresolved(golden_audit_case):
    with connect_database(golden_audit_case["db_path"]) as connection:
        report = conflict_report(connection)
    assert report["conflict_count"] == 2
    assert report["unresolved_conflict_count"] == 1
    conflict_keys = [
        (item["subject_kind"], item["subject_key"], item["fact_key"])
        for item in report["conflicts"]
    ]
    assert conflict_keys == [("item", "100", "name"), ("quest", "99", "giver")]
    assert report["conflicts"][0]["canonical_selection"]["selection_policy"] == (
        "fixture-source-priority/v1"
    )
    assert report["conflicts"][1]["canonical_selection"] is None


def test_trace_preserves_sources_values_and_relation_instances(golden_audit_case):
    with connect_database(golden_audit_case["db_path"]) as connection:
        item_trace = trace_report(connection, subject_kind="item", subject_key=100)
        creature_trace = trace_report(connection, subject_kind="creature", subject_key=12)
    assert item_trace["group_count"] == 2
    name_group = next(group for group in item_trace["groups"] if group["fact_key"] == "name")
    assert [observation["source_key"] for observation in name_group["observations"]] == [
        "source-a",
        "source-b",
    ]
    assert [observation["value"] for observation in name_group["observations"]] == [
        "Copper Widget",
        "Copper Gizmo",
    ]
    assert creature_trace["group_count"] == 2
    assert all(group["distinct_value_count"] == 1 for group in creature_trace["groups"])


def test_source_report_contains_machine_readable_import_summaries(golden_audit_case):
    with connect_database(golden_audit_case["db_path"]) as connection:
        report = source_report(connection, "source-a")
    assert report["source_count"] == 1
    source = report["sources"][0]
    assert source["source_key"] == "source-a"
    assert source["batch_count"] == 1
    assert source["batches"][0] == {
        "source_key": "source-a",
        "source_revision": "rev-a",
        "status": "succeeded",
        "rows_read": 5,
        "rows_accepted": 5,
        "rows_skipped": 0,
        "rows_inserted": 5,
        "rows_updated": 0,
        "warning_count": 0,
        "error_count": 0,
        "details": {"fixture_case": "provenance-audit"},
    }


def test_resolution_report_summarizes_selection_baseline(golden_audit_case):
    with connect_database(golden_audit_case["db_path"]) as connection:
        report = resolution_report(connection)
    assert report == {
        "scope": "provenance-resolution",
        "subject_kind": None,
        "fact_key": None,
        "observation_group_count": 5,
        "selected_group_count": 1,
        "unselected_group_count": 4,
        "empty_observation_group_count": 0,
        "conflict_group_count": 2,
        "resolved_conflict_group_count": 1,
        "unresolved_conflict_group_count": 1,
        "unselected_single_value_group_count": 3,
        "selection_policies": [
            {
                "selection_policy": "fixture-source-priority/v1",
                "selected_group_count": 1,
                "conflict_group_count": 1,
            }
        ],
        "selected_sources": [
            {
                "source_key": "source-b",
                "selected_group_count": 1,
                "conflict_group_count": 1,
            }
        ],
        "fact_families": [
            {
                "subject_kind": "creature",
                "fact_key": "loot.item",
                "fact_kind": "relation",
                "observation_group_count": 2,
                "selected_group_count": 0,
                "unselected_group_count": 2,
                "empty_observation_group_count": 0,
                "conflict_group_count": 0,
                "resolved_conflict_group_count": 0,
                "unresolved_conflict_group_count": 0,
                "unselected_single_value_group_count": 2,
            },
            {
                "subject_kind": "item",
                "fact_key": "name",
                "fact_kind": "scalar",
                "observation_group_count": 1,
                "selected_group_count": 1,
                "unselected_group_count": 0,
                "empty_observation_group_count": 0,
                "conflict_group_count": 1,
                "resolved_conflict_group_count": 1,
                "unresolved_conflict_group_count": 0,
                "unselected_single_value_group_count": 0,
            },
            {
                "subject_kind": "item",
                "fact_key": "quality",
                "fact_kind": "scalar",
                "observation_group_count": 1,
                "selected_group_count": 0,
                "unselected_group_count": 1,
                "empty_observation_group_count": 0,
                "conflict_group_count": 0,
                "resolved_conflict_group_count": 0,
                "unresolved_conflict_group_count": 0,
                "unselected_single_value_group_count": 1,
            },
            {
                "subject_kind": "quest",
                "fact_key": "giver",
                "fact_kind": "relation",
                "observation_group_count": 1,
                "selected_group_count": 0,
                "unselected_group_count": 1,
                "empty_observation_group_count": 0,
                "conflict_group_count": 1,
                "resolved_conflict_group_count": 0,
                "unresolved_conflict_group_count": 1,
                "unselected_single_value_group_count": 0,
            },
        ],
    }


def test_resolution_report_filters_subject_and_fact(golden_audit_case):
    with connect_database(golden_audit_case["db_path"]) as connection:
        report = resolution_report(connection, subject_kind="item", fact_key="name")
    assert report["subject_kind"] == "item"
    assert report["fact_key"] == "name"
    assert report["observation_group_count"] == 1
    assert report["selected_group_count"] == 1
    assert report["conflict_group_count"] == 1
    assert report["resolved_conflict_group_count"] == 1
    assert report["unresolved_conflict_group_count"] == 0
    assert report["selected_sources"][0]["source_key"] == "source-b"


def test_resolution_report_keeps_selection_without_named_policy(golden_audit_case):
    with connect_database(golden_audit_case["db_path"]) as connection:
        row = connection.execute(
            """
            SELECT og.id AS group_id, so.id AS observation_id
            FROM observation_groups AS og
            JOIN source_observations AS so ON so.observation_group_id = og.id
            WHERE og.subject_kind = 'item'
              AND og.subject_key = '100'
              AND og.fact_key = 'quality'
            """
        ).fetchone()
        select_canonical_observation(
            connection,
            observation_group_id=int(row["group_id"]),
            observation_id=int(row["observation_id"]),
            selection_reason="Fixture selection intentionally has no named policy.",
        )
        report = resolution_report(connection)
    assert report["selected_group_count"] == 2
    assert report["selection_policies"][0] == {
        "selection_policy": None,
        "selected_group_count": 1,
        "conflict_group_count": 0,
    }
    assert report["selection_policies"][1]["selection_policy"] == "fixture-source-priority/v1"


def test_unselected_report_is_exact_single_value_subset_with_provenance(golden_audit_case):
    with connect_database(golden_audit_case["db_path"]) as connection:
        report = unselected_report(connection)

    assert report["scope"] == "unselected-single-value"
    assert report["group_count"] == 3
    assert report["returned_group_count"] == 3
    assert report["classification_counts"] == {"unresolved": 3}
    assert [
        (group["subject_kind"], group["subject_key"], group["fact_key"])
        for group in report["groups"]
    ] == [
        ("creature", "12", "loot.item"),
        ("creature", "12", "loot.item"),
        ("item", "100", "quality"),
    ]
    assert all(group["canonical_selection"] is None for group in report["groups"])
    assert all(group["distinct_value_count"] == 1 for group in report["groups"])
    assert all(group["classification"]["label"] == "unresolved" for group in report["groups"])

    quality = report["groups"][2]
    assert quality["sole_value"] == 2
    assert quality["observations"] == [
        {
            "observation_id": quality["observations"][0]["observation_id"],
            "source_key": "source-a",
            "source_revision": "rev-a",
            "source_record_type": "item",
            "raw_identifier": "100",
            "value": 2,
            "confidence": None,
            "authority_tier": None,
            "import_batches": [
                {
                    "batch_id": quality["observations"][0]["import_batches"][0]["batch_id"],
                    "status": "succeeded",
                }
            ],
        }
    ]
    assert report["fact_families"] == [
        {
            "subject_kind": "creature",
            "fact_key": "loot.item",
            "fact_kind": "relation",
            "group_count": 2,
        },
        {
            "subject_kind": "item",
            "fact_key": "quality",
            "fact_kind": "scalar",
            "group_count": 1,
        },
    ]
    assert report["sources"] == [
        {"source_key": "source-a", "group_count": 3, "observation_count": 3}
    ]
    assert report["source_revisions"] == [
        {
            "source_key": "source-a",
            "source_revision": "rev-a",
            "group_count": 3,
            "observation_count": 3,
        }
    ]
    assert report["subject_fact_patterns"] == [
        {
            "subject_kind": "creature",
            "fact_keys": ["loot.item"],
            "subject_count": 1,
            "group_count": 2,
        },
        {
            "subject_kind": "item",
            "fact_keys": ["quality"],
            "subject_count": 1,
            "group_count": 1,
        },
    ]


def test_unselected_report_filters_subject_fact_key_and_source(golden_audit_case):
    with connect_database(golden_audit_case["db_path"]) as connection:
        item = unselected_report(connection, subject_kind="item")
        creature = unselected_report(connection, subject_key=12)
        quality = unselected_report(connection, fact_key="quality")
        source_a = unselected_report(connection, source_key="source-a")
        source_b = unselected_report(connection, source_key="source-b")

    assert item["group_count"] == 1
    assert creature["group_count"] == 2
    assert quality["group_count"] == 1
    assert source_a["group_count"] == 3
    assert source_b["group_count"] == 0
    assert source_b["groups"] == []


def test_unselected_report_treats_identical_json_observations_as_one_value(golden_audit_case):
    with connect_database(golden_audit_case["db_path"]) as connection:
        batch_b = int(
            connection.execute(
                """
                SELECT ib.id
                FROM import_batches AS ib
                JOIN data_sources AS ds ON ds.id = ib.source_id
                WHERE ds.source_key = 'source-b'
                """
            ).fetchone()[0]
        )
        record_scalar_observation(
            connection,
            subject_kind="item",
            subject_key=100,
            fact_key="quality",
            import_batch_id=batch_b,
            value=2,
            source_record_type="item",
            raw_identifier=100,
        )
        report = unselected_report(connection, fact_key="quality")
        source_b_report = unselected_report(connection, source_key="source-b", fact_key="quality")

    assert report["group_count"] == 1
    assert report["groups"][0]["observation_count"] == 2
    assert report["groups"][0]["distinct_value_count"] == 1
    assert [observation["source_key"] for observation in report["groups"][0]["observations"]] == [
        "source-a",
        "source-b",
    ]
    assert source_b_report["group_count"] == 1


def test_unselected_report_excludes_selected_single_value_and_exposes_sibling_policy(
    golden_audit_case,
):
    with connect_database(golden_audit_case["db_path"]) as connection:
        selected = connection.execute(
            """
            SELECT og.id AS group_id, so.id AS observation_id
            FROM observation_groups AS og
            JOIN source_observations AS so ON so.observation_group_id = og.id
            WHERE og.subject_kind = 'creature'
              AND og.subject_key = '12'
              AND og.fact_key = 'loot.item'
            ORDER BY og.fact_instance_key
            LIMIT 1
            """
        ).fetchone()
        select_canonical_observation(
            connection,
            observation_group_id=int(selected["group_id"]),
            observation_id=int(selected["observation_id"]),
            selection_policy="fixture-single-selected/v1",
            selection_reason="Fixture selects one comparable single-value sibling.",
        )
        report = unselected_report(connection, subject_kind="creature", subject_key=12)

    assert report["group_count"] == 1
    evidence = report["groups"][0]["classification_evidence"]
    assert evidence["selected_sibling_count"] == 1
    assert evidence["single_value_unselected_sibling_count"] == 1
    assert evidence["selected_sibling_policies"] == ["fixture-single-selected/v1"]
    assert evidence["selected_sibling_sources"] == ["source-a"]
    selected_sibling = next(
        sibling for sibling in report["groups"][0]["siblings"] if sibling["state"] == "selected"
    )
    assert selected_sibling["selection_policy"] == "fixture-single-selected/v1"
    assert selected_sibling["selected_source_key"] == "source-a"


def test_unselected_report_summary_only_is_deterministic(golden_audit_case):
    with connect_database(golden_audit_case["db_path"]) as connection:
        first = unselected_report(connection, limit=0)
        second = unselected_report(connection, limit=0)
        with pytest.raises(ValueError, match="limit must be non-negative"):
            unselected_report(connection, limit=-1)

    assert first == second
    assert first["group_count"] == 3
    assert first["returned_group_count"] == 0
    assert first["details_truncated"] is True
    assert first["groups"] == []
