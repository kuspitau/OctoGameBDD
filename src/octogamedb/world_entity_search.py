"""Provenance-aware read-only creature/gameobject exploration for P7-T05."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

MATCH_KNOWN = "known_match"
NON_MATCH_KNOWN = "known_non_match"
MATCH_UNKNOWN = "unknown"
QUERY_STATES = (MATCH_KNOWN, NON_MATCH_KNOWN, MATCH_UNKNOWN)
ENTITY_KINDS = ("creature", "gameobject")
WORLD_ENTITY_QUERY_SORT_FIELDS = ("entity_id", "name", "entity_kind")


@dataclass(frozen=True)
class WorldEntityPredicateState:
    predicate: str
    state: str
    actual: object | None
    reason: str


@dataclass(frozen=True)
class WorldEntityQueryResult:
    entity: dict[str, Any]
    match_state: str
    predicates: tuple[WorldEntityPredicateState, ...]


@dataclass(frozen=True)
class WorldEntityQuerySummary:
    total_entity_identities: int
    total_creature_identities: int
    total_gameobject_identities: int
    known_match_count: int
    known_non_match_count: int
    unknown_count: int
    returned_count: int
    limit: int


@dataclass(frozen=True)
class WorldEntityQueryPage:
    summary: WorldEntityQuerySummary
    results: tuple[WorldEntityQueryResult, ...]


@dataclass(frozen=True)
class _Candidate:
    entity_kind: str
    entity_id: int
    name: str
    row: sqlite3.Row
    state: str
    predicates: tuple[WorldEntityPredicateState, ...]


def _validate_nonnegative(name: str, value: int | None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _normalize_text(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _normalize_states(include_states: Sequence[str]) -> tuple[str, ...]:
    if isinstance(include_states, str):
        raise TypeError("include_states must be a sequence of query states")
    if not include_states:
        raise ValueError("include_states must contain at least one query state")
    invalid = sorted(set(include_states) - set(QUERY_STATES))
    if invalid:
        raise ValueError(f"unsupported query state(s): {', '.join(invalid)}")
    return tuple(state for state in QUERY_STATES if state in include_states)


def _provenance_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "source_key": str(row["source_key"]),
        "source_revision": str(row["source_revision"]),
        "source_record_type": (
            None if row["source_record_type"] is None else str(row["source_record_type"])
        ),
        "raw_identifier": None if row["raw_identifier"] is None else str(row["raw_identifier"]),
        "authority_tier": None if row["authority_tier"] is None else int(row["authority_tier"]),
        "observation_id": int(row["observation_id"]),
        "selection_policy": (
            None if row["selection_policy"] is None else str(row["selection_policy"])
        ),
        "selection_reason": str(row["selection_reason"]),
        "selected_value": json.loads(str(row["value_json"])),
    }


def _selected_fact(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_key: str | int,
    fact_key: str,
    fact_instance_key: str = "",
) -> tuple[object, dict[str, Any]] | None:
    row = connection.execute(
        """
        SELECT cs.observation_id, cs.selection_policy, cs.selection_reason,
               ds.source_key, so.source_revision, so.source_record_type,
               so.raw_identifier, so.authority_tier, so.value_json
        FROM observation_groups AS og
        JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        JOIN source_observations AS so ON so.id = cs.observation_id
        JOIN data_sources AS ds ON ds.id = so.source_id
        WHERE og.subject_kind = ? AND og.subject_key = ?
          AND og.fact_key = ? AND og.fact_instance_key = ?
        """,
        (subject_kind, str(subject_key), fact_key, fact_instance_key),
    ).fetchone()
    if row is None:
        return None
    provenance = _provenance_from_row(row)
    return provenance["selected_value"], provenance


def _selected_relation_rows(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    fact_key: str,
    instance_keys: Sequence[str],
) -> list[tuple[str, str, object, dict[str, Any]]]:
    if not instance_keys:
        return []
    placeholders = ", ".join("?" for _ in instance_keys)
    rows = connection.execute(
        f"""
        SELECT og.subject_key, og.fact_instance_key,
               cs.observation_id, cs.selection_policy, cs.selection_reason,
               ds.source_key, so.source_revision, so.source_record_type,
               so.raw_identifier, so.authority_tier, so.value_json
        FROM observation_groups AS og
        JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        JOIN source_observations AS so ON so.id = cs.observation_id
        JOIN data_sources AS ds ON ds.id = so.source_id
        WHERE og.subject_kind = ? AND og.fact_key = ?
          AND og.fact_instance_key IN ({placeholders})
        ORDER BY og.subject_key, og.fact_instance_key
        """,
        (subject_kind, fact_key, *instance_keys),
    ).fetchall()
    result: list[tuple[str, str, object, dict[str, Any]]] = []
    for row in rows:
        provenance = _provenance_from_row(row)
        result.append(
            (
                str(row["subject_key"]),
                str(row["fact_instance_key"]),
                provenance["selected_value"],
                provenance,
            )
        )
    return result


def _template_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT 'creature' AS entity_kind, creature_id AS entity_id, name,
               level_min, level_max, faction, classification, creature_type, npc_flags,
               NULL AS object_type
        FROM creatures
        UNION ALL
        SELECT 'gameobject' AS entity_kind, gameobject_id AS entity_id, name,
               NULL AS level_min, NULL AS level_max, NULL AS faction,
               NULL AS classification, NULL AS creature_type, NULL AS npc_flags,
               object_type
        FROM gameobjects
        ORDER BY entity_kind, entity_id
        """
    ).fetchall()


