"""Durable read-only acquisition campaign state for direct Octo item queries.

P6-T03 scales the P6-T02 query-scoped freshness proof without changing its evidence semantics.
The campaign ledger is an ignored local checkpoint; it is not canonical database state.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from octogamedb.itemcache_coverage import (
    FRESHNESS_HISTORICAL_CACHE,
    FRESHNESS_REFRESH_PROVEN,
    FRESHNESS_SESSION_OBSERVED,
    FRESHNESS_UNKNOWN,
    PROBE_STATUS_ALREADY_CACHED,
    PROBE_STATUS_LOADED_AFTER_QUERY,
    PROBE_STATUS_TIMEOUT,
    classify_probe_observation,
)

CAMPAIGN_FORMAT = "octogamedb-itemcache-acquisition-campaign"
CAMPAIGN_VERSION = 1
DEFAULT_BATCH_LIMIT = 10
MAX_BATCH_LIMIT = 20
DEFAULT_MAX_CAMPAIGN_ATTEMPTS = 2

STATE_QUEUED = "queued"
STATE_IN_FLIGHT = "in_flight"
STATE_REFRESH_PROVEN = FRESHNESS_REFRESH_PROVEN
STATE_SESSION_OBSERVED = FRESHNESS_SESSION_OBSERVED
STATE_HISTORICAL_CACHE = FRESHNESS_HISTORICAL_CACHE
STATE_UNKNOWN_RETRYABLE = "unknown_retryable"
STATE_UNKNOWN_TERMINAL = "unknown_terminal_or_deferred"

TERMINAL_STATES = frozenset(
    {
        STATE_REFRESH_PROVEN,
        STATE_SESSION_OBSERVED,
        STATE_HISTORICAL_CACHE,
        STATE_UNKNOWN_TERMINAL,
    }
)
ELIGIBLE_STATES = frozenset({STATE_QUEUED, STATE_UNKNOWN_RETRYABLE})
PROBE_TERMINAL_STATUSES = frozenset(
    {PROBE_STATUS_ALREADY_CACHED, PROBE_STATUS_LOADED_AFTER_QUERY, PROBE_STATUS_TIMEOUT}
)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256_revision(domain: bytes, value: Any) -> str:
    digest = hashlib.sha256()
    digest.update(domain)
    digest.update(b"\0")
    digest.update(_json_bytes(value))
    return f"sha256:{digest.hexdigest()}"


def compute_candidate_revision(
    *, canonical_sha256: str, coverage_revision: str, candidate_item_ids: Iterable[int]
) -> str:
    ids = sorted({int(item_id) for item_id in candidate_item_ids if int(item_id) > 0})
    return _sha256_revision(
        b"octogamedb-p6-t03-candidates-v1",
        {
            "canonical_sha256": canonical_sha256,
            "coverage_revision": coverage_revision,
            "candidate_item_ids": ids,
        },
    )


def compute_campaign_id(
    *, canonical_sha256: str, coverage_revision: str, candidate_revision: str
) -> str:
    return _sha256_revision(
        b"octogamedb-p6-t03-campaign-v1",
        {
            "canonical_sha256": canonical_sha256,
            "coverage_revision": coverage_revision,
            "candidate_revision": candidate_revision,
        },
    )


def compute_session_request_revision(
    *,
    campaign_id: str,
    ordinal: int,
    pre_coverage_revision: str,
    requested_item_ids: Sequence[int],
) -> str:
    return _sha256_revision(
        b"octogamedb-p6-t03-session-request-v1",
        {
            "campaign_id": campaign_id,
            "ordinal": int(ordinal),
            "pre_coverage_revision": pre_coverage_revision,
            "requested_item_ids": [int(item_id) for item_id in requested_item_ids],
        },
    )


def compute_session_merge_revision(
    *,
    request_revision: str,
    export: Mapping[str, Any] | None,
    post_record_sha256: Mapping[int, str],
) -> str:
    normalized_export: dict[str, Any] | None = None
    if export is not None:
        raw_results = export.get("results", {})
        if not isinstance(raw_results, Mapping):
            raise TypeError("session export results must be a mapping")
        normalized_export = {
            "probe_id": export.get("probe_id"),
            "started": export.get("started"),
            "realm": export.get("realm"),
            "character": export.get("character"),
            "locale": export.get("locale"),
            "client_version": export.get("client_version"),
            "client_build": export.get("client_build"),
            "ids": [int(value) for value in export.get("ids", [])],
            "results": {
                str(int(item_id)): {
                    "initial": str(result.get("initial", "")),
                    "status": str(result.get("status", "")),
                }
                for item_id, result in sorted(
                    ((int(key), value) for key, value in raw_results.items()),
                    key=lambda pair: pair[0],
                )
            },
            "complete": bool(export.get("complete")),
        }
    return _sha256_revision(
        b"octogamedb-p6-t03-session-merge-v1",
        {
            "request_revision": request_revision,
            "export": normalized_export,
            "post_record_sha256": {
                str(int(item_id)): value
                for item_id, value in sorted(post_record_sha256.items())
            },
        },
    )


def atomic_write_ledger(path: str | Path, ledger: Mapping[str, Any]) -> None:
    """Replace a ledger atomically so interruption cannot leave a half-written JSON checkpoint."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    payload = json.dumps(ledger, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_ledger(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("campaign ledger root must be an object")
    validate_ledger(payload)
    return payload


