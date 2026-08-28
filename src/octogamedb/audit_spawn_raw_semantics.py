"""Read-only P5-T07 raw-source semantic audit for concentrated spawn additions.

The audit deliberately does not execute Lua and does not mutate canonical state.  It
reuses the P1 pfQuest/Turtle composition parser, the P1 content-revision functions,
and the P5-T06 complete addition population.  Raw source entries are inspected only
for parents needed by the bounded P5-T07 slice.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tomllib
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RAW_SEMANTIC_SCOPE = "p5-t07-concentrated-spawn-addition-raw-semantics"
EXPECTED_CANONICAL_SHA256 = (
    "623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7"
)
EXPECTED_BASE_REVISION = (
    "sha256:5087d2d0a5b1c2706b7fc7ccb5ffd447c91aa24d91a23f102f2c7ac1d7440147"
)
EXPECTED_ACTIVE_REVISION = (
    "sha256:7fd719cac7a7a26e80c6865fa62b6100ccfa2301dabe3b2a399c0f1551372d8c"
)
EXPECTED_COMPARISON_REVISION = (
    "sha256:eddd325a9a0eab2616c7b70d03e23d55f1a0c4127a293426ea07a17c0f2421db"
)
EXPECTED_P5_T06_INCLUDED_TOTAL = 20_707
EXPECTED_FOUR_ZONE_TOTAL = 15_607
DEFAULT_ZONE_IDS = (406, 5602, 5581, 1584)
DEFAULT_ZONE_COUNTS = {
    406: 5_145,
    5602: 5_062,
    5581: 2_872,
    1584: 2_528,
}
SOURCE_SIDES = ("active", "comparison")
SOURCE_SIDE_FILTERS = ("active", "comparison", "both")
SPAWN_SUBJECT_KINDS = ("creature_spawn", "gameobject_spawn")
ADDITION_PARENT_CLASSES = (
    "parent_absent_from_base",
    "spawn_added_to_base_present_parent",
)
RAW_TRANSFORMATION_CLASSES = (
    "overlay_entry_inherited",
    "overlay_parent_added",
    "overlay_parent_removed",
    "overlay_whole_entry_replaced",
)
MEMBER_CLASSES = (
    "member_inherited_from_base",
    "member_added_by_overlay",
    "member_removed_by_overlay",
    "member_present_only_in_comparison",
)

_MISSING = object()
_PARENT_FILES = {
    "creature": ("units", "db/units.lua", "db/units-turtle.lua"),
    "gameobject": ("objects", "db/objects.lua", "db/objects-turtle.lua"),
}


class RawSemanticAuditError(ValueError):
    """Raised when P5-T07 cannot prove a required raw/composition invariant."""


@dataclass(frozen=True)
class _RawMembers:
    payloads: tuple[dict[str, Any], ...]
    unique: dict[str, dict[str, Any]]
    duplicate_keys: tuple[str, ...]
    raw_count: int


@dataclass(frozen=True)
class _CompositionInputs:
    base_tables: dict[tuple[str, str], dict[Any, Any]]
    patch_tables: dict[tuple[str, str], dict[Any, Any]]
    overwrite_touches: dict[tuple[str, str], set[int] | None]


def _subject_key_sort(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


def _percentage(count: int, total: int) -> float:
    return 0.0 if total == 0 else round(count * 100.0 / total, 6)


def _source_side(pattern: str) -> str:
    if pattern == "active_only_vs_base":
        return "active"
    if pattern == "comparison_only_vs_base":
        return "comparison"
    raise RawSemanticAuditError(f"unsupported P5-T07 addition pattern: {pattern!r}")


def _parent_kind_from_subject(subject_kind: str) -> str:
    if subject_kind == "creature_spawn":
        return "creature"
    if subject_kind == "gameobject_spawn":
        return "gameobject"
    raise RawSemanticAuditError(f"unsupported spawn subject kind: {subject_kind!r}")


def _classify_parent_transform(*, base_present: bool, patch_value: Any = _MISSING) -> str:
    """Classify the source-native top-entry transformation, without recursive merge semantics."""

    if patch_value is _MISSING:
        return "overlay_entry_inherited"
    if isinstance(patch_value, str) and patch_value == "_":
        return "overlay_parent_removed"
    if not isinstance(patch_value, dict):
        raise RawSemanticAuditError(
            "unsupported pfQuest overlay top-entry value; expected table, '_' or absence"
        )
    return "overlay_whole_entry_replaced" if base_present else "overlay_parent_added"


def _collapse_payloads(payloads: Iterable[dict[str, Any]]) -> _RawMembers:
    ordered = tuple(dict(payload) for payload in payloads)
    unique: dict[str, dict[str, Any]] = {}
    duplicate_counter: Counter[str] = Counter()
    for payload in ordered:
        spawn_key = payload.get("spawn_key")
        if not isinstance(spawn_key, str) or not spawn_key:
            raise RawSemanticAuditError("raw spawn payload is missing deterministic spawn_key")
        duplicate_counter[spawn_key] += 1
        unique.setdefault(spawn_key, payload)
    duplicate_keys = tuple(sorted(key for key, count in duplicate_counter.items() if count > 1))
    return _RawMembers(
        payloads=ordered,
        unique=unique,
        duplicate_keys=duplicate_keys,
        raw_count=len(ordered),
    )


def _stable_value(value: Any) -> Any:
    if isinstance(value, dict):
        return [
            [_stable_key(key), _stable_value(child)]
            for key, child in sorted(value.items(), key=lambda item: _stable_key(item[0]))
        ]
    if isinstance(value, (list, tuple)):
        return [_stable_value(item) for item in value]
    return value


def _stable_key(value: Any) -> str:
    return f"{type(value).__name__}:{value!r}"


def _payload_digest(value: Any) -> str:
    encoded = json.dumps(
        _stable_value(value), ensure_ascii=False, separators=(",", ":"), sort_keys=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _raw_members_from_entry(entry: Any, *, kind: str, entity_id: int) -> _RawMembers:
    if entry is None or entry is _MISSING or (isinstance(entry, str) and entry == "_"):
        return _collapse_payloads(())
    if not isinstance(entry, dict):
        raise RawSemanticAuditError(f"{kind}:{entity_id} raw entry must be a Lua table")

    from octogamedb.importers.pfquest_overlay_reconcile import _spawn_set
    from octogamedb.importers.pfquest_world import _parse_spawn_table

    spawns = _parse_spawn_table(entry.get("coords"), label=f"{kind}[{entity_id}]")
    return _collapse_payloads(_spawn_set(kind, entity_id, spawns))


def _entry_source_files(
    *,
    parent_kind: str,
    transform: str,
    overwrite_touched: bool,
) -> list[str]:
    _domain, base_file, overlay_file = _PARENT_FILES[parent_kind]
    if transform == "overlay_entry_inherited":
        return [base_file]
    files = [overlay_file]
    if overwrite_touched:
        files.append("overwrites.lua")
    return files


def _analyze_parent_entry(
    *,
    parent_kind: str,
    parent_key: int,
    base_entry: Any,
    patch_value: Any,
    overwrite_touched: bool = False,
    base_effective_parent_present: bool | None = None,
    effective_parent_present: bool | None = None,
    composition_transform: str | None = None,
    source_relative_paths: list[str] | None = None,
) -> dict[str, Any]:
    base_data_present = base_entry is not _MISSING
    data_transform = _classify_parent_transform(
        base_present=base_data_present, patch_value=patch_value
    )
    if data_transform == "overlay_entry_inherited":
        effective_entry = None if not base_data_present else base_entry
    elif data_transform == "overlay_parent_removed":
        effective_entry = None
    else:
        effective_entry = patch_value

    if base_effective_parent_present is None:
        base_effective_parent_present = base_data_present
    if effective_parent_present is None:
        effective_parent_present = effective_entry is not None
    transform = data_transform if composition_transform is None else composition_transform
    if transform not in RAW_TRANSFORMATION_CLASSES:
        raise RawSemanticAuditError(f"unsupported composition transformation: {transform!r}")

    base_raw_members = _raw_members_from_entry(
        None if not base_data_present else base_entry,
        kind=parent_kind,
        entity_id=parent_key,
    )
    patch_members = _raw_members_from_entry(
        None if patch_value is _MISSING else patch_value,
        kind=parent_kind,
        entity_id=parent_key,
    )
    effective_raw_members = _raw_members_from_entry(
        effective_entry,
        kind=parent_kind,
        entity_id=parent_key,
    )
    base_members = (
        base_raw_members
        if base_effective_parent_present
        else _collapse_payloads(())
    )
    effective_members = (
        effective_raw_members
        if effective_parent_present
        else _collapse_payloads(())
    )
    base_keys = set(base_members.unique)
    effective_keys = set(effective_members.unique)
    inherited_keys = base_keys & effective_keys
    added_keys = effective_keys - base_keys
    removed_keys = base_keys - effective_keys

    return {
        "base_entry_present": bool(base_effective_parent_present),
        "base_data_entry_present": base_data_present,
        "effective_parent_present": bool(effective_parent_present),
        "patch_top_entry_present": patch_value is not _MISSING,
        "raw_transformation_class": transform,
        "data_raw_transformation_class": data_transform,
        "raw_source_relative_paths": (
            list(source_relative_paths)
            if source_relative_paths is not None
            else _entry_source_files(
                parent_kind=parent_kind,
                transform=transform,
                overwrite_touched=overwrite_touched,
            )
        ),
        "raw_top_entry_key": str(parent_key),
        "overwrite_touched_top_entry": overwrite_touched,
        "patch_payload_sha256": None
        if patch_value is _MISSING
        else _payload_digest(patch_value),
        "base_raw_member_count": base_raw_members.raw_count,
        "base_raw_unique_member_count": len(base_raw_members.unique),
        "base_unique_member_count": len(base_members.unique),
        "base_duplicate_member_count": (
            base_raw_members.raw_count - len(base_raw_members.unique)
        ),
        "base_duplicate_spawn_keys": list(base_raw_members.duplicate_keys),
        "patch_raw_member_count": patch_members.raw_count,
        "patch_unique_member_count": len(patch_members.unique),
        "patch_duplicate_member_count": patch_members.raw_count - len(patch_members.unique),
        "patch_duplicate_spawn_keys": list(patch_members.duplicate_keys),
        "effective_raw_member_count": effective_raw_members.raw_count,
        "effective_raw_unique_member_count": len(effective_raw_members.unique),
        "effective_unique_member_count": len(effective_members.unique),
        "effective_duplicate_member_count": (
            effective_raw_members.raw_count - len(effective_raw_members.unique)
        ),
        "effective_duplicate_spawn_keys": list(effective_raw_members.duplicate_keys),
        "member_class_counts": {
            "member_inherited_from_base": len(inherited_keys),
            "member_added_by_overlay": len(added_keys),
            "member_removed_by_overlay": len(removed_keys),
            "member_present_only_in_comparison": 0,
        },
        "base_member_keys": sorted(base_keys),
        "effective_member_keys": sorted(effective_keys),
        "inherited_member_keys": sorted(inherited_keys),
        "added_member_keys": sorted(added_keys),
        "removed_member_keys": sorted(removed_keys),
        "effective_payloads": effective_members.unique,
        "base_payloads": base_members.unique,
    }


def _load_composition_inputs(
    base_root: Path, overlay_root: Path, *, overlay_kind: str
) -> _CompositionInputs:
    """Load the exact P1 world composition inputs using the already-reviewed P1 adapter helpers."""

    from octogamedb.importers.pfquest_overlay_world import (
        _WORLD_TABLES,
        _apply_direct_overwrites,
        _apply_turtle_phantom_zone_cleanup,
        _read_assignment,
        _read_optional_assignment,
        _validate_no_unhandled_world_mutations,
    )

    if overlay_kind not in {"turtle", "octo"}:
        raise RawSemanticAuditError("overlay_kind must be 'turtle' or 'octo'")

    bases: dict[tuple[str, str], dict[Any, Any]] = {}
    patches: dict[tuple[str, str], dict[Any, Any]] = {}
    for domain, base_table, base_relative, patch_table, patch_relative in _WORLD_TABLES:
        bases[(domain, base_table)] = _read_assignment(
            base_root / "db" / base_relative,
            domain,
            base_table,
        )
        patches[(domain, patch_table)] = _read_optional_assignment(
            overlay_root / "db" / patch_relative,
            domain,
            patch_table,
        )

    overwrite_path = overlay_root / "overwrites.lua"
    overwrite_text = overwrite_path.read_text(encoding="utf-8") if overwrite_path.is_file() else ""
    touches = _overwrite_touch_map(overwrite_text, tuple(patches))
    _apply_direct_overwrites(patches, overwrite_text)
    turtle_loop_handled = False
    if overlay_kind == "turtle":
        turtle_loop_handled = _apply_turtle_phantom_zone_cleanup(patches, overwrite_text)
    _validate_no_unhandled_world_mutations(
        overwrite_text,
        allow_turtle_loop=turtle_loop_handled,
    )
    return _CompositionInputs(bases, patches, touches)


def _overwrite_touch_map(
    text: str,
    table_keys: tuple[tuple[str, str], ...],
) -> dict[tuple[str, str], set[int] | None]:
    """Record which top entries supported direct overwrites touch; None means table-root touch."""

    from octogamedb.importers.pfquest_overlay_world import _direct_prefix
    from octogamedb.importers.pfquest_world import PfQuestParseError, _LuaLiteralParser

    result: dict[tuple[str, str], set[int] | None] = {key: set() for key in table_keys}
    for domain, table_name in table_keys:
        prefix = _direct_prefix(domain, table_name)
        for match in prefix.finditer(text):
            parser = _LuaLiteralParser(text, match.end())
            keys: list[Any] = []
            while parser._peek() == "[":
                parser.position += 1
                key = parser.parse_value()
                parser._consume("]")
                keys.append(key)
            try:
                parser._consume("=")
                parser.parse_value()
            except PfQuestParseError as exc:
                raise RawSemanticAuditError(
                    f"unsupported direct overwrite while tracing {domain}.{table_name}"
                ) from exc
            if not keys:
                result[(domain, table_name)] = None
            elif result[(domain, table_name)] is not None and isinstance(keys[0], int):
                result[(domain, table_name)].add(int(keys[0]))
    return result


def _composed_top_entry(base_value: Any, patch_value: Any) -> Any:
    if patch_value is _MISSING:
        return None if base_value is _MISSING else base_value
    if isinstance(patch_value, str) and patch_value == "_":
        return None
    return patch_value


def _usable_name(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _parent_raw_view(
    inputs: _CompositionInputs,
    *,
    parent_kind: str,
    parent_key: int,
) -> dict[str, Any]:
    domain, base_file, overlay_file = _PARENT_FILES[parent_kind]
    base_table = inputs.base_tables[(domain, "data")]
    patch_table = inputs.patch_tables[(domain, "data-turtle")]
    base_names = inputs.base_tables[(domain, "enUS")]
    patch_names = inputs.patch_tables[(domain, "enUS-turtle")]

    base_entry = base_table.get(parent_key, _MISSING)
    patch_value = patch_table.get(parent_key, _MISSING)
    base_name = base_names.get(parent_key, _MISSING)
    patch_name = patch_names.get(parent_key, _MISSING)
    effective_entry = _composed_top_entry(base_entry, patch_value)
    effective_name = _composed_top_entry(base_name, patch_name)

    base_parent_present = base_entry is not _MISSING and _usable_name(base_name)
    effective_parent_present = isinstance(effective_entry, dict) and _usable_name(effective_name)
    data_transform = _classify_parent_transform(
        base_present=base_entry is not _MISSING, patch_value=patch_value
    )
    if not base_parent_present and effective_parent_present:
        transform = "overlay_parent_added"
    elif base_parent_present and not effective_parent_present:
        transform = "overlay_parent_removed"
    elif data_transform == "overlay_whole_entry_replaced":
        transform = "overlay_whole_entry_replaced"
    elif data_transform == "overlay_parent_added" and not effective_parent_present:
        # A raw data-only orphan patch does not enter the effective P1 world.  Keep the
        # source-native addition class visible even though it contributes no effective members.
        transform = "overlay_parent_added"
    elif data_transform == "overlay_parent_removed" and not base_parent_present:
        transform = "overlay_parent_removed"
    else:
        transform = "overlay_entry_inherited"

    data_touches = inputs.overwrite_touches[(domain, "data-turtle")]
    name_touches = inputs.overwrite_touches[(domain, "enUS-turtle")]
    data_overwrite_touched = data_touches is None or parent_key in data_touches
    name_overwrite_touched = name_touches is None or parent_key in name_touches

    source_paths: list[str] = []
    if patch_value is _MISSING:
        if base_entry is not _MISSING:
            source_paths.append(base_file)
    else:
        source_paths.append(overlay_file)
        if data_overwrite_touched:
            source_paths.append("overwrites.lua")
    base_locale_file = (
        "db/enUS/units.lua" if parent_kind == "creature" else "db/enUS/objects.lua"
    )
    overlay_locale_file = (
        "db/enUS/units-turtle.lua"
        if parent_kind == "creature"
        else "db/enUS/objects-turtle.lua"
    )
    if patch_name is not _MISSING:
        source_paths.append(overlay_locale_file)
        if name_overwrite_touched:
            source_paths.append("overwrites.lua")
    elif base_name is not _MISSING:
        source_paths.append(base_locale_file)
    source_paths = list(dict.fromkeys(source_paths))

    view = _analyze_parent_entry(
        parent_kind=parent_kind,
        parent_key=parent_key,
        base_entry=base_entry,
        patch_value=patch_value,
        overwrite_touched=data_overwrite_touched,
        base_effective_parent_present=base_parent_present,
        effective_parent_present=effective_parent_present,
        composition_transform=transform,
        source_relative_paths=source_paths,
    )
    view["base_localization_entry_present"] = base_name is not _MISSING
    view["overlay_localization_top_entry_present"] = patch_name is not _MISSING
    view["effective_localization_present"] = _usable_name(effective_name)
    return view

def _require_exact_source_revisions(
    *,
    pfquest_root: Path,
    pfquest_turtle_root: Path,
    pfquest_octo_root: Path,
) -> dict[str, dict[str, str]]:
    from octogamedb.importers.pfquest_overlay_reconcile import (
        compute_pfquest_overlay_revision,
        compute_pfquest_world_revision,
    )

    measured = {
        "base": compute_pfquest_world_revision(pfquest_root),
        "active": compute_pfquest_overlay_revision(pfquest_turtle_root),
        "comparison": compute_pfquest_overlay_revision(pfquest_octo_root),
    }
    expected = {
        "base": EXPECTED_BASE_REVISION,
        "active": EXPECTED_ACTIVE_REVISION,
        "comparison": EXPECTED_COMPARISON_REVISION,
    }
    for side in ("base", "active", "comparison"):
        if measured[side] != expected[side]:
            raise RawSemanticAuditError(
                f"P5-T07 {side} source revision mismatch: expected {expected[side]}, "
                f"measured {measured[side]}"
            )
    return {
        "base": {"source_key": "pfquest", "source_revision": measured["base"]},
        "active": {"source_key": "pfquest-turtle", "source_revision": measured["active"]},
        "comparison": {
            "source_key": "pfquest-octo",
            "source_revision": measured["comparison"],
        },
    }


def _persisted_spawn_set_contexts(
    connection: sqlite3.Connection,
    *,
    source_key: str,
    source_revision: str,
    parents: set[tuple[str, str]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Bulk-load persisted spawn_set evidence for the requested parents."""

    from octogamedb.audit_comparison import _resolve_source_revision, _source_groups
    from octogamedb.audit_spawn_attribution import _group_batches
    from octogamedb.audit_spawn_divergence import _spawn_members

    source_id, revision, _source_batches = _resolve_source_revision(
        connection,
        source_key=source_key,
        source_revision=source_revision,
    )
    if revision != source_revision:
        raise RawSemanticAuditError(
            f"persisted {source_key} revision mismatch: expected {source_revision}, got {revision}"
        )
    source_groups, batch_map = _source_groups(
        connection,
        source_id=source_id,
        revision=revision,
    )

    contexts: dict[tuple[str, str], dict[str, Any]] = {}
    for parent_kind, parent_key in sorted(
        parents, key=lambda item: (item[0], _subject_key_sort(item[1]))
    ):
        group = source_groups.get((parent_kind, str(parent_key), "spawn_set", ""))
        if group is None:
            continue

        values: dict[str, dict[str, dict[str, Any]]] = {}
        batch_ids: set[int] = set()
        for observation in group["comparison_observations"]:
            observation_id = int(observation["observation_id"])
            succeeded_batches = [
                batch
                for batch in batch_map.get(observation_id, [])
                if str(batch["status"]) == "succeeded"
            ]
            if not succeeded_batches:
                continue
            members = _spawn_members(observation["value"])
            if members is None:
                raise RawSemanticAuditError(
                    f"persisted {source_key} spawn_set is malformed for "
                    f"{parent_kind}:{parent_key}"
                )
            normalized = json.dumps(
                sorted(members), ensure_ascii=False, separators=(",", ":")
            )
            values.setdefault(normalized, members)
            batch_ids.update(int(batch["batch_id"]) for batch in succeeded_batches)

        if not values:
            continue
        if len(values) != 1:
            raise RawSemanticAuditError(
                f"persisted {source_key} spawn_set is non-unique for "
                f"{parent_kind}:{parent_key}"
            )
        members = next(iter(values.values()))
        contexts[(parent_kind, str(parent_key))] = {
            "source_key": source_key,
            "source_revision": source_revision,
            "import_batches": [
                {"batch_id": batch_id, "status": "succeeded"}
                for batch_id in sorted(batch_ids)
            ],
            "member_keys": set(members),
            "unique_member_count": len(members),
        }
    return contexts