def _geography_rows(
    connection: sqlite3.Connection,
) -> dict[tuple[str, int], tuple[dict[str, Any], ...]]:
    rows = connection.execute(
        """
        SELECT 'creature' AS entity_kind, s.creature_id AS entity_id, s.spawn_key,
               s.zone_id, COALESCE(s.map_id, z.map_id) AS map_id
        FROM creature_spawns AS s
        LEFT JOIN zones AS z ON z.zone_id = s.zone_id
        UNION ALL
        SELECT 'gameobject' AS entity_kind, s.gameobject_id AS entity_id, s.spawn_key,
               s.zone_id, COALESCE(s.map_id, z.map_id) AS map_id
        FROM gameobject_spawns AS s
        LEFT JOIN zones AS z ON z.zone_id = s.zone_id
        ORDER BY entity_kind, entity_id, spawn_key
        """
    ).fetchall()
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["entity_kind"]), int(row["entity_id"]))
        grouped.setdefault(key, []).append(
            {
                "spawn_key": str(row["spawn_key"]),
                "zone_id": None if row["zone_id"] is None else int(row["zone_id"]),
                "map_id": None if row["map_id"] is None else int(row["map_id"]),
            }
        )
    return {key: tuple(value) for key, value in grouped.items()}


def _selected_spawn_sets(
    connection: sqlite3.Connection,
) -> dict[tuple[str, int], tuple[object, dict[str, Any]]]:
    rows = connection.execute(
        """
        SELECT og.subject_kind, og.subject_key,
               cs.observation_id, cs.selection_policy, cs.selection_reason,
               ds.source_key, so.source_revision, so.source_record_type,
               so.raw_identifier, so.authority_tier, so.value_json
        FROM observation_groups AS og
        JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        JOIN source_observations AS so ON so.id = cs.observation_id
        JOIN data_sources AS ds ON ds.id = so.source_id
        WHERE og.fact_key = 'spawn_set' AND og.fact_instance_key = ''
          AND og.subject_kind IN ('creature', 'gameobject')
        ORDER BY og.subject_kind, og.subject_key
        """
    ).fetchall()
    result: dict[tuple[str, int], tuple[object, dict[str, Any]]] = {}
    for row in rows:
        try:
            entity_id = int(str(row["subject_key"]))
        except ValueError as exc:
            raise TypeError("selected spawn_set subject key must be an integer") from exc
        provenance = _provenance_from_row(row)
        result[(str(row["subject_kind"]), entity_id)] = (
            provenance["selected_value"],
            provenance,
        )
    return result


def _spawn_set_coverage(
    spawns: Sequence[Mapping[str, Any]],
    selection: tuple[object, dict[str, Any]] | None,
) -> dict[str, Any]:
    materialized_keys = [str(spawn["spawn_key"]) for spawn in spawns]
    materialized_key_set = set(materialized_keys)
    if selection is None:
        return {
            "declared": False,
            "scope": None,
            "selected_member_count": None,
            "selected_distinct_member_count": None,
            "duplicate_source_member_count": 0,
            "duplicate_source_spawn_keys": [],
            "materialized_selected_member_count": None,
            "materialized_total_count": len(materialized_keys),
            "is_complete_for_canonical_view": False,
            "unresolved_members": [],
            "extra_materialized_spawns": materialized_keys,
            "provenance": None,
        }

    value, provenance = selection
    if not isinstance(value, list):
        raise TypeError("selected spawn_set must be a list")
    selected_keys: list[str] = []
    for member in value:
        if not isinstance(member, dict):
            raise TypeError("selected spawn_set member must be an object")
        spawn_key = member.get("spawn_key")
        if not isinstance(spawn_key, str) or not spawn_key:
            raise TypeError("selected spawn_set member must contain spawn_key")
        selected_keys.append(spawn_key)

    key_counts: dict[str, int] = {}
    for spawn_key in selected_keys:
        key_counts[spawn_key] = key_counts.get(spawn_key, 0) + 1
    duplicate_keys = sorted(key for key, count in key_counts.items() if count > 1)
    selected_key_set = set(selected_keys)
    unresolved = sorted(selected_key_set - materialized_key_set)
    extra = sorted(materialized_key_set - selected_key_set)
    materialized_selected = len(selected_key_set & materialized_key_set)
    return {
        "declared": True,
        "scope": "selected_effective_source_view",
        "selected_member_count": len(selected_keys),
        "selected_distinct_member_count": len(selected_key_set),
        "duplicate_source_member_count": len(selected_keys) - len(selected_key_set),
        "duplicate_source_spawn_keys": duplicate_keys,
        "materialized_selected_member_count": materialized_selected,
        "materialized_total_count": len(materialized_keys),
        "is_complete_for_canonical_view": not unresolved and not extra,
        "unresolved_members": unresolved,
        "extra_materialized_spawns": extra,
        "provenance": provenance,
    }


