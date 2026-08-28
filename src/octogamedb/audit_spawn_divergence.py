"""Read-only P5-T04 characterization of pfquest-octo spawn membership divergence."""

from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter, defaultdict
from typing import Any

from octogamedb.audit_comparison import (
    P1_WORLD_COMPARISON_SOURCE_KEY,
    _membership_contexts,
    _open_read_only_database,
    _resolve_source_revision,
    _selected_groups_for_subjects,
    _source_groups,
    _unique_comparison_value,
)

SPAWN_DIVERGENCE_SCOPE = "p5-t04-pfquest-octo-spawn-membership-divergence"
SPAWN_SUBJECT_KINDS = ("creature_spawn", "gameobject_spawn")
PARENT_KINDS = ("creature", "gameobject")
DIRECTIONS = ("active_only", "comparison_only")
PARENT_CLASSES = (
    "shared_only",
    "active_only_members",
    "comparison_only_members",
    "mixed_one_sided_members",
)

_DISTANCE_BANDS: dict[str, tuple[tuple[str, float], ...]] = {
    "zone_percent": (
        ("(0,0.1]", 0.1),
        ("(0.1,0.5]", 0.5),
        ("(0.5,1]", 1.0),
        ("(1,2]", 2.0),
        ("(2,5]", 5.0),
        (">5", math.inf),
    ),
    "world": (
        ("(0,1]", 1.0),
        ("(1,5]", 5.0),
        ("(5,20]", 20.0),
        ("(20,50]", 50.0),
        ("(50,100]", 100.0),
        (">100", math.inf),
    ),
}
_DISTANCE_EPSILON = 1e-9


