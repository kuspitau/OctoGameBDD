"""Deterministic P6-T05 migration-14 incremental item-template promotion planning.

This module does not mutate SQLite.  It combines already-established D-037 freshness evidence with
exact current WDB raw-record hashes, then separates truly incremental candidates from canonically
current no-ops.  Historical/session-only/unknown evidence remains non-authoritative for automatic
selection.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from octogamedb.itemcache_promotion import (
    FRESHNESS_HISTORICAL_CACHE,
    FRESHNESS_REFRESH_PROVEN,
    FRESHNESS_SESSION_OBSERVED,
    FRESHNESS_UNKNOWN,
    FreshnessProof,
)

PROMOTION_FORMAT = "octogamedb-p6-t05-incremental-promotion-plan"
PROMOTION_VERSION = 1
TARGET_MIGRATION = 14
_ACCEPTED_FRESHNESS = frozenset(
    {
        FRESHNESS_REFRESH_PROVEN,
        FRESHNESS_SESSION_OBSERVED,
        FRESHNESS_HISTORICAL_CACHE,
        FRESHNESS_UNKNOWN,
    }
)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _revision(domain: bytes, value: Any) -> str:
    digest = hashlib.sha256()
    digest.update(domain)
    digest.update(b"\0")
    digest.update(_canonical_json(value))
    return f"sha256:{digest.hexdigest()}"


def _require_hash(value: Any, *, label: str) -> str:
    digest = str(value or "").lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError(f"{label} must be a SHA-256 digest")
    return digest


def _freshness(value: Any, *, label: str) -> str:
    result = str(value or "")
    if result not in _ACCEPTED_FRESHNESS:
        raise ValueError(f"{label} has unsupported freshness class {result!r}")
    return result


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def proofs_from_campaign_ledger(
    ledger: Mapping[str, Any],
    *,
    artifact_sha256: str,
    expected_canonical_sha256: str,
    expected_canonical_migration: int,
    proof_kind: str = "p6_t05_campaign_ledger",
) -> tuple[FreshnessProof, ...]:
    """Read final per-item evidence from a validated acquisition ledger on the accepted baseline."""

    if ledger.get("format") != "octogamedb-itemcache-acquisition-campaign":
        raise ValueError("unsupported acquisition campaign ledger format")
    if int(ledger.get("version", 0)) != 1:
        raise ValueError("unsupported acquisition campaign ledger version")
    canonical = ledger.get("canonical")
    if not isinstance(canonical, Mapping):
        raise TypeError("campaign ledger lacks canonical metadata")
    if str(canonical.get("sha256", "")) != expected_canonical_sha256:
        raise ValueError("campaign ledger canonical SHA does not match the accepted baseline")
    if int(canonical.get("migration", -1)) != expected_canonical_migration:
        raise ValueError("campaign ledger migration does not match the accepted baseline")

    campaign_id = str(ledger.get("campaign_id", ""))
    if not campaign_id.startswith("sha256:"):
        raise ValueError("campaign ledger lacks deterministic campaign_id")
    sessions = ledger.get("sessions")
    if not isinstance(sessions, list):
        raise TypeError("campaign ledger sessions must be a list")
    session_revision_by_item: dict[int, str] = {}
    for session in sessions:
        if not isinstance(session, Mapping):
            raise TypeError("campaign session must be an object")
        merge_revision = str(session.get("merge_revision", ""))
        if not merge_revision.startswith("sha256:"):
            raise ValueError("campaign session lacks deterministic merge_revision")
        classifications = session.get("classifications", [])
        if not isinstance(classifications, list):
            raise TypeError("campaign classifications must be a list")
        for classification in classifications:
            if isinstance(classification, Mapping):
                item_id = int(classification.get("item_id", 0))
                if item_id > 0:
                    session_revision_by_item[item_id] = merge_revision

    items = ledger.get("items")
    if not isinstance(items, Mapping):
        raise TypeError("campaign ledger items must be an object")

    proofs: list[FreshnessProof] = []
    for raw_item_id, raw in items.items():
        if not isinstance(raw, Mapping):
            raise TypeError(f"campaign item {raw_item_id} must be an object")
        item_id = int(raw_item_id)
        if item_id <= 0:
            raise ValueError("campaign item IDs must be positive")
        freshness = _freshness(raw.get("freshness_class"), label=f"campaign item {item_id}")
        raw_hash = raw.get("post_record_sha256")
        if raw_hash is not None:
            raw_hash = _require_hash(raw_hash, label=f"campaign item {item_id} post hash")
        if freshness == FRESHNESS_REFRESH_PROVEN and raw_hash is None:
            raise ValueError(f"refresh-proven campaign item {item_id} lacks post-record hash")
        session_revision = session_revision_by_item.get(item_id)
        proof_revision = _revision(
            b"octogamedb-p6-t05-final-item-proof-v1",
            {
                "artifact_sha256": artifact_sha256,
                "campaign_id": campaign_id,
                "item_id": item_id,
                "freshness_class": freshness,
                "post_record_sha256": raw_hash,
                "session_revision": session_revision,
                "attempt_count": int(raw.get("attempt_count", 0)),
            },
        )
        proofs.append(
            FreshnessProof(
                item_id=item_id,
                freshness_class=freshness,
                raw_record_sha256=raw_hash,
                proof_kind=proof_kind,
                proof_revision=proof_revision,
                artifact_sha256=artifact_sha256,
                campaign_id=campaign_id,
                session_revision=session_revision,
            )
        )
    return tuple(sorted(proofs, key=lambda proof: (proof.item_id, proof.proof_revision)))


def campaign_counts(ledger: Mapping[str, Any]) -> dict[str, int]:
    items = ledger.get("items")
    if not isinstance(items, Mapping):
        raise TypeError("campaign ledger items must be an object")
    counts = Counter()
    attempted_unique = 0
    for raw in items.values():
        if not isinstance(raw, Mapping):
            raise TypeError("campaign item must be an object")
        freshness = _freshness(raw.get("freshness_class"), label="campaign item")
        counts[freshness] += 1
        if int(raw.get("attempt_count", 0)) > 0:
            attempted_unique += 1
    return {
        "candidate_items": len(items),
        "attempted_unique_items": attempted_unique,
        "refresh_proven_items": counts[FRESHNESS_REFRESH_PROVEN],
        "session_observed_items": counts[FRESHNESS_SESSION_OBSERVED],
        "historical_cache_items": counts[FRESHNESS_HISTORICAL_CACHE],
        "unknown_items": counts[FRESHNESS_UNKNOWN],
    }


@dataclass(frozen=True)
class IncrementalPromotionPlan:
    canonical_sha256: str
    canonical_migration: int
    itemcache_sha256: str
    itemcache_locale: str
    itemcache_client_version: int
    evidence_artifacts: tuple[dict[str, Any], ...]
    evidence_class_counts: dict[str, int]
    campaign_counts: dict[str, int]
    eligible_items: tuple[dict[str, Any], ...]
    already_current_noops: tuple[dict[str, Any], ...]
    excluded_refresh_proven: tuple[dict[str, Any], ...]
    noneligible_class_item_counts: dict[str, int]
    plan_revision: str

    @property
    def eligible_item_ids(self) -> tuple[int, ...]:
        return tuple(int(row["item_id"]) for row in self.eligible_items)

    def to_json(self) -> dict[str, Any]:
        return {
            "format": PROMOTION_FORMAT,
            "version": PROMOTION_VERSION,
            "canonical": {
                "sha256": self.canonical_sha256,
                "migration": self.canonical_migration,
            },
            "target_migration": TARGET_MIGRATION,
            "itemcache": {
                "sha256": self.itemcache_sha256,
                "locale": self.itemcache_locale,
                "client_version": self.itemcache_client_version,
            },
            "evidence_artifacts": list(self.evidence_artifacts),
            "evidence_class_counts": self.evidence_class_counts,
            "campaign_counts": self.campaign_counts,
            "eligible_item_ids": list(self.eligible_item_ids),
            "eligible_items": list(self.eligible_items),
            "already_current_noops": list(self.already_current_noops),
            "excluded_refresh_proven": list(self.excluded_refresh_proven),
            "noneligible_class_item_counts": self.noneligible_class_item_counts,
            "policy": {
                "automatic_selection_eligible_class": FRESHNESS_REFRESH_PROVEN,
                "exact_current_raw_hash_required": True,
                "already_current_effective_projection": "excluded_as_noop",
                "historical_cache_only": "excluded_not_currentness_proven",
                "session_observed_freshness_limited": "excluded_no_persisted_proven_field_bytes",
                "unknown": "excluded_never_negative_or_selection_authority",
                "schema_migration": "must_remain_14",
                "cache_only_identity_fabrication": False,
            },
            "plan_revision": self.plan_revision,
        }


def build_incremental_promotion_plan(
    *,
    canonical_sha256: str,
    canonical_migration: int,
    itemcache_sha256: str,
    itemcache_locale: str,
    itemcache_client_version: int,
    current_record_sha256: Mapping[int, str],
    proofs: Iterable[FreshnessProof],
    already_current_item_ids: Iterable[int],
    evidence_artifacts: Sequence[Mapping[str, Any]],
    current_campaign_counts: Mapping[str, int],
) -> IncrementalPromotionPlan:
    if canonical_migration != TARGET_MIGRATION:
        raise ValueError(
            f"P6-T05 incremental planning requires migration {TARGET_MIGRATION}, "
            f"found {canonical_migration}"
        )
    if not canonical_sha256 or not itemcache_sha256:
        raise ValueError("canonical and itemcache SHA values are required")

    normalized = tuple(
        sorted(
            proofs,
            key=lambda proof: (
                proof.item_id,
                proof.freshness_class,
                proof.raw_record_sha256 or "",
                proof.proof_kind,
                proof.proof_revision,
            ),
        )
    )
    class_counts = Counter(proof.freshness_class for proof in normalized)
    by_item: dict[int, list[FreshnessProof]] = defaultdict(list)
    noneligible: dict[str, set[int]] = defaultdict(set)
    for proof in normalized:
        by_item[proof.item_id].append(proof)
        if proof.freshness_class != FRESHNESS_REFRESH_PROVEN:
            noneligible[proof.freshness_class].add(proof.item_id)

    already_current = {int(item_id) for item_id in already_current_item_ids}
    eligible: list[dict[str, Any]] = []
    noops: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for item_id in sorted(by_item):
        refresh = [
            proof for proof in by_item[item_id] if proof.freshness_class == FRESHNESS_REFRESH_PROVEN
        ]
        if not refresh:
            continue
        current_hash = current_record_sha256.get(item_id)
        matching = [proof for proof in refresh if proof.raw_record_sha256 == current_hash]
        if current_hash is None or not matching:
            excluded.append(
                {
                    "item_id": item_id,
                    "reason": "current_record_missing_or_hash_drift_from_refresh_proof",
                    "current_record_sha256": current_hash,
                    "proven_record_sha256": sorted(
                        {
                            proof.raw_record_sha256
                            for proof in refresh
                            if proof.raw_record_sha256 is not None
                        }
                    ),
                    "proofs": [proof.to_json() for proof in refresh],
                }
            )
            continue
        row = {
            "item_id": item_id,
            "current_record_sha256": current_hash,
            "freshness_class": FRESHNESS_REFRESH_PROVEN,
            "matching_proofs": [proof.to_json() for proof in matching],
        }
        if item_id in already_current:
            noops.append({**row, "reason": "already_current_direct_projection"})
        else:
            eligible.append(row)

    artifacts = tuple(dict(entry) for entry in evidence_artifacts)
    payload = {
        "canonical_sha256": canonical_sha256,
        "canonical_migration": canonical_migration,
        "itemcache_sha256": itemcache_sha256,
        "itemcache_locale": itemcache_locale,
        "itemcache_client_version": itemcache_client_version,
        "evidence_artifacts": artifacts,
        "evidence_class_counts": dict(sorted(class_counts.items())),
        "campaign_counts": dict(
            sorted((str(key), int(value)) for key, value in current_campaign_counts.items())
        ),
        "eligible_items": eligible,
        "already_current_noops": noops,
        "excluded_refresh_proven": excluded,
        "noneligible_class_item_counts": {
            key: len(values) for key, values in sorted(noneligible.items())
        },
    }
    revision = _revision(b"octogamedb-p6-t05-incremental-plan-v1", payload)
    return IncrementalPromotionPlan(
        canonical_sha256=canonical_sha256,
        canonical_migration=canonical_migration,
        itemcache_sha256=itemcache_sha256,
        itemcache_locale=itemcache_locale,
        itemcache_client_version=itemcache_client_version,
        evidence_artifacts=artifacts,
        evidence_class_counts=dict(sorted(class_counts.items())),
        campaign_counts=dict(
            sorted((str(key), int(value)) for key, value in current_campaign_counts.items())
        ),
        eligible_items=tuple(eligible),
        already_current_noops=tuple(noops),
        excluded_refresh_proven=tuple(excluded),
        noneligible_class_item_counts={
            key: len(values) for key, values in sorted(noneligible.items())
        },
        plan_revision=revision,
    )


def write_plan(path: str | Path, plan: IncrementalPromotionPlan) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(plan.to_json(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
