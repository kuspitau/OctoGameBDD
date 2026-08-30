from __future__ import annotations

from octogamedb.itemcache_promotion import (
    FRESHNESS_HISTORICAL_CACHE,
    FRESHNESS_REFRESH_PROVEN,
    FRESHNESS_SESSION_OBSERVED,
    FRESHNESS_UNKNOWN,
    FreshnessProof,
    build_promotion_plan,
    proofs_from_p6_t02_report,
    proofs_from_p6_t03_ledger,
)

BASELINE = "6" * 64
ARTIFACT = "a" * 64


def proof(item_id: int, freshness: str, raw_hash: str | None) -> FreshnessProof:
    return FreshnessProof(
        item_id=item_id,
        freshness_class=freshness,
        raw_record_sha256=raw_hash,
        proof_kind="fixture",
        proof_revision=f"sha256:{item_id:064x}",
        artifact_sha256=ARTIFACT,
    )


def test_plan_promotes_only_exact_refresh_proven_bytes():
    fresh_hash = "1" * 64
    drifted_proof_hash = "2" * 64
    plan = build_promotion_plan(
        canonical_sha256=BASELINE,
        canonical_migration=13,
        itemcache_sha256="f" * 64,
        itemcache_locale="enUS",
        itemcache_client_version=5875,
        current_record_sha256={1001: fresh_hash, 1002: "3" * 64, 1003: "4" * 64},
        proofs=(
            proof(1001, FRESHNESS_REFRESH_PROVEN, fresh_hash),
            proof(1002, FRESHNESS_REFRESH_PROVEN, drifted_proof_hash),
            proof(1003, FRESHNESS_HISTORICAL_CACHE, "4" * 64),
            proof(1004, FRESHNESS_SESSION_OBSERVED, None),
            proof(1005, FRESHNESS_UNKNOWN, None),
        ),
        evidence_artifacts=(
            {"kind": "fixture", "name": "evidence.json", "sha256": ARTIFACT},
        ),
    )

    assert plan.eligible_item_ids == (1001,)
    assert [row["item_id"] for row in plan.excluded_refresh_proven] == [1002]
    assert plan.noneligible_class_item_counts == {
        FRESHNESS_HISTORICAL_CACHE: 1,
        FRESHNESS_SESSION_OBSERVED: 1,
        FRESHNESS_UNKNOWN: 1,
    }
    assert plan.evidence_class_counts[FRESHNESS_REFRESH_PROVEN] == 2
    assert plan.to_json()["policy"]["raw_hash_match_required"] is True


def test_plan_is_deterministic_across_proof_and_artifact_order():
    raw_hash = "1" * 64
    proofs = (
        proof(1001, FRESHNESS_REFRESH_PROVEN, raw_hash),
        proof(1002, FRESHNESS_UNKNOWN, None),
    )
    artifacts = (
        {"kind": "z", "name": "z.json", "sha256": "f" * 64},
        {"kind": "a", "name": "a.json", "sha256": "e" * 64},
    )
    common = {
        "canonical_sha256": BASELINE,
        "canonical_migration": 13,
        "itemcache_sha256": "d" * 64,
        "itemcache_locale": "enUS",
        "itemcache_client_version": 5875,
        "current_record_sha256": {1001: raw_hash},
    }
    first = build_promotion_plan(proofs=proofs, evidence_artifacts=artifacts, **common)
    second = build_promotion_plan(
        proofs=tuple(reversed(proofs)),
        evidence_artifacts=tuple(reversed(artifacts)),
        **common,
    )
    assert first.plan_revision == second.plan_revision
    assert first.to_json() == second.to_json()


def test_p6_t02_report_requires_baseline_and_preserves_classes():
    report = {
        "report_version": 2,
        "preflight": {"canonical_sha256": BASELINE, "coverage_revision": "sha256:coverage"},
        "capture": {"probe_id": "fixture"},
        "classifications": [
            {
                "item_id": 1001,
                "post_record_sha256": "1" * 64,
                "probe_status": "loaded_after_query",
                "freshness_class": FRESHNESS_REFRESH_PROVEN,
            },
            {
                "item_id": 1002,
                "post_record_sha256": None,
                "probe_status": "loaded_after_query",
                "freshness_class": FRESHNESS_SESSION_OBSERVED,
            },
            {
                "item_id": 1003,
                "post_record_sha256": None,
                "probe_status": "timeout_unknown",
                "freshness_class": FRESHNESS_UNKNOWN,
            },
        ],
    }
    proofs = proofs_from_p6_t02_report(
        report,
        artifact_sha256=ARTIFACT,
        expected_canonical_sha256=BASELINE,
    )
    assert [(value.item_id, value.freshness_class) for value in proofs] == [
        (1001, FRESHNESS_REFRESH_PROVEN),
        (1002, FRESHNESS_SESSION_OBSERVED),
        (1003, FRESHNESS_UNKNOWN),
    ]
    assert proofs[0].raw_record_sha256 == "1" * 64


def test_p6_t03_ledger_uses_final_item_state_and_session_revision():
    ledger = {
        "format": "octogamedb-itemcache-acquisition-campaign",
        "version": 1,
        "campaign_id": "sha256:campaign",
        "canonical": {"sha256": BASELINE, "migration": 13},
        "items": {
            "1001": {
                "freshness_class": FRESHNESS_REFRESH_PROVEN,
                "post_record_sha256": "1" * 64,
                "attempt_count": 1,
            },
            "1002": {
                "freshness_class": FRESHNESS_HISTORICAL_CACHE,
                "post_record_sha256": "2" * 64,
                "attempt_count": 0,
            },
            "1003": {
                "freshness_class": FRESHNESS_UNKNOWN,
                "post_record_sha256": None,
                "attempt_count": 1,
            },
        },
        "sessions": [
            {
                "merge_revision": "sha256:session-one",
                "classifications": [
                    {"item_id": 1001, "freshness_class": FRESHNESS_REFRESH_PROVEN}
                ],
            }
        ],
    }
    proofs = proofs_from_p6_t03_ledger(
        ledger,
        artifact_sha256=ARTIFACT,
        expected_canonical_sha256=BASELINE,
    )
    by_id = {value.item_id: value for value in proofs}
    assert by_id[1001].session_revision == "sha256:session-one"
    assert by_id[1001].campaign_id == "sha256:campaign"
    assert by_id[1002].freshness_class == FRESHNESS_HISTORICAL_CACHE
    assert by_id[1003].freshness_class == FRESHNESS_UNKNOWN