def _spawn_members(value: Any) -> dict[str, dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    members: dict[str, dict[str, Any]] = {}
    for raw in value:
        if not isinstance(raw, dict):
            return None
        spawn_key = raw.get("spawn_key")
        if not isinstance(spawn_key, str) or not spawn_key:
            return None
        # P5-T03 defines spawn-set membership by unique spawn_key values.
        # Real pfQuest-family complete sets may repeat an identical coordinate row,
        # so duplicate keys must collapse to one membership instead of invalidating
        # the whole parent. The first payload is deterministic because spawn_set
        # observations are persisted in deterministic order.
        members.setdefault(spawn_key, dict(raw))
    return members


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == value or str(value).strip() == str(parsed) else None


def _float_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _geography_lookup(
    connection: sqlite3.Connection,
    zone_ids: set[int],
    map_ids: set[int],
) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    zones: dict[int, dict[str, Any]] = {}
    if zone_ids:
        ordered = sorted(zone_ids)
        placeholders = ",".join("?" for _ in ordered)
        rows = connection.execute(
            f"SELECT zone_id, map_id, name FROM zones WHERE zone_id IN ({placeholders})",
            tuple(ordered),
        ).fetchall()
        zones = {
            int(row["zone_id"]): {
                "zone_id": int(row["zone_id"]),
                "zone_name": str(row["name"]),
                "map_id": None if row["map_id"] is None else int(row["map_id"]),
            }
            for row in rows
        }
        map_ids.update(
            int(item["map_id"])
            for item in zones.values()
            if item["map_id"] is not None
        )

    maps: dict[int, dict[str, Any]] = {}
    if map_ids:
        ordered = sorted(map_ids)
        placeholders = ",".join("?" for _ in ordered)
        rows = connection.execute(
            f"SELECT map_id, name FROM maps WHERE map_id IN ({placeholders})",
            tuple(ordered),
        ).fetchall()
        maps = {
            int(row["map_id"]): {
                "map_id": int(row["map_id"]),
                "map_name": str(row["name"]),
            }
            for row in rows
        }
    return zones, maps


def _normalized_member(
    *,
    subject_kind: str,
    parent_kind: str,
    parent_key: str,
    direction: str,
    raw: dict[str, Any],
    active_group: dict[str, Any] | None,
    active_position_group: dict[str, Any] | None,
    comparison_source_revision: str,
    comparison_batches: list[dict[str, Any]],
    zones: dict[int, dict[str, Any]],
    maps: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    zone_id = _int_or_none(raw.get("zone_id"))
    map_id = _int_or_none(raw.get("map_id"))
    zone = None if zone_id is None else zones.get(zone_id)
    if map_id is None and zone is not None:
        map_id = zone["map_id"]
    map_row = None if map_id is None else maps.get(map_id)
    return {
        "subject_kind": subject_kind,
        "parent_subject_kind": parent_kind,
        "parent_subject_key": parent_key,
        "spawn_key": str(raw["spawn_key"]),
        "direction": direction,
        "coordinate_space": raw.get("coordinate_space"),
        "zone_id": zone_id,
        "zone_name": None if zone is None else zone["zone_name"],
        "map_id": map_id,
        "map_name": None if map_row is None else map_row["map_name"],
        "x": _float_or_none(raw.get("x")),
        "y": _float_or_none(raw.get("y")),
        "z": _float_or_none(raw.get("z")),
        "active_membership_source_key": None
        if active_group is None
        else active_group["source_key"],
        "active_membership_source_revision": None
        if active_group is None
        else active_group["source_revision"],
        "active_membership_selection_policy": None
        if active_group is None
        else active_group["selection_policy"],
        "active_position_source_key": None
        if active_position_group is None
        else active_position_group["source_key"],
        "active_position_source_revision": None
        if active_position_group is None
        else active_position_group["source_revision"],
        "active_position_selection_policy": None
        if active_position_group is None
        else active_position_group["selection_policy"],
        "comparison_source_key": P1_WORLD_COMPARISON_SOURCE_KEY,
        "comparison_source_revision": comparison_source_revision,
        "comparison_import_batches": comparison_batches,
    }


def _compatible_context(left: dict[str, Any], right: dict[str, Any]) -> bool:
    space = left.get("coordinate_space")
    if space != right.get("coordinate_space") or space not in _DISTANCE_BANDS:
        return False
    if space == "zone_percent":
        return left.get("zone_id") is not None and left.get("zone_id") == right.get("zone_id")
    if space == "world":
        return left.get("map_id") is not None and left.get("map_id") == right.get("map_id")
    return False


def _coordinate_context_key(member: dict[str, Any]) -> tuple[str, int] | None:
    space = member.get("coordinate_space")
    if space == "zone_percent" and member.get("zone_id") is not None:
        return ("zone_percent", int(member["zone_id"]))
    if space == "world" and member.get("map_id") is not None:
        return ("world", int(member["map_id"]))
    return None


def _distance(left: dict[str, Any], right: dict[str, Any]) -> float | None:
    if not _compatible_context(left, right):
        return None
    lx = left.get("x")
    ly = left.get("y")
    rx = right.get("x")
    ry = right.get("y")
    if None in {lx, ly, rx, ry}:
        return None
    components = [(float(lx) - float(rx)) ** 2, (float(ly) - float(ry)) ** 2]
    if left.get("coordinate_space") == "world":
        lz = left.get("z")
        rz = right.get("z")
        if lz is not None and rz is not None:
            components.append((float(lz) - float(rz)) ** 2)
    return math.sqrt(sum(components))


def _distance_band(coordinate_space: str, distance: float) -> str:
    if distance <= _DISTANCE_EPSILON:
        return "0"
    bands = _DISTANCE_BANDS[coordinate_space]
    for label, upper_bound in bands:
        if distance <= upper_bound + _DISTANCE_EPSILON:
            return label
    raise AssertionError("distance bands must end at infinity")


def _candidate_analysis(
    members: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    by_parent: dict[
        tuple[str, str],
        dict[str, dict[tuple[str, int], list[dict[str, Any]]]],
    ] = defaultdict(
        lambda: {"active_only": defaultdict(list), "comparison_only": defaultdict(list)}
    )
    member_by_key = {str(member["spawn_key"]): member for member in members}
    member_stats: dict[str, dict[str, Any]] = {
        spawn_key: {
            "compatible_candidate_count": 0,
            "nearest_distance": None,
            "nearest_partner_keys": [],
        }
        for spawn_key in member_by_key
    }

    for member in members:
        context_key = _coordinate_context_key(member)
        if context_key is None:
            continue
        parent = (str(member["parent_subject_kind"]), str(member["parent_subject_key"]))
        by_parent[parent][str(member["direction"])][context_key].append(member)

    def update_member(spawn_key: str, partner_key: str, distance: float) -> None:
        stats = member_stats[spawn_key]
        stats["compatible_candidate_count"] += 1
        minimum = stats["nearest_distance"]
        if minimum is None or distance < float(minimum) - _DISTANCE_EPSILON:
            stats["nearest_distance"] = distance
            stats["nearest_partner_keys"] = [partner_key]
        elif math.isclose(
            distance,
            float(minimum),
            rel_tol=0.0,
            abs_tol=_DISTANCE_EPSILON,
        ):
            stats["nearest_partner_keys"].append(partner_key)

    for parent in sorted(by_parent):
        shared_contexts = sorted(
            set(by_parent[parent]["active_only"])
            & set(by_parent[parent]["comparison_only"])
        )
        for context_key in shared_contexts:
            active_members = sorted(
                by_parent[parent]["active_only"][context_key],
                key=lambda item: item["spawn_key"],
            )
            comparison_members = sorted(
                by_parent[parent]["comparison_only"][context_key],
                key=lambda item: item["spawn_key"],
            )
            for active in active_members:
                active_key = str(active["spawn_key"])
                for comparison in comparison_members:
                    distance = _distance(active, comparison)
                    if distance is None:
                        continue
                    comparison_key = str(comparison["spawn_key"])
                    update_member(active_key, comparison_key, distance)
                    update_member(comparison_key, active_key, distance)

    pair_registry: dict[tuple[str, str], dict[str, Any]] = {}
    for spawn_key in sorted(member_stats):
        member = member_by_key[spawn_key]
        for partner_key in sorted(set(member_stats[spawn_key]["nearest_partner_keys"])):
            if member["direction"] == "active_only":
                active_key, comparison_key = spawn_key, partner_key
                nearest_flag = "nearest_for_active"
            else:
                active_key, comparison_key = partner_key, spawn_key
                nearest_flag = "nearest_for_comparison"
            pair_key = (active_key, comparison_key)
            active = member_by_key[active_key]
            comparison = member_by_key[comparison_key]
            distance = _distance(active, comparison)
            if distance is None:
                raise AssertionError("persisted nearest pair must remain coordinate-compatible")
            row = pair_registry.setdefault(
                pair_key,
                {
                    "active_spawn_key": active_key,
                    "comparison_spawn_key": comparison_key,
                    "subject_kind": active["subject_kind"],
                    "parent_subject_kind": active["parent_subject_kind"],
                    "parent_subject_key": active["parent_subject_key"],
                    "coordinate_space": active["coordinate_space"],
                    "zone_id": active["zone_id"],
                    "map_id": active["map_id"],
                    "distance": distance,
                    "distance_band": _distance_band(
                        str(active["coordinate_space"]), distance
                    ),
                    "nearest_for_active": False,
                    "nearest_for_comparison": False,
                },
            )
            row[nearest_flag] = True

    nearest_rows = [pair_registry[key] for key in sorted(pair_registry)]
    return member_stats, nearest_rows


def _compatible_pair_aggregate(
    members: list[dict[str, Any]],
    filtered_keys: set[str],
) -> tuple[int, Counter[tuple[str, str]]]:
    by_parent: dict[
        tuple[str, str],
        dict[str, dict[tuple[str, int], list[dict[str, Any]]]],
    ] = defaultdict(
        lambda: {"active_only": defaultdict(list), "comparison_only": defaultdict(list)}
    )
    for member in members:
        context_key = _coordinate_context_key(member)
        if context_key is None:
            continue
        parent = (str(member["parent_subject_kind"]), str(member["parent_subject_key"]))
        by_parent[parent][str(member["direction"])][context_key].append(member)

    pair_count = 0
    distance_bands: Counter[tuple[str, str]] = Counter()
    for parent in sorted(by_parent):
        shared_contexts = sorted(
            set(by_parent[parent]["active_only"])
            & set(by_parent[parent]["comparison_only"])
        )
        for context_key in shared_contexts:
            active_members = sorted(
                by_parent[parent]["active_only"][context_key],
                key=lambda item: item["spawn_key"],
            )
            comparison_members = sorted(
                by_parent[parent]["comparison_only"][context_key],
                key=lambda item: item["spawn_key"],
            )
            for active in active_members:
                active_key = str(active["spawn_key"])
                for comparison in comparison_members:
                    comparison_key = str(comparison["spawn_key"])
                    if active_key not in filtered_keys and comparison_key not in filtered_keys:
                        continue
                    distance = _distance(active, comparison)
                    if distance is None:
                        continue
                    pair_count += 1
                    distance_bands[
                        (
                            str(active["coordinate_space"]),
                            _distance_band(str(active["coordinate_space"]), distance),
                        )
                    ] += 1
    return pair_count, distance_bands

def _parent_class(active_only_count: int, comparison_only_count: int) -> str:
    if active_only_count and comparison_only_count:
        return "mixed_one_sided_members"
    if active_only_count:
        return "active_only_members"
    if comparison_only_count:
        return "comparison_only_members"
    return "shared_only"


def spawn_divergence_report(
    connection: sqlite3.Connection,
    *,
    source_key: str = P1_WORLD_COMPARISON_SOURCE_KEY,
    source_revision: str | None = None,
    subject_kind: str | None = None,
    parent_key: str | int | None = None,
    direction: str | None = None,
    zone_id: int | None = None,
    candidate_cardinality: str | None = None,
    limit: int = 100,
    top: int = 20,
) -> dict[str, Any]:
    """Characterize unique spawn-set membership differences without mutating SQLite.

    Relocation evidence uses threshold-free compatible nearest neighbours. Equal-distance nearest
    neighbours are all retained, so ambiguous topology stays explicit instead of being greedily
    paired. Distance bands are descriptive only and never establish spawn identity equivalence.
    """

    if source_key != P1_WORLD_COMPARISON_SOURCE_KEY:
        raise ValueError("P5-T04 semantics are bounded to comparison source pfquest-octo")
    if subject_kind is not None and subject_kind not in SPAWN_SUBJECT_KINDS:
        raise ValueError(f"subject_kind must be one of {list(SPAWN_SUBJECT_KINDS)!r}")
    if direction is not None and direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {list(DIRECTIONS)!r}")
    if candidate_cardinality not in {None, "zero", "one", "multiple"}:
        raise ValueError("candidate_cardinality must be zero, one, or multiple")
    if limit < 0 or top < 0:
        raise ValueError("limit and top must be non-negative")

    source_id, revision, source_batches = _resolve_source_revision(
        connection,
        source_key=source_key,
        source_revision=source_revision,
    )
    source_groups, source_batch_map = _source_groups(
        connection,
        source_id=source_id,
        revision=revision,
    )

    parent_keys: dict[str, set[str]] = {kind: set() for kind in PARENT_KINDS}
    for key in source_groups:
        if key[0] in PARENT_KINDS and key[2] == "spawn_set":
            parent_keys[key[0]].add(key[1])

    selected_groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for kind in PARENT_KINDS:
        selected_groups.update(
            _selected_groups_for_subjects(
                connection,
                subject_kind=kind,
                subject_keys=parent_keys[kind],
            )
        )
    contexts = _membership_contexts(source_groups, selected_groups)

    active_only_spawn_keys: dict[str, set[str]] = {kind: set() for kind in SPAWN_SUBJECT_KINDS}
    for (template_kind, _template_key), context in contexts.items():
        if not context["directly_comparable"]:
            continue
        spawn_kind = f"{template_kind}_spawn"
        active_only_spawn_keys[spawn_kind].update(
            context["active_keys"] - context["comparison_keys"]
        )
    selected_spawn_groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for spawn_kind in SPAWN_SUBJECT_KINDS:
        selected_spawn_groups.update(
            _selected_groups_for_subjects(
                connection,
                subject_kind=spawn_kind,
                subject_keys=active_only_spawn_keys[spawn_kind],
            )
        )

    raw_parents: list[dict[str, Any]] = []
    raw_members: list[dict[str, Any]] = []
    zone_ids: set[int] = set()
    map_ids: set[int] = set()

    for (template_kind, template_key), context in sorted(contexts.items()):
        if not context["directly_comparable"]:
            continue
        group_key = (template_kind, template_key, "spawn_set", "")
        source_group = source_groups.get(group_key)
        _value_json, comparison_value = _unique_comparison_value(source_group)
        comparison_members = _spawn_members(comparison_value)
        active_group = context["active_group"]
        active_members = None if active_group is None else _spawn_members(active_group["value"])
        if comparison_members is None or active_members is None:
            continue

        comparison_batches: list[dict[str, Any]] = []
        if source_group is not None:
            seen_batches: set[tuple[int, str]] = set()
            for observation in source_group["comparison_observations"]:
                for batch in source_batch_map.get(int(observation["observation_id"]), []):
                    key = (int(batch["batch_id"]), str(batch["status"]))
                    if key not in seen_batches:
                        seen_batches.add(key)
                        comparison_batches.append(
                            {"batch_id": key[0], "status": key[1]}
                        )
        comparison_batches.sort(key=lambda item: (item["batch_id"], item["status"]))

        active_keys = set(active_members)
        comparison_keys = set(comparison_members)
        active_only = sorted(active_keys - comparison_keys)
        comparison_only = sorted(comparison_keys - active_keys)
        shared = sorted(active_keys & comparison_keys)
        spawn_kind = f"{template_kind}_spawn"
        raw_parents.append(
            {
                "subject_kind": spawn_kind,
                "parent_subject_kind": template_kind,
                "parent_subject_key": template_key,
                "parent_class": _parent_class(len(active_only), len(comparison_only)),
                "shared_member_count": len(shared),
                "active_only_member_count": len(active_only),
                "comparison_only_member_count": len(comparison_only),
                "one_sided_member_count": len(active_only) + len(comparison_only),
                "active_source_key": active_group["source_key"],
                "active_source_revision": active_group["source_revision"],
                "selection_policy": active_group["selection_policy"],
            }
        )
        for member_direction, keys, members in (
            ("active_only", active_only, active_members),
            ("comparison_only", comparison_only, comparison_members),
        ):
            for spawn_key in keys:
                raw = members[spawn_key]
                raw_members.append(
                    {
                        "subject_kind": spawn_kind,
                        "parent_subject_kind": template_kind,
                        "parent_subject_key": template_key,
                        "direction": member_direction,
                        "raw": raw,
                        "active_group": active_group,
                        "active_position_group": selected_spawn_groups.get(
                            (spawn_kind, spawn_key, "position", "")
                        )
                        if member_direction == "active_only"
                        else None,
                        "comparison_batches": comparison_batches,
                    }
                )
                raw_zone_id = _int_or_none(raw.get("zone_id"))
                raw_map_id = _int_or_none(raw.get("map_id"))
                if raw_zone_id is not None:
                    zone_ids.add(raw_zone_id)
                if raw_map_id is not None:
                    map_ids.add(raw_map_id)

    zones, maps = _geography_lookup(connection, zone_ids, map_ids)
    members = [
        _normalized_member(
            subject_kind=str(item["subject_kind"]),
            parent_kind=str(item["parent_subject_kind"]),
            parent_key=str(item["parent_subject_key"]),
            direction=str(item["direction"]),
            raw=item["raw"],
            active_group=item["active_group"],
            active_position_group=item["active_position_group"],
            comparison_source_revision=revision,
            comparison_batches=item["comparison_batches"],
            zones=zones,
            maps=maps,
        )
        for item in raw_members
    ]
    members.sort(
        key=lambda item: (
            item["subject_kind"],
            item["parent_subject_key"],
            item["direction"],
            item["spawn_key"],
        )
    )

    member_candidate_stats, nearest_pairs = _candidate_analysis(members)
    for member in members:
        stats = member_candidate_stats[str(member["spawn_key"])]
        nearest_distance = stats["nearest_distance"]
        member["compatible_candidate_count"] = stats["compatible_candidate_count"]
        member["nearest_candidate_count"] = len(stats["nearest_partner_keys"])
        member["nearest_candidate_distance"] = nearest_distance
        member["nearest_candidate_distance_band"] = (
            None
            if nearest_distance is None
            else _distance_band(str(member["coordinate_space"]), float(nearest_distance))
        )

    parent_rows = sorted(
        raw_parents,
        key=lambda item: (item["subject_kind"], item["parent_subject_key"]),
    )

    baseline_by_kind: list[dict[str, Any]] = []
    for spawn_kind in SPAWN_SUBJECT_KINDS:
        parents = [item for item in parent_rows if item["subject_kind"] == spawn_kind]
        baseline_by_kind.append(
            {
                "subject_kind": spawn_kind,
                "parent_count": len(parents),
                "shared_member_count": sum(int(item["shared_member_count"]) for item in parents),
                "active_only_member_count": sum(
                    int(item["active_only_member_count"]) for item in parents
                ),
                "comparison_only_member_count": sum(
                    int(item["comparison_only_member_count"]) for item in parents
                ),
            }
        )

    def cardinality_label(member: dict[str, Any]) -> str:
        count = int(member["compatible_candidate_count"])
        return "zero" if count == 0 else "one" if count == 1 else "multiple"

    filtered = [
        member
        for member in members
        if (subject_kind is None or member["subject_kind"] == subject_kind)
        and (parent_key is None or member["parent_subject_key"] == str(parent_key))
        and (direction is None or member["direction"] == direction)
        and (zone_id is None or member["zone_id"] == zone_id)
        and (candidate_cardinality is None or cardinality_label(member) == candidate_cardinality)
    ]
    filtered_keys = {str(item["spawn_key"]) for item in filtered}
    compatible_pair_count, distance_bands = _compatible_pair_aggregate(members, filtered_keys)
    filtered_nearest_pairs = [
        pair
        for pair in nearest_pairs
        if pair["active_spawn_key"] in filtered_keys
        or pair["comparison_spawn_key"] in filtered_keys
    ]

    kind_direction_counter: Counter[tuple[str, str]] = Counter(
        (str(item["subject_kind"]), str(item["direction"])) for item in filtered
    )
    parent_class_counts = Counter(str(item["parent_class"]) for item in parent_rows)
    parent_class_by_kind = Counter(
        (str(item["subject_kind"]), str(item["parent_class"])) for item in parent_rows
    )
    one_sided_distribution = Counter(int(item["one_sided_member_count"]) for item in parent_rows)
    cardinality_counter = Counter(
        (
            0
            if item["compatible_candidate_count"] == 0
            else 1
            if item["compatible_candidate_count"] == 1
            else 2
        )
        for item in filtered
    )
    nearest_tie_counter = Counter(
        (
            0
            if item["nearest_candidate_count"] == 0
            else 1
            if item["nearest_candidate_count"] == 1
            else 2
        )
        for item in filtered
    )
    membership_contexts: dict[tuple[str, str, str | None], Counter[str]] = defaultdict(Counter)
    position_contexts: Counter[tuple[str | None, str | None, str | None]] = Counter()
    for member in filtered:
        membership_key = (
            str(member["active_membership_source_key"]),
            str(member["active_membership_source_revision"]),
            member["active_membership_selection_policy"],
        )
        membership_contexts[membership_key][str(member["direction"])] += 1
        if member["direction"] == "active_only":
            position_contexts[
                (
                    member["active_position_source_key"],
                    member["active_position_source_revision"],
                    member["active_position_selection_policy"],
                )
            ] += 1

    zone_counter: Counter[tuple[str, str, str | None, int | None, int | None]] = Counter()
    for member in filtered:
        zone_counter[
            (
                str(member["subject_kind"]),
                str(member["direction"]),
                member["coordinate_space"],
                member["zone_id"],
                member["map_id"],
            )
        ] += 1

    parent_filtered_counter: Counter[tuple[str, str]] = Counter(
        (str(item["subject_kind"]), str(item["parent_subject_key"])) for item in filtered
    )

    top_parents = []
    for key, count in sorted(
        parent_filtered_counter.items(), key=lambda item: (-item[1], item[0][0], item[0][1])
    )[:top]:
        parent = next(
            row
            for row in parent_rows
            if row["subject_kind"] == key[0] and row["parent_subject_key"] == key[1]
        )
        top_parents.append({**parent, "filtered_one_sided_member_count": count})

    top_zones = []
    for key, count in sorted(
        zone_counter.items(),
        key=lambda item: (
            -item[1],
            item[0][0],
            item[0][1],
            "" if item[0][2] is None else str(item[0][2]),
            -1 if item[0][3] is None else int(item[0][3]),
            -1 if item[0][4] is None else int(item[0][4]),
        ),
    )[:top]:
        zone = None if key[3] is None else zones.get(int(key[3]))
        map_row = None if key[4] is None else maps.get(int(key[4]))
        top_zones.append(
            {
                "subject_kind": key[0],
                "direction": key[1],
                "coordinate_space": key[2],
                "zone_id": key[3],
                "zone_name": None if zone is None else zone["zone_name"],
                "map_id": key[4],
                "map_name": None if map_row is None else map_row["map_name"],
                "one_sided_member_count": count,
            }
        )

    no_compatible = [item for item in filtered if item["compatible_candidate_count"] == 0]
    details = filtered[:limit] if limit else []
    candidate_details = filtered_nearest_pairs[:limit] if limit else []

    return {
        "scope": SPAWN_DIVERGENCE_SCOPE,
        "filters": {
            "subject_kind": subject_kind,
            "parent_key": None if parent_key is None else str(parent_key),
            "direction": direction,
            "zone_id": zone_id,
            "candidate_cardinality": candidate_cardinality,
        },
        "comparison_source": {
            "source_key": source_key,
            "source_revision": revision,
            "import_batches": source_batches,
        },
        "distance_method": {
            "strategy": "compatible_nearest_neighbour_with_ties",
            "identity_merge": False,
            "threshold": None,
            "zone_percent": "Euclidean XY distance in zone percentage points, same zone only.",
            "world": (
                "Euclidean XY distance (XYZ when both Z values exist), same canonical map only."
            ),
            "bands": {
                space: ["0", *[label for label, _upper in bands]]
                for space, bands in _DISTANCE_BANDS.items()
            },
        },
        "membership_baseline": {
            "by_subject_kind": baseline_by_kind,
            "shared_member_count": sum(item["shared_member_count"] for item in baseline_by_kind),
            "active_only_member_count": sum(
                item["active_only_member_count"] for item in baseline_by_kind
            ),
            "comparison_only_member_count": sum(
                item["comparison_only_member_count"] for item in baseline_by_kind
            ),
            "one_sided_member_count": len(members),
        },
        "filtered_one_sided_member_count": len(filtered),
        "one_sided_by_subject_kind_direction": [
            {
                "subject_kind": key[0],
                "direction": key[1],
                "member_count": kind_direction_counter[key],
            }
            for key in sorted(kind_direction_counter)
        ],
        "parent_topology": {
            "directly_comparable_parent_count": len(parent_rows),
            "class_counts": {
                label: parent_class_counts[label] for label in PARENT_CLASSES
            },
            "by_subject_kind": [
                {
                    "subject_kind": spawn_kind,
                    "class_counts": {
                        label: parent_class_by_kind[(spawn_kind, label)]
                        for label in PARENT_CLASSES
                    },
                }
                for spawn_kind in SPAWN_SUBJECT_KINDS
            ],
            "one_sided_member_count_distribution": [
                {"one_sided_member_count": key, "parent_count": one_sided_distribution[key]}
                for key in sorted(one_sided_distribution)
            ],
        },
        "active_membership_contexts": [
            {
                "source_key": key[0],
                "source_revision": key[1],
                "selection_policy": key[2],
                "active_only_member_count": membership_contexts[key]["active_only"],
                "comparison_only_member_count": membership_contexts[key]["comparison_only"],
                "one_sided_member_count": sum(membership_contexts[key].values()),
            }
            for key in sorted(
                membership_contexts,
                key=lambda item: (item[0], item[1], "" if item[2] is None else str(item[2])),
            )
        ],
        "active_only_selected_position_contexts": [
            {
                "source_key": key[0],
                "source_revision": key[1],
                "selection_policy": key[2],
                "member_count": position_contexts[key],
            }
            for key in sorted(
                position_contexts,
                key=lambda item: (
                    "" if item[0] is None else str(item[0]),
                    "" if item[1] is None else str(item[1]),
                    "" if item[2] is None else str(item[2]),
                ),
            )
        ],
        "relocation_candidate_analysis": {
            "interpretation": (
                "Coordinate-compatible candidates are analytical possibilities, not proven moves. "
                "Members with zero compatible opposites form a conservative residual only; they "
                "are not automatically proven additions/removals."
            ),
            "compatible_candidate_pair_count": compatible_pair_count,
            "unique_nearest_candidate_pair_count": len(filtered_nearest_pairs),
            "member_candidate_cardinality": {
                "zero": cardinality_counter[0],
                "one": cardinality_counter[1],
                "multiple": cardinality_counter[2],
            },
            "member_nearest_tie_cardinality": {
                "zero": nearest_tie_counter[0],
                "one": nearest_tie_counter[1],
                "multiple": nearest_tie_counter[2],
            },
            "members_without_compatible_opposite_count": len(no_compatible),
            "compatible_pair_distance_bands": [
                {
                    "coordinate_space": key[0],
                    "distance_band": key[1],
                    "compatible_pair_count": distance_bands[key],
                }
                for key in sorted(distance_bands)
            ],
        },
        "top_parent_concentrations": top_parents,
        "top_zone_map_concentrations": top_zones,
        "detail_limit": limit,
        "top_limit": top,
        "returned_member_count": len(details),
        "returned_candidate_pair_count": len(candidate_details),
        "members_truncated": len(details) < len(filtered),
        "candidate_pairs_truncated": len(candidate_details) < len(filtered_nearest_pairs),
        "members": details,
        "candidate_pairs": candidate_details,
    }


def _nonnegative_int(value: str) -> int:
    import argparse

    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def _print_human(payload: dict[str, Any]) -> None:
    baseline = payload["membership_baseline"]
    print(f"Spawn divergence scope: {payload['scope']}")
    source = payload["comparison_source"]
    print(f"Comparison source: {source['source_key']}@{source['source_revision']}")
    print(
        "Membership baseline: "
        f"shared={baseline['shared_member_count']}, "
        f"active-only={baseline['active_only_member_count']}, "
        f"comparison-only={baseline['comparison_only_member_count']}, "
        f"one-sided={baseline['one_sided_member_count']}"
    )
    print(f"Filtered one-sided members: {payload['filtered_one_sided_member_count']}")
    topology = payload["parent_topology"]
    print(f"Directly comparable parents: {topology['directly_comparable_parent_count']}")
    print("Parent classes:")
    for label in PARENT_CLASSES:
        print(f"- {label}: {topology['class_counts'][label]}")
    candidates = payload["relocation_candidate_analysis"]
    print(
        "Coordinate-compatible candidate pairs: "
        f"{candidates['compatible_candidate_pair_count']}"
    )
    print(
        "Unique nearest candidate pairs: "
        f"{candidates['unique_nearest_candidate_pair_count']}"
    )
    print(
        "Member candidate cardinality: "
        f"zero={candidates['member_candidate_cardinality']['zero']}, "
        f"one={candidates['member_candidate_cardinality']['one']}, "
        f"multiple={candidates['member_candidate_cardinality']['multiple']}"
    )
    print(
        "Members without a coordinate-compatible opposite: "
        f"{candidates['members_without_compatible_opposite_count']}"
    )
    for member in payload["members"]:
        print(
            f"- {member['subject_kind']} parent={member['parent_subject_key']} "
            f"{member['direction']} {member['spawn_key']} "
            f"nearest={member['nearest_candidate_distance']}"
        )


def main(argv: list[str] | None = None) -> int:
    """Run the P5-T04 read-only spawn membership divergence audit."""

    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        prog="python -m octogamedb.audit_spawn_divergence",
        description=(
            "Characterize pfquest-octo one-sided P1 spawn memberships and threshold-free nearest "
            "relocation candidates without changing canonical data."
        ),
    )
    parser.add_argument("source_key", nargs="?", default=P1_WORLD_COMPARISON_SOURCE_KEY)
    parser.add_argument("--source-revision")
    parser.add_argument("--subject-kind", choices=SPAWN_SUBJECT_KINDS)
    parser.add_argument("--parent-key")
    parser.add_argument("--direction", choices=DIRECTIONS)
    parser.add_argument("--zone-id", type=int)
    parser.add_argument("--candidate-cardinality", choices=("zero", "one", "multiple"))
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
        payload = spawn_divergence_report(
            connection,
            source_key=args.source_key,
            source_revision=args.source_revision,
            subject_kind=args.subject_kind,
            parent_key=args.parent_key,
            direction=args.direction,
            zone_id=args.zone_id,
            candidate_cardinality=args.candidate_cardinality,
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