def _persisted_spawn_set_context(
    connection: sqlite3.Connection,
    *,
    source_key: str,
    source_revision: str,
    parent_kind: str,
    parent_key: str,
) -> dict[str, Any] | None:
    """Compatibility wrapper for a single parent; bulk audit paths avoid N+1 SQL."""

    return _persisted_spawn_set_contexts(
        connection,
        source_key=source_key,
        source_revision=source_revision,
        parents={(parent_kind, str(parent_key))},
    ).get((parent_kind, str(parent_key)))

def _verify_overlay_persistence(
    *,
    parent_kind: str,
    parent_key: str,
    side: str,
    view: dict[str, Any],
    base_context: dict[str, Any],
    persisted_context: dict[str, Any] | None,
) -> dict[str, Any]:
    if view["raw_transformation_class"] == "overlay_entry_inherited":
        persisted = {
            "source_key": base_context["source_key"],
            "source_revision": base_context["source_revision"],
            "import_batches": list(base_context["import_batches"]),
            "member_keys": set(base_context["member_keys"]),
            "membership_evidence": "inherited_base_spawn_set",
        }
    else:
        source_key = "pfquest-turtle" if side == "active" else "pfquest-octo"
        source_revision = (
            EXPECTED_ACTIVE_REVISION if side == "active" else EXPECTED_COMPARISON_REVISION
        )
        persisted = persisted_context
        if persisted is None:
            raw_keys = set(view["effective_member_keys"])
            base_keys = set(base_context["member_keys"])
            if (
                view["base_entry_present"]
                and view["effective_parent_present"]
                and raw_keys == base_keys
            ):
                persisted = {
                    "source_key": base_context["source_key"],
                    "source_revision": base_context["source_revision"],
                    "import_batches": list(base_context["import_batches"]),
                    "member_keys": base_keys,
                    "membership_evidence": "raw_transform_without_spawn_set_change",
                }
            elif (
                not view["base_entry_present"]
                and not view["effective_parent_present"]
                and not raw_keys
            ):
                persisted = {
                    "source_key": source_key,
                    "source_revision": source_revision,
                    "import_batches": [],
                    "member_keys": set(),
                    "membership_evidence": "absent_from_unchanged_effective_view",
                }
            else:
                raise RawSemanticAuditError(
                    f"missing persisted {source_key} spawn_set for raw "
                    f"{view['raw_transformation_class']} "
                    f"parent {parent_kind}:{parent_key}"
                )
        else:
            persisted["membership_evidence"] = "overlay_spawn_set_observation"

    raw_keys = set(view["effective_member_keys"])
    persisted_keys = set(persisted["member_keys"])
    if raw_keys != persisted_keys:
        raw_only = sorted(raw_keys - persisted_keys)[:5]
        persisted_only = sorted(persisted_keys - raw_keys)[:5]
        raise RawSemanticAuditError(
            f"raw effective membership != persisted spawn_set for {side} "
            f"{parent_kind}:{parent_key}; "
            f"raw_only={raw_only}, persisted_only={persisted_only}"
        )
    return {
        "source_key": persisted["source_key"],
        "source_revision": persisted["source_revision"],
        "import_batches": persisted["import_batches"],
        "membership_evidence": persisted["membership_evidence"],
        "unique_member_count": len(persisted_keys),
        "raw_matches_persisted": True,
    }