def _candidate_ids(ledger: Mapping[str, Any]) -> list[int]:
    raw = ledger.get("candidate_item_ids")
    if not isinstance(raw, list):
        raise ValueError("campaign ledger candidate_item_ids must be a list")
    ids = [int(value) for value in raw]
    if ids != sorted(set(ids)) or any(item_id <= 0 for item_id in ids):
        raise ValueError("campaign candidate_item_ids must be unique positive IDs in sorted order")
    return ids


def validate_ledger(ledger: Mapping[str, Any]) -> None:
    if ledger.get("format") != CAMPAIGN_FORMAT:
        raise ValueError(f"unsupported campaign format: {ledger.get('format')!r}")
    if ledger.get("version") != CAMPAIGN_VERSION:
        raise ValueError(f"unsupported campaign version: {ledger.get('version')!r}")

    canonical = ledger.get("canonical")
    initial_cache = ledger.get("initial_cache")
    policy = ledger.get("policy")
    items = ledger.get("items")
    sessions = ledger.get("sessions")
    if not isinstance(canonical, Mapping) or not isinstance(initial_cache, Mapping):
        raise ValueError("campaign ledger lacks canonical/initial_cache metadata")
    if (
        not isinstance(policy, Mapping)
        or not isinstance(items, Mapping)
        or not isinstance(sessions, list)
    ):
        raise ValueError("campaign ledger policy/items/sessions shape is invalid")

    ids = _candidate_ids(ledger)
    candidate_revision = compute_candidate_revision(
        canonical_sha256=str(canonical.get("sha256", "")),
        coverage_revision=str(initial_cache.get("coverage_revision", "")),
        candidate_item_ids=ids,
    )
    if candidate_revision != ledger.get("candidate_revision"):
        raise ValueError("campaign candidate revision does not match ledger inputs")
    campaign_id = compute_campaign_id(
        canonical_sha256=str(canonical.get("sha256", "")),
        coverage_revision=str(initial_cache.get("coverage_revision", "")),
        candidate_revision=candidate_revision,
    )
    if campaign_id != ledger.get("campaign_id"):
        raise ValueError("campaign ID does not match ledger inputs")

    if set(items) != {str(item_id) for item_id in ids}:
        raise ValueError("campaign items mapping does not exactly match candidate IDs")
    allowed_states = ELIGIBLE_STATES | TERMINAL_STATES | {STATE_IN_FLIGHT}
    for item_id in ids:
        row = items[str(item_id)]
        if not isinstance(row, Mapping):
            raise ValueError(f"campaign item {item_id} must be an object")
        if row.get("state") not in allowed_states:
            raise ValueError(f"campaign item {item_id} has invalid state {row.get('state')!r}")
        attempts = int(row.get("attempt_count", -1))
        session_count = int(row.get("session_count", -1))
        if attempts < 0 or session_count < 0 or session_count > attempts:
            raise ValueError(f"campaign item {item_id} has invalid attempt/session counts")

    active = ledger.get("active_session")
    in_flight = [item_id for item_id in ids if items[str(item_id)]["state"] == STATE_IN_FLIGHT]
    if active is None and in_flight:
        raise ValueError("campaign has in_flight items but no active_session")
    if active is not None:
        if not isinstance(active, Mapping):
            raise ValueError("active_session must be an object or null")
        requested = [int(value) for value in active.get("requested_item_ids", [])]
        if not requested or any(
            items.get(str(item_id), {}).get("state") != STATE_IN_FLIGHT
            for item_id in requested
        ):
            raise ValueError("active_session requested IDs must all be in_flight")
        if sorted(in_flight) != sorted(requested):
            raise ValueError("all and only active_session requested IDs must be in_flight")


