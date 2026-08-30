"""Provenance-aware read-only quest search and progression exploration for P7-T03."""

from __future__ import annotations

import json
import sqlite3
from collections import deque
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from octogamedb.quests import quest_by_id

MATCH_KNOWN = "known_match"
NON_MATCH_KNOWN = "known_non_match"
MATCH_UNKNOWN = "unknown"
QUERY_STATES = (MATCH_KNOWN, NON_MATCH_KNOWN, MATCH_UNKNOWN)
QUEST_QUERY_SORT_FIELDS = ("quest_id", "name", "quest_level", "minimum_level")
TRAVERSAL_DIRECTIONS = ("prerequisite", "follow_up")


@dataclass(frozen=True)
class QuestPredicateState:
    predicate: str
    state: str
    actual: object | None
    reason: str


@dataclass(frozen=True)
class QuestQueryResult:
    quest: dict[str, Any]
    match_state: str
    predicates: tuple[QuestPredicateState, ...]


@dataclass(frozen=True)
class QuestQuerySummary:
    total_quest_identities: int
    known_match_count: int
    known_non_match_count: int
    unknown_count: int
    returned_count: int
    limit: int


@dataclass(frozen=True)
class QuestQueryPage:
    summary: QuestQuerySummary
    results: tuple[QuestQueryResult, ...]


@dataclass
class _Candidate:
    quest_id: int
    name: str
    quest_level: int | None
    minimum_level: int | None
    state: str
    predicates: tuple[QuestPredicateState, ...]
    detail: dict[str, Any] | None = None