def _location_matches(
    spawn: Mapping[str, Any], *, zone_id: int | None, map_id: int | None
) -> bool:
    if zone_id is not None and spawn.get("zone_id") != zone_id:
        return False
    return map_id is None or spawn.get("map_id") == map_id


def _geography_predicate(
    *,
    spawns: Sequence[Mapping[str, Any]],
    spawn_set: dict[str, Any],
    zone_id: int | None,
    map_id: int | None,
) -> WorldEntityPredicateState | None:
    if zone_id is None and map_id is None:
        return None
    parts: list[str] = []
    if zone_id is not None:
        parts.append(f"zone={zone_id}")
    if map_id is not None:
        parts.append(f"map={map_id}")
    label = f"spawn_geography[{','.join(parts)}]"
    actual = {
        "materialized_spawn_count": len(spawns),
        "spawn_set_declared": bool(spawn_set["declared"]),
        "spawn_set_complete_for_canonical_view": bool(
            spawn_set["is_complete_for_canonical_view"]
        ),
    }

    if any(_location_matches(spawn, zone_id=zone_id, map_id=map_id) for spawn in spawns):
        return WorldEntityPredicateState(
            predicate=label,
            state=MATCH_KNOWN,
            actual=actual,
            reason="known_matching_canonical_spawn",
        )

    if not spawn_set["declared"]:
        return WorldEntityPredicateState(
            predicate=label,
            state=MATCH_UNKNOWN,
            actual=actual,
            reason="no_selected_complete_spawn_set_negative_not_proven",
        )
    if not spawn_set["is_complete_for_canonical_view"]:
        return WorldEntityPredicateState(
            predicate=label,
            state=MATCH_UNKNOWN,
            actual=actual,
            reason="selected_spawn_set_does_not_cover_complete_canonical_spawn_view",
        )
    if zone_id is not None and any(spawn.get("zone_id") is None for spawn in spawns):
        return WorldEntityPredicateState(
            predicate=label,
            state=MATCH_UNKNOWN,
            actual=actual,
            reason="complete_spawn_set_contains_spawn_with_unresolved_zone",
        )
    if map_id is not None and any(spawn.get("map_id") is None for spawn in spawns):
        return WorldEntityPredicateState(
            predicate=label,
            state=MATCH_UNKNOWN,
            actual=actual,
            reason="complete_spawn_set_contains_spawn_with_unresolved_map",
        )
    return WorldEntityPredicateState(
        predicate=label,
        state=NON_MATCH_KNOWN,
        actual=actual,
        reason="selected_complete_effective_spawn_set_proves_no_match",
    )


def _known_predicate(
    predicate: str, matches: bool, actual: object, reason: str
) -> WorldEntityPredicateState:
    return WorldEntityPredicateState(
        predicate=predicate,
        state=MATCH_KNOWN if matches else NON_MATCH_KNOWN,
        actual=actual,
        reason=reason,
    )


def _combined_state(predicates: Sequence[WorldEntityPredicateState]) -> str:
    if any(predicate.state == NON_MATCH_KNOWN for predicate in predicates):
        return NON_MATCH_KNOWN
    if any(predicate.state == MATCH_UNKNOWN for predicate in predicates):
        return MATCH_UNKNOWN
    return MATCH_KNOWN


def _evaluate_candidate(
    row: sqlite3.Row,
    *,
    entity_kind: str | None,
    entity_id: int | None,
    name_contains: str | None,
    zone_id: int | None,
    map_id: int | None,
    geography: Mapping[tuple[str, int], Sequence[Mapping[str, Any]]],
    selected_spawn_sets: Mapping[tuple[str, int], tuple[object, dict[str, Any]]],
) -> tuple[str, tuple[WorldEntityPredicateState, ...]]:
    row_kind = str(row["entity_kind"])
    row_id = int(row["entity_id"])
    row_name = str(row["name"])
    predicates: list[WorldEntityPredicateState] = []
    if entity_kind is not None:
        predicates.append(
            _known_predicate(
                f"entity_kind={entity_kind}",
                row_kind == entity_kind,
                row_kind,
                "canonical_entity_kind",
            )
        )
    if entity_id is not None:
        predicates.append(
            _known_predicate(
                f"entity_id={entity_id}",
                row_id == entity_id,
                row_id,
                "canonical_native_identity",
            )
        )
    if name_contains is not None:
        predicates.append(
            _known_predicate(
                f"name_contains={name_contains!r}",
                name_contains.casefold() in row_name.casefold(),
                row_name,
                "canonical_entity_name",
            )
        )
    if zone_id is not None or map_id is not None:
        key = (row_kind, row_id)
        spawns = tuple(geography.get(key, ()))
        coverage = _spawn_set_coverage(spawns, selected_spawn_sets.get(key))
        predicate = _geography_predicate(
            spawns=spawns,
            spawn_set=coverage,
            zone_id=zone_id,
            map_id=map_id,
        )
        if predicate is not None:
            predicates.append(predicate)
    frozen = tuple(predicates)
    return _combined_state(frozen), frozen