def create_campaign_ledger(
    *,
    canonical_sha256: str,
    canonical_migration: int,
    canonical_item_count: int,
    coverage_revision: str,
    cache_pre_exists: bool,
    cache_pre_sha256: str | None,
    initial_matching_cache_count: int,
    initial_cache_only_count: int,
    candidate_item_ids: Iterable[int],
    created_utc: str,
    batch_limit: int = DEFAULT_BATCH_LIMIT,
    max_campaign_attempts: int = DEFAULT_MAX_CAMPAIGN_ATTEMPTS,
) -> dict[str, Any]:
    ids = sorted({int(item_id) for item_id in candidate_item_ids if int(item_id) > 0})
    if not ids:
        raise ValueError("campaign requires at least one known canonical cache-missing ID")
    if not 1 <= batch_limit <= MAX_BATCH_LIMIT:
        raise ValueError(f"batch_limit must be between 1 and {MAX_BATCH_LIMIT}")
    if max_campaign_attempts < 1:
        raise ValueError("max_campaign_attempts must be positive")

    candidate_revision = compute_candidate_revision(
        canonical_sha256=canonical_sha256,
        coverage_revision=coverage_revision,
        candidate_item_ids=ids,
    )
    campaign_id = compute_campaign_id(
        canonical_sha256=canonical_sha256,
        coverage_revision=coverage_revision,
        candidate_revision=candidate_revision,
    )
    ledger: dict[str, Any] = {
        "format": CAMPAIGN_FORMAT,
        "version": CAMPAIGN_VERSION,
        "campaign_id": campaign_id,
        "created_utc": created_utc,
        "updated_utc": created_utc,
        "canonical": {
            "sha256": canonical_sha256,
            "migration": int(canonical_migration),
            "item_count": int(canonical_item_count),
        },
        "initial_cache": {
            "exists": bool(cache_pre_exists),
            "sha256": cache_pre_sha256,
            "coverage_revision": coverage_revision,
            "matching_canonical_count": int(initial_matching_cache_count),
            "cache_only_native_id_count": int(initial_cache_only_count),
        },
        "candidate_revision": candidate_revision,
        "candidate_item_ids": ids,
        "policy": {
            "batch_limit": int(batch_limit),
            "max_campaign_attempts": int(max_campaign_attempts),
            "client_poll_seconds": 0.20,
            "client_retry_seconds": 3.0,
            "client_timeout_seconds": 15.0,
            "client_max_attempts_per_session": 5,
            "one_outstanding_query": True,
        },
        "items": {
            str(item_id): {
                "state": STATE_QUEUED,
                "attempt_count": 0,
                "session_count": 0,
                "last_probe_status": None,
                "freshness_class": FRESHNESS_UNKNOWN,
                "pre_record_sha256": None,
                "post_record_sha256": None,
                "last_session_request_revision": None,
                "terminal": False,
                "retryable": True,
                "reason": (
                    "Known canonical item ID absent from the campaign initial cache snapshot."
                ),
                "updated_utc": created_utc,
            }
            for item_id in ids
        },
        "active_session": None,
        "sessions": [],
        "duplicate_noop_session_imports": 0,
    }
    validate_ledger(ledger)
    return ledger


