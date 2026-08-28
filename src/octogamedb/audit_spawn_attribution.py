"""Read-only P5-T05 three-way base/active/comparison spawn attribution audit."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from typing import Any

from octogamedb.audit_comparison import (
    P1_WORLD_COMPARISON_SOURCE_KEY,
    _open_read_only_database,
    _resolve_source_revision,
    _source_groups,
    _unique_comparison_value,
)
from octogamedb.audit_spawn_divergence import (
    DIRECTIONS,
    PARENT_CLASSES,
    SPAWN_SUBJECT_KINDS,
    _coordinate_context_key,
    _distance,
    _distance_band,
    _parent_class,
    _spawn_members,
    spawn_divergence_report,
)

SPAWN_ATTRIBUTION_SCOPE = "p5-t05-three-way-base-active-octo-spawn-attribution"
BASE_SOURCE_KEY = "pfquest"
BASE_COMPLETE_VIEW_IMPORTER = "pfquest-overlay-reconcile/1-base-evidence"
EXPECTED_BASE_REVISION = (
    "sha256:5087d2d0a5b1c2706b7fc7ccb5ffd447c91aa24d91a23f102f2c7ac1d7440147"
)
EXPECTED_COMPARISON_REVISION = (
    "sha256:eddd325a9a0eab2616c7b70d03e23d55f1a0c4127a293426ea07a17c0f2421db"
)

PATTERNS = (
    "base_active_not_comparison",
    "active_only_vs_base",
    "base_comparison_not_active",
    "comparison_only_vs_base",
)
PATTERN_DESCRIPTIONS = {
    "base_active_not_comparison": "Comparison-side absence/change relative to base membership.",
    "active_only_vs_base": "Active-side addition relative to base membership.",
    "base_comparison_not_active": "Active-side absence/change relative to base membership.",
    "comparison_only_vs_base": "Comparison-side addition relative to base membership.",
}

PAIR_CLASSES = {
    "comparison_side_possible_replacement": (
        "base_active_not_comparison",
        "comparison_only_vs_base",
    ),
    "active_side_possible_replacement": (
        "active_only_vs_base",
        "base_comparison_not_active",
    ),
}
_DISTANCE_EPSILON = 1e-9


def _pattern(*, base_contains: bool, active_contains: bool, comparison_contains: bool) -> str:
    vector = (base_contains, active_contains, comparison_contains)
    mapping = {
        (True, True, False): "base_active_not_comparison",
        (False, True, False): "active_only_vs_base",
        (True, False, True): "base_comparison_not_active",
        (False, False, True): "comparison_only_vs_base",
    }
    try:
        return mapping[vector]
    except KeyError as exc:
        raise ValueError(
            "P5-T05 expects only one-sided active/comparison members; "
            f"unsupported B/A/C vector: {tuple(int(value) for value in vector)}"
        ) from exc


def _group_batches(
    group: dict[str, Any] | None,
    batch_map: dict[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    if group is None:
        return []
    batches: dict[tuple[int, str], dict[str, Any]] = {}
    for observation in group["comparison_observations"]:
        observation_id = int(observation["observation_id"])
        for batch in batch_map.get(observation_id, []):
            key = (int(batch["batch_id"]), str(batch["status"]))
            batches[key] = {"batch_id": key[0], "status": key[1]}
    return [batches[key] for key in sorted(batches)]


def _base_membership_contexts(
    connection: sqlite3.Connection,
    *,
    source_key: str,
    source_revision: str | None,
    parents: set[tuple[str, str]],
) -> tuple[str, list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    source_id, revision, source_batches = _resolve_source_revision(
        connection,
        source_key=source_key,
        source_revision=source_revision,
    )
    source_groups, batch_map = _source_groups(
        connection,
        source_id=source_id,
        revision=revision,
    )

    complete_view_batches = [
        row
        for row in source_batches
        if row["importer_version"] == BASE_COMPLETE_VIEW_IMPORTER
        and row["status"] == "succeeded"
    ]
    revision_batches = [
        {"batch_id": int(row["batch_id"]), "status": str(row["status"])}
        for row in complete_view_batches
    ]
    contexts: dict[tuple[str, str], dict[str, Any]] = {}
    invalid: list[str] = []
    for parent_kind, parent_key in sorted(parents):
        group = source_groups.get((parent_kind, parent_key, "spawn_set", ""))
        if group is not None:
            _value_json, value = _unique_comparison_value(group)
            members = _spawn_members(value)
            if members is None:
                invalid.append(f"{parent_kind}:{parent_key}")
                continue
            contexts[(parent_kind, parent_key)] = {
                "member_keys": set(members),
                "source_key": source_key,
                "source_revision": revision,
                "import_batches": _group_batches(group, batch_map),
                "membership_evidence": "spawn_set_observation",
            }
            continue

        presence_group = source_groups.get((parent_kind, parent_key, "world_presence", ""))
        _presence_json, presence = _unique_comparison_value(presence_group)
        if presence is True:
            invalid.append(f"{parent_kind}:{parent_key}")
            continue
        if presence not in (None, False) or not complete_view_batches:
            invalid.append(f"{parent_kind}:{parent_key}")
            continue

        # The P1-T04 base provenance batch represents the complete base world view. A parent
        # absent from that view has an empty base spawn set even though no per-parent spawn_set
        # observation can exist for an entity that the source does not contain.
        contexts[(parent_kind, parent_key)] = {
            "member_keys": set(),
            "source_key": source_key,
            "source_revision": revision,
            "import_batches": _group_batches(presence_group, batch_map) or revision_batches,
            "membership_evidence": "absent_from_complete_base_view",
        }

    if invalid:
        preview = ", ".join(invalid[:10])
        suffix = "" if len(invalid) <= 10 else f" (+{len(invalid) - 10} more)"
        raise ValueError(
            "P5-T05 could not reconstruct a unique persisted base spawn_set for: "
            + preview
            + suffix
        )
    return revision, source_batches, contexts


def _parent_classes(members: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    counts: Counter[tuple[str, str, str]] = Counter()
    for member in members:
        counts[
            (
                str(member["parent_subject_kind"]),
                str(member["parent_subject_key"]),
                str(member["direction"]),
            )
        ] += 1
    parents = {(key[0], key[1]) for key in counts}
    return {
        parent: _parent_class(
            counts[(parent[0], parent[1], "active_only")],
            counts[(parent[0], parent[1], "comparison_only")],
        )
        for parent in sorted(parents)
    }


def _attributed_members(
    members: list[dict[str, Any]],
    base_contexts: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    parent_classes = _parent_classes(members)
    attributed: list[dict[str, Any]] = []
    for source_member in members:
        member = dict(source_member)
        parent = (
            str(member["parent_subject_kind"]),
            str(member["parent_subject_key"]),
        )
        base = base_contexts[parent]
        active_contains = member["direction"] == "active_only"
        comparison_contains = member["direction"] == "comparison_only"
        base_contains = str(member["spawn_key"]) in base["member_keys"]
        pattern = _pattern(
            base_contains=base_contains,
            active_contains=active_contains,
            comparison_contains=comparison_contains,
        )
        member.update(
            {
                "base_contains": base_contains,
                "active_contains": active_contains,
                "comparison_contains": comparison_contains,
                "three_way_pattern": pattern,
                "parent_topology_class": parent_classes[parent],
                "base_source_key": base["source_key"],
                "base_source_revision": base["source_revision"],
                "base_import_batches": base["import_batches"],
                "base_membership_evidence": base["membership_evidence"],
                "active_selected_source_key": member.pop("active_membership_source_key"),
                "active_selected_source_revision": member.pop(
                    "active_membership_source_revision"
                ),
                "active_selected_selection_policy": member.pop(
                    "active_membership_selection_policy"
                ),
            }
        )
        attributed.append(member)
    attributed.sort(
        key=lambda item: (
            str(item["subject_kind"]),
            str(item["parent_subject_key"]),
            str(item["direction"]),
            str(item["spawn_key"]),
        )
    )
    return attributed


def _nearest_update(
    stats: dict[str, dict[str, Any]],
    *,
    spawn_key: str,
    partner_key: str,
    distance: float,
) -> None:
    row = stats.setdefault(
        spawn_key,
        {
            "compatible_candidate_count": 0,
            "nearest_distance": None,
            "nearest_partner_keys": [],
        },
    )
    row["compatible_candidate_count"] += 1
    minimum = row["nearest_distance"]
    if minimum is None or distance < float(minimum) - _DISTANCE_EPSILON:
        row["nearest_distance"] = distance
        row["nearest_partner_keys"] = [partner_key]
    elif abs(distance - float(minimum)) <= _DISTANCE_EPSILON:
        row["nearest_partner_keys"].append(partner_key)


def _source_local_replacement_analysis(members: list[dict[str, Any]]) -> dict[str, Any]:
    by_parent_context: dict[
        tuple[str, str],
        dict[tuple[str, int], list[dict[str, Any]]],
    ] = defaultdict(lambda: defaultdict(list))
    for member in members:
        context = _coordinate_context_key(member)
        if context is None:
            continue
        parent = (
            str(member["parent_subject_kind"]),
            str(member["parent_subject_key"]),
        )
        by_parent_context[parent][context].append(member)

    class_stats: dict[str, dict[str, Any]] = {}
    candidate_pairs: list[dict[str, Any]] = []
    for pair_class, (active_pattern, comparison_pattern) in PAIR_CLASSES.items():
        nearest: dict[str, dict[str, Any]] = {}
        pair_rows: list[dict[str, Any]] = []
        distance_bands: Counter[tuple[str, str]] = Counter()

        for parent in sorted(by_parent_context):
            for context in sorted(by_parent_context[parent]):
                rows = by_parent_context[parent][context]
                active_rows = sorted(
                    [
                        row
                        for row in rows
                        if row["direction"] == "active_only"
                        and row["three_way_pattern"] == active_pattern
                    ],
                    key=lambda row: str(row["spawn_key"]),
                )
                comparison_rows = sorted(
                    [
                        row
                        for row in rows
                        if row["direction"] == "comparison_only"
                        and row["three_way_pattern"] == comparison_pattern
                    ],
                    key=lambda row: str(row["spawn_key"]),
                )
                for active in active_rows:
                    for comparison in comparison_rows:
                        distance = _distance(active, comparison)
                        if distance is None:
                            continue
                        active_key = str(active["spawn_key"])
                        comparison_key = str(comparison["spawn_key"])
                        _nearest_update(
                            nearest,
                            spawn_key=active_key,
                            partner_key=comparison_key,
                            distance=distance,
                        )
                        _nearest_update(
                            nearest,
                            spawn_key=comparison_key,
                            partner_key=active_key,
                            distance=distance,
                        )
                        distance_bands[
                            (
                                str(active["coordinate_space"]),
                                _distance_band(str(active["coordinate_space"]), distance),
                            )
                        ] += 1
                        pair_rows.append(
                            {
                                "pair_class": pair_class,
                                "active_spawn_key": active_key,
                                "comparison_spawn_key": comparison_key,
                                "subject_kind": active["subject_kind"],
                                "parent_subject_kind": active["parent_subject_kind"],
                                "parent_subject_key": active["parent_subject_key"],
                                "coordinate_space": active["coordinate_space"],
                                "zone_id": active["zone_id"],
                                "map_id": active["map_id"],
                                "active_pattern": active_pattern,
                                "comparison_pattern": comparison_pattern,
                                "distance": distance,
                                "distance_band": _distance_band(
                                    str(active["coordinate_space"]), distance
                                ),
                            }
                        )

        nearest_pair_keys: set[tuple[str, str]] = set()
        mutual_pair_keys: set[tuple[str, str]] = set()
        for row in pair_rows:
            active_key = str(row["active_spawn_key"])
            comparison_key = str(row["comparison_spawn_key"])
            active_nearest = comparison_key in set(nearest[active_key]["nearest_partner_keys"])
            comparison_nearest = active_key in set(nearest[comparison_key]["nearest_partner_keys"])
            row["nearest_for_active"] = active_nearest
            row["nearest_for_comparison"] = comparison_nearest
            row["mutual_nearest"] = active_nearest and comparison_nearest
            if active_nearest or comparison_nearest:
                nearest_pair_keys.add((active_key, comparison_key))
            if row["mutual_nearest"]:
                mutual_pair_keys.add((active_key, comparison_key))

        nearest_distance_bands: Counter[tuple[str, str]] = Counter()
        mutual_distance_bands: Counter[tuple[str, str]] = Counter()
        for row in pair_rows:
            band_key = (str(row["coordinate_space"]), str(row["distance_band"]))
            if row["nearest_for_active"] or row["nearest_for_comparison"]:
                nearest_distance_bands[band_key] += 1
            if row["mutual_nearest"]:
                mutual_distance_bands[band_key] += 1

        candidate_keys = {
            str(row["spawn_key"])
            for row in members
            if row["three_way_pattern"] in {active_pattern, comparison_pattern}
        }
        cardinality = Counter()
        tie_cardinality = Counter()
        for key in sorted(candidate_keys):
            stats = nearest.get(key)
            count = 0 if stats is None else int(stats["compatible_candidate_count"])
            nearest_count = 0 if stats is None else len(set(stats["nearest_partner_keys"]))
            cardinality["zero" if count == 0 else "one" if count == 1 else "multiple"] += 1
            tie_cardinality[
                "zero"
                if nearest_count == 0
                else "one"
                if nearest_count == 1
                else "multiple"
            ] += 1

        pair_rows.sort(
            key=lambda row: (
                str(row["subject_kind"]),
                str(row["parent_subject_key"]),
                str(row["active_spawn_key"]),
                str(row["comparison_spawn_key"]),
            )
        )
        candidate_pairs.extend(pair_rows)
        class_stats[pair_class] = {
            "active_pattern": active_pattern,
            "comparison_pattern": comparison_pattern,
            "eligible_member_count": len(candidate_keys),
            "compatible_candidate_pair_count": len(pair_rows),
            "unique_nearest_candidate_pair_count": len(nearest_pair_keys),
            "mutual_nearest_candidate_pair_count": len(mutual_pair_keys),
            "member_candidate_cardinality": {
                label: cardinality[label] for label in ("zero", "one", "multiple")
            },
            "member_nearest_tie_cardinality": {
                label: tie_cardinality[label] for label in ("zero", "one", "multiple")
            },
            "compatible_pair_distance_bands": [
                {
                    "coordinate_space": key[0],
                    "distance_band": key[1],
                    "compatible_pair_count": distance_bands[key],
                }
                for key in sorted(distance_bands)
            ],
            "nearest_pair_distance_bands": [
                {
                    "coordinate_space": key[0],
                    "distance_band": key[1],
                    "nearest_pair_count": nearest_distance_bands[key],
                }
                for key in sorted(nearest_distance_bands)
            ],
            "mutual_nearest_pair_distance_bands": [
                {
                    "coordinate_space": key[0],
                    "distance_band": key[1],
                    "mutual_nearest_pair_count": mutual_distance_bands[key],
                }
                for key in sorted(mutual_distance_bands)
            ],
        }

    candidate_pairs.sort(
        key=lambda row: (
            str(row["pair_class"]),
            not bool(row["mutual_nearest"]),
            not bool(row["nearest_for_active"] or row["nearest_for_comparison"]),
            float(row["distance"]),
            str(row["subject_kind"]),
            str(row["parent_subject_key"]),
            str(row["active_spawn_key"]),
            str(row["comparison_spawn_key"]),
        )
    )
    return {
        "interpretation": (
            "Pairs are source-attributed coordinate-compatible possibilities, not proven moves or "
            "spawn-identity equivalences. Nearest ties are preserved."
        ),
        "pair_classes": [
            {"pair_class": pair_class, **class_stats[pair_class]}
            for pair_class in sorted(class_stats)
        ],
        "candidate_pairs": candidate_pairs,
    }


def _pattern_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(str(row["three_way_pattern"]) for row in rows)
    return {pattern: counter[pattern] for pattern in PATTERNS}


def _percentage(count: int, total: int) -> float:
    return 0.0 if total == 0 else round(count * 100.0 / total, 6)


def spawn_attribution_report(
    connection: sqlite3.Connection,
    *,
    base_source_key: str = BASE_SOURCE_KEY,
    base_source_revision: str | None = EXPECTED_BASE_REVISION,
    comparison_source_key: str = P1_WORLD_COMPARISON_SOURCE_KEY,
    comparison_source_revision: str | None = EXPECTED_COMPARISON_REVISION,
    subject_kind: str | None = None,
    parent_key: str | int | None = None,
    direction: str | None = None,
    zone_id: int | None = None,
    pattern: str | None = None,
    pair_class: str | None = None,
    limit: int = 100,
    top: int = 20,
) -> dict[str, Any]:
    """Attribute every P5-T04 one-sided spawn member across base/active/comparison views."""

    if base_source_key != BASE_SOURCE_KEY:
        raise ValueError("P5-T05 semantics are bounded to base source pfquest")
    if comparison_source_key != P1_WORLD_COMPARISON_SOURCE_KEY:
        raise ValueError("P5-T05 semantics are bounded to comparison source pfquest-octo")
    if subject_kind is not None and subject_kind not in SPAWN_SUBJECT_KINDS:
        raise ValueError(f"subject_kind must be one of {list(SPAWN_SUBJECT_KINDS)!r}")
    if direction is not None and direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {list(DIRECTIONS)!r}")
    if pattern is not None and pattern not in PATTERNS:
        raise ValueError(f"pattern must be one of {list(PATTERNS)!r}")
    if pair_class is not None and pair_class not in PAIR_CLASSES:
        raise ValueError(f"pair_class must be one of {list(PAIR_CLASSES)!r}")
    if limit < 0 or top < 0:
        raise ValueError("limit and top must be non-negative")

    divergence = spawn_divergence_report(
        connection,
        source_key=comparison_source_key,
        source_revision=comparison_source_revision,
        limit=1_000_000_000,
        top=0,
    )
    if divergence["members_truncated"]:
        raise RuntimeError("P5-T05 requires the complete P5-T04 one-sided membership population")

    source_members = list(divergence["members"])
    parents = {
        (str(member["parent_subject_kind"]), str(member["parent_subject_key"]))
        for member in source_members
    }
    base_revision, base_batches, base_contexts = _base_membership_contexts(
        connection,
        source_key=base_source_key,
        source_revision=base_source_revision,
        parents=parents,
    )
    members = _attributed_members(source_members, base_contexts)
    baseline_counts = _pattern_counts(members)
    one_sided_total = len(members)
    if sum(baseline_counts.values()) != one_sided_total:
        raise AssertionError("three-way patterns must partition every P5-T04 one-sided member")

    subject_key_filter = None if parent_key is None else str(parent_key)
    filtered = [
        member
        for member in members
        if (subject_kind is None or member["subject_kind"] == subject_kind)
        and (subject_key_filter is None or member["parent_subject_key"] == subject_key_filter)
        and (direction is None or member["direction"] == direction)
        and (zone_id is None or member["zone_id"] == zone_id)
        and (pattern is None or member["three_way_pattern"] == pattern)
    ]
    filtered_keys = {str(member["spawn_key"]) for member in filtered}
    filtered_counts = _pattern_counts(filtered)

    by_kind_pattern: Counter[tuple[str, str]] = Counter(
        (str(member["subject_kind"]), str(member["three_way_pattern"])) for member in members
    )
    by_direction_pattern: Counter[tuple[str, str]] = Counter(
        (str(member["direction"]), str(member["three_way_pattern"])) for member in members
    )

    parent_pattern_members: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    parent_topology: dict[tuple[str, str], str] = {}
    for member in members:
        parent = (str(member["subject_kind"]), str(member["parent_subject_key"]))
        parent_pattern_members[parent][str(member["three_way_pattern"])] += 1
        parent_topology[parent] = str(member["parent_topology_class"])
    parent_count_by_pattern = {
        pattern_name: sum(
            int(counter[pattern_name] > 0) for counter in parent_pattern_members.values()
        )
        for pattern_name in PATTERNS
    }
    parent_topology_pattern: Counter[tuple[str, str]] = Counter()
    for parent, counter in parent_pattern_members.items():
        for pattern_name in PATTERNS:
            if counter[pattern_name]:
                parent_topology_pattern[(parent_topology[parent], pattern_name)] += counter[
                    pattern_name
                ]

    parent_pattern_counts = [
        {
            "subject_kind": parent[0],
            "parent_subject_key": parent[1],
            "parent_topology_class": parent_topology[parent],
            "one_sided_member_count": sum(parent_pattern_members[parent].values()),
            "pattern_counts": {
                pattern_name: parent_pattern_members[parent][pattern_name]
                for pattern_name in PATTERNS
            },
        }
        for parent in sorted(parent_pattern_members)
    ]

    zone_pattern: Counter[
        tuple[str, str, str | None, int | None, str | None, int | None, str | None]
    ] = Counter()
    for member in members:
        zone_pattern[
            (
                str(member["subject_kind"]),
                str(member["three_way_pattern"]),
                member["coordinate_space"],
                member["zone_id"],
                member["zone_name"],
                member["map_id"],
                member["map_name"],
            )
        ] += 1

    active_contexts: dict[tuple[str, str, str | None], Counter[str]] = defaultdict(Counter)
    for member in members:
        key = (
            str(member["active_selected_source_key"]),
            str(member["active_selected_source_revision"]),
            member["active_selected_selection_policy"],
        )
        active_contexts[key][str(member["three_way_pattern"])] += 1

    base_evidence_counts = Counter(str(member["base_membership_evidence"]) for member in members)

    filtered_parent_counter: Counter[tuple[str, str]] = Counter(
        (str(member["subject_kind"]), str(member["parent_subject_key"])) for member in filtered
    )
    top_parents = []
    for parent, count in sorted(
        filtered_parent_counter.items(), key=lambda item: (-item[1], item[0][0], item[0][1])
    )[:top]:
        pattern_counter = Counter(
            str(member["three_way_pattern"])
            for member in filtered
            if member["subject_kind"] == parent[0]
            and member["parent_subject_key"] == parent[1]
        )
        top_parents.append(
            {
                "subject_kind": parent[0],
                "parent_subject_key": parent[1],
                "parent_topology_class": parent_topology[parent],
                "one_sided_member_count": count,
                "pattern_counts": {
                    pattern_name: pattern_counter[pattern_name] for pattern_name in PATTERNS
                },
            }
        )

    filtered_zone_counter: Counter[
        tuple[str, str | None, int | None, str | None, int | None, str | None]
    ] = Counter()
    for member in filtered:
        filtered_zone_counter[
            (
                str(member["subject_kind"]),
                member["coordinate_space"],
                member["zone_id"],
                member["zone_name"],
                member["map_id"],
                member["map_name"],
            )
        ] += 1
    top_zones = []
    for key, count in sorted(
        filtered_zone_counter.items(),
        key=lambda item: (
            -item[1],
            item[0][0],
            "" if item[0][1] is None else str(item[0][1]),
            -1 if item[0][2] is None else int(item[0][2]),
            -1 if item[0][4] is None else int(item[0][4]),
        ),
    )[:top]:
        pattern_counter = Counter(
            str(member["three_way_pattern"])
            for member in filtered
            if member["subject_kind"] == key[0]
            and member["coordinate_space"] == key[1]
            and member["zone_id"] == key[2]
            and member["map_id"] == key[4]
        )
        top_zones.append(
            {
                "subject_kind": key[0],
                "coordinate_space": key[1],
                "zone_id": key[2],
                "zone_name": key[3],
                "map_id": key[4],
                "map_name": key[5],
                "one_sided_member_count": count,
                "pattern_counts": {
                    pattern_name: pattern_counter[pattern_name] for pattern_name in PATTERNS
                },
            }
        )

    replacement = _source_local_replacement_analysis(members)
    candidate_pairs = [
        row
        for row in replacement["candidate_pairs"]
        if (
            row["active_spawn_key"] in filtered_keys
            or row["comparison_spawn_key"] in filtered_keys
        )
        and (pair_class is None or row["pair_class"] == pair_class)
    ]
    details = filtered[:limit] if limit else []
    pair_details = candidate_pairs[:limit] if limit else []

    return {
        "scope": SPAWN_ATTRIBUTION_SCOPE,
        "filters": {
            "subject_kind": subject_kind,
            "parent_key": subject_key_filter,
            "direction": direction,
            "zone_id": zone_id,
            "pattern": pattern,
            "pair_class": pair_class,
        },
        "base_source": {
            "source_key": base_source_key,
            "source_revision": base_revision,
            "import_batches": base_batches,
        },
        "comparison_source": divergence["comparison_source"],
        "p5_t04_membership_baseline": divergence["membership_baseline"],
        "patterns": [
            {
                "pattern": pattern_name,
                "description": PATTERN_DESCRIPTIONS[pattern_name],
                "member_count": baseline_counts[pattern_name],
                "percentage_of_one_sided": _percentage(
                    baseline_counts[pattern_name], one_sided_total
                ),
                "parent_count": parent_count_by_pattern[pattern_name],
            }
            for pattern_name in PATTERNS
        ],
        "one_sided_member_count": one_sided_total,
        "active_only_member_count": sum(
            1 for member in members if member["direction"] == "active_only"
        ),
        "comparison_only_member_count": sum(
            1 for member in members if member["direction"] == "comparison_only"
        ),
        "by_subject_kind_pattern": [
            {
                "subject_kind": kind,
                "pattern": pattern_name,
                "member_count": by_kind_pattern[(kind, pattern_name)],
            }
            for kind in SPAWN_SUBJECT_KINDS
            for pattern_name in PATTERNS
        ],
        "by_direction_pattern": [
            {
                "direction": direction_name,
                "pattern": pattern_name,
                "member_count": by_direction_pattern[(direction_name, pattern_name)],
            }
            for direction_name in DIRECTIONS
            for pattern_name in PATTERNS
        ],
        "parent_topology_pattern_counts": [
            {
                "parent_topology_class": parent_class,
                "pattern": pattern_name,
                "member_count": parent_topology_pattern[(parent_class, pattern_name)],
            }
            for parent_class in PARENT_CLASSES
            for pattern_name in PATTERNS
        ],
        "parent_pattern_counts": parent_pattern_counts,
        "base_membership_evidence_counts": {
            label: base_evidence_counts[label]
            for label in ("spawn_set_observation", "absent_from_complete_base_view")
        },
        "zone_map_pattern_counts": [
            {
                "subject_kind": key[0],
                "pattern": key[1],
                "coordinate_space": key[2],
                "zone_id": key[3],
                "zone_name": key[4],
                "map_id": key[5],
                "map_name": key[6],
                "member_count": zone_pattern[key],
            }
            for key in sorted(
                zone_pattern,
                key=lambda item: (
                    item[0],
                    item[1],
                    "" if item[2] is None else str(item[2]),
                    -1 if item[3] is None else int(item[3]),
                    -1 if item[5] is None else int(item[5]),
                ),
            )
        ],
        "active_selected_contexts": [
            {
                "source_key": key[0],
                "source_revision": key[1],
                "selection_policy": key[2],
                "member_count": sum(active_contexts[key].values()),
                "pattern_counts": {
                    pattern_name: active_contexts[key][pattern_name]
                    for pattern_name in PATTERNS
                },
            }
            for key in sorted(
                active_contexts,
                key=lambda item: (item[0], item[1], "" if item[2] is None else str(item[2])),
            )
        ],
        "source_local_replacement_analysis": {
            "interpretation": replacement["interpretation"],
            "pair_classes": replacement["pair_classes"],
        },
        "filtered_one_sided_member_count": len(filtered),
        "filtered_pattern_counts": filtered_counts,
        "top_parent_concentrations": top_parents,
        "top_zone_map_concentrations": top_zones,
        "detail_limit": limit,
        "top_limit": top,
        "returned_member_count": len(details),
        "returned_candidate_pair_count": len(pair_details),
        "members_truncated": len(details) < len(filtered),
        "candidate_pairs_truncated": len(pair_details) < len(candidate_pairs),
        "members": details,
        "candidate_pairs": pair_details,
    }


def _nonnegative_int(value: str) -> int:
    import argparse

    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def _print_human(payload: dict[str, Any]) -> None:
    print(f"Spawn attribution scope: {payload['scope']}")
    base = payload["base_source"]
    comparison = payload["comparison_source"]
    print(f"Base source: {base['source_key']}@{base['source_revision']}")
    print(
        f"Comparison source: {comparison['source_key']}@{comparison['source_revision']}"
    )
    print(f"One-sided members: {payload['one_sided_member_count']}")
    print("Three-way patterns:")
    for row in payload["patterns"]:
        print(
            f"- {row['pattern']}: {row['member_count']} "
            f"({row['percentage_of_one_sided']:.2f}%), parents={row['parent_count']}"
        )
    print(f"Filtered one-sided members: {payload['filtered_one_sided_member_count']}")
    for member in payload["members"]:
        print(
            f"- {member['subject_kind']} parent={member['parent_subject_key']} "
            f"{member['three_way_pattern']} {member['spawn_key']}"
        )


def main(argv: list[str] | None = None) -> int:
    """Run the P5-T05 read-only three-way spawn attribution audit."""

    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        prog="python -m octogamedb.audit_spawn_attribution",
        description=(
            "Attribute P5-T04 one-sided spawn memberships across pfquest base, the active selected "
            "effective view, and pfquest-octo comparison evidence without changing canonical data."
        ),
    )
    parser.add_argument("--base-source", default=BASE_SOURCE_KEY)
    parser.add_argument("--base-source-revision", default=EXPECTED_BASE_REVISION)
    parser.add_argument("--comparison-source", default=P1_WORLD_COMPARISON_SOURCE_KEY)
    parser.add_argument("--comparison-source-revision", default=EXPECTED_COMPARISON_REVISION)
    parser.add_argument("--subject-kind", choices=SPAWN_SUBJECT_KINDS)
    parser.add_argument("--parent-key")
    parser.add_argument("--direction", choices=DIRECTIONS)
    parser.add_argument("--zone-id", type=int)
    parser.add_argument("--pattern", choices=PATTERNS)
    parser.add_argument("--pair-class", choices=tuple(PAIR_CLASSES))
    parser.add_argument("--limit", type=_nonnegative_int, default=100)
    parser.add_argument("--top", type=_nonnegative_int, default=20)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/generated/octogamedb.sqlite3"),
        help="SQLite database path (opened mode=ro).",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    connection = _open_read_only_database(str(args.db))
    try:
        payload = spawn_attribution_report(
            connection,
            base_source_key=args.base_source,
            base_source_revision=args.base_source_revision,
            comparison_source_key=args.comparison_source,
            comparison_source_revision=args.comparison_source_revision,
            subject_kind=args.subject_kind,
            parent_key=args.parent_key,
            direction=args.direction,
            zone_id=args.zone_id,
            pattern=args.pattern,
            pair_class=args.pair_class,
            limit=args.limit,
            top=args.top,
        )
    finally:
        connection.close()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_human(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
