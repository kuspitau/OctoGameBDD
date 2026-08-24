from __future__ import annotations

from octogamedb.audit import conflict_report, coverage_report, source_report, trace_report
from octogamedb.db import connect_database


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
    assert conflict_keys == [
        ("item", "100", "name"),
        ("quest", "99", "giver"),
    ]
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