def _spread_select(values: Sequence[int], limit: int) -> list[int]:
    ordered = sorted({int(value) for value in values})
    if limit <= 0 or not ordered:
        return []
    if len(ordered) <= limit:
        return ordered
    if limit == 1:
        return [ordered[len(ordered) // 2]]
    indexes = [round(index * (len(ordered) - 1) / (limit - 1)) for index in range(limit)]
    return [ordered[index] for index in indexes]


def select_next_batch(ledger: Mapping[str, Any], *, limit: int | None = None) -> tuple[int, ...]:
    validate_ledger(ledger)
    if ledger.get("active_session") is not None:
        raise RuntimeError("campaign has an active in-flight session; merge or recover it first")
    policy_limit = int(ledger["policy"]["batch_limit"])
    batch_limit = policy_limit if limit is None else int(limit)
    if not 1 <= batch_limit <= min(policy_limit, MAX_BATCH_LIMIT):
        raise ValueError("batch selection limit exceeds the campaign policy")

    ids = _candidate_ids(ledger)
    items = ledger["items"]
    queued = [item_id for item_id in ids if items[str(item_id)]["state"] == STATE_QUEUED]
    retryable = [
        item_id for item_id in ids if items[str(item_id)]["state"] == STATE_UNKNOWN_RETRYABLE
    ]

    if retryable and queued and batch_limit >= 2:
        retry_part = _spread_select(retryable, 1)
        queued_part = _spread_select(queued, batch_limit - 1)
        return tuple(retry_part + queued_part)
    if queued:
        return tuple(_spread_select(queued, batch_limit))
    return tuple(_spread_select(retryable, batch_limit))


def reconcile_pre_session_cache_presence(
    ledger: dict[str, Any], *, current_record_sha256: Mapping[int, str], updated_utc: str
) -> list[int]:
    """Conservatively retire newly pre-cached eligible IDs without calling them fresh."""

    validate_ledger(ledger)
    if ledger.get("active_session") is not None:
        raise RuntimeError("cannot reconcile pre-session cache while a session is active")
    changed: list[int] = []
    for item_id in _candidate_ids(ledger):
        row = ledger["items"][str(item_id)]
        if row["state"] not in ELIGIBLE_STATES:
            continue
        record_hash = current_record_sha256.get(item_id)
        if record_hash is None:
            continue
        row.update(
            {
                "state": STATE_HISTORICAL_CACHE,
                "last_probe_status": PROBE_STATUS_ALREADY_CACHED,
                "freshness_class": FRESHNESS_HISTORICAL_CACHE,
                "pre_record_sha256": record_hash,
                "post_record_sha256": record_hash,
                "terminal": True,
                "retryable": False,
                "reason": (
                    "The candidate is present before this campaign session. Its raw cache record "
                    "is "
                    "positive Octo evidence, but D-037 does not treat pre-existing cache presence "
                    "as current-session freshness proof."
                ),
                "updated_utc": updated_utc,
            }
        )
        changed.append(item_id)
    if changed:
        ledger["updated_utc"] = updated_utc
    validate_ledger(ledger)
    return changed


def begin_session(
    ledger: dict[str, Any],
    *,
    requested_item_ids: Sequence[int],
    pre_coverage_revision: str,
    pre_cache_exists: bool,
    pre_cache_sha256: str | None,
    pre_record_sha256: Mapping[int, str | None],
    started_utc: str,
) -> str:
    validate_ledger(ledger)
    if ledger.get("active_session") is not None:
        raise RuntimeError("campaign already has an active session")
    requested = [int(item_id) for item_id in requested_item_ids]
    if not requested or len(requested) != len(set(requested)):
        raise ValueError("session requested IDs must be a non-empty unique sequence")
    if len(requested) > int(ledger["policy"]["batch_limit"]):
        raise ValueError("session request exceeds campaign batch_limit")

    items = ledger["items"]
    for item_id in requested:
        row = items.get(str(item_id))
        if row is None or row["state"] not in ELIGIBLE_STATES:
            raise ValueError(f"item {item_id} is not eligible for a campaign session")
        if pre_record_sha256.get(item_id) is not None:
            raise ValueError(
                f"item {item_id} has a pre-session WDB record; reconcile it as historical first"
            )

    ordinal = len(ledger["sessions"]) + 1
    request_revision = compute_session_request_revision(
        campaign_id=str(ledger["campaign_id"]),
        ordinal=ordinal,
        pre_coverage_revision=pre_coverage_revision,
        requested_item_ids=requested,
    )
    for item_id in requested:
        row = items[str(item_id)]
        row["state"] = STATE_IN_FLIGHT
        row["attempt_count"] = int(row["attempt_count"]) + 1
        row["session_count"] = int(row["session_count"]) + 1
        row["last_session_request_revision"] = request_revision
        row["pre_record_sha256"] = None
        row["reason"] = "Reserved for the active bounded client session; outcome not yet observed."
        row["terminal"] = False
        row["retryable"] = False
        row["updated_utc"] = started_utc

    ledger["active_session"] = {
        "ordinal": ordinal,
        "request_revision": request_revision,
        "started_utc": started_utc,
        "requested_item_ids": requested,
        "pre_coverage_revision": pre_coverage_revision,
        "pre_cache_exists": bool(pre_cache_exists),
        "pre_cache_sha256": pre_cache_sha256,
        "pre_record_sha256": {
            str(item_id): pre_record_sha256.get(item_id) for item_id in requested
        },
    }
    ledger["updated_utc"] = started_utc
    validate_ledger(ledger)
    return request_revision


def _unknown_state(row: Mapping[str, Any], max_attempts: int) -> tuple[str, bool, bool]:
    retryable = int(row["attempt_count"]) < max_attempts
    if retryable:
        return STATE_UNKNOWN_RETRYABLE, False, True
    return STATE_UNKNOWN_TERMINAL, True, False


def _normalize_results(export: Mapping[str, Any]) -> dict[int, Mapping[str, Any]]:
    raw = export.get("results")
    if not isinstance(raw, Mapping):
        raise ValueError("session export results must be a mapping")
    results: dict[int, Mapping[str, Any]] = {}
    for raw_id, raw_result in raw.items():
        item_id = int(raw_id)
        if item_id in results:
            raise ValueError(f"duplicate result for item {item_id}")
        if not isinstance(raw_result, Mapping):
            raise ValueError(f"result for item {item_id} must be an object")
        status = str(raw_result.get("status", ""))
        if status not in PROBE_TERMINAL_STATUSES:
            raise ValueError(f"unsupported probe status for item {item_id}: {status!r}")
        initial = str(raw_result.get("initial", ""))
        if initial not in {"missing", "present"}:
            raise ValueError(f"unsupported initial cache state for item {item_id}: {initial!r}")
        results[item_id] = raw_result
    return results


def merge_active_session(
    ledger: dict[str, Any],
    *,
    export: Mapping[str, Any],
    post_record_sha256: Mapping[int, str],
    post_cache_exists: bool,
    post_cache_sha256: str | None,
    merged_utc: str,
    require_complete: bool,
) -> dict[str, Any]:
    """Merge one SavedVariables/WDB observation without duplicating or downgrading evidence."""

    validate_ledger(ledger)
    active = ledger.get("active_session")
    exported_ids = [int(value) for value in export.get("ids", [])]
    if isinstance(active, Mapping):
        requested = [int(value) for value in active["requested_item_ids"]]
    else:
        # Re-importing the just-completed SavedVariables/WDB pair is a supported no-op.  Resolve
        # its immutable request metadata from history before touching any item state.
        historical = next(
            (
                session
                for session in reversed(ledger["sessions"])
                if [int(value) for value in session.get("requested_item_ids", [])] == exported_ids
            ),
            None,
        )
        if historical is None:
            raise RuntimeError("campaign has no active or matching historical session to merge")
        active = {
            "ordinal": historical["ordinal"],
            "request_revision": historical["request_revision"],
            "started_utc": historical["started_utc"],
            "requested_item_ids": historical["requested_item_ids"],
            "pre_coverage_revision": historical["pre_coverage_revision"],
            "pre_cache_exists": historical["pre_cache_exists"],
            "pre_cache_sha256": historical["pre_cache_sha256"],
            "pre_record_sha256": {str(item_id): None for item_id in exported_ids},
        }
        requested = exported_ids
    if exported_ids != requested:
        raise ValueError(
            f"SavedVariables ID list does not match active session: expected={requested} "
            f"actual={exported_ids}"
        )
    complete = bool(export.get("complete"))
    if require_complete and not complete:
        raise ValueError("SavedVariables capture is incomplete")
    results = _normalize_results(export)
    extra = sorted(set(results) - set(requested))
    if extra:
        raise ValueError(f"SavedVariables contains results outside active session: {extra}")
    if complete:
        missing = [item_id for item_id in requested if item_id not in results]
        if missing:
            raise ValueError(f"complete SavedVariables capture lacks requested IDs: {missing}")

    merge_revision = compute_session_merge_revision(
        request_revision=str(active["request_revision"]),
        export=export,
        post_record_sha256={
            item_id: post_record_sha256[item_id]
            for item_id in requested
            if item_id in post_record_sha256
        },
    )
    existing = next(
        (
            session
            for session in ledger["sessions"]
            if session.get("merge_revision") == merge_revision
        ),
        None,
    )
    if existing is not None:
        ledger["duplicate_noop_session_imports"] = int(
            ledger.get("duplicate_noop_session_imports", 0)
        ) + 1
        ledger["updated_utc"] = merged_utc
        return {"duplicate": True, "merge_revision": merge_revision, "classifications": []}

    max_attempts = int(ledger["policy"]["max_campaign_attempts"])
    classifications: list[dict[str, Any]] = []
    newly_materialized = 0
    for item_id in requested:
        row = ledger["items"][str(item_id)]
        if row["state"] != STATE_IN_FLIGHT:
            raise ValueError(f"active item {item_id} is no longer in_flight")
        result = results.get(item_id)
        post_hash = post_record_sha256.get(item_id)
        if post_hash is not None:
            newly_materialized += 1
        if result is None:
            state, terminal, retryable = _unknown_state(row, max_attempts)
            row.update(
                {
                    "state": state,
                    "last_probe_status": None,
                    "freshness_class": FRESHNESS_UNKNOWN,
                    "post_record_sha256": post_hash,
                    "terminal": terminal,
                    "retryable": retryable,
                    "reason": (
                        "The client session ended/interrupted without a supported per-ID result. "
                        "No negative item evidence is inferred."
                    ),
                    "updated_utc": merged_utc,
                }
            )
            classifications.append(
                {
                    "item_id": item_id,
                    "freshness_class": FRESHNESS_UNKNOWN,
                    "state": state,
                    "probe_status": None,
                    "reason": row["reason"],
                }
            )
            continue

        status = str(result["status"])
        classification = classify_probe_observation(
            item_id=item_id,
            pre_record_sha256=active["pre_record_sha256"].get(str(item_id)),
            post_record_sha256=post_hash,
            probe_status=status,
        )
        if classification.freshness_class == FRESHNESS_REFRESH_PROVEN:
            state, terminal, retryable = STATE_REFRESH_PROVEN, True, False
        elif classification.freshness_class == FRESHNESS_SESSION_OBSERVED:
            state, terminal, retryable = STATE_SESSION_OBSERVED, True, False
        elif classification.freshness_class == FRESHNESS_HISTORICAL_CACHE:
            state, terminal, retryable = STATE_HISTORICAL_CACHE, True, False
        else:
            state, terminal, retryable = _unknown_state(row, max_attempts)

        row.update(
            {
                "state": state,
                "last_probe_status": status,
                "freshness_class": classification.freshness_class,
                "post_record_sha256": post_hash,
                "terminal": terminal,
                "retryable": retryable,
                "reason": classification.reason,
                "updated_utc": merged_utc,
            }
        )
        classifications.append({**classification.to_json(), "state": state})

    session = {
        "ordinal": int(active["ordinal"]),
        "request_revision": str(active["request_revision"]),
        "merge_revision": merge_revision,
        "started_utc": active["started_utc"],
        "merged_utc": merged_utc,
        "requested_item_ids": requested,
        "pre_coverage_revision": active["pre_coverage_revision"],
        "pre_cache_exists": active["pre_cache_exists"],
        "pre_cache_sha256": active["pre_cache_sha256"],
        "capture": {
            "probe_id": export.get("probe_id"),
            "started": export.get("started"),
            "realm": export.get("realm"),
            "character": export.get("character"),
            "locale": export.get("locale"),
            "client_version": export.get("client_version"),
            "client_build": export.get("client_build"),
            "complete": complete,
        },
        "post_cache_exists": bool(post_cache_exists),
        "post_cache_sha256": post_cache_sha256,
        "newly_materialized_wdb_record_count": newly_materialized,
        "classifications": classifications,
    }
    ledger["sessions"].append(session)
    ledger["active_session"] = None
    ledger["updated_utc"] = merged_utc
    validate_ledger(ledger)
    return {
        "duplicate": False,
        "merge_revision": merge_revision,
        "classifications": classifications,
        "newly_materialized_wdb_record_count": newly_materialized,
    }


def recover_active_session_without_export(
    ledger: dict[str, Any],
    *,
    post_record_sha256: Mapping[int, str],
    recovered_utc: str,
) -> dict[str, Any]:
    """Recover an interrupted session when no matching SavedVariables export survived.

    A post-WDB record without matching session-success evidence is retained as positive bytes but is
    freshness-unknown and deferred: re-querying it would start from a historical cache hit and could
    no longer reproduce P6-T02's cache-miss freshness proof without cache rotation.
    """

    validate_ledger(ledger)
    active = ledger.get("active_session")
    if not isinstance(active, Mapping):
        raise RuntimeError("campaign has no active session to recover")
    requested = [int(value) for value in active["requested_item_ids"]]
    max_attempts = int(ledger["policy"]["max_campaign_attempts"])
    classifications: list[dict[str, Any]] = []
    for item_id in requested:
        row = ledger["items"][str(item_id)]
        post_hash = post_record_sha256.get(item_id)
        if post_hash is not None:
            state, terminal, retryable = STATE_UNKNOWN_TERMINAL, True, False
            reason = (
                "The item gained a post-session WDB record, but no matching SavedVariables result "
                "survived to prove the query outcome. Freshness remains unknown and the item is "
                "deferred rather than re-queried from a now-historical cache hit."
            )
        else:
            state, terminal, retryable = _unknown_state(row, max_attempts)
            reason = (
                "No matching SavedVariables result and no post-session WDB record survived. The "
                "interrupted attempt remains unknown and may be retried only within campaign "
                "policy."
            )
        row.update(
            {
                "state": state,
                "last_probe_status": None,
                "freshness_class": FRESHNESS_UNKNOWN,
                "post_record_sha256": post_hash,
                "terminal": terminal,
                "retryable": retryable,
                "reason": reason,
                "updated_utc": recovered_utc,
            }
        )
        classifications.append(
            {
                "item_id": item_id,
                "freshness_class": FRESHNESS_UNKNOWN,
                "state": state,
                "probe_status": None,
                "reason": reason,
            }
        )

    merge_revision = compute_session_merge_revision(
        request_revision=str(active["request_revision"]),
        export=None,
        post_record_sha256={
            item_id: post_record_sha256[item_id]
            for item_id in requested
            if item_id in post_record_sha256
        },
    )
    ledger["sessions"].append(
        {
            "ordinal": int(active["ordinal"]),
            "request_revision": str(active["request_revision"]),
            "merge_revision": merge_revision,
            "started_utc": active["started_utc"],
            "merged_utc": recovered_utc,
            "requested_item_ids": requested,
            "pre_coverage_revision": active["pre_coverage_revision"],
            "pre_cache_exists": active["pre_cache_exists"],
            "pre_cache_sha256": active["pre_cache_sha256"],
            "capture": None,
            "post_cache_exists": bool(post_record_sha256),
            "post_cache_sha256": None,
            "newly_materialized_wdb_record_count": sum(
                item_id in post_record_sha256 for item_id in requested
            ),
            "recovered_without_savedvariables": True,
            "classifications": classifications,
        }
    )
    ledger["active_session"] = None
    ledger["updated_utc"] = recovered_utc
    validate_ledger(ledger)
    return {
        "duplicate": False,
        "merge_revision": merge_revision,
        "classifications": classifications,
    }


def campaign_report(
    ledger: Mapping[str, Any],
    *,
    canonical_sha256_after: str,
    current_matching_cache_count: int | None = None,
    current_missing_cache_count: int | None = None,
) -> dict[str, Any]:
    validate_ledger(ledger)
    ids = _candidate_ids(ledger)
    items = ledger["items"]
    state_counts: dict[str, int] = {}
    freshness_counts: dict[str, int] = {}
    attempted = 0
    retries = 0
    materialized: set[int] = set()
    for item_id in ids:
        row = items[str(item_id)]
        state = str(row["state"])
        freshness = str(row["freshness_class"])
        state_counts[state] = state_counts.get(state, 0) + 1
        freshness_counts[freshness] = freshness_counts.get(freshness, 0) + 1
        attempts = int(row["attempt_count"])
        if attempts:
            attempted += 1
            retries += max(0, attempts - 1)
        if row.get("post_record_sha256") is not None:
            materialized.add(item_id)

    refresh_count = state_counts.get(STATE_REFRESH_PROVEN, 0)
    session_limited_count = state_counts.get(STATE_SESSION_OBSERVED, 0)
    unknown_count = state_counts.get(STATE_UNKNOWN_RETRYABLE, 0) + state_counts.get(
        STATE_UNKNOWN_TERMINAL, 0
    )
    terminal_deferred = state_counts.get(STATE_UNKNOWN_TERMINAL, 0)
    unattempted = state_counts.get(STATE_QUEUED, 0)

    def rate(count: int) -> float | None:
        return None if attempted == 0 else round(count / attempted, 8)

    success_ids = [
        item_id for item_id in ids if items[str(item_id)]["state"] == STATE_REFRESH_PROVEN
    ]
    unknown_ids = [
        item_id
        for item_id in ids
        if items[str(item_id)]["state"] in {STATE_UNKNOWN_RETRYABLE, STATE_UNKNOWN_TERMINAL}
    ]

    return {
        "report_version": 1,
        "campaign_id": ledger["campaign_id"],
        "candidate_revision": ledger["candidate_revision"],
        "canonical_sha256_before": ledger["canonical"]["sha256"],
        "canonical_sha256_after": canonical_sha256_after,
        "canonical_db_unchanged": canonical_sha256_after == ledger["canonical"]["sha256"],
        "initial_canonical_population": int(ledger["canonical"]["item_count"]),
        "initial_matching_cache_coverage": int(
            ledger["initial_cache"]["matching_canonical_count"]
        ),
        "campaign_candidate_count": len(ids),
        "attempted_unique_ids": attempted,
        "refresh_proven_count": refresh_count,
        "refresh_proven_rate": rate(refresh_count),
        "session_limited_count": session_limited_count,
        "session_limited_rate": rate(session_limited_count),
        "unknown_count": unknown_count,
        "unknown_rate": rate(unknown_count),
        "retries": retries,
        "terminal_or_deferred_count": terminal_deferred,
        "newly_materialized_wdb_record_count": len(materialized),
        "duplicate_noop_session_imports": int(ledger.get("duplicate_noop_session_imports", 0)),
        "remaining_unattempted_candidate_count": unattempted,
        "remaining_eligible_candidate_count": unattempted
        + state_counts.get(STATE_UNKNOWN_RETRYABLE, 0),
        "current_matching_cache_coverage": current_matching_cache_count,
        "remaining_canonical_cache_missing_count": current_missing_cache_count,
        "state_counts": dict(sorted(state_counts.items())),
        "freshness_class_counts": dict(sorted(freshness_counts.items())),
        "representative_refresh_proven_ids": _spread_select(success_ids, 5),
        "representative_unknown_ids": _spread_select(unknown_ids, 5),
        "session_count": len(ledger["sessions"]),
        "active_session": ledger.get("active_session"),
        "interpretation": (
            "Remaining/timeout populations are unknown, not unavailable. Only "
            "refresh_proven_direct_observation combines pre-session cache miss, current-session "
            "successful load and a post-session raw WDB record."
        ),
    }


def clone_ledger(ledger: Mapping[str, Any]) -> dict[str, Any]:
    """Small test/caller helper for applying a tentative transition before atomic persistence."""

    return deepcopy(dict(ledger))