def _full_spawns(
    connection: sqlite3.Connection, *, entity_kind: str, entity_id: int
) -> tuple[dict[str, Any], ...]:
    if entity_kind == "creature":
        table = "creature_spawns"
        id_column = "creature_id"
    else:
        table = "gameobject_spawns"
        id_column = "gameobject_id"
    rows = connection.execute(
        f"""
        SELECT s.spawn_id, s.spawn_key, s.coordinate_space, s.x, s.y, s.z,
               s.orientation, s.respawn_seconds, s.zone_id, z.name AS zone_name,
               COALESCE(s.map_id, z.map_id) AS map_id, m.name AS map_name
        FROM {table} AS s
        LEFT JOIN zones AS z ON z.zone_id = s.zone_id
        LEFT JOIN maps AS m ON m.map_id = COALESCE(s.map_id, z.map_id)
        WHERE s.{id_column} = ?
        ORDER BY s.spawn_key
        """,
        (entity_id,),
    ).fetchall()
    result: list[dict[str, Any]] = []
    subject_kind = f"{entity_kind}_spawn"
    for row in rows:
        spawn_key = str(row["spawn_key"])
        position = _selected_fact(
            connection,
            subject_kind=subject_kind,
            subject_key=spawn_key,
            fact_key="position",
        )
        respawn = _selected_fact(
            connection,
            subject_kind=subject_kind,
            subject_key=spawn_key,
            fact_key="respawn_seconds",
        )
        result.append(
            {
                "spawn_id": int(row["spawn_id"]),
                "spawn_key": spawn_key,
                "coordinate_space": str(row["coordinate_space"]),
                "x": float(row["x"]),
                "y": float(row["y"]),
                "z": None if row["z"] is None else float(row["z"]),
                "orientation": (
                    None if row["orientation"] is None else float(row["orientation"])
                ),
                "respawn_seconds": (
                    None if row["respawn_seconds"] is None else int(row["respawn_seconds"])
                ),
                "zone_id": None if row["zone_id"] is None else int(row["zone_id"]),
                "zone_name": None if row["zone_name"] is None else str(row["zone_name"]),
                "map_id": None if row["map_id"] is None else int(row["map_id"]),
                "map_name": None if row["map_name"] is None else str(row["map_name"]),
                "provenance": {
                    "position": None if position is None else position[1],
                    "respawn_seconds": None if respawn is None else respawn[1],
                },
            }
        )
    return tuple(result)


def _vendor_max_count(
    connection: sqlite3.Connection, *, item_id: int, vendor_id: int
) -> tuple[int, dict[str, Any]]:
    selected = _selected_fact(
        connection,
        subject_kind="item",
        subject_key=item_id,
        fact_key="vendor_source",
        fact_instance_key=f"creature:{vendor_id}",
    )
    if selected is None:
        raise RuntimeError("canonical vendor relation has no selected provenance payload")
    value, provenance = selected
    if not isinstance(value, dict):
        raise TypeError("selected vendor relation payload must be an object")
    target = value.get("target")
    attributes = value.get("attributes")
    if not isinstance(target, dict) or not isinstance(attributes, dict):
        raise TypeError("selected vendor relation payload is incomplete")
    if target.get("kind") != "creature" or str(target.get("key")) != str(vendor_id):
        raise RuntimeError("selected vendor relation target does not match canonical vendor")
    max_count = attributes.get("max_count")
    if isinstance(max_count, bool) or not isinstance(max_count, int) or max_count < 0:
        raise TypeError("selected vendor relation has no non-negative integer max_count")
    return max_count, provenance


