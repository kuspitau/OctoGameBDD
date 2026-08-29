from __future__ import annotations

from pathlib import Path

import pytest

from octogamedb.itemcache_campaign import (
    STATE_HISTORICAL_CACHE,
    STATE_IN_FLIGHT,
    STATE_QUEUED,
    STATE_REFRESH_PROVEN,
    STATE_UNKNOWN_RETRYABLE,
    STATE_UNKNOWN_TERMINAL,
    atomic_write_ledger,
    begin_session,
    campaign_report,
    compute_candidate_revision,
    create_campaign_ledger,
    load_ledger,
    merge_active_session,
    reconcile_pre_session_cache_presence,
    recover_active_session_without_export,
    select_next_batch,
)


def _ledger(*, ids=range(1, 11), batch_limit=4, max_attempts=2):
    return create_campaign_ledger(
        canonical_sha256="a" * 64,
        canonical_migration=13,
        canonical_item_count=20,
        coverage_revision="sha256:" + "b" * 64,
        cache_pre_exists=True,
        cache_pre_sha256="c" * 64,
        initial_matching_cache_count=10,
        initial_cache_only_count=2,
        candidate_item_ids=ids,
        created_utc="20260829T190000Z",
        batch_limit=batch_limit,
        max_campaign_attempts=max_attempts,
    )


def _begin(ledger, ids, *, when="20260829T190100Z"):
    return begin_session(
        ledger,
        requested_item_ids=ids,
        pre_coverage_revision="sha256:" + "d" * 64,
        pre_cache_exists=True,
        pre_cache_sha256="e" * 64,
        pre_record_sha256={item_id: None for item_id in ids},
        started_utc=when,
    )


def _export(ids, results, *, complete=True):
    return {
        "probe_id": "probe-1",
        "started": "123",
        "realm": "N_Zoth",
        "character": "Tester",
        "locale": "enUS",
        "client_version": "1.12.1",
        "client_build": "5875",
        "ids": list(ids),
        "results": results,
        "complete": complete,
    }


def test_candidate_revision_and_ledger_are_deterministic_and_versioned():
    first = _ledger(ids=[9, 2, 5, 2])
    second = _ledger(ids=[5, 9, 2])
    assert first["candidate_item_ids"] == [2, 5, 9]
    assert first["candidate_revision"] == second["candidate_revision"]
    assert first["campaign_id"] == second["campaign_id"]
    assert first["version"] == 1
    assert set(first["items"]) == {"2", "5", "9"}
    assert all(row["state"] == STATE_QUEUED for row in first["items"].values())

    changed = compute_candidate_revision(
        canonical_sha256="f" * 64,
        coverage_revision=first["initial_cache"]["coverage_revision"],
        candidate_item_ids=[2, 5, 9],
    )
    assert changed != first["candidate_revision"]


def test_next_batch_is_bounded_deterministic_and_spread_over_candidates():
    ledger = _ledger(ids=[1, 2, 3, 4, 5, 6, 7, 8, 9], batch_limit=4)
    assert select_next_batch(ledger) == (1, 4, 6, 9)
    assert select_next_batch(ledger) == (1, 4, 6, 9)


def test_completed_session_classifies_freshness_and_reimport_is_duplicate_noop():
    ledger = _ledger(ids=[10, 20, 30], batch_limit=3)
    _begin(ledger, [10, 20, 30])
    assert all(
        ledger["items"][str(item_id)]["state"] == STATE_IN_FLIGHT
        for item_id in [10, 20, 30]
    )

    export = _export(
        [10, 20, 30],
        {
            10: {"initial": "missing", "status": "loaded_after_query"},
            20: {"initial": "missing", "status": "timeout_unknown"},
            30: {"initial": "missing", "status": "loaded_after_query"},
        },
    )
    first = merge_active_session(
        ledger,
        export=export,
        post_record_sha256={10: "h10", 30: "h30"},
        post_cache_exists=True,
        post_cache_sha256="post-cache",
        merged_utc="20260829T190300Z",
        require_complete=True,
    )
    assert first["duplicate"] is False
    assert ledger["items"]["10"]["state"] == STATE_REFRESH_PROVEN
    assert ledger["items"]["30"]["state"] == STATE_REFRESH_PROVEN
    assert ledger["items"]["20"]["state"] == STATE_UNKNOWN_RETRYABLE
    assert ledger["active_session"] is None
    assert len(ledger["sessions"]) == 1

    item_snapshot = {key: dict(value) for key, value in ledger["items"].items()}
    second = merge_active_session(
        ledger,
        export=export,
        post_record_sha256={10: "h10", 30: "h30"},
        post_cache_exists=True,
        post_cache_sha256="post-cache",
        merged_utc="20260829T190400Z",
        require_complete=True,
    )
    assert second["duplicate"] is True
    assert len(ledger["sessions"]) == 1
    assert ledger["items"] == item_snapshot
    assert ledger["duplicate_noop_session_imports"] == 1


