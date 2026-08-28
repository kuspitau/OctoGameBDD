"""Read-only P5-T08 semantic audit for shared overlay whole-entry replacements.

The audit is deliberately bounded to the P5-T07 routed parent population where both
pfQuest-turtle and pfquest-octo perform a whole-entry replacement.  It reuses the
validated P1/P5 Lua composition, deterministic ``spawn_key`` identity, P5-T06 routed
addition population and P5-T07 bulk provenance loaders.  No canonical selection or
SQLite row is modified.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sqlite3
import tomllib
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPLACEMENT_SEMANTIC_SCOPE = "p5-t08-shared-parent-overlay-replacement-semantic-divergence"
EXPECTED_P5_T06_INCLUDED_TOTAL = 20_707
EXPECTED_P5_T07_FOUR_ZONE_TOTAL = 15_607
EXPECTED_FIXED_PARENT_COUNT = 1_085
EXPECTED_DIFFERENT_REPLACEMENT_PAYLOAD_COUNT = 1_085
EXPECTED_SHARED_EXACT_ADDED_ROUTED_COUNT = 3
DEFAULT_ZONE_IDS = (406, 5602, 5581, 1584)
DEFAULT_ZONE_COUNTS = {406: 5_145, 5602: 5_062, 5581: 2_872, 1584: 2_528}

SET_RELATION_CLASSES = (
    "active_equals_comparison",
    "active_strict_superset",
    "comparison_strict_superset",
    "partial_overlap",
    "disjoint",
)
RAW_PAYLOAD_DIFFERENCE_CLASSES = (
    "spawn_membership_only",
    "localization_name_only",
    "other_top_entry_fields_only",
    "spawn_plus_other_fields",
    "unsupported_unclassified",
)
SOURCE_CONTRIBUTION_CLASSES = ("active_only", "comparison_only", "both_sources")
PARENT_KINDS = ("creature", "gameobject")
BASE_PARENT_CLASSES = (
    "parent_absent_from_base",
    "spawn_added_to_base_present_parent",
)

_PARENT_DOMAINS = {"creature": "units", "gameobject": "objects"}


class ReplacementSemanticAuditError(ValueError):
    """Raised when P5-T08 cannot prove an exact bounded semantic invariant."""


def _raw_module() -> Any:
    """Resolve P5-T07 helpers lazily so reduced tests can inject a synthetic module."""

    return importlib.import_module("octogamedb.audit_spawn_raw_semantics")


@dataclass(frozen=True)
class _BulkPersistence:
    base_revision: str
    base_contexts: dict[tuple[str, str], dict[str, Any]]
    active_contexts: dict[tuple[str, str], dict[str, Any]]
    comparison_contexts: dict[tuple[str, str], dict[str, Any]]


def _subject_key_sort(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


def _source_side(pattern: str) -> str:
    if pattern == "active_only_vs_base":
        return "active"
    if pattern == "comparison_only_vs_base":
        return "comparison"
    raise ReplacementSemanticAuditError(f"unsupported routed addition pattern: {pattern!r}")


def classify_set_relation(active: set[str], comparison: set[str]) -> str:
    """Classify exact A/C membership using deterministic spawn keys only."""

    if active == comparison:
        return "active_equals_comparison"
    if active > comparison:
        return "active_strict_superset"
    if comparison > active:
        return "comparison_strict_superset"
    if active.isdisjoint(comparison):
        return "disjoint"
    return "partial_overlap"


def _set_cardinalities(base: set[str], active: set[str], comparison: set[str]) -> dict[str, int]:
    values = {
        "base": len(base),
        "active": len(active),
        "comparison": len(comparison),
        "active_intersection_comparison": len(active & comparison),
        "active_minus_comparison": len(active - comparison),
        "comparison_minus_active": len(comparison - active),
        "active_minus_base": len(active - base),
        "comparison_minus_base": len(comparison - base),
        "base_minus_active": len(base - active),
        "base_minus_comparison": len(base - comparison),
    }
    if values["active"] != (
        values["active_intersection_comparison"] + values["active_minus_comparison"]
    ):
        raise AssertionError("P5-T08 active set cardinality identity failed")
    if values["comparison"] != (
        values["active_intersection_comparison"] + values["comparison_minus_active"]
    ):
        raise AssertionError("P5-T08 comparison set cardinality identity failed")
    if values["active"] != (
        len(active & base) + values["active_minus_base"]
    ):
        raise AssertionError("P5-T08 active/base cardinality identity failed")
    if values["comparison"] != (
        len(comparison & base) + values["comparison_minus_base"]
    ):
        raise AssertionError("P5-T08 comparison/base cardinality identity failed")
    return values


def classify_raw_payload_difference(
    *,
    spawn_membership_differs: bool,
    localization_differs: bool,
    other_top_entry_fields_differ: bool,
    unsupported_reasons: Iterable[str] = (),
) -> str:
    """Classify semantic payload divergence without assigning meaning to unknown fields."""

    if tuple(unsupported_reasons):
        return "unsupported_unclassified"
    other_semantics_differ = localization_differs or other_top_entry_fields_differ
    if spawn_membership_differs and other_semantics_differ:
        return "spawn_plus_other_fields"
    if spawn_membership_differs:
        return "spawn_membership_only"
    if localization_differs and not other_top_entry_fields_differ:
        return "localization_name_only"
    if other_top_entry_fields_differ:
        return "other_top_entry_fields_only"
    return "unsupported_unclassified"


def _display_key(value: Any) -> str:
    return value if isinstance(value, str) else f"{type(value).__name__}:{value!r}"


def _other_top_entry_fields(entry: Any) -> dict[Any, Any]:
    if not isinstance(entry, dict):
        raise ReplacementSemanticAuditError(
            "P5-T08 fixed replacement entry must be a Lua table after P1 composition"
        )
    return {key: value for key, value in entry.items() if key != "coords"}


def _changed_top_entry_fields(active: dict[Any, Any], comparison: dict[Any, Any]) -> list[str]:
    raw = _raw_module()

    keys = set(active) | set(comparison)
    changed = []
    for key in keys:
        if key not in active or key not in comparison:
            changed.append(_display_key(key))
            continue
        if raw._payload_digest(active[key]) != raw._payload_digest(comparison[key]):
            changed.append(_display_key(key))
    return sorted(changed)


def _effective_localization(inputs: Any, *, parent_kind: str, parent_key: int) -> Any:
    raw = _raw_module()

    domain = _PARENT_DOMAINS[parent_kind]
    base_names = inputs.base_tables[(domain, "enUS")]
    patch_names = inputs.patch_tables[(domain, "enUS-turtle")]
    base_value = base_names.get(parent_key, raw._MISSING)
    patch_value = patch_names.get(parent_key, raw._MISSING)
    return raw._composed_top_entry(base_value, patch_value)


def _semantic_payload_difference(
    *,
    parent_kind: str,
    parent_key: int,
    active_inputs: Any,
    comparison_inputs: Any,
    active_view: dict[str, Any],
    comparison_view: dict[str, Any],
) -> dict[str, Any]:
    raw = _raw_module()

    domain = _PARENT_DOMAINS[parent_kind]
    active_patch = active_inputs.patch_tables[(domain, "data-turtle")].get(
        parent_key, raw._MISSING
    )
    comparison_patch = comparison_inputs.patch_tables[(domain, "data-turtle")].get(
        parent_key, raw._MISSING
    )
    if not isinstance(active_patch, dict) or not isinstance(comparison_patch, dict):
        raise ReplacementSemanticAuditError(
            f"fixed parent {parent_kind}:{parent_key} no longer has two replacement tables"
        )

    active_other = _other_top_entry_fields(active_patch)
    comparison_other = _other_top_entry_fields(comparison_patch)
    changed_fields = _changed_top_entry_fields(active_other, comparison_other)
    active_other_digest = raw._payload_digest(active_other)
    comparison_other_digest = raw._payload_digest(comparison_other)

    active_name = _effective_localization(
        active_inputs, parent_kind=parent_kind, parent_key=parent_key
    )
    comparison_name = _effective_localization(
        comparison_inputs, parent_kind=parent_kind, parent_key=parent_key
    )
    unsupported: list[str] = []
    for side, value in (("active", active_name), ("comparison", comparison_name)):
        if value is not None and not isinstance(value, str):
            unsupported.append(f"{side}_effective_localization_type={type(value).__name__}")

    active_keys = set(active_view["effective_member_keys"])
    comparison_keys = set(comparison_view["effective_member_keys"])
    spawn_differs = active_keys != comparison_keys
    localization_differs = active_name != comparison_name
    other_differs = active_other_digest != comparison_other_digest
    difference_class = classify_raw_payload_difference(
        spawn_membership_differs=spawn_differs,
        localization_differs=localization_differs,
        other_top_entry_fields_differ=other_differs,
        unsupported_reasons=unsupported,
    )

    # A raw replacement payload can differ while its deterministic membership and all
    # supported non-coordinate semantics compare equal (for example duplicate/order-only
    # coordinate representation).  The task explicitly requires fail-closed behavior for
    # such an interpretation rather than silently calling it semantic equality.
    if difference_class == "unsupported_unclassified":
        if not unsupported:
            unsupported.append(
                "replacement payload differs but supported effective spawn/name/other-field "
                "semantics compare equal"
            )
        raise ReplacementSemanticAuditError(
            f"unsupported/unclassified raw divergence for {parent_kind}:{parent_key}: "
            + "; ".join(unsupported)
        )

    return {
        "difference_class": difference_class,
        "spawn_membership_differs": spawn_differs,
        "localization_name_differs": localization_differs,
        "other_top_entry_fields_differ": other_differs,
        "other_changed_field_keys": changed_fields,
        "active_other_top_entry_sha256": active_other_digest,
        "comparison_other_top_entry_sha256": comparison_other_digest,
        "active_effective_name": active_name,
        "comparison_effective_name": comparison_name,
        "unsupported_reasons": unsupported,
    }


def _routed_parent_contexts(
    members: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for member in members:
        key = (str(member["parent_subject_kind"]), str(member["parent_subject_key"]))
        grouped[key].append(member)

    result: dict[tuple[str, str], dict[str, Any]] = {}
    for key, rows in grouped.items():
        classes = {str(row["addition_parent_class"]) for row in rows}
        if len(classes) != 1:
            raise ReplacementSemanticAuditError(
                f"routed parent {key[0]}:{key[1]} has conflicting base-parent classes"
            )
        side_counts = Counter(_source_side(str(row["three_way_pattern"])) for row in rows)
        if side_counts["active"] and side_counts["comparison"]:
            contribution = "both_sources"
        elif side_counts["active"]:
            contribution = "active_only"
        else:
            contribution = "comparison_only"

        zone_groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            zone_groups[int(row["zone_id"])].append(row)
        zones = []
        for zone_id in sorted(zone_groups):
            zrows = zone_groups[zone_id]
            zcounts = Counter(_source_side(str(row["three_way_pattern"])) for row in zrows)
            if zcounts["active"] and zcounts["comparison"]:
                zclass = "both_sources"
            elif zcounts["active"]:
                zclass = "active_only"
            else:
                zclass = "comparison_only"
            zones.append(
                {
                    "zone_id": zone_id,
                    "zone_name": zrows[0].get("zone_name"),
                    "map_id": zrows[0].get("map_id"),
                    "map_name": zrows[0].get("map_name"),
                    "source_contribution_class": zclass,
                    "active_one_sided_member_count": zcounts["active"],
                    "comparison_one_sided_member_count": zcounts["comparison"],
                    "total_one_sided_member_count": len(zrows),
                }
            )
        result[key] = {
            "base_parent_class": next(iter(classes)),
            "source_contribution_class": contribution,
            "active_one_sided_member_count": side_counts["active"],
            "comparison_one_sided_member_count": side_counts["comparison"],
            "total_one_sided_member_count": len(rows),
            "routed_zones": zones,
        }
    return result


def _bulk_persistence_contexts(
    connection: sqlite3.Connection,
    *,
    parents: set[tuple[str, str]],
) -> _BulkPersistence:
    """Load all reusable provenance/membership contexts exactly once per source side."""

    raw = _raw_module()
    from octogamedb.audit_spawn_attribution import _base_membership_contexts

    base_revision, _base_batches, base_contexts = _base_membership_contexts(
        connection,
        source_key="pfquest",
        source_revision=raw.EXPECTED_BASE_REVISION,
        parents=parents,
    )
    if base_revision != raw.EXPECTED_BASE_REVISION:
        raise ReplacementSemanticAuditError("persisted base revision changed during P5-T08")
    active = raw._persisted_spawn_set_contexts(
        connection,
        source_key="pfquest-turtle",
        source_revision=raw.EXPECTED_ACTIVE_REVISION,
        parents=parents,
    )
    comparison = raw._persisted_spawn_set_contexts(
        connection,
        source_key="pfquest-octo",
        source_revision=raw.EXPECTED_COMPARISON_REVISION,
        parents=parents,
    )
    return _BulkPersistence(base_revision, base_contexts, active, comparison)


def _public_base_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_key": context["source_key"],
        "source_revision": context["source_revision"],
        "import_batches": list(context["import_batches"]),
        "unique_member_count": len(set(context["member_keys"])),
    }


def _source_evidence(view: dict[str, Any], persisted: dict[str, Any]) -> dict[str, Any]:
    return {
        "raw_source_relative_paths": list(view["raw_source_relative_paths"]),
        "raw_top_entry_key": view["raw_top_entry_key"],
        "patch_payload_sha256": view["patch_payload_sha256"],
        "persisted_spawn_set": persisted,
    }


def _build_fixed_parent(
    *,
    key: tuple[str, str],
    routed: dict[str, Any],
    active_inputs: Any,
    comparison_inputs: Any,
    persistence: _BulkPersistence,
    active_view: dict[str, Any],
    comparison_view: dict[str, Any],
) -> dict[str, Any]:
    raw = _raw_module()

    parent_kind, parent_key = key
    numeric_key = int(parent_key)
    active = active_view
    comparison = comparison_view
    if active["raw_transformation_class"] != "overlay_whole_entry_replaced" or comparison[
        "raw_transformation_class"
    ] != "overlay_whole_entry_replaced":
        raise AssertionError("_build_fixed_parent called for a non-fixed P5-T08 parent")
    if active["patch_payload_sha256"] == comparison["patch_payload_sha256"]:
        raise ReplacementSemanticAuditError(
            "P5-T08 fixed parent replacement payload unexpectedly equal: "
            f"{parent_kind}:{parent_key}"
        )

    base_context = persistence.base_contexts.get(key)
    if base_context is None:
        raise ReplacementSemanticAuditError(
            f"missing persisted base context for fixed parent {parent_kind}:{parent_key}"
        )
    base = set(base_context["member_keys"])
    if set(active["base_member_keys"]) != base or set(comparison["base_member_keys"]) != base:
        raise ReplacementSemanticAuditError(
            f"raw base membership != persisted base spawn_set for {parent_kind}:{parent_key}"
        )

    active_persisted = raw._verify_overlay_persistence(
        parent_kind=parent_kind,
        parent_key=parent_key,
        side="active",
        view=active,
        base_context=base_context,
        persisted_context=persistence.active_contexts.get(key),
    )
    comparison_persisted = raw._verify_overlay_persistence(
        parent_kind=parent_kind,
        parent_key=parent_key,
        side="comparison",
        view=comparison,
        base_context=base_context,
        persisted_context=persistence.comparison_contexts.get(key),
    )

    active_set = set(active["effective_member_keys"])
    comparison_set = set(comparison["effective_member_keys"])
    relation = classify_set_relation(active_set, comparison_set)
    cardinalities = _set_cardinalities(base, active_set, comparison_set)
    payload = _semantic_payload_difference(
        parent_kind=parent_kind,
        parent_key=numeric_key,
        active_inputs=active_inputs,
        comparison_inputs=comparison_inputs,
        active_view=active,
        comparison_view=comparison,
    )
    return {
        "parent_subject_kind": parent_kind,
        "parent_subject_key": parent_key,
        "base_parent_class": routed["base_parent_class"],
        "source_contribution_class": routed["source_contribution_class"],
        "routed_contribution": routed,
        "set_relation_class": relation,
        "set_cardinalities": cardinalities,
        "raw_payload_difference": payload,
        "base_provenance": _public_base_context(base_context),
        "active_evidence": _source_evidence(active, active_persisted),
        "comparison_evidence": _source_evidence(comparison, comparison_persisted),
    }


def _aggregate_counts(
    parents: list[dict[str, Any]], fields: tuple[str, ...]
) -> list[dict[str, Any]]:
    counter: Counter[tuple[Any, ...]] = Counter()
    for parent in parents:
        values = []
        for field in fields:
            if field == "raw_payload_difference_class":
                values.append(parent["raw_payload_difference"]["difference_class"])
            else:
                values.append(parent[field])
        counter[tuple(values)] += 1
    rows = []
    for values, count in sorted(counter.items(), key=lambda item: tuple(str(v) for v in item[0])):
        row = dict(zip(fields, values, strict=True))
        row["parent_count"] = count
        rows.append(row)
    return rows


def _zone_stratification(parents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[tuple[Any, ...]] = Counter()
    metadata: dict[int, tuple[Any, Any, Any]] = {}
    for parent in parents:
        for zone in parent["routed_contribution"]["routed_zones"]:
            zone_id = int(zone["zone_id"])
            metadata.setdefault(
                zone_id,
                (zone.get("zone_name"), zone.get("map_id"), zone.get("map_name")),
            )
            key = (
                zone_id,
                parent["parent_subject_kind"],
                parent["base_parent_class"],
                zone["source_contribution_class"],
                parent["set_relation_class"],
                parent["raw_payload_difference"]["difference_class"],
            )
            counter[key] += 1
    rows = []
    for key, count in sorted(counter.items(), key=lambda item: tuple(str(v) for v in item[0])):
        zone_id, kind, base_class, source_class, set_class, raw_class = key
        zone_name, map_id, map_name = metadata[zone_id]
        rows.append(
            {
                "zone_id": zone_id,
                "zone_name": zone_name,
                "map_id": map_id,
                "map_name": map_name,
                "parent_subject_kind": kind,
                "base_parent_class": base_class,
                "source_contribution_class": source_class,
                "set_relation_class": set_class,
                "raw_payload_difference_class": raw_class,
                "parent_count": count,
            }
        )
    return rows


def _representative_examples(
    parents: list[dict[str, Any]],
    *,
    source_revisions: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    """Emit one deterministic parent per non-empty routed-zone semantic combination."""

    seen: set[tuple[Any, ...]] = set()
    examples: list[dict[str, Any]] = []
    ordered = sorted(
        parents,
        key=lambda parent: (
            parent["parent_subject_kind"],
            _subject_key_sort(str(parent["parent_subject_key"])),
        ),
    )
    for parent in ordered:
        for zone in parent["routed_contribution"]["routed_zones"]:
            combo = (
                int(zone["zone_id"]),
                parent["parent_subject_kind"],
                parent["base_parent_class"],
                zone["source_contribution_class"],
                parent["set_relation_class"],
                parent["raw_payload_difference"]["difference_class"],
            )
            if combo in seen:
                continue
            seen.add(combo)
            examples.append(
                {
                    "zone_id": zone["zone_id"],
                    "zone_name": zone["zone_name"],
                    "parent_subject_kind": parent["parent_subject_kind"],
                    "parent_subject_key": parent["parent_subject_key"],
                    "base_parent_class": parent["base_parent_class"],
                    "source_contribution_class": zone["source_contribution_class"],
                    "set_relation_class": parent["set_relation_class"],
                    "set_cardinalities": parent["set_cardinalities"],
                    "raw_payload_difference": parent["raw_payload_difference"],
                    "source_revisions": source_revisions,
                    "base_provenance": parent["base_provenance"],
                    "active_evidence": parent["active_evidence"],
                    "comparison_evidence": parent["comparison_evidence"],
                }
            )
    return examples


def _filter_parents(
    parents: list[dict[str, Any]],
    *,
    parent_key: str | None,
    parent_kind: str | None,
    set_relation_class: str | None,
    raw_payload_difference_class: str | None,
    source_contribution_class: str | None,
    zone_id: int | None,
) -> list[dict[str, Any]]:
    result = []
    for parent in parents:
        if parent_key is not None and str(parent["parent_subject_key"]) != parent_key:
            continue
        if parent_kind is not None and parent["parent_subject_kind"] != parent_kind:
            continue
        if set_relation_class is not None and parent["set_relation_class"] != set_relation_class:
            continue
        if (
            raw_payload_difference_class is not None
            and parent["raw_payload_difference"]["difference_class"]
            != raw_payload_difference_class
        ):
            continue
        if (
            source_contribution_class is not None
            and parent["source_contribution_class"] != source_contribution_class
        ):
            continue
        if zone_id is not None and zone_id not in {
            int(row["zone_id"]) for row in parent["routed_contribution"]["routed_zones"]
        }:
            continue
        result.append(parent)
    return result


def replacement_semantic_report(
    connection: sqlite3.Connection,
    *,
    pfquest_root: str | Path,
    pfquest_turtle_root: str | Path,
    pfquest_octo_root: str | Path,
    parent_key: str | int | None = None,
    parent_kind: str | None = None,
    set_relation_class: str | None = None,
    raw_payload_difference_class: str | None = None,
    source_contribution_class: str | None = None,
    zone_id: int | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Run the bounded P5-T08 exact-set and raw semantic divergence audit."""

    if parent_kind is not None and parent_kind not in PARENT_KINDS:
        raise ValueError(f"parent_kind must be one of {list(PARENT_KINDS)!r}")
    if set_relation_class is not None and set_relation_class not in SET_RELATION_CLASSES:
        raise ValueError(f"set_relation_class must be one of {list(SET_RELATION_CLASSES)!r}")
    if (
        raw_payload_difference_class is not None
        and raw_payload_difference_class not in RAW_PAYLOAD_DIFFERENCE_CLASSES
    ):
        raise ValueError(
            "raw_payload_difference_class must be one of "
            f"{list(RAW_PAYLOAD_DIFFERENCE_CLASSES)!r}"
        )
    if (
        source_contribution_class is not None
        and source_contribution_class not in SOURCE_CONTRIBUTION_CLASSES
    ):
        raise ValueError(
            f"source_contribution_class must be one of {list(SOURCE_CONTRIBUTION_CLASSES)!r}"
        )
    if zone_id is not None and int(zone_id) not in DEFAULT_ZONE_IDS:
        raise ValueError(f"zone_id must be one of {list(DEFAULT_ZONE_IDS)!r}")
    if limit < 0:
        raise ValueError("limit must be non-negative")

    roots = [Path(value).expanduser().resolve() for value in (
        pfquest_root,
        pfquest_turtle_root,
        pfquest_octo_root,
    )]
    for label, root in zip(("pfquest", "pfquest_turtle", "pfquest_octo"), roots, strict=True):
        if not root.is_dir():
            raise FileNotFoundError(f"P5-T08 source root not found for {label}: {root}")

    raw = _raw_module()
    from octogamedb.audit_overlay_additions import _load_addition_population

    source_revisions = raw._require_exact_source_revisions(
        pfquest_root=roots[0],
        pfquest_turtle_root=roots[1],
        pfquest_octo_root=roots[2],
    )
    population = _load_addition_population(
        connection,
        base_source_revision=raw.EXPECTED_BASE_REVISION,
        comparison_source_revision=raw.EXPECTED_COMPARISON_REVISION,
    )
    all_additions = list(population["members"])
    if len(all_additions) != EXPECTED_P5_T06_INCLUDED_TOTAL:
        raise ReplacementSemanticAuditError(
            f"P5-T08 requires exact P5-T06 baseline {EXPECTED_P5_T06_INCLUDED_TOTAL}, "
            f"measured {len(all_additions)}"
        )
    routed_members = [
        member
        for member in all_additions
        if member.get("zone_id") is not None and int(member["zone_id"]) in DEFAULT_ZONE_IDS
    ]
    if len(routed_members) != EXPECTED_P5_T07_FOUR_ZONE_TOTAL:
        raise ReplacementSemanticAuditError(
            f"P5-T08 requires exact P5-T07 routed total {EXPECTED_P5_T07_FOUR_ZONE_TOTAL}, "
            f"measured {len(routed_members)}"
        )
    measured_zone_counts = Counter(int(member["zone_id"]) for member in routed_members)
    if dict(measured_zone_counts) != DEFAULT_ZONE_COUNTS:
        raise ReplacementSemanticAuditError(
            f"P5-T08 routed zone counts changed: expected {DEFAULT_ZONE_COUNTS}, "
            f"measured {dict(measured_zone_counts)}"
        )

    routed_contexts = _routed_parent_contexts(routed_members)
    active_inputs = raw._load_composition_inputs(roots[0], roots[1], overlay_kind="turtle")
    comparison_inputs = raw._load_composition_inputs(roots[0], roots[2], overlay_kind="octo")

    fixed_views: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
    fixed: set[tuple[str, str]] = set()
    shared_exact_added = 0
    both_add_parent_count = 0
    different_payload_count = 0
    audited_zone_ids = set(DEFAULT_ZONE_IDS)
    for key in sorted(routed_contexts, key=lambda item: (item[0], _subject_key_sort(item[1]))):
        kind, text_key = key
        numeric_key = int(text_key)
        active = raw._parent_raw_view(active_inputs, parent_kind=kind, parent_key=numeric_key)
        comparison = raw._parent_raw_view(
            comparison_inputs, parent_kind=kind, parent_key=numeric_key
        )
        cross = raw._cross_overlay_membership_sets(
            active, comparison, audited_zone_ids=audited_zone_ids
        )
        shared_exact_added += len(cross["shared_added_in_audited_zones"])
        if cross["active_added_in_audited_zones"] and cross["comparison_added_in_audited_zones"]:
            both_add_parent_count += 1
        if (
            active["raw_transformation_class"] == "overlay_whole_entry_replaced"
            and comparison["raw_transformation_class"] == "overlay_whole_entry_replaced"
        ):
            fixed.add(key)
            fixed_views[key] = (active, comparison)
            if active["patch_payload_sha256"] != comparison["patch_payload_sha256"]:
                different_payload_count += 1

    if shared_exact_added != EXPECTED_SHARED_EXACT_ADDED_ROUTED_COUNT:
        raise ReplacementSemanticAuditError(
            "P5-T08 shared exact routed additions regression failed: "
            f"expected {EXPECTED_SHARED_EXACT_ADDED_ROUTED_COUNT}, measured {shared_exact_added}"
        )
    if len(fixed) != EXPECTED_FIXED_PARENT_COUNT:
        raise ReplacementSemanticAuditError(
            f"P5-T08 fixed parent population changed: expected {EXPECTED_FIXED_PARENT_COUNT}, "
            f"measured {len(fixed)}"
        )
    if different_payload_count != EXPECTED_DIFFERENT_REPLACEMENT_PAYLOAD_COUNT:
        raise ReplacementSemanticAuditError(
            "P5-T08 replacement-payload regression failed: "
            f"expected {EXPECTED_DIFFERENT_REPLACEMENT_PAYLOAD_COUNT}, "
            f"measured {different_payload_count}"
        )

    persistence = _bulk_persistence_contexts(connection, parents=fixed)
    parents = [
        _build_fixed_parent(
            key=key,
            routed=routed_contexts[key],
            active_inputs=active_inputs,
            comparison_inputs=comparison_inputs,
            persistence=persistence,
            active_view=fixed_views[key][0],
            comparison_view=fixed_views[key][1],
        )
        for key in sorted(fixed, key=lambda item: (item[0], _subject_key_sort(item[1])))
    ]
    if len(parents) != EXPECTED_FIXED_PARENT_COUNT:
        raise AssertionError("every P5-T08 fixed parent must be classified exactly once")

    set_counts = Counter(parent["set_relation_class"] for parent in parents)
    raw_counts = Counter(
        parent["raw_payload_difference"]["difference_class"] for parent in parents
    )
    if sum(set_counts.values()) != EXPECTED_FIXED_PARENT_COUNT:
        raise AssertionError("P5-T08 set relation classes do not reconcile")
    if sum(raw_counts.values()) != EXPECTED_FIXED_PARENT_COUNT:
        raise AssertionError("P5-T08 raw payload difference classes do not reconcile")
    if raw_counts["unsupported_unclassified"]:
        raise ReplacementSemanticAuditError(
            "P5-T08 unsupported raw payload semantics escaped fail-closed"
        )

    zone_strata = _zone_stratification(parents)
    examples = _representative_examples(parents, source_revisions=source_revisions)
    filtered = _filter_parents(
        parents,
        parent_key=None if parent_key is None else str(parent_key),
        parent_kind=parent_kind,
        set_relation_class=set_relation_class,
        raw_payload_difference_class=raw_payload_difference_class,
        source_contribution_class=source_contribution_class,
        zone_id=zone_id,
    )
    returned = filtered[:limit]

    return {
        "scope": REPLACEMENT_SEMANTIC_SCOPE,
        "read_only": True,
        "source_revisions": source_revisions,
        "p5_t07_regression": {
            "p5_t06_global_included_member_count": len(all_additions),
            "routed_four_zone_member_count": len(routed_members),
            "routed_zone_counts": {str(key): measured_zone_counts[key] for key in DEFAULT_ZONE_IDS},
            "both_overlays_add_parent_count": both_add_parent_count,
            "both_whole_entry_replacement_parent_count": len(fixed),
            "different_whole_entry_replacement_payload_parent_count": different_payload_count,
            "shared_exact_added_member_count_in_routed_zones": shared_exact_added,
        },
        "fixed_parent_count": len(parents),
        "set_relation_classes": list(SET_RELATION_CLASSES),
        "raw_payload_difference_classes": list(RAW_PAYLOAD_DIFFERENCE_CLASSES),
        "set_relation_counts": {name: set_counts[name] for name in SET_RELATION_CLASSES},
        "raw_payload_difference_counts": {
            name: raw_counts[name] for name in RAW_PAYLOAD_DIFFERENCE_CLASSES
        },
        "stratification": {
            "by_parent_kind": _aggregate_counts(parents, ("parent_subject_kind",)),
            "by_base_parent_class": _aggregate_counts(parents, ("base_parent_class",)),
            "by_source_contribution_class": _aggregate_counts(
                parents, ("source_contribution_class",)
            ),
            "by_set_relation_and_raw_difference": _aggregate_counts(
                parents, ("set_relation_class", "raw_payload_difference_class")
            ),
            "by_parent_kind_base_class_source_relation_raw": _aggregate_counts(
                parents,
                (
                    "parent_subject_kind",
                    "base_parent_class",
                    "source_contribution_class",
                    "set_relation_class",
                    "raw_payload_difference_class",
                ),
            ),
            "by_routed_zone": zone_strata,
        },
        "bulk_load_diagnostics": {
            "base_membership_bulk_loads": 1,
            "active_persisted_spawn_set_bulk_loads": 1,
            "comparison_persisted_spawn_set_bulk_loads": 1,
            "per_parent_provenance_query_loop": False,
            "fixed_parent_count": len(parents),
        },
        "representative_examples": examples,
        "representative_example_count": len(examples),
        "reconciliation": {
            "fixed_parent_count": len(parents),
            "set_relation_class_total": sum(set_counts.values()),
            "raw_payload_difference_class_total": sum(raw_counts.values()),
        },
        "filters": {
            "parent_key": None if parent_key is None else str(parent_key),
            "parent_kind": parent_kind,
            "set_relation_class": set_relation_class,
            "raw_payload_difference_class": raw_payload_difference_class,
            "source_contribution_class": source_contribution_class,
            "zone_id": zone_id,
        },
        "filtered_parent_count": len(filtered),
        "returned_parent_count": len(returned),
        "parents_truncated": len(returned) < len(filtered),
        "parents": returned,
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
                f"P5-T08 requires [source_paths].{key} in {config_path}; "
                "run the handoff get_path.bat or pass the explicit root option"
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
        "--db", type=Path, default=project_root / "data" / "generated" / "octogamedb.sqlite3"
    )
    parser.add_argument("--config", type=Path, default=project_root / "config.local.toml")
    parser.add_argument("--pfquest-root", type=Path)
    parser.add_argument("--pfquest-turtle-root", type=Path)
    parser.add_argument("--pfquest-octo-root", type=Path)
    parser.add_argument("--parent-key")
    parser.add_argument("--parent-kind", choices=PARENT_KINDS)
    parser.add_argument("--set-relation-class", choices=SET_RELATION_CLASSES)
    parser.add_argument("--raw-payload-difference-class", choices=RAW_PAYLOAD_DIFFERENCE_CLASSES)
    parser.add_argument("--source-contribution-class", choices=SOURCE_CONTRIBUTION_CLASSES)
    parser.add_argument("--zone-id", type=int, choices=DEFAULT_ZONE_IDS)
    parser.add_argument("--limit", type=int, default=100)
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
        report = replacement_semantic_report(
            connection,
            pfquest_root=roots[0],
            pfquest_turtle_root=roots[1],
            pfquest_octo_root=roots[2],
            parent_key=args.parent_key,
            parent_kind=args.parent_kind,
            set_relation_class=args.set_relation_class,
            raw_payload_difference_class=args.raw_payload_difference_class,
            source_contribution_class=args.source_contribution_class,
            zone_id=args.zone_id,
            limit=args.limit,
        )
    finally:
        connection.close()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    print(f"Scope: {report['scope']}")
    print(f"Fixed replacement parents: {report['fixed_parent_count']}")
    print("A/C set relations:")
    for name, count in report["set_relation_counts"].items():
        print(f"  {name}: {count}")
    print("Raw payload semantic differences:")
    for name, count in report["raw_payload_difference_counts"].items():
        print(f"  {name}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