def _item_roles(
    connection: sqlite3.Connection, *, entity_kind: str, entity_id: int
) -> tuple[dict[str, Any], ...]:
    paths_by_item: dict[int, dict[str, Any]] = {}

    def add(item_id: int, item_name: str, path: dict[str, Any]) -> None:
        item = paths_by_item.setdefault(
            item_id,
            {"item_id": item_id, "item_name": item_name, "acquisition_paths": []},
        )
        item["acquisition_paths"].append(path)

    if entity_kind == "creature":
        direct_rows = connection.execute(
            """
            SELECT l.item_id, i.name, l.chance_percent
            FROM creature_loot AS l
            JOIN items AS i ON i.item_id = l.item_id
            WHERE l.creature_id = ?
            ORDER BY l.item_id
            """,
            (entity_id,),
        ).fetchall()
        reference_rows = connection.execute(
            """
            SELECT irl.item_id, i.name, irl.reference_loot_id, irl.chance_percent
            FROM reference_loot_creatures AS members
            JOIN item_reference_loot AS irl
              ON irl.reference_loot_id = members.reference_loot_id
            JOIN items AS i ON i.item_id = irl.item_id
            WHERE members.creature_id = ?
            ORDER BY irl.item_id, irl.reference_loot_id
            """,
            (entity_id,),
        ).fetchall()
        vendor_rows = connection.execute(
            """
            SELECT v.item_id, i.name
            FROM vendor_items AS v
            JOIN items AS i ON i.item_id = v.item_id
            WHERE v.vendor_creature_id = ?
            ORDER BY v.item_id
            """,
            (entity_id,),
        ).fetchall()
    else:
        direct_rows = connection.execute(
            """
            SELECT l.item_id, i.name, l.chance_percent
            FROM gameobject_loot AS l
            JOIN items AS i ON i.item_id = l.item_id
            WHERE l.gameobject_id = ?
            ORDER BY l.item_id
            """,
            (entity_id,),
        ).fetchall()
        reference_rows = connection.execute(
            """
            SELECT irl.item_id, i.name, irl.reference_loot_id, irl.chance_percent
            FROM reference_loot_gameobjects AS members
            JOIN item_reference_loot AS irl
              ON irl.reference_loot_id = members.reference_loot_id
            JOIN items AS i ON i.item_id = irl.item_id
            WHERE members.gameobject_id = ?
            ORDER BY irl.item_id, irl.reference_loot_id
            """,
            (entity_id,),
        ).fetchall()
        vendor_rows = []

    for row in direct_rows:
        item_id = int(row["item_id"])
        selected = _selected_fact(
            connection,
            subject_kind="item",
            subject_key=item_id,
            fact_key="loot_source",
            fact_instance_key=f"{entity_kind}:{entity_id}",
        )
        add(
            item_id,
            str(row["name"]),
            {
                "path_kind": "direct",
                "chance_percent": float(row["chance_percent"]),
                "reference_loot_id": None,
                "vendor_max_count": None,
                "relation_provenance": None if selected is None else selected[1],
                "reference_membership_provenance": None,
            },
        )

    for row in reference_rows:
        item_id = int(row["item_id"])
        reference_id = int(row["reference_loot_id"])
        relation = _selected_fact(
            connection,
            subject_kind="item",
            subject_key=item_id,
            fact_key="loot_reference",
            fact_instance_key=f"reference:{reference_id}",
        )
        membership = _selected_fact(
            connection,
            subject_kind="loot_reference",
            subject_key=reference_id,
            fact_key="loot_source_member",
            fact_instance_key=f"{entity_kind}:{entity_id}",
        )
        add(
            item_id,
            str(row["name"]),
            {
                "path_kind": "reference",
                "chance_percent": float(row["chance_percent"]),
                "reference_loot_id": reference_id,
                "vendor_max_count": None,
                "relation_provenance": None if relation is None else relation[1],
                "reference_membership_provenance": (
                    None if membership is None else membership[1]
                ),
            },
        )

    for row in vendor_rows:
        item_id = int(row["item_id"])
        max_count, provenance = _vendor_max_count(
            connection, item_id=item_id, vendor_id=entity_id
        )
        add(
            item_id,
            str(row["name"]),
            {
                "path_kind": "vendor",
                "chance_percent": None,
                "reference_loot_id": None,
                "vendor_max_count": max_count,
                "relation_provenance": provenance,
                "reference_membership_provenance": None,
            },
        )

    path_order = {"direct": 0, "reference": 1, "vendor": 2}
    for item in paths_by_item.values():
        item["acquisition_paths"].sort(
            key=lambda path: (
                path_order[str(path["path_kind"])],
                -1 if path["reference_loot_id"] is None else int(path["reference_loot_id"]),
            )
        )
    return tuple(paths_by_item[item_id] for item_id in sorted(paths_by_item))


