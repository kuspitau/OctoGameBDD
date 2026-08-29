from __future__ import annotations

import sqlite3
from pathlib import Path

from octogamedb.importers.octo_itemcache import parse_itemcache_wdb
from octogamedb.itemcache_coverage import (
    FRESHNESS_HISTORICAL_CACHE,
    FRESHNESS_REFRESH_PROVEN,
    FRESHNESS_SESSION_OBSERVED,
    FRESHNESS_UNKNOWN,
    PROBE_STATUS_ALREADY_CACHED,
    PROBE_STATUS_LOADED_AFTER_QUERY,
    PROBE_STATUS_TIMEOUT,
    build_absent_itemcache_coverage_report,
    build_itemcache_coverage_report,
    choose_missing_canonical_probe_ids,
    classify_probe_observation,
    compute_itemcache_coverage_revision,
)

FIXTURE = Path(__file__).parent / "fixtures" / "p6_t01" / "itemcache.wdb"


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE items(item_id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    connection.executemany(
        "INSERT INTO items(item_id,name) VALUES (?,?)",
        [(1001, "Sword"), (1002, "Chest"), (2000, "Known Missing")],
    )
    return connection


def test_coverage_report_separates_cache_presence_from_canonical_identity():
    connection = _connection()
    report = build_itemcache_coverage_report(connection, source_path=FIXTURE)

    assert report["counts"]["cache_records"] == 3
    assert report["counts"]["canonical_items"] == 3
    assert report["counts"]["cache_records_with_canonical_identity"] == 2
    assert report["counts"]["cache_only_native_ids"] == 1
    assert report["counts"]["canonical_item_ids_missing_from_cache_unknown"] == 1
    assert report["cache_only_native_item_ids"] == [900001]
    assert report["canonical_item_ids_missing_from_cache_unknown"] == [2000]
    assert report["counts"]["records_with_nonempty_stat_slots"] >= 1
    assert report["diagnostics"]["parser_policy"].startswith("fail_closed")


def test_coverage_revision_is_deterministic_and_depends_on_canonical_population():
    snapshot = parse_itemcache_wdb(FIXTURE)
    first = compute_itemcache_coverage_revision(snapshot, [1001, 1002, 2000])
    assert first == compute_itemcache_coverage_revision(snapshot, [2000, 1002, 1001, 1001])
    assert first != compute_itemcache_coverage_revision(snapshot, [1001, 1002])


def test_probe_candidate_selection_is_bounded_deterministic_and_not_numeric_bruteforce():
    report = {"canonical_item_ids_missing_from_cache_unknown": [2, 10, 25, 100, 1000, 900000]}
    assert choose_missing_canonical_probe_ids(report, limit=3) == (2, 25, 900000)
    assert choose_missing_canonical_probe_ids(report, limit=1) == (100,)


def test_freshness_classification_requires_before_after_evidence():
    historical = classify_probe_observation(
        item_id=1,
        pre_record_sha256="aaa",
        post_record_sha256="aaa",
        probe_status=PROBE_STATUS_ALREADY_CACHED,
    )
    assert historical.freshness_class == FRESHNESS_HISTORICAL_CACHE

    proven = classify_probe_observation(
        item_id=2,
        pre_record_sha256=None,
        post_record_sha256="bbb",
        probe_status=PROBE_STATUS_LOADED_AFTER_QUERY,
    )
    assert proven.freshness_class == FRESHNESS_REFRESH_PROVEN

    session_only = classify_probe_observation(
        item_id=3,
        pre_record_sha256=None,
        post_record_sha256=None,
        probe_status=PROBE_STATUS_LOADED_AFTER_QUERY,
    )
    assert session_only.freshness_class == FRESHNESS_SESSION_OBSERVED

    unknown = classify_probe_observation(
        item_id=4,
        pre_record_sha256=None,
        post_record_sha256=None,
        probe_status=PROBE_STATUS_TIMEOUT,
    )
    assert unknown.freshness_class == FRESHNESS_UNKNOWN


def test_absent_cache_report_keeps_every_canonical_id_unknown_without_synthetic_wdb():
    connection = _connection()
    report = build_absent_itemcache_coverage_report(
        connection, expected_source_path=Path("WDB/enUS/itemcache.wdb")
    )

    assert report["cache_state"] == "absent_before_probe"
    assert report["header"] is None
    assert report["counts"]["cache_records"] == 0
    assert report["counts"]["canonical_items"] == 3
    assert report["counts"]["canonical_item_ids_missing_from_cache_unknown"] == 3
    assert report["canonical_item_ids_missing_from_cache_unknown"] == [1001, 1002, 2000]
    assert report["diagnostics"]["parser_policy"].startswith("clean_cache")
