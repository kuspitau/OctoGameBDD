"""Read-only coverage and freshness helpers for the Octo Vanilla item cache.

P6-T02 deliberately separates source coverage from canonical materialization.  A cache miss is
unknown, not negative item evidence, and an already-cached record is not considered fresh merely
because the client can display it during the current session.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from octogamedb.importers.octo_itemcache import (
    ItemCacheRecord,
    ItemCacheSnapshot,
    parse_itemcache_wdb,
)

FRESHNESS_REFRESH_PROVEN = "refresh_proven_direct_observation"
FRESHNESS_SESSION_OBSERVED = "session_observed_freshness_limited"
FRESHNESS_HISTORICAL_CACHE = "historical_cache_only"
FRESHNESS_UNKNOWN = "unknown"

PROBE_STATUS_ALREADY_CACHED = "already_cached"
PROBE_STATUS_LOADED_AFTER_QUERY = "loaded_after_query"
PROBE_STATUS_TIMEOUT = "timeout_unknown"
PROBE_STATUS_PENDING = "pending"


@dataclass(frozen=True)
class ProbeClassification:
    item_id: int
    pre_record_sha256: str | None
    post_record_sha256: str | None
    probe_status: str
    freshness_class: str
    reason: str

    def to_json(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "pre_record_sha256": self.pre_record_sha256,
            "post_record_sha256": self.post_record_sha256,
            "probe_status": self.probe_status,
            "freshness_class": self.freshness_class,
            "reason": self.reason,
        }


def raw_record_sha256(record: ItemCacheRecord) -> str:
    """Return the exact raw WDB record digest without implying freshness."""

    return hashlib.sha256(record.raw_record).hexdigest()


def itemcache_record_hashes(snapshot: ItemCacheSnapshot) -> dict[int, str]:
    return {record.item_id: raw_record_sha256(record) for record in snapshot.records}


def compute_itemcache_coverage_revision(
    snapshot: ItemCacheSnapshot, canonical_item_ids: Iterable[int]
) -> str:
    """Hash the complete cache membership plus canonical item-ID population deterministically."""

    canonical = tuple(sorted({int(item_id) for item_id in canonical_item_ids}))
    digest = hashlib.sha256()
    digest.update(b"octogamedb-itemcache-coverage-v1\0")
    digest.update(snapshot.header.signature.encode("ascii"))
    digest.update(
        struct.pack(
            "<III",
            snapshot.header.client_version,
            snapshot.header.record_size,
            snapshot.header.record_version,
        )
    )
    digest.update(snapshot.header.locale.encode("ascii", errors="strict"))
    digest.update(b"\0CANONICAL\0")
    for item_id in canonical:
        digest.update(struct.pack("<I", item_id))
    digest.update(b"\0CACHE\0")
    for record in sorted(snapshot.records, key=lambda value: value.item_id):
        digest.update(struct.pack("<I", record.item_id))
        digest.update(hashlib.sha256(record.raw_record).digest())
    return f"sha256:{digest.hexdigest()}"


def compute_absent_itemcache_coverage_revision(canonical_item_ids: Iterable[int]) -> str:
    """Hash a clean/absent cache state plus the canonical item-ID population."""

    canonical = tuple(sorted({int(item_id) for item_id in canonical_item_ids}))
    digest = hashlib.sha256()
    digest.update(b"octogamedb-itemcache-coverage-v1\0ABSENT\0CANONICAL\0")
    for item_id in canonical:
        digest.update(struct.pack("<I", item_id))
    return f"sha256:{digest.hexdigest()}"


def build_absent_itemcache_coverage_report(
    connection: sqlite3.Connection, *, expected_source_path: str | Path | None = None
) -> dict[str, Any]:
    """Represent a clean WDB state without inventing a synthetic cache file."""

    canonical_rows = connection.execute("SELECT item_id FROM items ORDER BY item_id").fetchall()
    canonical_ids = tuple(int(row[0]) for row in canonical_rows)
    canonical_missing = list(canonical_ids)

    return {
        "report_version": 1,
        "source_kind": "octo-itemcache",
        "cache_state": "absent_before_probe",
        "expected_source_path": (
            None if expected_source_path is None else str(Path(expected_source_path))
        ),
        "coverage_revision": compute_absent_itemcache_coverage_revision(canonical_ids),
        "header": None,
        "counts": {
            "cache_records": 0,
            "canonical_items": len(canonical_ids),
            "cache_records_with_canonical_identity": 0,
            "cache_only_native_ids": 0,
            "canonical_item_ids_missing_from_cache_unknown": len(canonical_ids),
            "canonical_cache_coverage_ratio": 0.0 if canonical_ids else None,
            "records_with_nonempty_stat_slots": 0,
            "records_with_armor": 0,
            "records_with_max_durability": 0,
            "records_with_nonzero_resistance": 0,
        },
        "restrictions": {
            "required_level": 0,
            "class_mask_restricted": 0,
            "race_mask_restricted": 0,
            "required_skill": 0,
            "required_spell": 0,
            "required_reputation": 0,
        },
        "class_subclass_distribution": [],
        "quality_distribution": [],
        "inventory_type_distribution": [],
        "item_level_distribution": [],
        "required_level_distribution": [],
        "representative_ids": {
            "lowest_cache_item_id": None,
            "highest_cache_item_id": None,
            "lowest_matching_canonical_item_id": None,
            "highest_matching_canonical_item_id": None,
            "lowest_cache_only_item_id": None,
            "highest_cache_only_item_id": None,
        },
        "cache_only_native_item_ids": [],
        "canonical_item_ids_missing_from_cache_unknown": canonical_missing,
        "diagnostics": {
            "duplicate_records": 0,
            "malformed_records": 0,
            "unsupported_records": 0,
            "parser_policy": (
                "clean_cache: no itemcache.wdb existed at preflight, so no synthetic file was "
                "created and every canonical cache absence remains unknown"
            ),
        },
    }


def _counter_rows(counter: Counter[Any], names: tuple[str, ...]) -> list[dict[str, int]]:
    rows: list[dict[str, int]] = []
    for key, count in sorted(counter.items()):
        values = key if isinstance(key, tuple) else (key,)
        row = {name: int(value) for name, value in zip(names, values, strict=True)}
        row["count"] = int(count)
        rows.append(row)
    return rows


def _coverage_ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 8)


def build_itemcache_coverage_report(
    connection: sqlite3.Connection, *, source_path: str | Path
) -> dict[str, Any]:
    """Build a deterministic, read-only coverage report against canonical item identities."""

    source_path = Path(source_path)
    snapshot = parse_itemcache_wdb(source_path)
    canonical_rows = connection.execute("SELECT item_id FROM items ORDER BY item_id").fetchall()
    canonical_ids = tuple(int(row[0]) for row in canonical_rows)
    canonical_set = set(canonical_ids)
    cache_ids = tuple(sorted(record.item_id for record in snapshot.records))
    cache_set = set(cache_ids)
    matching = sorted(cache_set & canonical_set)
    cache_only = sorted(cache_set - canonical_set)
    canonical_missing = sorted(canonical_set - cache_set)

    class_subclass = Counter((record.class_id, record.subclass_id) for record in snapshot.records)
    quality = Counter(record.quality for record in snapshot.records)
    inventory = Counter(record.inventory_type for record in snapshot.records)
    item_level = Counter(record.item_level for record in snapshot.records)
    required_level = Counter(record.required_level for record in snapshot.records)

    nonempty_stats = sum(
        1
        for record in snapshot.records
        if any(slot.stat_type != 0 or slot.stat_value != 0 for slot in record.stat_slots)
    )
    with_resistance = sum(
        1
        for record in snapshot.records
        if any(
            value > 0
            for value in (
                record.holy_resistance,
                record.fire_resistance,
                record.nature_resistance,
                record.frost_resistance,
                record.shadow_resistance,
                record.arcane_resistance,
            )
        )
    )
    restrictions = {
        "required_level": sum(record.required_level > 0 for record in snapshot.records),
        "class_mask_restricted": sum(
            record.allowable_class_mask != -1 for record in snapshot.records
        ),
        "race_mask_restricted": sum(
            record.allowable_race_mask != -1 for record in snapshot.records
        ),
        "required_skill": sum(
            record.required_skill_id > 0 or record.required_skill_rank > 0
            for record in snapshot.records
        ),
        "required_spell": sum(record.required_spell_id > 0 for record in snapshot.records),
        "required_reputation": sum(
            record.required_reputation_faction_id > 0 or record.required_reputation_rank > 0
            for record in snapshot.records
        ),
    }

    representative = {
        "lowest_cache_item_id": cache_ids[0] if cache_ids else None,
        "highest_cache_item_id": cache_ids[-1] if cache_ids else None,
        "lowest_matching_canonical_item_id": matching[0] if matching else None,
        "highest_matching_canonical_item_id": matching[-1] if matching else None,
        "lowest_cache_only_item_id": cache_only[0] if cache_only else None,
        "highest_cache_only_item_id": cache_only[-1] if cache_only else None,
    }

    return {
        "report_version": 1,
        "source_kind": "octo-itemcache",
        "cache_state": "present",
        "coverage_revision": compute_itemcache_coverage_revision(snapshot, canonical_ids),
        "header": {
            "signature": snapshot.header.signature,
            "client_version": snapshot.header.client_version,
            "locale": snapshot.header.locale,
            "record_size": snapshot.header.record_size,
            "record_version": snapshot.header.record_version,
        },
        "counts": {
            "cache_records": len(cache_ids),
            "canonical_items": len(canonical_ids),
            "cache_records_with_canonical_identity": len(matching),
            "cache_only_native_ids": len(cache_only),
            "canonical_item_ids_missing_from_cache_unknown": len(canonical_missing),
            "canonical_cache_coverage_ratio": _coverage_ratio(len(matching), len(canonical_ids)),
            "records_with_nonempty_stat_slots": nonempty_stats,
            "records_with_armor": sum(record.armor > 0 for record in snapshot.records),
            "records_with_max_durability": sum(
                record.max_durability > 0 for record in snapshot.records
            ),
            "records_with_nonzero_resistance": with_resistance,
        },
        "restrictions": restrictions,
        "class_subclass_distribution": _counter_rows(
            class_subclass, ("class_id", "subclass_id")
        ),
        "quality_distribution": _counter_rows(quality, ("quality",)),
        "inventory_type_distribution": _counter_rows(inventory, ("inventory_type",)),
        "item_level_distribution": _counter_rows(item_level, ("item_level",)),
        "required_level_distribution": _counter_rows(required_level, ("required_level",)),
        "representative_ids": representative,
        "cache_only_native_item_ids": cache_only,
        "canonical_item_ids_missing_from_cache_unknown": canonical_missing,
        "diagnostics": {
            "duplicate_records": 0,
            "malformed_records": 0,
            "unsupported_records": 0,
            "parser_policy": (
                "fail_closed: duplicate, malformed, truncated or unsupported record shapes abort "
                "the report instead of being silently skipped"
            ),
        },
    }


def write_json_report(path: str | Path, report: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def choose_missing_canonical_probe_ids(report: Mapping[str, Any], *, limit: int) -> tuple[int, ...]:
    """Choose a deterministic bounded spread from known canonical IDs missing from the cache."""

    if limit < 1:
        raise ValueError("limit must be positive")
    raw = report.get("canonical_item_ids_missing_from_cache_unknown")
    if not isinstance(raw, list):
        raise TypeError("coverage report lacks canonical missing-ID list")
    values = sorted({int(value) for value in raw if int(value) > 0})
    if len(values) <= limit:
        return tuple(values)
    if limit == 1:
        return (values[len(values) // 2],)
    # Spread candidates over the known canonical-missing population instead of taking an arbitrary
    # numeric range. Integer arithmetic makes selection deterministic across platforms.
    indexes = [round(index * (len(values) - 1) / (limit - 1)) for index in range(limit)]
    return tuple(values[index] for index in indexes)


def classify_probe_observation(
    *,
    item_id: int,
    pre_record_sha256: str | None,
    post_record_sha256: str | None,
    probe_status: str,
) -> ProbeClassification:
    """Classify freshness conservatively from external before/after evidence plus addon state."""

    if pre_record_sha256 is not None:
        return ProbeClassification(
            item_id=item_id,
            pre_record_sha256=pre_record_sha256,
            post_record_sha256=post_record_sha256,
            probe_status=probe_status,
            freshness_class=FRESHNESS_HISTORICAL_CACHE,
            reason=(
                "The record existed before the bounded probe; the reviewed Vanilla tooltip path "
                "does not prove that an already-cached record was re-fetched from the server."
            ),
        )
    if probe_status == PROBE_STATUS_LOADED_AFTER_QUERY and post_record_sha256 is not None:
        return ProbeClassification(
            item_id=item_id,
            pre_record_sha256=None,
            post_record_sha256=post_record_sha256,
            probe_status=probe_status,
            freshness_class=FRESHNESS_REFRESH_PROVEN,
            reason=(
                "The explicit item ID was absent from the pre-probe WDB snapshot, the in-client "
                "probe observed it load after SetHyperlink, and the post-probe WDB contains a raw "
                "record whose hash is captured."
            ),
        )
    if probe_status == PROBE_STATUS_LOADED_AFTER_QUERY:
        return ProbeClassification(
            item_id=item_id,
            pre_record_sha256=None,
            post_record_sha256=None,
            probe_status=probe_status,
            freshness_class=FRESHNESS_SESSION_OBSERVED,
            reason=(
                "The current client session observed a successful load after the explicit query, "
                "but no post-session WDB record is available to tie the normalized result to raw "
                "cache bytes."
            ),
        )
    return ProbeClassification(
        item_id=item_id,
        pre_record_sha256=pre_record_sha256,
        post_record_sha256=post_record_sha256,
        probe_status=probe_status,
        freshness_class=FRESHNESS_UNKNOWN,
        reason=(
            "No supported positive completion proof was observed; timeout/failure/cache absence "
            "remains unknown and is never negative item evidence."
        ),
    )
