"""P6-T04 evidence planning for guarded migration-14 canonical promotion.

The module deliberately separates evidence eligibility from SQLite mutation.  Only exact raw WDB
bytes already proved fresh by D-037 are eligible for automatic canonical selection; historical,
session-only and unknown observations remain excluded from this promotion cycle.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FRESHNESS_REFRESH_PROVEN = "refresh_proven_direct_observation"
FRESHNESS_SESSION_OBSERVED = "session_observed_freshness_limited"
FRESHNESS_HISTORICAL_CACHE = "historical_cache_only"
FRESHNESS_UNKNOWN = "unknown"

PROMOTION_FORMAT = "octogamedb-p6-t04-promotion-plan"
PROMOTION_VERSION = 1
TARGET_MIGRATION = 14

_ACCEPTED_FRESHNESS_CLASSES = frozenset(
    {
        FRESHNESS_REFRESH_PROVEN,
        FRESHNESS_SESSION_OBSERVED,
        FRESHNESS_HISTORICAL_CACHE,
        FRESHNESS_UNKNOWN,
    }
)


@dataclass(frozen=True)
class FreshnessProof:
    """One exact persisted-byte freshness proof from P6-T02 or P6-T03."""

    item_id: int
    freshness_class: str
    raw_record_sha256: str | None
    proof_kind: str
    proof_revision: str
    artifact_sha256: str
    campaign_id: str | None = None
    session_revision: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "freshness_class": self.freshness_class,
            "raw_record_sha256": self.raw_record_sha256,
            "proof_kind": self.proof_kind,
            "proof_revision": self.proof_revision,
            "artifact_sha256": self.artifact_sha256,
            "campaign_id": self.campaign_id,
            "session_revision": self.session_revision,
        }


@dataclass(frozen=True)
class PromotionPlan:
    """Deterministic, read-only plan binding evidence to the exact current cache bytes."""

    canonical_sha256: str
    canonical_migration: int
    target_migration: int
    itemcache_sha256: str
    itemcache_locale: str
    itemcache_client_version: int
    evidence_artifacts: tuple[dict[str, Any], ...]
    evidence_class_counts: dict[str, int]
    eligible_items: tuple[dict[str, Any], ...]
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
            "target_migration": self.target_migration,
            "itemcache": {
                "sha256": self.itemcache_sha256,
                "locale": self.itemcache_locale,
                "client_version": self.itemcache_client_version,
            },
            "evidence_artifacts": list(self.evidence_artifacts),
            "evidence_class_counts": self.evidence_class_counts,
            "eligible_item_ids": list(self.eligible_item_ids),
            "eligible_items": list(self.eligible_items),
            "excluded_refresh_proven": list(self.excluded_refresh_proven),
            "noneligible_class_item_counts": self.noneligible_class_item_counts,
            "policy": {
                "automatic_selection_eligible_class": FRESHNESS_REFRESH_PROVEN,
                "session_observed_freshness_limited": "excluded_no_persisted_proven_field_bytes",
                "historical_cache_only": "excluded_not_currentness_proven",
                "unknown": "excluded_never_negative_or_selection_authority",
                "raw_hash_match_required": True,
                "cache_only_identity_fabrication": False,
            },
            "plan_revision": self.plan_revision,
        }


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
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
    digest.update(_canonical_json_bytes(value))
    return f"sha256:{digest.hexdigest()}"


def _require_sha256(value: Any, *, label: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text.lower()):
        raise ValueError(f"{label} must be a lowercase/hex SHA-256 digest")
    return text.lower()


def _freshness_class(value: Any, *, label: str) -> str:
    text = str(value or "")
    if text not in _ACCEPTED_FRESHNESS_CLASSES:
        raise ValueError(f"{label} has unsupported freshness class {text!r}")
    return text


def load_json_object(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path}: JSON root must be an object")
    return payload


def proofs_from_p6_t02_report(
    report: Mapping[str, Any],
    *,
    artifact_sha256: str,
    expected_canonical_sha256: str,
) -> tuple[FreshnessProof, ...]:
    """Read exact P6-T02 persisted-byte proofs from one successful refresh report."""

    if int(report.get("report_version", 0)) != 2:
        raise ValueError("P6-T02 refresh report must have report_version=2")
    preflight = report.get("preflight")
    if not isinstance(preflight, Mapping):
        raise TypeError("P6-T02 refresh report lacks preflight metadata")
    canonical_sha = str(preflight.get("canonical_sha256", ""))
    if canonical_sha != expected_canonical_sha256:
        raise ValueError(
            "P6-T02 refresh report canonical SHA does not match the accepted P6-T04 baseline"
        )
    coverage_revision = str(preflight.get("coverage_revision", ""))
    if not coverage_revision.startswith("sha256:"):
        raise ValueError("P6-T02 refresh report lacks a deterministic coverage revision")

    classifications = report.get("classifications")
    if not isinstance(classifications, list):
        raise TypeError("P6-T02 refresh report classifications must be a list")

    proofs: list[FreshnessProof] = []
    for raw in classifications:
        if not isinstance(raw, Mapping):
            raise TypeError("P6-T02 classification entries must be objects")
        item_id = int(raw.get("item_id", 0))
        if item_id <= 0:
            raise ValueError("P6-T02 classification item_id must be positive")
        freshness = _freshness_class(
            raw.get("freshness_class"), label=f"P6-T02 item {item_id}"
        )
        raw_hash = raw.get("post_record_sha256")
        if raw_hash is not None:
            raw_hash = _require_sha256(raw_hash, label=f"P6-T02 item {item_id} post hash")
        if freshness == FRESHNESS_REFRESH_PROVEN and raw_hash is None:
            raise ValueError(f"P6-T02 refresh-proven item {item_id} lacks post-record hash")

        capture = report.get("capture")
        probe_id = capture.get("probe_id") if isinstance(capture, Mapping) else None
        proof_revision = _revision(
            b"octogamedb-p6-t02-refresh-proof-v1",
            {
                "artifact_sha256": artifact_sha256,
                "coverage_revision": coverage_revision,
                "probe_id": probe_id,
                "item_id": item_id,
                "freshness_class": freshness,
                "post_record_sha256": raw_hash,
            },
        )
        proofs.append(
            FreshnessProof(
                item_id=item_id,
                freshness_class=freshness,
                raw_record_sha256=raw_hash,
                proof_kind="p6_t02_refresh_report",
                proof_revision=proof_revision,
                artifact_sha256=artifact_sha256,
            )
        )
    return tuple(proofs)


def _campaign_session_revision_by_item(ledger: Mapping[str, Any]) -> dict[int, str]:
    revisions: dict[int, str] = {}
    sessions = ledger.get("sessions", [])
    if not isinstance(sessions, list):
        raise TypeError("P6-T03 campaign sessions must be a list")
    for session in sessions:
        if not isinstance(session, Mapping):
            raise TypeError("P6-T03 campaign session must be an object")
        merge_revision = str(session.get("merge_revision", ""))
        if not merge_revision.startswith("sha256:"):
            raise ValueError("P6-T03 campaign session lacks deterministic merge_revision")
        classifications = session.get("classifications", [])
        if not isinstance(classifications, list):
            raise TypeError("P6-T03 session classifications must be a list")
        for classification in classifications:
            if not isinstance(classification, Mapping):
                raise TypeError("P6-T03 session classification must be an object")
            item_id = int(classification.get("item_id", 0))
            if item_id > 0:
                revisions[item_id] = merge_revision
    return revisions


def proofs_from_p6_t03_ledger(
    ledger: Mapping[str, Any],
    *,
    artifact_sha256: str,
    expected_canonical_sha256: str,
) -> tuple[FreshnessProof, ...]:
    """Read the durable final P6-T03 per-item evidence state without broadening its semantics."""

    if ledger.get("format") != "octogamedb-itemcache-acquisition-campaign":
        raise ValueError("unsupported P6-T03 campaign ledger format")
    if int(ledger.get("version", 0)) != 1:
        raise ValueError("unsupported P6-T03 campaign ledger version")
    canonical = ledger.get("canonical")
    if not isinstance(canonical, Mapping):
        raise TypeError("P6-T03 campaign lacks canonical metadata")
    if str(canonical.get("sha256", "")) != expected_canonical_sha256:
        raise ValueError("P6-T03 campaign canonical SHA does not match the P6-T04 baseline")
    if int(canonical.get("migration", -1)) != 13:
        raise ValueError("P6-T03 campaign was not anchored to migration 13")

    campaign_id = str(ledger.get("campaign_id", ""))
    if not campaign_id.startswith("sha256:"):
        raise ValueError("P6-T03 campaign lacks deterministic campaign_id")
    session_revisions = _campaign_session_revision_by_item(ledger)
    items = ledger.get("items")
    if not isinstance(items, Mapping):
        raise TypeError("P6-T03 campaign items must be an object")

    proofs: list[FreshnessProof] = []
    for raw_item_id, raw in items.items():
        if not isinstance(raw, Mapping):
            raise TypeError(f"P6-T03 campaign item {raw_item_id} must be an object")
        item_id = int(raw_item_id)
        if item_id <= 0:
            raise ValueError("P6-T03 campaign item IDs must be positive")
        freshness = _freshness_class(
            raw.get("freshness_class"), label=f"P6-T03 item {item_id}"
        )
        raw_hash = raw.get("post_record_sha256")
        if raw_hash is not None:
            raw_hash = _require_sha256(raw_hash, label=f"P6-T03 item {item_id} post hash")
        if freshness == FRESHNESS_REFRESH_PROVEN and raw_hash is None:
            raise ValueError(f"P6-T03 refresh-proven item {item_id} lacks post-record hash")

        session_revision = session_revisions.get(item_id)
        proof_revision = _revision(
            b"octogamedb-p6-t03-final-item-proof-v1",
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
                proof_kind="p6_t03_campaign_ledger",
                proof_revision=proof_revision,
                artifact_sha256=artifact_sha256,
                campaign_id=campaign_id,
                session_revision=session_revision,
            )
        )
    return tuple(proofs)


def build_promotion_plan(
    *,
    canonical_sha256: str,
    canonical_migration: int,
    itemcache_sha256: str,
    itemcache_locale: str,
    itemcache_client_version: int,
    current_record_sha256: Mapping[int, str],
    proofs: Iterable[FreshnessProof],
    evidence_artifacts: Sequence[Mapping[str, Any]],
) -> PromotionPlan:
    """Bind accepted freshness proofs to the exact current WDB record bytes.

    A refresh-proven item is eligible only if the current raw record hash is identical to at
    least one refresh-proven proof hash. Later cache drift is not silently relabelled fresh.
    """

    if canonical_migration != 13:
        raise ValueError(f"P6-T04 planning requires migration 13, found {canonical_migration}")
    if not canonical_sha256:
        raise ValueError("canonical_sha256 must not be empty")
    if not itemcache_sha256:
        raise ValueError("itemcache_sha256 must not be empty")

    normalized_proofs = tuple(
        sorted(
            proofs,
            key=lambda proof: (
                proof.item_id,
                proof.freshness_class,
                proof.raw_record_sha256 or "",
                proof.proof_kind,
                proof.proof_revision,
                proof.artifact_sha256,
            ),
        )
    )
    counts = Counter(proof.freshness_class for proof in normalized_proofs)
    by_item: dict[int, list[FreshnessProof]] = defaultdict(list)
    noneligible_items: dict[str, set[int]] = defaultdict(set)
    for proof in normalized_proofs:
        by_item[proof.item_id].append(proof)
        if proof.freshness_class != FRESHNESS_REFRESH_PROVEN:
            noneligible_items[proof.freshness_class].add(proof.item_id)

    eligible: list[dict[str, Any]] = []
    excluded_refresh: list[dict[str, Any]] = []
    for item_id in sorted(by_item):
        refresh_proofs = [
            proof
            for proof in by_item[item_id]
            if proof.freshness_class == FRESHNESS_REFRESH_PROVEN
        ]
        if not refresh_proofs:
            continue
        current_hash = current_record_sha256.get(item_id)
        matching = [proof for proof in refresh_proofs if proof.raw_record_sha256 == current_hash]
        if current_hash is not None and matching:
            eligible.append(
                {
                    "item_id": item_id,
                    "current_record_sha256": current_hash,
                    "freshness_class": FRESHNESS_REFRESH_PROVEN,
                    "matching_proofs": [proof.to_json() for proof in matching],
                }
            )
            continue

        excluded_refresh.append(
            {
                "item_id": item_id,
                "reason": "current_record_missing_or_hash_drift_from_refresh_proof",
                "current_record_sha256": current_hash,
                "proven_record_sha256": sorted(
                    {
                        proof.raw_record_sha256
                        for proof in refresh_proofs
                        if proof.raw_record_sha256 is not None
                    }
                ),
                "proofs": [proof.to_json() for proof in refresh_proofs],
            }
        )

    normalized_artifacts = tuple(
        sorted(
            (dict(artifact) for artifact in evidence_artifacts),
            key=lambda artifact: (
                str(artifact.get("kind", "")),
                str(artifact.get("sha256", "")),
                str(artifact.get("name", "")),
            ),
        )
    )
    semantic = {
        "canonical_sha256": canonical_sha256,
        "canonical_migration": canonical_migration,
        "target_migration": TARGET_MIGRATION,
        "itemcache_sha256": itemcache_sha256,
        "itemcache_locale": itemcache_locale,
        "itemcache_client_version": int(itemcache_client_version),
        "evidence_artifacts": normalized_artifacts,
        "evidence_class_counts": dict(sorted(counts.items())),
        "eligible_items": eligible,
        "excluded_refresh_proven": excluded_refresh,
        "noneligible_class_item_counts": {
            key: len(value) for key, value in sorted(noneligible_items.items())
        },
    }
    plan_revision = _revision(b"octogamedb-p6-t04-promotion-plan-v1", semantic)
    return PromotionPlan(
        canonical_sha256=canonical_sha256,
        canonical_migration=canonical_migration,
        target_migration=TARGET_MIGRATION,
        itemcache_sha256=itemcache_sha256,
        itemcache_locale=itemcache_locale,
        itemcache_client_version=int(itemcache_client_version),
        evidence_artifacts=normalized_artifacts,
        evidence_class_counts=dict(sorted(counts.items())),
        eligible_items=tuple(eligible),
        excluded_refresh_proven=tuple(excluded_refresh),
        noneligible_class_item_counts={
            key: len(value) for key, value in sorted(noneligible_items.items())
        },
        plan_revision=plan_revision,
    )


def write_plan(path: str | Path, plan: PromotionPlan) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(plan.to_json(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