def _selected_quest_role_rows(
    connection: sqlite3.Connection, *, entity_kind: str, entity_id: int
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    endpoint_instances = (
        f"giver:{entity_kind}:{entity_id}",
        f"finisher:{entity_kind}:{entity_id}",
    )
    for subject_key, _, value, provenance in _selected_relation_rows(
        connection,
        subject_kind="quest",
        fact_key="endpoint",
        instance_keys=endpoint_instances,
    ):
        if not isinstance(value, dict):
            raise TypeError("selected quest endpoint payload must be an object")
        target = value.get("target")
        attributes = value.get("attributes")
        if not isinstance(target, dict) or not isinstance(attributes, dict):
            raise TypeError("selected quest endpoint payload is incomplete")
        role = attributes.get("endpoint_kind")
        if role not in {"giver", "finisher"}:
            raise TypeError("selected quest endpoint has invalid endpoint_kind")
        if target.get("kind") != entity_kind or str(target.get("key")) != str(entity_id):
            raise RuntimeError("selected quest endpoint target does not match relation instance")
        result.append(
            {
                "quest_id": int(subject_key),
                "role": role,
                "objective_kind": None,
                "provenance": provenance,
            }
        )

    fact_key = "objective_creature" if entity_kind == "creature" else "objective_gameobject"
    for subject_key, _, value, provenance in _selected_relation_rows(
        connection,
        subject_kind="quest",
        fact_key=fact_key,
        instance_keys=(str(entity_id),),
    ):
        if not isinstance(value, dict):
            raise TypeError("selected quest objective payload must be an object")
        target = value.get("target")
        if not isinstance(target, dict):
            raise TypeError("selected quest objective payload is incomplete")
        if target.get("kind") != entity_kind or str(target.get("key")) != str(entity_id):
            raise RuntimeError("selected quest objective target does not match relation instance")
        result.append(
            {
                "quest_id": int(subject_key),
                "role": "objective",
                "objective_kind": entity_kind,
                "provenance": provenance,
            }
        )
    return result


def _quest_roles(
    connection: sqlite3.Connection, *, entity_kind: str, entity_id: int
) -> tuple[dict[str, Any], ...]:
    roles: dict[tuple[int, str, str | None], dict[str, Any]] = {}
    if entity_kind == "creature":
        endpoint_table = "quest_creature_endpoints"
        objective_table = "quest_creature_objectives"
        id_column = "creature_id"
        objective_fact = "objective_creature"
    else:
        endpoint_table = "quest_gameobject_endpoints"
        objective_table = "quest_gameobject_objectives"
        id_column = "gameobject_id"
        objective_fact = "objective_gameobject"

    endpoint_rows = connection.execute(
        f"""
        SELECT e.quest_id, q.name, e.endpoint_kind
        FROM {endpoint_table} AS e
        JOIN quests AS q ON q.quest_id = e.quest_id
        WHERE e.{id_column} = ?
        ORDER BY e.quest_id, e.endpoint_kind
        """,
        (entity_id,),
    ).fetchall()
    for row in endpoint_rows:
        quest_id = int(row["quest_id"])
        role = str(row["endpoint_kind"])
        selected = _selected_fact(
            connection,
            subject_kind="quest",
            subject_key=quest_id,
            fact_key="endpoint",
            fact_instance_key=f"{role}:{entity_kind}:{entity_id}",
        )
        roles[(quest_id, role, None)] = {
            "quest_id": quest_id,
            "quest_name": str(row["name"]),
            "quest_resolved": True,
            "role": role,
            "objective_kind": None,
            "relation_materialized": True,
            "relation_resolution_reason": None,
            "provenance": None if selected is None else selected[1],
            "quest_detail_owner": "P7-T03",
        }

    objective_rows = connection.execute(
        f"""
        SELECT o.quest_id, q.name
        FROM {objective_table} AS o
        JOIN quests AS q ON q.quest_id = o.quest_id
        WHERE o.{id_column} = ?
        ORDER BY o.quest_id
        """,
        (entity_id,),
    ).fetchall()
    for row in objective_rows:
        quest_id = int(row["quest_id"])
        selected = _selected_fact(
            connection,
            subject_kind="quest",
            subject_key=quest_id,
            fact_key=objective_fact,
            fact_instance_key=str(entity_id),
        )
        roles[(quest_id, "objective", entity_kind)] = {
            "quest_id": quest_id,
            "quest_name": str(row["name"]),
            "quest_resolved": True,
            "role": "objective",
            "objective_kind": entity_kind,
            "relation_materialized": True,
            "relation_resolution_reason": None,
            "provenance": None if selected is None else selected[1],
            "quest_detail_owner": "P7-T03",
        }

    for selected in _selected_quest_role_rows(
        connection, entity_kind=entity_kind, entity_id=entity_id
    ):
        quest_id = int(selected["quest_id"])
        role = str(selected["role"])
        objective_kind = selected["objective_kind"]
        key = (quest_id, role, objective_kind)
        if key in roles:
            roles[key]["provenance"] = selected["provenance"]
            continue
        quest = connection.execute(
            "SELECT name FROM quests WHERE quest_id = ?", (quest_id,)
        ).fetchone()
        roles[key] = {
            "quest_id": quest_id,
            "quest_name": None if quest is None else str(quest["name"]),
            "quest_resolved": quest is not None,
            "role": role,
            "objective_kind": objective_kind,
            "relation_materialized": False,
            "relation_resolution_reason": "selected_relation_not_materialized",
            "provenance": selected["provenance"],
            "quest_detail_owner": "P7-T03",
        }

    role_order = {"giver": 0, "finisher": 1, "objective": 2}
    return tuple(
        sorted(
            roles.values(),
            key=lambda row: (
                int(row["quest_id"]),
                role_order[str(row["role"])],
                "" if row["objective_kind"] is None else str(row["objective_kind"]),
            ),
        )
    )


def _trainer_roles(
    connection: sqlite3.Connection, *, entity_kind: str, entity_id: int
) -> tuple[dict[str, Any], ...]:
    if entity_kind != "creature":
        return ()
    rows = connection.execute(
        """
        SELECT ts.recipe_id, r.crafting_spell_id, s.name AS recipe_name,
               ts.trainer_kind, ts.native_trainer_entry, ts.creature_id,
               ts.trainer_template_id, ts.acquisition_spell_id,
               acq.name AS acquisition_spell_name, ts.learning_proof_kind,
               ts.learn_effect_index, ts.server_learn_active, ts.spell_cost,
               ts.required_skill_line_id, sl.name AS required_skill_line_name,
               ts.required_skill_value, ts.required_character_level
        FROM recipe_trainer_sources AS ts
        JOIN recipes AS r ON r.recipe_id = ts.recipe_id
        JOIN spells AS s ON s.spell_id = r.crafting_spell_id
        JOIN spells AS acq ON acq.spell_id = ts.acquisition_spell_id
        LEFT JOIN skill_lines AS sl ON sl.skill_line_id = ts.required_skill_line_id
        WHERE ts.native_trainer_entry = ?
        ORDER BY ts.recipe_id, ts.trainer_kind, ts.acquisition_spell_id
        """,
        (entity_id,),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        recipe_id = int(row["recipe_id"])
        trainer_kind = str(row["trainer_kind"])
        native_entry = int(row["native_trainer_entry"])
        template_id = (
            None if row["trainer_template_id"] is None else int(row["trainer_template_id"])
        )
        acquisition_spell_id = int(row["acquisition_spell_id"])
        instance_key = (
            f"{trainer_kind}:creature:{native_entry}:template:{template_id or 0}:"
            f"spell:{acquisition_spell_id}"
        )
        selected = _selected_fact(
            connection,
            subject_kind="recipe",
            subject_key=recipe_id,
            fact_key="trainer_source",
            fact_instance_key=instance_key,
        )
        result.append(
            {
                "recipe_id": recipe_id,
                "crafting_spell_id": int(row["crafting_spell_id"]),
                "recipe_name": None if row["recipe_name"] is None else str(row["recipe_name"]),
                "trainer_kind": trainer_kind,
                "native_trainer_entry": native_entry,
                "creature_id": None if row["creature_id"] is None else int(row["creature_id"]),
                "resolved": row["creature_id"] is not None,
                "unresolved_reason": (
                    None
                    if row["creature_id"] is not None
                    else "missing_canonical_creature_identity"
                ),
                "trainer_template_id": template_id,
                "acquisition_spell_id": acquisition_spell_id,
                "acquisition_spell_name": (
                    None
                    if row["acquisition_spell_name"] is None
                    else str(row["acquisition_spell_name"])
                ),
                "learning_proof_kind": str(row["learning_proof_kind"]),
                "learn_effect_index": (
                    None if row["learn_effect_index"] is None else int(row["learn_effect_index"])
                ),
                "server_learn_active": (
                    None
                    if row["server_learn_active"] is None
                    else int(row["server_learn_active"])
                ),
                "spell_cost": int(row["spell_cost"]),
                "required_skill_line_id": (
                    None
                    if row["required_skill_line_id"] is None
                    else int(row["required_skill_line_id"])
                ),
                "required_skill_line_name": (
                    None
                    if row["required_skill_line_name"] is None
                    else str(row["required_skill_line_name"])
                ),
                "required_skill_value": int(row["required_skill_value"]),
                "required_character_level": int(row["required_character_level"]),
                "provenance": None if selected is None else selected[1],
                "recipe_detail_owner": "P7-T04",
            }
        )
    return tuple(result)


def _template_provenance(
    connection: sqlite3.Connection, *, entity_kind: str, entity_id: int
) -> dict[str, Any]:
    fields = (
        ("name",)
        if entity_kind == "gameobject"
        else (
            "name",
            "level_min",
            "level_max",
            "faction",
            "classification",
            "creature_type",
            "npc_flags",
        )
    )
    if entity_kind == "gameobject":
        fields = ("name", "object_type")
    result: dict[str, Any] = {}
    for field in fields:
        selected = _selected_fact(
            connection,
            subject_kind=entity_kind,
            subject_key=entity_id,
            fact_key=field,
        )
        result[field] = None if selected is None else selected[1]
    return result


def _entity_detail(
    connection: sqlite3.Connection,
    candidate: _Candidate,
) -> dict[str, Any]:
    row = candidate.row
    kind = candidate.entity_kind
    entity_id = candidate.entity_id
    spawns = _full_spawns(connection, entity_kind=kind, entity_id=entity_id)
    spawn_set_selection = _selected_fact(
        connection,
        subject_kind=kind,
        subject_key=entity_id,
        fact_key="spawn_set",
    )
    spawn_set = _spawn_set_coverage(spawns, spawn_set_selection)
    presence = _selected_fact(
        connection,
        subject_kind=kind,
        subject_key=entity_id,
        fact_key="world_presence",
    )
    item_roles = _item_roles(connection, entity_kind=kind, entity_id=entity_id)
    quest_roles = _quest_roles(connection, entity_kind=kind, entity_id=entity_id)
    trainer_roles = _trainer_roles(connection, entity_kind=kind, entity_id=entity_id)

    path_counts = {"direct": 0, "reference": 0, "vendor": 0}
    for item in item_roles:
        for path in item["acquisition_paths"]:
            path_counts[str(path["path_kind"])] += 1
    quest_counts = {"giver": 0, "finisher": 0, "objective": 0}
    for quest in quest_roles:
        quest_counts[str(quest["role"])] += 1

    if kind == "creature":
        template = {
            "level_min": None if row["level_min"] is None else int(row["level_min"]),
            "level_max": None if row["level_max"] is None else int(row["level_max"]),
            "faction": None if row["faction"] is None else str(row["faction"]),
            "classification": (
                None if row["classification"] is None else str(row["classification"])
            ),
            "creature_type": (
                None if row["creature_type"] is None else str(row["creature_type"])
            ),
            "npc_flags": None if row["npc_flags"] is None else int(row["npc_flags"]),
        }
    else:
        template = {
            "object_type": None if row["object_type"] is None else str(row["object_type"])
        }

    return {
        "entity_kind": kind,
        "entity_id": entity_id,
        "name": candidate.name,
        "template": template,
        "template_provenance": _template_provenance(
            connection, entity_kind=kind, entity_id=entity_id
        ),
        "world_presence": {
            "selected_value": None if presence is None else presence[0],
            "provenance": None if presence is None else presence[1],
            "semantics": "source_effective_view_not_universal_existence",
        },
        "spawns": list(spawns),
        "spawn_set": spawn_set,
        "roles": {
            "item_acquisition": list(item_roles),
            "quests": list(quest_roles),
            "trainers": list(trainer_roles),
            "summary": {
                "direct_loot_path_count": path_counts["direct"],
                "reference_loot_path_count": path_counts["reference"],
                "vendor_path_count": path_counts["vendor"],
                "is_vendor": path_counts["vendor"] > 0,
                "trainer_relation_count": len(trainer_roles),
                "is_trainer": bool(trainer_roles),
                "quest_giver_count": quest_counts["giver"],
                "quest_finisher_count": quest_counts["finisher"],
                "quest_objective_count": quest_counts["objective"],
            },
        },
        "coverage_semantics": (
            "selected_complete_spawn_sets_may_prove_bounded_geography_negatives; "
            "missing_or_incomplete_geography_remains_unknown"
        ),
    }


def _sort_candidates(
    candidates: list[_Candidate], *, sort_by: str, descending: bool
) -> list[_Candidate]:
    if sort_by == "entity_id":
        return sorted(
            candidates,
            key=lambda row: (row.entity_id, row.entity_kind),
            reverse=descending,
        )
    if sort_by == "entity_kind":
        return sorted(
            candidates,
            key=lambda row: (row.entity_kind, row.entity_id),
            reverse=descending,
        )
    return sorted(
        candidates,
        key=lambda row: (row.name.casefold(), row.entity_kind, row.entity_id),
        reverse=descending,
    )


def query_world_entities(
    connection: sqlite3.Connection,
    *,
    entity_kind: str | None = None,
    entity_id: int | None = None,
    name_contains: str | None = None,
    zone_id: int | None = None,
    map_id: int | None = None,
    include_states: Sequence[str] = (MATCH_KNOWN,),
    sort_by: str = "entity_id",
    descending: bool = False,
    limit: int = 100,
) -> WorldEntityQueryPage:
    """Search canonical creature/gameobject templates and compose bounded role/geography detail."""

    if entity_kind is not None:
        if not isinstance(entity_kind, str):
            raise TypeError("entity_kind must be a string")
        if entity_kind not in ENTITY_KINDS:
            raise ValueError(f"unsupported entity kind: {entity_kind}")
    _validate_nonnegative("entity_id", entity_id)
    _validate_nonnegative("zone_id", zone_id)
    _validate_nonnegative("map_id", map_id)
    normalized_name = _normalize_text("name_contains", name_contains)
    normalized_states = _normalize_states(include_states)
    if sort_by not in WORLD_ENTITY_QUERY_SORT_FIELDS:
        raise ValueError(f"unsupported sort field: {sort_by}")
    if not isinstance(descending, bool):
        raise TypeError("descending must be a boolean")
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")

    rows = _template_rows(connection)
    geography: dict[tuple[str, int], tuple[dict[str, Any], ...]] = {}
    selected_spawn_sets: dict[tuple[str, int], tuple[object, dict[str, Any]]] = {}
    if zone_id is not None or map_id is not None:
        geography = _geography_rows(connection)
        selected_spawn_sets = _selected_spawn_sets(connection)

    candidates: list[_Candidate] = []
    state_counts = {state: 0 for state in QUERY_STATES}
    creature_count = 0
    gameobject_count = 0
    for row in rows:
        row_kind = str(row["entity_kind"])
        if row_kind == "creature":
            creature_count += 1
        else:
            gameobject_count += 1
        state, predicates = _evaluate_candidate(
            row,
            entity_kind=entity_kind,
            entity_id=entity_id,
            name_contains=normalized_name,
            zone_id=zone_id,
            map_id=map_id,
            geography=geography,
            selected_spawn_sets=selected_spawn_sets,
        )
        state_counts[state] += 1
        if state in normalized_states:
            candidates.append(
                _Candidate(
                    entity_kind=row_kind,
                    entity_id=int(row["entity_id"]),
                    name=str(row["name"]),
                    row=row,
                    state=state,
                    predicates=predicates,
                )
            )

    ordered = _sort_candidates(candidates, sort_by=sort_by, descending=descending)
    selected_candidates = ordered[:limit]
    results = tuple(
        WorldEntityQueryResult(
            entity=_entity_detail(connection, candidate),
            match_state=candidate.state,
            predicates=candidate.predicates,
        )
        for candidate in selected_candidates
    )
    return WorldEntityQueryPage(
        summary=WorldEntityQuerySummary(
            total_entity_identities=len(rows),
            total_creature_identities=creature_count,
            total_gameobject_identities=gameobject_count,
            known_match_count=state_counts[MATCH_KNOWN],
            known_non_match_count=state_counts[NON_MATCH_KNOWN],
            unknown_count=state_counts[MATCH_UNKNOWN],
            returned_count=len(results),
            limit=limit,
        ),
        results=results,
    )


def world_entity_query_page_to_dict(page: WorldEntityQueryPage) -> dict[str, object]:
    return {
        "summary": asdict(page.summary),
        "results": [
            {
                "entity": result.entity,
                "match_state": result.match_state,
                "predicates": [asdict(predicate) for predicate in result.predicates],
            }
            for result in page.results
        ],
    }