def _cross_overlay_membership_sets(
    active: dict[str, Any],
    comparison: dict[str, Any],
    *,
    audited_zone_ids: set[int],
) -> dict[str, set[str]]:
    active_effective = set(active["effective_member_keys"])
    comparison_effective = set(comparison["effective_member_keys"])
    active_added = set(active["added_member_keys"])
    comparison_added = set(comparison["added_member_keys"])
    shared_added = active_added & comparison_added
    active_one_sided = active_added - comparison_effective
    comparison_one_sided = comparison_added - active_effective
    return {
        "active_added": active_added,
        "comparison_added": comparison_added,
        "shared_added": shared_added,
        "active_one_sided": active_one_sided,
        "comparison_one_sided": comparison_one_sided,
        "active_added_in_audited_zones": _keys_in_zones(
            active_added, active, audited_zone_ids
        ),
        "comparison_added_in_audited_zones": _keys_in_zones(
            comparison_added, comparison, audited_zone_ids
        ),
        "shared_added_in_audited_zones": _keys_in_zones(
            shared_added, active, audited_zone_ids
        ),
        "active_one_sided_in_audited_zones": _keys_in_zones(
            active_one_sided, active, audited_zone_ids
        ),
        "comparison_one_sided_in_audited_zones": _keys_in_zones(
            comparison_one_sided, comparison, audited_zone_ids
        ),
    }