def test_retryable_timeout_gets_one_slot_then_becomes_terminal_at_attempt_cap():
    ledger = _ledger(ids=[10, 20, 30, 40, 50], batch_limit=3, max_attempts=2)
    _begin(ledger, [10])
    merge_active_session(
        ledger,
        export=_export([10], {10: {"initial": "missing", "status": "timeout_unknown"}}),
        post_record_sha256={},
        post_cache_exists=True,
        post_cache_sha256="post-1",
        merged_utc="20260829T190200Z",
        require_complete=True,
    )
    assert ledger["items"]["10"]["state"] == STATE_UNKNOWN_RETRYABLE
    next_batch = select_next_batch(ledger)
    assert next_batch[0] == 10
    assert len(next_batch) == 3

    _begin(ledger, list(next_batch), when="20260829T190300Z")
    results = {
        item_id: {"initial": "missing", "status": "timeout_unknown"}
        for item_id in next_batch
    }
    merge_active_session(
        ledger,
        export=_export(next_batch, results),
        post_record_sha256={},
        post_cache_exists=True,
        post_cache_sha256="post-2",
        merged_utc="20260829T190500Z",
        require_complete=True,
    )
    assert ledger["items"]["10"]["state"] == STATE_UNKNOWN_TERMINAL
    assert 10 not in select_next_batch(ledger)


def test_incomplete_session_recovers_unreported_ids_as_unknown_not_negative():
    ledger = _ledger(ids=[10, 20], batch_limit=2)
    _begin(ledger, [10, 20])
    merge_active_session(
        ledger,
        export=_export(
            [10, 20],
            {10: {"initial": "missing", "status": "loaded_after_query"}},
            complete=False,
        ),
        post_record_sha256={10: "h10"},
        post_cache_exists=True,
        post_cache_sha256="post",
        merged_utc="20260829T190300Z",
        require_complete=False,
    )
    assert ledger["items"]["10"]["state"] == STATE_REFRESH_PROVEN
    assert ledger["items"]["20"]["state"] == STATE_UNKNOWN_RETRYABLE
    assert ledger["items"]["20"]["freshness_class"] == "unknown"


def test_recovery_without_savedvariables_defers_post_wdb_record_and_retries_true_miss():
    ledger = _ledger(ids=[10, 20], batch_limit=2)
    _begin(ledger, [10, 20])
    recover_active_session_without_export(
        ledger,
        post_record_sha256={10: "post-hash"},
        recovered_utc="20260829T190300Z",
    )
    assert ledger["items"]["10"]["state"] == STATE_UNKNOWN_TERMINAL
    assert ledger["items"]["10"]["freshness_class"] == "unknown"
    assert ledger["items"]["20"]["state"] == STATE_UNKNOWN_RETRYABLE


def test_preexisting_record_before_new_session_is_historical_and_never_relabelled_fresh():
    ledger = _ledger(ids=[10, 20, 30], batch_limit=2)
    changed = reconcile_pre_session_cache_presence(
        ledger,
        current_record_sha256={20: "historical-hash"},
        updated_utc="20260829T190100Z",
    )
    assert changed == [20]
    assert ledger["items"]["20"]["state"] == STATE_HISTORICAL_CACHE
    assert ledger["items"]["20"]["freshness_class"] == "historical_cache_only"
    assert 20 not in select_next_batch(ledger)


def test_mismatched_or_malformed_session_input_fails_closed():
    ledger = _ledger(ids=[10, 20], batch_limit=2)
    _begin(ledger, [10, 20])
    with pytest.raises(ValueError, match="does not match active session"):
        merge_active_session(
            ledger,
            export=_export([20, 10], {}),
            post_record_sha256={},
            post_cache_exists=True,
            post_cache_sha256="post",
            merged_utc="20260829T190300Z",
            require_complete=False,
        )

    with pytest.raises(ValueError, match="unsupported probe status"):
        merge_active_session(
            ledger,
            export=_export(
                [10, 20],
                {
                    10: {"initial": "missing", "status": "invented"},
                    20: {"initial": "missing", "status": "timeout_unknown"},
                },
            ),
            post_record_sha256={},
            post_cache_exists=True,
            post_cache_sha256="post",
            merged_utc="20260829T190300Z",
            require_complete=True,
        )


def test_atomic_checkpoint_roundtrip_and_report_keep_canonical_read_only_contract(tmp_path: Path):
    ledger = _ledger(ids=[10, 20], batch_limit=2)
    path = tmp_path / "campaign.json"
    atomic_write_ledger(path, ledger)
    restored = load_ledger(path)
    assert restored == ledger
    assert not list(tmp_path.glob("*.tmp"))

    report = campaign_report(
        restored,
        canonical_sha256_after="a" * 64,
        current_matching_cache_count=10,
        current_missing_cache_count=10,
    )
    assert report["canonical_db_unchanged"] is True
    assert report["campaign_candidate_count"] == 2
    assert report["attempted_unique_ids"] == 0
    assert report["remaining_unattempted_candidate_count"] == 2
