from __future__ import annotations

from octogamedb.itemcache_incremental_promotion import (
    build_incremental_promotion_plan,
    campaign_counts,
    proofs_from_campaign_ledger,
)
from octogamedb.itemcache_promotion import (
    FRESHNESS_HISTORICAL_CACHE,
    FRESHNESS_REFRESH_PROVEN,
    FRESHNESS_UNKNOWN,
    FreshnessProof,
)


def _proof(item_id: int, freshness: str, raw_hash: str | None, suffix: str) -> FreshnessProof:
    return FreshnessProof(
        item_id=item_id,
        freshness_class=freshness,
        raw_record_sha256=raw_hash,
        proof_kind="fixture",
        proof_revision=f"sha256:{suffix * 64}"[:71],
        artifact_sha256=(suffix * 64)[:64],
    )


def _ledger(*, sha: str = "a" * 64, migration: int = 14):
    return {
        "format": "octogamedb-itemcache-acquisition-campaign",
        "version": 1,
        "campaign_id": "sha256:" + "c" * 64,
        "canonical": {"sha256": sha, "migration": migration},
        "sessions": [
            {
                "merge_revision": "sha256:" + "d" * 64,
                "classifications": [{"item_id": 10}],
            }
        ],
        "items": {
            "10": {
                "freshness_class": FRESHNESS_REFRESH_PROVEN,
                "post_record_sha256": "1" * 64,
                "attempt_count": 1,
            },
            "20": {
                "freshness_class": FRESHNESS_UNKNOWN,
                "post_record_sha256": None,
                "attempt_count": 2,
            },
            "30": {
                "freshness_class": FRESHNESS_HISTORICAL_CACHE,
                "post_record_sha256": "3" * 64,
                "attempt_count": 0,
            },
        },
    }


def test_campaign_proofs_require_exact_current_baseline():
    ledger = _ledger()
    proofs = proofs_from_campaign_ledger(
        ledger,
        artifact_sha256="f" * 64,
        expected_canonical_sha256="a" * 64,
        expected_canonical_migration=14,
    )
    assert [proof.item_id for proof in proofs] == [10, 20, 30]
    assert proofs[0].freshness_class == FRESHNESS_REFRESH_PROVEN

    try:
        proofs_from_campaign_ledger(
            ledger,
            artifact_sha256="f" * 64,
            expected_canonical_sha256="a" * 64,
            expected_canonical_migration=13,
        )
    except ValueError as exc:
        assert "migration" in str(exc)
    else:  # pragma: no cover - fail loudly without pytest dependency in this pure test
        raise AssertionError("migration-13 baseline should be rejected")


def test_campaign_counts_track_unique_attempts_not_retry_count():
    counts = campaign_counts(_ledger())
    assert counts["candidate_items"] == 3
    assert counts["attempted_unique_items"] == 2
    assert counts["refresh_proven_items"] == 1
    assert counts["unknown_items"] == 1


def test_exact_current_hash_and_already_current_noop_partition():
    proofs = [
        _proof(10, FRESHNESS_REFRESH_PROVEN, "1" * 64, "a"),
        _proof(20, FRESHNESS_REFRESH_PROVEN, "2" * 64, "b"),
        _proof(30, FRESHNESS_HISTORICAL_CACHE, "3" * 64, "c"),
    ]
    plan = build_incremental_promotion_plan(
        canonical_sha256="f" * 64,
        canonical_migration=14,
        itemcache_sha256="e" * 64,
        itemcache_locale="enUS",
        itemcache_client_version=5875,
        current_record_sha256={10: "1" * 64, 20: "9" * 64, 30: "3" * 64},
        proofs=proofs,
        already_current_item_ids={10},
        evidence_artifacts=(),
        current_campaign_counts={"attempted_unique_items": 3},
    )
    assert plan.eligible_item_ids == ()
    assert [row["item_id"] for row in plan.already_current_noops] == [10]
    assert [row["item_id"] for row in plan.excluded_refresh_proven] == [20]
    assert plan.noneligible_class_item_counts[FRESHNESS_HISTORICAL_CACHE] == 1


def test_matching_refresh_proof_is_incrementally_eligible_and_plan_is_deterministic():
    proof = _proof(42, FRESHNESS_REFRESH_PROVEN, "4" * 64, "d")
    kwargs = {
        "canonical_sha256": "f" * 64,
        "canonical_migration": 14,
        "itemcache_sha256": "e" * 64,
        "itemcache_locale": "enUS",
        "itemcache_client_version": 5875,
        "current_record_sha256": {42: "4" * 64},
        "proofs": [proof],
        "already_current_item_ids": (),
        "evidence_artifacts": ({"kind": "fixture", "sha256": "a" * 64},),
        "current_campaign_counts": {
            "refresh_proven_items": 10,
            "attempted_unique_items": 20,
        },
    }
    first = build_incremental_promotion_plan(**kwargs)
    second = build_incremental_promotion_plan(**kwargs)
    assert first.eligible_item_ids == (42,)
    assert first.plan_revision == second.plan_revision