def _build_parent_audit(
    *,
    parent_kind: str,
    parent_key: str,
    parent_members: list[dict[str, Any]],
    active_inputs: _CompositionInputs,
    comparison_inputs: _CompositionInputs,
    base_context: dict[str, Any],
    active_persisted_context: dict[str, Any] | None,
    comparison_persisted_context: dict[str, Any] | None,
    audited_zone_ids: set[int],
) -> dict[str, Any]:
    numeric_key = int(parent_key)
    active = _parent_raw_view(active_inputs, parent_kind=parent_kind, parent_key=numeric_key)
    comparison = _parent_raw_view(
        comparison_inputs, parent_kind=parent_kind, parent_key=numeric_key
    )
    base_raw_keys = set(active["base_member_keys"])
    if base_raw_keys != set(comparison["base_member_keys"]):
        raise AssertionError("active/comparison raw views must share the exact base entry")
    if base_raw_keys != set(base_context["member_keys"]):
        raise RawSemanticAuditError(
            f"raw base membership != persisted base spawn_set for {parent_kind}:{parent_key}"
        )

    active_persisted = _verify_overlay_persistence(
        parent_kind=parent_kind,
        parent_key=parent_key,
        side="active",
        view=active,
        base_context=base_context,
        persisted_context=active_persisted_context,
    )
    comparison_persisted = _verify_overlay_persistence(
        parent_kind=parent_kind,
        parent_key=parent_key,
        side="comparison",
        view=comparison,
        base_context=base_context,
        persisted_context=comparison_persisted_context,
    )

    cross_sets = _cross_overlay_membership_sets(
        active, comparison, audited_zone_ids=audited_zone_ids
    )
    comparison_one_sided = cross_sets["comparison_one_sided"]
    raw_active_zone = cross_sets["active_one_sided_in_audited_zones"]
    raw_comparison_zone = cross_sets["comparison_one_sided_in_audited_zones"]
    p5_active = {
        str(member["spawn_key"])
        for member in parent_members
        if member["three_way_pattern"] == "active_only_vs_base"
    }
    p5_comparison = {
        str(member["spawn_key"])
        for member in parent_members
        if member["three_way_pattern"] == "comparison_only_vs_base"
    }
    if raw_active_zone != p5_active or raw_comparison_zone != p5_comparison:
        raise RawSemanticAuditError(
            f"raw one-sided additions do not reconcile P5-T06 for {parent_kind}:{parent_key}; "
            f"active raw/P5={len(raw_active_zone)}/{len(p5_active)}, "
            f"comparison raw/P5={len(raw_comparison_zone)}/{len(p5_comparison)}"
        )

    expected_parent_class = (
        "spawn_added_to_base_present_parent"
        if active["base_entry_present"]
        else "parent_absent_from_base"
    )
    measured_classes = {str(member["addition_parent_class"]) for member in parent_members}
    if measured_classes != {expected_parent_class}:
        raise RawSemanticAuditError(
            f"raw base parent presence disagrees with P5-T06 class for {parent_kind}:{parent_key}: "
            f"raw={expected_parent_class}, p5={sorted(measured_classes)}"
        )

    comparison["member_class_counts"]["member_present_only_in_comparison"] = len(
        comparison_one_sided
    )
    shared_added_zone = cross_sets["shared_added_in_audited_zones"]
    active_added_zone = cross_sets["active_added_in_audited_zones"]
    comparison_added_zone = cross_sets["comparison_added_in_audited_zones"]

    return {
        "parent_subject_kind": parent_kind,
        "parent_subject_key": parent_key,
        "base_entry_present": active["base_entry_present"],
        "addition_parent_class": expected_parent_class,
        "addition_member_count": len(parent_members),
        "active_addition_member_count": len(p5_active),
        "comparison_addition_member_count": len(p5_comparison),
        "active": _public_view(active, active_persisted),
        "comparison": _public_view(comparison, comparison_persisted),
        "cross_overlay": {
            "active_added_member_count_in_audited_zones": len(active_added_zone),
            "comparison_added_member_count_in_audited_zones": len(comparison_added_zone),
            "shared_exact_added_member_count_in_audited_zones": len(shared_added_zone),
            "shared_exact_added_spawn_keys": sorted(shared_added_zone),
            "active_one_sided_member_count_in_audited_zones": len(raw_active_zone),
            "comparison_one_sided_member_count_in_audited_zones": len(raw_comparison_zone),
            "both_overlays_add": bool(active_added_zone and comparison_added_zone),
            "one_sided_additions_disjoint": not bool(shared_added_zone),
            "both_whole_entry_replacements": (
                active["raw_transformation_class"] == "overlay_whole_entry_replaced"
                and comparison["raw_transformation_class"] == "overlay_whole_entry_replaced"
            ),
            "replacement_payloads_equal": (
                active["patch_payload_sha256"] == comparison["patch_payload_sha256"]
                if active["patch_payload_sha256"] is not None
                and comparison["patch_payload_sha256"] is not None
                else None
            ),
        },
    }