def _validate_nonnegative(name: str, value: int | None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _normalize_states(include_states: Sequence[str]) -> tuple[str, ...]:
    if isinstance(include_states, str):
        raise TypeError("include_states must be a sequence of query states")
    if not include_states:
        raise ValueError("include_states must contain at least one query state")
    invalid = sorted(set(include_states) - set(QUERY_STATES))
    if invalid:
        raise ValueError(f"unsupported query state(s): {', '.join(invalid)}")
    return tuple(state for state in QUERY_STATES if state in include_states)


def _selected_fact(
    connection: sqlite3.Connection,
    *,
    quest_id: int,
    fact_key: str,
    fact_instance_key: str = "",
) -> tuple[object, dict[str, Any]] | None:
    row = connection.execute(
        """
        SELECT cs.observation_id, cs.selection_policy, ds.source_key,
               so.source_revision, so.value_json
        FROM observation_groups AS og
        JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        JOIN source_observations AS so ON so.id = cs.observation_id
        JOIN data_sources AS ds ON ds.id = so.source_id
        WHERE og.subject_kind = 'quest' AND og.subject_key = ?
          AND og.fact_key = ? AND og.fact_instance_key = ?
        """,
        (str(quest_id), fact_key, fact_instance_key),
    ).fetchone()
    if row is None:
        return None
    return (
        json.loads(str(row["value_json"])),
        {
            "source_key": str(row["source_key"]),
            "source_revision": str(row["source_revision"]),
            "observation_id": int(row["observation_id"]),
            "selection_policy": (
                None if row["selection_policy"] is None else str(row["selection_policy"])
            ),
        },
    )


def _selected_endpoint_relations(
    connection: sqlite3.Connection, quest_id: int
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT og.fact_instance_key, cs.observation_id, cs.selection_policy,
               ds.source_key, so.source_revision, so.value_json
        FROM observation_groups AS og
        JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        JOIN source_observations AS so ON so.id = cs.observation_id
        JOIN data_sources AS ds ON ds.id = so.source_id
        WHERE og.subject_kind = 'quest' AND og.subject_key = ?
          AND og.fact_key = 'endpoint'
        ORDER BY og.fact_instance_key
        """,
        (str(quest_id),),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        value = json.loads(str(row["value_json"]))
        if not isinstance(value, dict):
            continue
        target = value.get("target")
        attributes = value.get("attributes")
        if not isinstance(target, dict) or not isinstance(attributes, dict):
            continue
        entity_type = target.get("kind")
        endpoint_kind = attributes.get("endpoint_kind")
        raw_id = target.get("key")
        if entity_type not in {"creature", "gameobject"}:
            continue
        if endpoint_kind not in {"giver", "finisher"}:
            continue
        if isinstance(raw_id, bool):
            continue
        try:
            entity_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if entity_id <= 0:
            continue
        result.append(
            {
                "endpoint_kind": endpoint_kind,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "fact_instance_key": str(row["fact_instance_key"]),
                "selection": {
                    "source_key": str(row["source_key"]),
                    "source_revision": str(row["source_revision"]),
                    "observation_id": int(row["observation_id"]),
                    "selection_policy": (
                        None
                        if row["selection_policy"] is None
                        else str(row["selection_policy"])
                    ),
                },
            }
        )
    return result


def _target_identity_and_locations(
    connection: sqlite3.Connection, *, entity_type: str, entity_id: int
) -> tuple[str | None, list[dict[str, Any]]]:
    if entity_type == "creature":
        identity = connection.execute(
            "SELECT name FROM creatures WHERE creature_id = ?", (entity_id,)
        ).fetchone()
        rows = connection.execute(
            """
            SELECT s.spawn_id, COALESCE(s.map_id, z.map_id) AS map_id, m.name AS map_name,
                   s.zone_id, z.name AS zone_name, s.coordinate_space, s.x, s.y, s.z
            FROM creature_spawns AS s
            LEFT JOIN zones AS z ON z.zone_id = s.zone_id
            LEFT JOIN maps AS m ON m.map_id = COALESCE(s.map_id, z.map_id)
            WHERE s.creature_id = ?
            ORDER BY COALESCE(s.map_id, z.map_id), s.zone_id, s.spawn_id
            """,
            (entity_id,),
        ).fetchall()
    elif entity_type == "gameobject":
        identity = connection.execute(
            "SELECT name FROM gameobjects WHERE gameobject_id = ?", (entity_id,)
        ).fetchone()
        rows = connection.execute(
            """
            SELECT s.spawn_id, COALESCE(s.map_id, z.map_id) AS map_id, m.name AS map_name,
                   s.zone_id, z.name AS zone_name, s.coordinate_space, s.x, s.y, s.z
            FROM gameobject_spawns AS s
            LEFT JOIN zones AS z ON z.zone_id = s.zone_id
            LEFT JOIN maps AS m ON m.map_id = COALESCE(s.map_id, z.map_id)
            WHERE s.gameobject_id = ?
            ORDER BY COALESCE(s.map_id, z.map_id), s.zone_id, s.spawn_id
            """,
            (entity_id,),
        ).fetchall()
    else:
        raise ValueError(f"unsupported endpoint entity type: {entity_type}")
    return (
        None if identity is None else str(identity["name"]),
        [dict(row) for row in rows] if identity is not None else [],
    )


def _materialized_endpoint_keys(detail: dict[str, Any]) -> set[tuple[str, str, int]]:
    return {
        (
            str(endpoint["endpoint_kind"]),
            str(endpoint["entity_type"]),
            int(endpoint["entity_id"]),
        )
        for endpoint in detail.get("endpoints", [])
    }


def _parse_endpoint_set(value: object) -> list[tuple[str, str, int]] | None:
    if not isinstance(value, list):
        return None
    result: set[tuple[str, str, int]] = set()
    for row in value:
        if not isinstance(row, dict):
            return None
        endpoint_kind = row.get("endpoint_kind")
        entity_type = row.get("target_kind")
        entity_id = row.get("target_id")
        if endpoint_kind not in {"giver", "finisher"}:
            return None
        if entity_type not in {"creature", "gameobject"}:
            return None
        if isinstance(entity_id, bool) or not isinstance(entity_id, int) or entity_id <= 0:
            return None
        result.add((endpoint_kind, entity_type, entity_id))
    return sorted(result)


def _enrich_endpoints(
    connection: sqlite3.Connection, *, quest_id: int, detail: dict[str, Any]
) -> None:
    selected_relations = _selected_endpoint_relations(connection, quest_id)
    selected_by_key = {
        (row["endpoint_kind"], row["entity_type"], row["entity_id"]): row
        for row in selected_relations
    }
    materialized = _materialized_endpoint_keys(detail)

    enriched: list[dict[str, Any]] = []
    for endpoint in detail.get("endpoints", []):
        copied = dict(endpoint)
        key = (
            str(copied["endpoint_kind"]),
            str(copied["entity_type"]),
            int(copied["entity_id"]),
        )
        copied["resolved"] = True
        copied["unresolved_reason"] = None
        copied["selection"] = (
            None if key not in selected_by_key else selected_by_key[key]["selection"]
        )
        locations = copied.get("locations", [])
        copied["geography_resolved"] = bool(locations)
        copied["geography_unresolved_reason"] = None if locations else "no_canonical_spawns"
        enriched.append(copied)

    for key, selected in sorted(selected_by_key.items()):
        if key in materialized:
            continue
        endpoint_kind, entity_type, entity_id = key
        name, locations = _target_identity_and_locations(
            connection, entity_type=entity_type, entity_id=entity_id
        )
        enriched.append(
            {
                "endpoint_kind": endpoint_kind,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "entity_name": name,
                "resolved": False,
                "unresolved_reason": (
                    f"missing_{entity_type}_identity"
                    if name is None
                    else "primitive_relation_not_materialized"
                ),
                "locations": locations,
                "geography_resolved": bool(locations),
                "geography_unresolved_reason": (
                    None
                    if locations
                    else ("missing_identity" if name is None else "no_canonical_spawns")
                ),
                "selection": selected["selection"],
            }
        )

    enriched.sort(
        key=lambda row: (row["endpoint_kind"], row["entity_type"], row["entity_id"])
    )
    detail["endpoints"] = enriched

    set_selection = _selected_fact(
        connection, quest_id=quest_id, fact_key="quest_endpoint_set"
    )
    if set_selection is None:
        for endpoint in enriched:
            endpoint["selected_by_complete_set"] = None
        detail["endpoint_set"] = {
            "declared": False,
            "selected_member_count": None,
            "materialized_selected_member_count": None,
            "is_complete": None,
            "unresolved_members": [],
            "provenance": None,
        }
        return
    value, provenance = set_selection
    selected_keys = _parse_endpoint_set(value)
    if selected_keys is None:
        raise TypeError(f"selected quest_endpoint_set for quest {quest_id} has invalid shape")
    selected_key_set = set(selected_keys)
    for endpoint in enriched:
        endpoint["selected_by_complete_set"] = (
            endpoint["endpoint_kind"], endpoint["entity_type"], endpoint["entity_id"]
        ) in selected_key_set
    unresolved = [
        {
            "endpoint_kind": endpoint_kind,
            "entity_type": entity_type,
            "entity_id": entity_id,
        }
        for endpoint_kind, entity_type, entity_id in selected_keys
        if (endpoint_kind, entity_type, entity_id) not in materialized
    ]
    detail["endpoint_set"] = {
        "declared": True,
        "selected_member_count": len(selected_keys),
        "materialized_selected_member_count": len(selected_keys) - len(unresolved),
        "is_complete": not unresolved,
        "unresolved_members": unresolved,
        "provenance": provenance,
    }


def _parse_selected_id_set(value: object, *, fact_key: str, quest_id: int) -> list[int]:
    if not isinstance(value, list):
        raise TypeError(f"selected {fact_key} for quest {quest_id} must be an ID list")
    result: set[int] = set()
    for member_id in value:
        if isinstance(member_id, bool) or not isinstance(member_id, int) or member_id <= 0:
            raise TypeError(f"selected {fact_key} for quest {quest_id} contains invalid ID")
        result.add(member_id)
    return sorted(result)


def _enrich_progression_set(
    connection: sqlite3.Connection,
    *,
    quest_id: int,
    set_model: dict[str, Any],
    set_fact_key: str,
    relation_fact_key: str,
) -> None:
    selection = _selected_fact(connection, quest_id=quest_id, fact_key=set_fact_key)
    if selection is None:
        set_model["selected_member_ids"] = None
        set_model["selected_materialized_member_count"] = None
        set_model["unresolved_members"] = []
        return
    value, _ = selection
    selected_ids = _parse_selected_id_set(value, fact_key=set_fact_key, quest_id=quest_id)
    materialized_ids = {int(member["quest_id"]) for member in set_model.get("members", [])}
    unresolved: list[dict[str, Any]] = []
    for member_id in selected_ids:
        primitive = _selected_fact(
            connection,
            quest_id=quest_id,
            fact_key=relation_fact_key,
            fact_instance_key=str(member_id),
        )
        target = connection.execute(
            "SELECT name FROM quests WHERE quest_id = ?", (member_id,)
        ).fetchone()
        if member_id not in materialized_ids:
            unresolved.append(
                {
                    "quest_id": member_id,
                    "name": None if target is None else str(target["name"]),
                    "reason": (
                        "missing_quest_identity"
                        if target is None
                        else "primitive_relation_not_materialized"
                    ),
                    "selection": None if primitive is None else primitive[1],
                }
            )
    for member in set_model.get("members", []):
        member_id = int(member["quest_id"])
        primitive = _selected_fact(
            connection,
            quest_id=quest_id,
            fact_key=relation_fact_key,
            fact_instance_key=str(member_id),
        )
        member["selected_by_complete_set"] = member_id in selected_ids
        member["selection"] = None if primitive is None else primitive[1]
    set_model["selected_member_ids"] = selected_ids
    set_model["selected_materialized_member_count"] = sum(
        1 for member_id in selected_ids if member_id in materialized_ids
    )
    set_model["unresolved_members"] = unresolved


def _quest_detail(connection: sqlite3.Connection, quest_id: int) -> dict[str, Any] | None:
    detail = quest_by_id(connection, quest_id)
    if detail is None:
        return None
    _enrich_endpoints(connection, quest_id=quest_id, detail=detail)
    progression = detail["progression"]
    _enrich_progression_set(
        connection,
        quest_id=quest_id,
        set_model=progression["prerequisite_set"],
        set_fact_key="quest_prerequisite_set",
        relation_fact_key="prerequisite",
    )
    _enrich_progression_set(
        connection,
        quest_id=quest_id,
        set_model=progression["close_set"],
        set_fact_key="quest_close_set",
        relation_fact_key="close_group_member",
    )
    for follow_up in progression.get("follow_ups", []):
        reverse_selection = _selected_fact(
            connection,
            quest_id=int(follow_up["quest_id"]),
            fact_key="prerequisite",
            fact_instance_key=str(quest_id),
        )
        follow_up["selection"] = (
            None if reverse_selection is None else reverse_selection[1]
        )
    name_selection = _selected_fact(connection, quest_id=quest_id, fact_key="name")
    detail["identity_provenance"] = None if name_selection is None else name_selection[1]
    return detail


def _known_predicate(
    predicate: str, matches: bool, actual: object, reason: str
) -> QuestPredicateState:
    return QuestPredicateState(
        predicate=predicate,
        state=MATCH_KNOWN if matches else NON_MATCH_KNOWN,
        actual=actual,
        reason=reason,
    )


def _unknown_predicate(predicate: str, reason: str) -> QuestPredicateState:
    return QuestPredicateState(
        predicate=predicate,
        state=MATCH_UNKNOWN,
        actual=None,
        reason=reason,
    )


def _combined_state(predicates: Sequence[QuestPredicateState]) -> str:
    if any(predicate.state == NON_MATCH_KNOWN for predicate in predicates):
        return NON_MATCH_KNOWN
    if any(predicate.state == MATCH_UNKNOWN for predicate in predicates):
        return MATCH_UNKNOWN
    return MATCH_KNOWN


def _scalar_predicates(
    row: sqlite3.Row,
    *,
    quest_id: int | None,
    title_contains: str | None,
    min_quest_level: int | None,
    max_quest_level: int | None,
    min_minimum_level: int | None,
    max_minimum_level: int | None,
) -> list[QuestPredicateState]:
    predicates: list[QuestPredicateState] = []
    row_id = int(row["quest_id"])
    row_name = str(row["name"])
    if quest_id is not None:
        predicates.append(
            _known_predicate(
                f"quest_id={quest_id}",
                row_id == quest_id,
                row_id,
                "canonical_quest_identity",
            )
        )
    if title_contains is not None:
        predicates.append(
            _known_predicate(
                f"title_contains={title_contains!r}",
                title_contains.casefold() in row_name.casefold(),
                row_name,
                "canonical_quest_title",
            )
        )

    for field, minimum, maximum in (
        ("quest_level", min_quest_level, max_quest_level),
        ("minimum_level", min_minimum_level, max_minimum_level),
    ):
        actual = row[field]
        if minimum is not None:
            label = f"{field}>={minimum}"
            if actual is None:
                predicates.append(_unknown_predicate(label, f"{field}_not_materialized"))
            else:
                predicates.append(
                    _known_predicate(label, int(actual) >= minimum, int(actual), "known_scalar")
                )
        if maximum is not None:
            label = f"{field}<={maximum}"
            if actual is None:
                predicates.append(_unknown_predicate(label, f"{field}_not_materialized"))
            else:
                predicates.append(
                    _known_predicate(label, int(actual) <= maximum, int(actual), "known_scalar")
                )
    return predicates


def _location_matches(location: dict[str, Any], zone_id: int | None, map_id: int | None) -> bool:
    if zone_id is not None and location.get("zone_id") != zone_id:
        return False
    return map_id is None or location.get("map_id") == map_id


def _endpoint_locations(detail: dict[str, Any], endpoint_kind: str) -> list[dict[str, Any]]:
    return [
        dict(location)
        for endpoint in detail.get("endpoints", [])
        if endpoint.get("endpoint_kind") == endpoint_kind
        and (
            endpoint.get("resolved") is True
            or endpoint.get("selected_by_complete_set") is not False
        )
        for location in endpoint.get("locations", [])
    ]


def _objective_locations(detail: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    objective_view = detail.get("objectives")
    if not isinstance(objective_view, dict):
        return result
    for objective in objective_view.get("objectives", []):
        subtype = objective.get("source_subtype")
        if subtype in {"U", "O"}:
            result.extend(dict(location) for location in objective.get("locations", []))
        elif subtype == "A":
            area = objective.get("area_trigger")
            if isinstance(area, dict):
                result.extend(dict(location) for location in area.get("locations", []))
        elif subtype == "Z":
            zone = objective.get("zone")
            if isinstance(zone, dict):
                result.append(
                    {
                        "zone_id": zone.get("zone_id"),
                        "zone_name": zone.get("zone_name"),
                        "map_id": zone.get("map_id"),
                        "map_name": zone.get("map_name"),
                    }
                )
        elif subtype == "IR":
            item_use = objective.get("item_use_targets")
            if isinstance(item_use, dict):
                for target in item_use.get("targets", []):
                    result.extend(dict(location) for location in target.get("locations", []))
    return result


def _geography_predicate(
    *,
    role: str,
    locations: Sequence[dict[str, Any]],
    zone_id: int | None,
    map_id: int | None,
) -> QuestPredicateState | None:
    if zone_id is None and map_id is None:
        return None
    parts = []
    if zone_id is not None:
        parts.append(f"zone={zone_id}")
    if map_id is not None:
        parts.append(f"map={map_id}")
    label = f"{role}_geography[{','.join(parts)}]"
    if any(_location_matches(location, zone_id, map_id) for location in locations):
        return QuestPredicateState(
            predicate=label,
            state=MATCH_KNOWN,
            actual={"known_location_count": len(locations)},
            reason=f"known_matching_{role}_location",
        )
    return _unknown_predicate(label, f"no_known_matching_{role}_location_negative_not_proven")


def _sort_candidates(
    candidates: list[_Candidate], *, sort_by: str, descending: bool
) -> list[_Candidate]:
    if sort_by == "name":
        return sorted(
            candidates,
            key=lambda candidate: (candidate.name.casefold(), candidate.quest_id),
            reverse=descending,
        )
    if sort_by == "quest_id":
        return sorted(candidates, key=lambda candidate: candidate.quest_id, reverse=descending)
    known = [candidate for candidate in candidates if getattr(candidate, sort_by) is not None]
    unknown = [candidate for candidate in candidates if getattr(candidate, sort_by) is None]
    known.sort(
        key=lambda candidate: (getattr(candidate, sort_by), candidate.quest_id),
        reverse=descending,
    )
    unknown.sort(key=lambda candidate: candidate.quest_id)
    return known + unknown


def query_quests(
    connection: sqlite3.Connection,
    *,
    quest_id: int | None = None,
    title_contains: str | None = None,
    min_quest_level: int | None = None,
    max_quest_level: int | None = None,
    min_minimum_level: int | None = None,
    max_minimum_level: int | None = None,
    giver_zone_id: int | None = None,
    giver_map_id: int | None = None,
    finisher_zone_id: int | None = None,
    finisher_map_id: int | None = None,
    objective_zone_id: int | None = None,
    objective_map_id: int | None = None,
    include_states: Sequence[str] = (MATCH_KNOWN,),
    sort_by: str = "quest_id",
    descending: bool = False,
    limit: int = 100,
) -> QuestQueryPage:
    """Search the canonical quest universe with conservative relation-specific geography filters."""

    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    if sort_by not in QUEST_QUERY_SORT_FIELDS:
        raise ValueError(f"unsupported sort field: {sort_by}")
    if not isinstance(descending, bool):
        raise TypeError("descending must be a boolean")
    for name, value in (
        ("quest_id", quest_id),
        ("min_quest_level", min_quest_level),
        ("max_quest_level", max_quest_level),
        ("min_minimum_level", min_minimum_level),
        ("max_minimum_level", max_minimum_level),
        ("giver_zone_id", giver_zone_id),
        ("giver_map_id", giver_map_id),
        ("finisher_zone_id", finisher_zone_id),
        ("finisher_map_id", finisher_map_id),
        ("objective_zone_id", objective_zone_id),
        ("objective_map_id", objective_map_id),
    ):
        _validate_nonnegative(name, value)
    for low_name, low, high_name, high in (
        ("min_quest_level", min_quest_level, "max_quest_level", max_quest_level),
        (
            "min_minimum_level",
            min_minimum_level,
            "max_minimum_level",
            max_minimum_level,
        ),
    ):
        if low is not None and high is not None and low > high:
            raise ValueError(f"{low_name} must not exceed {high_name}")
    if title_contains is not None:
        if not isinstance(title_contains, str):
            raise TypeError("title_contains must be a string")
        title_contains = title_contains.strip()
        if not title_contains:
            raise ValueError("title_contains must not be empty")
    states = _normalize_states(include_states)

    rows = connection.execute(
        """
        SELECT quest_id, name, quest_level, minimum_level
        FROM quests
        ORDER BY quest_id
        """
    ).fetchall()
    geography_active = any(
        value is not None
        for value in (
            giver_zone_id,
            giver_map_id,
            finisher_zone_id,
            finisher_map_id,
            objective_zone_id,
            objective_map_id,
        )
    )
    candidates: list[_Candidate] = []
    state_counts = {state: 0 for state in QUERY_STATES}
    for row in rows:
        predicates = _scalar_predicates(
            row,
            quest_id=quest_id,
            title_contains=title_contains,
            min_quest_level=min_quest_level,
            max_quest_level=max_quest_level,
            min_minimum_level=min_minimum_level,
            max_minimum_level=max_minimum_level,
        )
        detail: dict[str, Any] | None = None
        if geography_active and not any(
            predicate.state == NON_MATCH_KNOWN for predicate in predicates
        ):
            detail = _quest_detail(connection, int(row["quest_id"]))
            if detail is None:
                raise RuntimeError(f"quest {row['quest_id']} disappeared during query")
            for predicate in (
                _geography_predicate(
                    role="giver",
                    locations=_endpoint_locations(detail, "giver"),
                    zone_id=giver_zone_id,
                    map_id=giver_map_id,
                ),
                _geography_predicate(
                    role="finisher",
                    locations=_endpoint_locations(detail, "finisher"),
                    zone_id=finisher_zone_id,
                    map_id=finisher_map_id,
                ),
                _geography_predicate(
                    role="objective",
                    locations=_objective_locations(detail),
                    zone_id=objective_zone_id,
                    map_id=objective_map_id,
                ),
            ):
                if predicate is not None:
                    predicates.append(predicate)
        state = _combined_state(predicates)
        state_counts[state] += 1
        candidates.append(
            _Candidate(
                quest_id=int(row["quest_id"]),
                name=str(row["name"]),
                quest_level=None if row["quest_level"] is None else int(row["quest_level"]),
                minimum_level=(
                    None if row["minimum_level"] is None else int(row["minimum_level"])
                ),
                state=state,
                predicates=tuple(predicates),
                detail=detail,
            )
        )

    ordered = _sort_candidates(candidates, sort_by=sort_by, descending=descending)
    selected = [candidate for candidate in ordered if candidate.state in states][:limit]
    results: list[QuestQueryResult] = []
    for candidate in selected:
        detail = candidate.detail or _quest_detail(connection, candidate.quest_id)
        if detail is None:
            raise RuntimeError(f"quest {candidate.quest_id} disappeared during query")
        results.append(
            QuestQueryResult(
                quest=detail,
                match_state=candidate.state,
                predicates=candidate.predicates,
            )
        )
    return QuestQueryPage(
        summary=QuestQuerySummary(
            total_quest_identities=len(rows),
            known_match_count=state_counts[MATCH_KNOWN],
            known_non_match_count=state_counts[NON_MATCH_KNOWN],
            unknown_count=state_counts[MATCH_UNKNOWN],
            returned_count=len(results),
            limit=limit,
        ),
        results=tuple(results),
    )


def quest_query_page_to_dict(page: QuestQueryPage) -> dict[str, Any]:
    return {
        "summary": asdict(page.summary),
        "results": [
            {
                "match_state": result.match_state,
                "predicates": [asdict(predicate) for predicate in result.predicates],
                "quest": result.quest,
            }
            for result in page.results
        ],
    }


def _traversal_neighbors(
    detail: dict[str, Any], direction: str
) -> tuple[list[dict[str, Any]], bool]:
    progression = detail["progression"]
    if direction == "prerequisite":
        prerequisite = progression["prerequisite_set"]
        selected_ids = prerequisite.get("selected_member_ids")
        if selected_ids is None:
            selected_ids = [member["quest_id"] for member in prerequisite.get("members", [])]
        materialized = {
            int(member["quest_id"]): member for member in prerequisite.get("members", [])
        }
        unresolved = {
            int(member["quest_id"]): member for member in prerequisite.get("unresolved_members", [])
        }
        neighbors = []
        for target_id in sorted(int(member_id) for member_id in selected_ids):
            member = materialized.get(target_id)
            missing = unresolved.get(target_id)
            neighbors.append(
                {
                    "quest_id": target_id,
                    "name": None if member is None else member.get("name"),
                    "resolved": member is not None,
                    "unresolved_reason": None if missing is None else missing.get("reason"),
                    "selection": (
                        member.get("selection")
                        if member is not None
                        else (None if missing is None else missing.get("selection"))
                    ),
                }
            )
        selected_materialized = prerequisite.get("selected_materialized_member_count")
        if selected_ids is not None and selected_materialized is not None:
            incomplete = int(selected_materialized) != len(selected_ids)
        else:
            incomplete = not bool(prerequisite.get("is_complete", True))
        return neighbors, incomplete

    neighbors = [
        {
            "quest_id": int(member["quest_id"]),
            "name": str(member["name"]),
            "resolved": True,
            "unresolved_reason": None,
            "selection": member.get("selection"),
        }
        for member in progression.get("follow_ups", [])
    ]
    neighbors.sort(key=lambda row: row["quest_id"])
    return neighbors, False


def traverse_quest_progression(
    connection: sqlite3.Connection,
    quest_id: int,
    *,
    direction: str = "prerequisite",
    max_depth: int = 5,
    max_nodes: int = 100,
) -> dict[str, Any] | None:
    """Traverse selected prerequisite or derived follow-up edges with explicit ambiguity/cycles."""

    _validate_nonnegative("quest_id", quest_id)
    if quest_id <= 0:
        raise ValueError("quest_id must be positive")
    if direction not in TRAVERSAL_DIRECTIONS:
        raise ValueError(f"unsupported traversal direction: {direction}")
    if isinstance(max_depth, bool) or not isinstance(max_depth, int):
        raise TypeError("max_depth must be an integer")
    if max_depth < 0 or max_depth > 20:
        raise ValueError("max_depth must be between 0 and 20")
    if isinstance(max_nodes, bool) or not isinstance(max_nodes, int):
        raise TypeError("max_nodes must be an integer")
    if max_nodes < 1 or max_nodes > 500:
        raise ValueError("max_nodes must be between 1 and 500")

    root = _quest_detail(connection, quest_id)
    if root is None:
        return None
    nodes: dict[int, dict[str, Any]] = {
        quest_id: {"quest_id": quest_id, "name": root["name"], "depth": 0}
    }
    queue: deque[tuple[int, int, tuple[int, ...]]] = deque([(quest_id, 0, (quest_id,))])
    visited = {quest_id}
    edges: list[dict[str, Any]] = []
    unresolved_target_ids: set[int] = set()
    incomplete_quest_ids: set[int] = set()
    ambiguous_quest_ids: set[int] = set()
    cycle_edges = 0
    truncated = False

    while queue:
        current_id, depth, path = queue.popleft()
        detail = root if current_id == quest_id else _quest_detail(connection, current_id)
        if detail is None:
            unresolved_target_ids.add(current_id)
            continue
        neighbors, incomplete = _traversal_neighbors(detail, direction)
        if incomplete:
            incomplete_quest_ids.add(current_id)
        if len(neighbors) > 1:
            ambiguous_quest_ids.add(current_id)
        if depth >= max_depth:
            if neighbors:
                truncated = True
            continue
        for neighbor in neighbors:
            target_id = int(neighbor["quest_id"])
            cycle = target_id in path
            if cycle:
                cycle_edges += 1
            edge = {
                "from_quest_id": current_id,
                "to_quest_id": target_id,
                "depth": depth + 1,
                "direction": direction,
                "relation_semantics": (
                    "any_of_prerequisite_member"
                    if direction == "prerequisite"
                    else "derived_reverse_of_any_of_prerequisite_member"
                ),
                "target_resolved": bool(neighbor["resolved"]),
                "unresolved_reason": neighbor["unresolved_reason"],
                "cycle": cycle,
                "selection": neighbor["selection"],
            }
            edges.append(edge)
            if not neighbor["resolved"]:
                unresolved_target_ids.add(target_id)
                continue
            if cycle or target_id in visited:
                continue
            if len(nodes) >= max_nodes:
                truncated = True
                continue
            visited.add(target_id)
            nodes[target_id] = {
                "quest_id": target_id,
                "name": neighbor["name"],
                "depth": depth + 1,
            }
            queue.append((target_id, depth + 1, (*path, target_id)))

    ordered_nodes = sorted(nodes.values(), key=lambda row: (row["depth"], row["quest_id"]))
    edges.sort(
        key=lambda row: (
            row["depth"],
            row["from_quest_id"],
            row["to_quest_id"],
            row["direction"],
        )
    )
    ambiguous = bool(
        ambiguous_quest_ids
        or incomplete_quest_ids
        or unresolved_target_ids
        or cycle_edges
        or truncated
    )
    return {
        "root_quest_id": quest_id,
        "direction": direction,
        "max_depth": max_depth,
        "max_nodes": max_nodes,
        "derivation": (
            "breadth_first_shortest_edge_distance_over_selected_any_of_prerequisite_members"
            if direction == "prerequisite"
            else (
                "breadth_first_shortest_edge_distance_over_materialized_reverse_"
                "prerequisite_membership"
            )
        ),
        "depth_is_chain_step": False,
        "close_sets_traversed": False,
        "ambiguous": ambiguous,
        "ambiguous_quest_ids": sorted(ambiguous_quest_ids),
        "incomplete_quest_ids": sorted(incomplete_quest_ids),
        "unresolved_target_ids": sorted(unresolved_target_ids),
        "cycle_edge_count": cycle_edges,
        "truncated": truncated,
        "nodes": ordered_nodes,
        "edges": edges,
    }