def _keys_in_zones(keys: set[str], view: dict[str, Any], zone_ids: set[int]) -> set[str]:
    payloads = view["effective_payloads"]
    result: set[str] = set()
    for key in keys:
        payload = payloads.get(key)
        if payload is None:
            continue
        zone_id = payload.get("zone_id")
        if isinstance(zone_id, int) and zone_id in zone_ids:
            result.add(key)
    return result


def _public_view(view: dict[str, Any], persisted: dict[str, Any]) -> dict[str, Any]:
    hidden = {
        "base_member_keys",
        "effective_member_keys",
        "inherited_member_keys",
        "added_member_keys",
        "removed_member_keys",
        "effective_payloads",
        "base_payloads",
    }
    result = {key: value for key, value in view.items() if key not in hidden}
    result["persisted_spawn_set"] = persisted
    return result


def _zone_rows(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for member in members:
        if member.get("zone_id") is not None:
            grouped[int(member["zone_id"])].append(member)
    rows: list[dict[str, Any]] = []
    for zone_id in sorted(grouped, key=lambda zid: (-len(grouped[zid]), zid)):
        rows_for_zone = grouped[zone_id]
        source_counts = Counter(
            _source_side(str(row["three_way_pattern"])) for row in rows_for_zone
        )
        class_counts = Counter(str(row["addition_parent_class"]) for row in rows_for_zone)
        kind_counts = Counter(str(row["subject_kind"]) for row in rows_for_zone)
        rows.append(
            {
                "zone_id": zone_id,
                "zone_name": rows_for_zone[0].get("zone_name"),
                "map_id": rows_for_zone[0].get("map_id"),
                "map_name": rows_for_zone[0].get("map_name"),
                "addition_member_count": len(rows_for_zone),
                "percentage_of_audited_total": 0.0,
                "distinct_parent_count": len(
                    {
                        (str(row["parent_subject_kind"]), str(row["parent_subject_key"]))
                        for row in rows_for_zone
                    }
                ),
                "source_side_counts": {side: source_counts[side] for side in SOURCE_SIDES},
                "addition_parent_class_counts": {
                    name: class_counts[name] for name in ADDITION_PARENT_CLASSES
                },
                "subject_kind_counts": {name: kind_counts[name] for name in SPAWN_SUBJECT_KINDS},
            }
        )
    total = sum(int(row["addition_member_count"]) for row in rows)
    for row in rows:
        row["percentage_of_audited_total"] = _percentage(int(row["addition_member_count"]), total)
    return rows


def _aggregate_rows(
    members: list[dict[str, Any]],
    parent_audits: dict[tuple[str, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    zone_parent_class: Counter[tuple[int, str]] = Counter()
    zone_source: Counter[tuple[int, str]] = Counter()
    zone_transform: Counter[tuple[int, str, str]] = Counter()
    for member in members:
        zone_id = int(member["zone_id"])
        source_side = _source_side(str(member["three_way_pattern"]))
        parent_key = (str(member["parent_subject_kind"]), str(member["parent_subject_key"]))
        transform = str(parent_audits[parent_key][source_side]["raw_transformation_class"])
        zone_parent_class[(zone_id, str(member["addition_parent_class"]))] += 1
        zone_source[(zone_id, source_side)] += 1
        zone_transform[(zone_id, source_side, transform)] += 1

    parent_class_rows = [
        {"zone_id": zone, "addition_parent_class": class_name, "member_count": count}
        for (zone, class_name), count in sorted(zone_parent_class.items())
    ]
    source_rows = [
        {"zone_id": zone, "source_side": side, "member_count": count}
        for (zone, side), count in sorted(zone_source.items())
    ]
    transform_rows = [
        {
            "zone_id": zone,
            "source_side": side,
            "raw_transformation_class": transform,
            "member_count": count,
        }
        for (zone, side, transform), count in sorted(zone_transform.items())
    ]
    return parent_class_rows, source_rows, transform_rows


def _parent_rows(
    members: list[dict[str, Any]],
    parent_audits: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str, str]] = Counter()
    for member in members:
        key = (
            str(member["parent_subject_kind"]),
            str(member["parent_subject_key"]),
            _source_side(str(member["three_way_pattern"])),
        )
        counts[key] += 1
    by_parent: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for (kind, key, side), count in counts.items():
        by_parent[(kind, key)][side] += count
    rows: list[dict[str, Any]] = []
    for kind, key in sorted(
        by_parent,
        key=lambda value: (
            -sum(by_parent[value].values()),
            value[0],
            _subject_key_sort(value[1]),
        ),
    ):
        counter = by_parent[(kind, key)]
        audit = parent_audits[(kind, key)]
        rows.append(
            {
                "parent_subject_kind": kind,
                "parent_subject_key": key,
                "addition_parent_class": audit["addition_parent_class"],
                "active_addition_member_count": counter["active"],
                "comparison_addition_member_count": counter["comparison"],
                "total_addition_member_count": counter["active"] + counter["comparison"],
                "active_raw_transformation_class": audit["active"]["raw_transformation_class"],
                "comparison_raw_transformation_class": audit["comparison"][
                    "raw_transformation_class"
                ],
                "shared_exact_added_member_count_in_audited_zones": audit["cross_overlay"][
                    "shared_exact_added_member_count_in_audited_zones"
                ],
                "both_overlays_add": audit["cross_overlay"]["both_overlays_add"],
            }
        )
    return rows


def _zone_parent_rows(
    members: list[dict[str, Any]],
    parent_audits: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    counts: Counter[tuple[int, str, str, str]] = Counter()
    metadata: dict[tuple[int, str, str], dict[str, Any]] = {}
    for member in members:
        zone_id = int(member["zone_id"])
        kind = str(member["parent_subject_kind"])
        key = str(member["parent_subject_key"])
        side = _source_side(str(member["three_way_pattern"]))
        counts[(zone_id, kind, key, side)] += 1
        metadata.setdefault(
            (zone_id, kind, key),
            {
                "zone_name": member.get("zone_name"),
                "map_id": member.get("map_id"),
                "map_name": member.get("map_name"),
            },
        )
    parent_keys = {(zone, kind, key) for zone, kind, key, _side in counts}
    rows: list[dict[str, Any]] = []
    for zone_id, kind, key in sorted(
        parent_keys,
        key=lambda item: (
            item[0],
            -(
                counts[(item[0], item[1], item[2], "active")]
                + counts[(item[0], item[1], item[2], "comparison")]
            ),
            item[1],
            _subject_key_sort(item[2]),
        ),
    ):
        active_count = counts[(zone_id, kind, key, "active")]
        comparison_count = counts[(zone_id, kind, key, "comparison")]
        audit = parent_audits[(kind, key)]
        rows.append(
            {
                "zone_id": zone_id,
                "zone_name": metadata[(zone_id, kind, key)]["zone_name"],
                "map_id": metadata[(zone_id, kind, key)]["map_id"],
                "map_name": metadata[(zone_id, kind, key)]["map_name"],
                "parent_subject_kind": kind,
                "parent_subject_key": key,
                "addition_parent_class": audit["addition_parent_class"],
                "active_addition_member_count": active_count,
                "comparison_addition_member_count": comparison_count,
                "total_addition_member_count": active_count + comparison_count,
                "active_raw_transformation_class": audit["active"]["raw_transformation_class"],
                "comparison_raw_transformation_class": audit["comparison"][
                    "raw_transformation_class"
                ],
            }
        )
    return rows


def _top_zone_parents(zone_parent_rows: list[dict[str, Any]], *, top: int) -> list[dict[str, Any]]:
    if top == 0:
        return []
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in zone_parent_rows:
        grouped[int(row["zone_id"])].append(row)
    result: list[dict[str, Any]] = []
    for zone_id in sorted(grouped):
        ordered = sorted(
            grouped[zone_id],
            key=lambda row: (
                -int(row["total_addition_member_count"]),
                str(row["parent_subject_kind"]),
                _subject_key_sort(str(row["parent_subject_key"])),
            ),
        )
        for rank, row in enumerate(ordered[:top], start=1):
            result.append({"zone_rank": rank, **row})
    return result


def _zone_parent_transformation_counts(
    zone_parent_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    counter: Counter[tuple[int, str, str]] = Counter()
    for row in zone_parent_rows:
        for side in SOURCE_SIDES:
            counter[(
                int(row["zone_id"]),
                side,
                str(row[f"{side}_raw_transformation_class"]),
            )] += 1
    return [
        {
            "zone_id": zone_id,
            "source_side": side,
            "raw_transformation_class": transform,
            "distinct_parent_count": count,
        }
        for (zone_id, side, transform), count in sorted(counter.items())
    ]


def _base_present_member_composition(
    parent_audits: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (kind, key), audit in sorted(
        parent_audits.items(), key=lambda item: (item[0][0], _subject_key_sort(item[0][1]))
    ):
        if not audit["base_entry_present"]:
            continue
        for side in SOURCE_SIDES:
            counts = audit[side]["member_class_counts"]
            inherited = int(counts["member_inherited_from_base"])
            added = int(counts["member_added_by_overlay"])
            removed = int(counts["member_removed_by_overlay"])
            effective = int(audit[side]["effective_unique_member_count"])
            rows.append(
                {
                    "parent_subject_kind": kind,
                    "parent_subject_key": key,
                    "source_side": side,
                    "raw_transformation_class": audit[side]["raw_transformation_class"],
                    "effective_unique_member_count": effective,
                    "member_inherited_from_base_count": inherited,
                    "member_added_by_overlay_count": added,
                    "member_removed_by_overlay_count": removed,
                    "inherited_percentage_of_effective_set": _percentage(inherited, effective),
                    "added_percentage_of_effective_set": _percentage(added, effective),
                }
            )
    return rows


def _descriptive_zone_signals(zone_summary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in zone_summary:
        total = int(row["addition_member_count"])
        absent = int(row["addition_parent_class_counts"]["parent_absent_from_base"])
        base_extra = int(row["addition_parent_class_counts"]["spawn_added_to_base_present_parent"])
        active = int(row["source_side_counts"]["active"])
        comparison = int(row["source_side_counts"]["comparison"])
        signals: list[str] = []
        if base_extra > absent:
            signals.append("base_content_spawn_set_enrichment_candidate")
        if absent >= base_extra:
            signals.append("overlay_added_or_custom_content_candidate")
        if active and comparison:
            signals.append("both_source_families_contribute")
        elif active and not comparison:
            signals.append("active_source_family_only_in_p5_t06_slice")
        elif comparison and not active:
            signals.append("comparison_source_family_only_in_p5_t06_slice")
        rows.append(
            {
                "zone_id": row["zone_id"],
                "zone_name": row["zone_name"],
                "signals": signals,
                "parent_absent_percentage": _percentage(absent, total),
                "base_present_extra_percentage": _percentage(base_extra, total),
                "interpretive_boundary": (
                    "descriptive raw-source evidence only; does not authorize source promotion"
                ),
            }
        )
    return rows

def _duplicate_summary(parent_audits: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    base = 0
    active_patch = 0
    comparison_patch = 0
    examples: list[dict[str, Any]] = []
    for (kind, key), audit in sorted(parent_audits.items()):
        base += int(audit["active"]["base_duplicate_member_count"])
        active_patch += int(audit["active"]["patch_duplicate_member_count"])
        comparison_patch += int(audit["comparison"]["patch_duplicate_member_count"])
        for side in SOURCE_SIDES:
            duplicate_keys = audit[side]["patch_duplicate_spawn_keys"]
            if duplicate_keys and len(examples) < 12:
                examples.append(
                    {
                        "parent_subject_kind": kind,
                        "parent_subject_key": key,
                        "source_side": side,
                        "duplicate_spawn_keys": duplicate_keys[:5],
                    }
                )
    return {
        "base_raw_duplicate_row_count": base,
        "active_overlay_raw_duplicate_row_count": active_patch,
        "comparison_overlay_raw_duplicate_row_count": comparison_patch,
        "duplicate_rows_collapse_by_spawn_key": True,
        "examples": examples,
    }


def _cross_overlay_summary(parent_audits: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    both_add = 0
    shared = 0
    both_replaced = 0
    different_replacements = 0
    for audit in parent_audits.values():
        cross = audit["cross_overlay"]
        both_add += int(bool(cross["both_overlays_add"]))
        shared += int(cross["shared_exact_added_member_count_in_audited_zones"])
        if cross["both_whole_entry_replacements"]:
            both_replaced += 1
            if cross["replacement_payloads_equal"] is False:
                different_replacements += 1
    return {
        "both_overlays_add_parent_count": both_add,
        "shared_exact_added_member_count_in_audited_zones": shared,
        "both_whole_entry_replacement_parent_count": both_replaced,
        "different_whole_entry_replacement_payload_parent_count": different_replacements,
    }


def _source_examples(
    parent_rows: list[dict[str, Any]],
    parent_audits: dict[tuple[str, str], dict[str, Any]],
    *,
    top: int,
) -> list[dict[str, Any]]:
    if top == 0:
        return []
    seen: set[tuple[str, str]] = set()
    rows: list[dict[str, Any]] = []
    for parent in parent_rows:
        key = (str(parent["parent_subject_kind"]), str(parent["parent_subject_key"]))
        audit = parent_audits[key]
        for side in SOURCE_SIDES:
            transform = str(audit[side]["raw_transformation_class"])
            class_key = (side, transform)
            if class_key in seen:
                continue
            seen.add(class_key)
            rows.append(
                {
                    "source_side": side,
                    "raw_transformation_class": transform,
                    "parent_subject_kind": key[0],
                    "parent_subject_key": key[1],
                    "raw_source_relative_paths": audit[side]["raw_source_relative_paths"],
                    "raw_top_entry_key": audit[side]["raw_top_entry_key"],
                    "patch_payload_sha256": audit[side]["patch_payload_sha256"],
                }
            )
            if top >= 0 and len(rows) >= top:
                return rows
    return rows


def _decorate_members(
    members: list[dict[str, Any]],
    parent_audits: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    decorated: list[dict[str, Any]] = []
    for raw in members:
        member = dict(raw)
        side = _source_side(str(member["three_way_pattern"]))
        parent_key = (str(member["parent_subject_kind"]), str(member["parent_subject_key"]))
        view = parent_audits[parent_key][side]
        member["source_side"] = side
        member["raw_member_class"] = (
            "member_added_by_overlay" if side == "active" else "member_present_only_in_comparison"
        )
        member["raw_transformation_class"] = view["raw_transformation_class"]
        member["raw_source_family"] = "pfquest-turtle" if side == "active" else "pfquest-octo"
        member["raw_source_relative_path"] = view["raw_source_relative_paths"][0]
        member["raw_source_relative_paths"] = view["raw_source_relative_paths"]
        member["raw_top_entry_key"] = view["raw_top_entry_key"]
        member["raw_effective_matches_persisted_spawn_set"] = view["persisted_spawn_set"][
            "raw_matches_persisted"
        ]
        decorated.append(member)
    decorated.sort(
        key=lambda row: (
            int(row["zone_id"]),
            str(row["subject_kind"]),
            _subject_key_sort(str(row["parent_subject_key"])),
            str(row["source_side"]),
            str(row["spawn_key"]),
        )
    )
    return decorated


def _filter_members(
    members: list[dict[str, Any]],
    *,
    parent_key: str | None,
    subject_kind: str | None,
    source_side: str | None,
    addition_parent_class: str | None,
    raw_transformation_class: str | None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for member in members:
        if parent_key is not None and str(member["parent_subject_key"]) != str(parent_key):
            continue
        if subject_kind is not None and member["subject_kind"] != subject_kind:
            continue
        if source_side not in (None, "both") and member["source_side"] != source_side:
            continue
        if (
            addition_parent_class is not None
            and member["addition_parent_class"] != addition_parent_class
        ):
            continue
        if (
            raw_transformation_class is not None
            and member["raw_transformation_class"] != raw_transformation_class
        ):
            continue
        filtered.append(member)
    return filtered


def raw_spawn_semantic_report(
    connection: sqlite3.Connection,
    *,
    pfquest_root: str | Path,
    pfquest_turtle_root: str | Path,
    pfquest_octo_root: str | Path,
    zone_ids: Iterable[int] = DEFAULT_ZONE_IDS,
    parent_key: str | int | None = None,
    subject_kind: str | None = None,
    source_side: str | None = None,
    addition_parent_class: str | None = None,
    raw_transformation_class: str | None = None,
    limit: int = 100,
    top: int = 20,
) -> dict[str, Any]:
    """Trace the bounded P5-T07 addition slice from raw entries to persisted P5 evidence."""

    if subject_kind is not None and subject_kind not in SPAWN_SUBJECT_KINDS:
        raise ValueError(f"subject_kind must be one of {list(SPAWN_SUBJECT_KINDS)!r}")
    if source_side is not None and source_side not in SOURCE_SIDE_FILTERS:
        raise ValueError(f"source_side must be one of {list(SOURCE_SIDE_FILTERS)!r}")
    if addition_parent_class is not None and addition_parent_class not in ADDITION_PARENT_CLASSES:
        raise ValueError(
            f"addition_parent_class must be one of {list(ADDITION_PARENT_CLASSES)!r}"
        )
    if (
        raw_transformation_class is not None
        and raw_transformation_class not in RAW_TRANSFORMATION_CLASSES
    ):
        raise ValueError(
            f"raw_transformation_class must be one of {list(RAW_TRANSFORMATION_CLASSES)!r}"
        )
    if limit < 0 or top < 0:
        raise ValueError("limit and top must be non-negative")

    pfquest_root = Path(pfquest_root).expanduser().resolve()
    pfquest_turtle_root = Path(pfquest_turtle_root).expanduser().resolve()
    pfquest_octo_root = Path(pfquest_octo_root).expanduser().resolve()
    for label, root in (
        ("pfquest", pfquest_root),
        ("pfquest_turtle", pfquest_turtle_root),
        ("pfquest_octo", pfquest_octo_root),
    ):
        if not root.is_dir():
            raise FileNotFoundError(f"P5-T07 source root not found for {label}: {root}")

    source_revisions = _require_exact_source_revisions(
        pfquest_root=pfquest_root,
        pfquest_turtle_root=pfquest_turtle_root,
        pfquest_octo_root=pfquest_octo_root,
    )

    from octogamedb.audit_overlay_additions import _load_addition_population
    from octogamedb.audit_spawn_attribution import _base_membership_contexts

    population = _load_addition_population(
        connection,
        base_source_revision=EXPECTED_BASE_REVISION,
        comparison_source_revision=EXPECTED_COMPARISON_REVISION,
    )
    all_additions = list(population["members"])
    if len(all_additions) != EXPECTED_P5_T06_INCLUDED_TOTAL:
        raise RawSemanticAuditError(
            f"P5-T07 requires exact P5-T06 baseline {EXPECTED_P5_T06_INCLUDED_TOTAL}, "
            f"measured {len(all_additions)}"
        )

    audited_zone_ids = {int(zone_id) for zone_id in zone_ids}
    if not audited_zone_ids:
        raise ValueError("at least one zone_id is required")
    zone_members = [
        member
        for member in all_additions
        if member.get("zone_id") is not None and int(member["zone_id"]) in audited_zone_ids
    ]
    if audited_zone_ids == set(DEFAULT_ZONE_IDS) and len(zone_members) != EXPECTED_FOUR_ZONE_TOTAL:
        raise RawSemanticAuditError(
            f"P5-T07 four-zone baseline mismatch: expected {EXPECTED_FOUR_ZONE_TOTAL}, "
            f"measured {len(zone_members)}"
        )

    parents = {
        (str(member["parent_subject_kind"]), str(member["parent_subject_key"]))
        for member in zone_members
    }
    base_revision, _base_batches, base_contexts = _base_membership_contexts(
        connection,
        source_key="pfquest",
        source_revision=EXPECTED_BASE_REVISION,
        parents=parents,
    )
    if base_revision != EXPECTED_BASE_REVISION:
        raise RawSemanticAuditError("persisted base revision changed during P5-T07")

    active_inputs = _load_composition_inputs(
        pfquest_root, pfquest_turtle_root, overlay_kind="turtle"
    )
    comparison_inputs = _load_composition_inputs(
        pfquest_root, pfquest_octo_root, overlay_kind="octo"
    )
    active_persisted_contexts = _persisted_spawn_set_contexts(
        connection,
        source_key="pfquest-turtle",
        source_revision=EXPECTED_ACTIVE_REVISION,
        parents=parents,
    )
    comparison_persisted_contexts = _persisted_spawn_set_contexts(
        connection,
        source_key="pfquest-octo",
        source_revision=EXPECTED_COMPARISON_REVISION,
        parents=parents,
    )

    parent_members: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for member in zone_members:
        key = (str(member["parent_subject_kind"]), str(member["parent_subject_key"]))
        parent_members[key].append(member)

    parent_audits: dict[tuple[str, str], dict[str, Any]] = {}
    for key in sorted(parents, key=lambda item: (item[0], _subject_key_sort(item[1]))):
        base_context = base_contexts.get(key)
        if base_context is None:
            raise RawSemanticAuditError(f"missing persisted base context for {key[0]}:{key[1]}")
        parent_audits[key] = _build_parent_audit(
            parent_kind=key[0],
            parent_key=key[1],
            parent_members=parent_members[key],
            active_inputs=active_inputs,
            comparison_inputs=comparison_inputs,
            base_context=base_context,
            active_persisted_context=active_persisted_contexts.get(key),
            comparison_persisted_context=comparison_persisted_contexts.get(key),
            audited_zone_ids=audited_zone_ids,
        )

    decorated = _decorate_members(zone_members, parent_audits)
    zone_summary = _zone_rows(decorated)
    if audited_zone_ids == set(DEFAULT_ZONE_IDS):
        measured_zone_counts = {
            int(row["zone_id"]): int(row["addition_member_count"]) for row in zone_summary
        }
        if measured_zone_counts != DEFAULT_ZONE_COUNTS:
            raise RawSemanticAuditError(
                f"P5-T07 exact four-zone counts changed: expected {DEFAULT_ZONE_COUNTS}, "
                f"measured {measured_zone_counts}"
            )

    zone_parent_class, zone_source_side, zone_transform = _aggregate_rows(decorated, parent_audits)
    parent_rows = _parent_rows(decorated, parent_audits)
    zone_parent_rows = _zone_parent_rows(decorated, parent_audits)
    zone_parent_transforms = _zone_parent_transformation_counts(zone_parent_rows)
    base_present_composition = _base_present_member_composition(parent_audits)
    top_zone_parents = _top_zone_parents(zone_parent_rows, top=top)
    cross_summary = _cross_overlay_summary(parent_audits)
    duplicate_summary = _duplicate_summary(parent_audits)
    source_examples = _source_examples(parent_rows, parent_audits, top=top)
    descriptive_signals = _descriptive_zone_signals(zone_summary)

    reconciliation_totals = (
        sum(int(row["addition_member_count"]) for row in zone_summary),
        sum(int(row["member_count"]) for row in zone_parent_class),
        sum(int(row["member_count"]) for row in zone_source_side),
        sum(int(row["member_count"]) for row in zone_transform),
        sum(int(row["total_addition_member_count"]) for row in zone_parent_rows),
    )
    if any(value != len(decorated) for value in reconciliation_totals):
        raise AssertionError(
            f"P5-T07 four-zone aggregates do not reconcile: {reconciliation_totals}"
        )

    filtered = _filter_members(
        decorated,
        parent_key=None if parent_key is None else str(parent_key),
        subject_kind=subject_kind,
        source_side=source_side,
        addition_parent_class=addition_parent_class,
        raw_transformation_class=raw_transformation_class,
    )
    returned = filtered[:limit]
    parent_limit = parent_rows[:top]
    public_parent_audits = [
        parent_audits[(row["parent_subject_kind"], row["parent_subject_key"])]
        for row in parent_limit
    ]

    return {
        "scope": RAW_SEMANTIC_SCOPE,
        "read_only": True,
        "source_revisions": source_revisions,
        "p5_t06_global_included_member_count": len(all_additions),
        "audited_zone_ids": sorted(audited_zone_ids),
        "audited_zone_member_count": len(decorated),
        "zone_summary": zone_summary,
        "zone_by_addition_parent_class": zone_parent_class,
        "zone_by_source_side": zone_source_side,
        "zone_by_raw_transformation_class": zone_transform,
        "raw_transformation_classes": list(RAW_TRANSFORMATION_CLASSES),
        "raw_member_classes": list(MEMBER_CLASSES),
        "parent_count": len(parent_rows),
        "parent_counts": parent_rows,
        "zone_parent_counts": zone_parent_rows,
        "top_parent_concentrations_by_zone": top_zone_parents,
        "zone_parent_transformation_counts": zone_parent_transforms,
        "base_present_parent_member_composition": base_present_composition,
        "cross_overlay_membership": cross_summary,
        "descriptive_zone_signals": descriptive_signals,
        "reconciliation": {
            "zone_summary_total": sum(int(row["addition_member_count"]) for row in zone_summary),
            "zone_parent_class_total": sum(int(row["member_count"]) for row in zone_parent_class),
            "zone_source_side_total": sum(int(row["member_count"]) for row in zone_source_side),
            "zone_raw_transformation_member_total": sum(
                int(row["member_count"]) for row in zone_transform
            ),
            "zone_parent_total": sum(
                int(row["total_addition_member_count"]) for row in zone_parent_rows
            ),
        },
        "duplicate_diagnostics": duplicate_summary,
        "source_file_top_entry_examples": source_examples,
        "filters": {
            "parent_key": None if parent_key is None else str(parent_key),
            "subject_kind": subject_kind,
            "source_side": source_side,
            "addition_parent_class": addition_parent_class,
            "raw_transformation_class": raw_transformation_class,
        },
        "filtered_member_count": len(filtered),
        "returned_member_count": len(returned),
        "members_truncated": len(returned) < len(filtered),
        "members": returned,
        "returned_parent_audit_count": len(public_parent_audits),
        "parent_audits_truncated": len(public_parent_audits) < len(parent_rows),
        "parent_audits": public_parent_audits,
    }


def _read_source_paths(
    *,
    config_path: Path,
    pfquest_root: Path | None,
    pfquest_turtle_root: Path | None,
    pfquest_octo_root: Path | None,
) -> tuple[Path, Path, Path]:
    configured: dict[str, Any] = {}
    if config_path.is_file():
        with config_path.open("rb") as handle:
            payload = tomllib.load(handle)
        section = payload.get("source_paths")
        if isinstance(section, dict):
            configured = section

    def resolve(explicit: Path | None, key: str) -> Path:
        if explicit is not None:
            return explicit
        value = configured.get(key)
        if not isinstance(value, str) or not value.strip():
            raise FileNotFoundError(
                f"P5-T07 requires [source_paths].{key} in {config_path}; "
                "run the task handoff get_path.bat or pass the explicit root option"
            )
        return Path(value)

    return (
        resolve(pfquest_root, "pfquest"),
        resolve(pfquest_turtle_root, "pfquest_turtle"),
        resolve(pfquest_octo_root, "pfquest_octo"),
    )


def _parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=project_root / "data" / "generated" / "octogamedb.sqlite3",
    )
    parser.add_argument("--config", type=Path, default=project_root / "config.local.toml")
    parser.add_argument("--pfquest-root", type=Path)
    parser.add_argument("--pfquest-turtle-root", type=Path)
    parser.add_argument("--pfquest-octo-root", type=Path)
    parser.add_argument("--zone-id", type=int, action="append")
    parser.add_argument("--parent-key")
    parser.add_argument("--subject-kind", choices=SPAWN_SUBJECT_KINDS)
    parser.add_argument("--source-side", choices=SOURCE_SIDE_FILTERS)
    parser.add_argument("--addition-parent-class", choices=ADDITION_PARENT_CLASSES)
    parser.add_argument("--raw-transformation-class", choices=RAW_TRANSFORMATION_CLASSES)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    roots = _read_source_paths(
        config_path=args.config,
        pfquest_root=args.pfquest_root,
        pfquest_turtle_root=args.pfquest_turtle_root,
        pfquest_octo_root=args.pfquest_octo_root,
    )
    from octogamedb.audit_comparison import _open_read_only_database

    connection = _open_read_only_database(args.db)
    try:
        report = raw_spawn_semantic_report(
            connection,
            pfquest_root=roots[0],
            pfquest_turtle_root=roots[1],
            pfquest_octo_root=roots[2],
            zone_ids=DEFAULT_ZONE_IDS if args.zone_id is None else args.zone_id,
            parent_key=args.parent_key,
            subject_kind=args.subject_kind,
            source_side=args.source_side,
            addition_parent_class=args.addition_parent_class,
            raw_transformation_class=args.raw_transformation_class,
            limit=args.limit,
            top=args.top,
        )
    finally:
        connection.close()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    print(f"Scope: {report['scope']}")
    print(f"P5-T06 additions: {report['p5_t06_global_included_member_count']}")
    print(f"Audited-zone additions: {report['audited_zone_member_count']}")
    for row in report["zone_summary"]:
        print(
            f"  {row['zone_id']} {row['zone_name']}: {row['addition_member_count']} "
            f"({row['percentage_of_audited_total']:.2f}%)"
        )
    print(f"Relevant parents: {report['parent_count']}")
    print(
        "Shared exact overlay-added members in audited zones: "
        f"{report['cross_overlay_membership']['shared_exact_added_member_count_in_audited_zones']}"
    )
    if report["filtered_member_count"]:
        print(f"Detailed members returned: {report['returned_member_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
