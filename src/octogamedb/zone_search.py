"""Provenance-aware read-only zone-centric exploration for P7-T06."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from octogamedb.zone_recipe_projection import project_zone_recipes
from octogamedb.world_entity_search import query_world_entities, world_entity_query_page_to_dict

MATCH_KNOWN = "known_match"
NON_MATCH_KNOWN = "known_non_match"
MATCH_UNKNOWN = "unknown"
QUERY_STATES = (MATCH_KNOWN, NON_MATCH_KNOWN, MATCH_UNKNOWN)
ZONE_QUERY_SORT_FIELDS = ("zone_id", "name", "map_id", "map_name")


@dataclass(frozen=True)
class ZonePredicateState:
    predicate: str
    state: str
    actual: object | None
    reason: str


@dataclass(frozen=True)
class ZoneQueryResult:
    zone: dict[str, Any]
    match_state: str
    predicates: tuple[ZonePredicateState, ...]


@dataclass(frozen=True)
class ZoneQuerySummary:
    total_zone_identities: int
    known_match_count: int
    known_non_match_count: int
    unknown_count: int
    returned_count: int
    limit: int


@dataclass(frozen=True)
class ZoneQueryPage:
    summary: ZoneQuerySummary
    results: tuple[ZoneQueryResult, ...]


@dataclass(frozen=True)
class _ZoneCandidate:
    row: sqlite3.Row
    state: str
    predicates: tuple[ZonePredicateState, ...]


def _validate_nonnegative(name: str, value: int | None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _validate_limit(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 1 or value > 1000:
        raise ValueError(f"{name} must be between 1 and 1000")


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


def _known_predicate(
    predicate: str, matches: bool, actual: object, reason: str
) -> ZonePredicateState:
    return ZonePredicateState(
        predicate=predicate,
        state=MATCH_KNOWN if matches else NON_MATCH_KNOWN,
        actual=actual,
        reason=reason,
    )


def _unknown_predicate(
    predicate: str, reason: str, actual: object | None = None
) -> ZonePredicateState:
    return ZonePredicateState(
        predicate=predicate,
        state=MATCH_UNKNOWN,
        actual=actual,
        reason=reason,
    )


def _combined_state(predicates: Sequence[ZonePredicateState]) -> str:
    if any(predicate.state == NON_MATCH_KNOWN for predicate in predicates):
        return NON_MATCH_KNOWN
    if any(predicate.state == MATCH_UNKNOWN for predicate in predicates):
        return MATCH_UNKNOWN
    return MATCH_KNOWN


def _selected_provenance(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_key: str | int,
    fact_key: str,
) -> dict[str, Any] | None:
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
          AND og.fact_key = ? AND og.fact_instance_key = ''
        """,
        (subject_kind, str(subject_key), fact_key),
    ).fetchone()
    if row is None:
        return None
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


def _zone_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT z.zone_id, z.name, z.map_id, z.parent_zone_id,
               parent.name AS parent_zone_name,
               m.name AS map_name, m.map_kind, m.parent_map_id,
               parent_map.name AS parent_map_name
        FROM zones AS z
        LEFT JOIN zones AS parent ON parent.zone_id = z.parent_zone_id
        LEFT JOIN maps AS m ON m.map_id = z.map_id
        LEFT JOIN maps AS parent_map ON parent_map.map_id = m.parent_map_id
        ORDER BY z.zone_id
        """
    ).fetchall()


def _evaluate_zone(
    row: sqlite3.Row,
    *,
    zone_id: int | None,
    name_contains: str | None,
    map_id: int | None,
    map_name_contains: str | None,
) -> tuple[str, tuple[ZonePredicateState, ...]]:
    predicates: list[ZonePredicateState] = []
    current_zone_id = int(row["zone_id"])
    current_name = str(row["name"])
    current_map_id = None if row["map_id"] is None else int(row["map_id"])
    current_map_name = None if row["map_name"] is None else str(row["map_name"])

    if zone_id is not None:
        predicates.append(
            _known_predicate(
                f"zone_id={zone_id}",
                current_zone_id == zone_id,
                current_zone_id,
                "canonical_zone_identity",
            )
        )
    if name_contains is not None:
        predicates.append(
            _known_predicate(
                f"name_contains={name_contains!r}",
                name_contains.casefold() in current_name.casefold(),
                current_name,
                "canonical_zone_name",
            )
        )
    if map_id is not None:
        if current_map_id is None:
            predicates.append(
                _unknown_predicate(
                    f"map_id={map_id}",
                    "zone_map_identity_not_materialized",
                )
            )
        else:
            predicates.append(
                _known_predicate(
                    f"map_id={map_id}",
                    current_map_id == map_id,
                    current_map_id,
                    "canonical_zone_map_identity",
                )
            )
    if map_name_contains is not None:
        if current_map_name is None:
            predicates.append(
                _unknown_predicate(
                    f"map_name_contains={map_name_contains!r}",
                    "zone_map_name_not_materialized",
                    current_map_id,
                )
            )
        else:
            predicates.append(
                _known_predicate(
                    f"map_name_contains={map_name_contains!r}",
                    map_name_contains.casefold() in current_map_name.casefold(),
                    current_map_name,
                    "canonical_map_name",
                )
            )
    frozen = tuple(predicates)
    return _combined_state(frozen), frozen


def _zone_identity(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    zone_id = int(row["zone_id"])
    map_id = None if row["map_id"] is None else int(row["map_id"])
    return {
        "zone_id": zone_id,
        "name": str(row["name"]),
        "parent_zone": {
            "zone_id": None if row["parent_zone_id"] is None else int(row["parent_zone_id"]),
            "name": None if row["parent_zone_name"] is None else str(row["parent_zone_name"]),
        },
        "map": {
            "map_id": map_id,
            "name": None if row["map_name"] is None else str(row["map_name"]),
            "map_kind": None if row["map_kind"] is None else str(row["map_kind"]),
            "parent_map_id": (
                None if row["parent_map_id"] is None else int(row["parent_map_id"])
            ),
            "parent_map_name": (
                None if row["parent_map_name"] is None else str(row["parent_map_name"])
            ),
        },
        "provenance": {
            "zone_name": _selected_provenance(
                connection, subject_kind="zone", subject_key=zone_id, fact_key="name"
            ),
            "map_name": (
                None
                if map_id is None
                else _selected_provenance(
                    connection, subject_kind="map", subject_key=map_id, fact_key="name"
                )
            ),
        },
    }


def _sort_candidates(
    candidates: list[_ZoneCandidate], *, sort_by: str, descending: bool
) -> list[_ZoneCandidate]:
    if sort_by == "zone_id":
        return sorted(candidates, key=lambda c: int(c.row["zone_id"]), reverse=descending)
    if sort_by == "name":
        return sorted(
            candidates,
            key=lambda c: (str(c.row["name"]).casefold(), int(c.row["zone_id"])),
            reverse=descending,
        )
    if sort_by == "map_id":
        known = [candidate for candidate in candidates if candidate.row["map_id"] is not None]
        unknown = [candidate for candidate in candidates if candidate.row["map_id"] is None]
        known.sort(
            key=lambda c: (int(c.row["map_id"]), int(c.row["zone_id"])),
            reverse=descending,
        )
        unknown.sort(key=lambda c: int(c.row["zone_id"]))
        return known + unknown
    known = [candidate for candidate in candidates if candidate.row["map_name"] is not None]
    unknown = [candidate for candidate in candidates if candidate.row["map_name"] is None]
    known.sort(
        key=lambda c: (str(c.row["map_name"]).casefold(), int(c.row["zone_id"])),
        reverse=descending,
    )
    unknown.sort(key=lambda c: int(c.row["zone_id"]))
    return known + unknown


def query_zones(
    connection: sqlite3.Connection,
    *,
    zone_id: int | None = None,
    name_contains: str | None = None,
    map_id: int | None = None,
    map_name_contains: str | None = None,
    include_states: Sequence[str] = (MATCH_KNOWN,),
    sort_by: str = "zone_id",
    descending: bool = False,
    limit: int = 100,
) -> ZoneQueryPage:
    """Search canonical zones/maps without flattening hierarchy or derived contents."""

    _validate_nonnegative("zone_id", zone_id)
    _validate_nonnegative("map_id", map_id)
    normalized_name = _normalize_text("name_contains", name_contains)
    normalized_map_name = _normalize_text("map_name_contains", map_name_contains)
    states = _normalize_states(include_states)
    if sort_by not in ZONE_QUERY_SORT_FIELDS:
        raise ValueError(f"unsupported sort field: {sort_by}")
    if not isinstance(descending, bool):
        raise TypeError("descending must be a boolean")
    _validate_limit("limit", limit)

    rows = _zone_rows(connection)
    counts = {state: 0 for state in QUERY_STATES}
    candidates: list[_ZoneCandidate] = []
    for row in rows:
        state, predicates = _evaluate_zone(
            row,
            zone_id=zone_id,
            name_contains=normalized_name,
            map_id=map_id,
            map_name_contains=normalized_map_name,
        )
        counts[state] += 1
        if state in states:
            candidates.append(_ZoneCandidate(row=row, state=state, predicates=predicates))

    selected = _sort_candidates(candidates, sort_by=sort_by, descending=descending)[:limit]
    results = tuple(
        ZoneQueryResult(
            zone=_zone_identity(connection, candidate.row),
            match_state=candidate.state,
            predicates=candidate.predicates,
        )
        for candidate in selected
    )
    return ZoneQueryPage(
        summary=ZoneQuerySummary(
            total_zone_identities=len(rows),
            known_match_count=counts[MATCH_KNOWN],
            known_non_match_count=counts[NON_MATCH_KNOWN],
            unknown_count=counts[MATCH_UNKNOWN],
            returned_count=len(results),
            limit=limit,
        ),
        results=results,
    )


def zone_query_page_to_dict(page: ZoneQueryPage) -> dict[str, Any]:
    """Return a stable JSON-friendly representation of a zone identity query."""

    return {
        "summary": asdict(page.summary),
        "results": [
            {
                "match_state": result.match_state,
                "predicates": [asdict(predicate) for predicate in result.predicates],
                "zone": result.zone,
            }
            for result in page.results
        ],
    }


def _matching_zone_spawns(entity: Mapping[str, Any], zone_id: int) -> list[dict[str, Any]]:
    return [
        dict(spawn)
        for spawn in entity.get("spawns", [])
        if isinstance(spawn, Mapping) and spawn.get("zone_id") == zone_id
    ]


def _project_zone_entities(world_payload: Mapping[str, Any], zone_id: int) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for result in world_payload.get("results", []):
        if not isinstance(result, Mapping):
            continue
        entity = result.get("entity")
        if not isinstance(entity, Mapping):
            continue
        matching_spawns = _matching_zone_spawns(entity, zone_id)
        if not matching_spawns:
            raise RuntimeError("P7-T05 known zone match returned no concrete matching spawn")
        projected.append(
            {
                "entity_kind": str(entity["entity_kind"]),
                "entity_id": int(entity["entity_id"]),
                "name": str(entity["name"]),
                "template": entity.get("template"),
                "template_provenance": entity.get("template_provenance"),
                "world_presence": entity.get("world_presence"),
                "matching_spawns": matching_spawns,
                "all_materialized_spawn_count": len(entity.get("spawns", [])),
                "spawn_set": entity.get("spawn_set"),
                "roles": entity.get("roles", {}),
                "geography_state": MATCH_KNOWN,
                "geography_reason": "known_concrete_canonical_spawn_in_zone",
                "entity_detail_owner": "P7-T05",
            }
        )
    return projected


def _collect_item_acquisition(entities: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    items: dict[int, dict[str, Any]] = {}
    path_order = {"direct": 0, "reference": 1, "vendor": 2}
    for entity in entities:
        roles = entity.get("roles")
        if not isinstance(roles, Mapping):
            continue
        for item in roles.get("item_acquisition", []):
            if not isinstance(item, Mapping):
                continue
            item_id = int(item["item_id"])
            target = items.setdefault(
                item_id,
                {
                    "item_id": item_id,
                    "item_name": item.get("item_name"),
                    "paths": [],
                    "item_detail_owner": "P7-T02",
                },
            )
            for path in item.get("acquisition_paths", []):
                if not isinstance(path, Mapping):
                    continue
                target["paths"].append(
                    {
                        **dict(path),
                        "source": {
                            "entity_kind": entity["entity_kind"],
                            "entity_id": entity["entity_id"],
                            "name": entity["name"],
                        },
                        "matching_spawns": list(entity["matching_spawns"]),
                        "geography_state": MATCH_KNOWN,
                        "geography_reason": "known_acquisition_source_spawn_in_zone",
                    }
                )
    for item in items.values():
        item["paths"].sort(
            key=lambda path: (
                path_order.get(str(path.get("path_kind")), 99),
                str(path["source"]["entity_kind"]),
                int(path["source"]["entity_id"]),
                -1 if path.get("reference_loot_id") is None else int(path["reference_loot_id"]),
            )
        )
    return [items[item_id] for item_id in sorted(items)]


def _collect_quests(entities: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {
        "given": [],
        "finished": [],
        "objectives": [],
    }
    role_key = {"giver": "given", "finisher": "finished", "objective": "objectives"}
    for entity in entities:
        roles = entity.get("roles")
        if not isinstance(roles, Mapping):
            continue
        for quest in roles.get("quests", []):
            if not isinstance(quest, Mapping):
                continue
            role = str(quest["role"])
            bucket = role_key.get(role)
            if bucket is None:
                raise RuntimeError(f"unsupported P7-T05 quest role: {role}")
            result[bucket].append(
                {
                    **dict(quest),
                    "source": {
                        "entity_kind": entity["entity_kind"],
                        "entity_id": entity["entity_id"],
                        "name": entity["name"],
                    },
                    "matching_spawns": list(entity["matching_spawns"]),
                    "geography_state": MATCH_KNOWN,
                    "geography_reason": "known_quest_role_source_spawn_in_zone",
                }
            )
    for rows in result.values():
        rows.sort(
            key=lambda row: (
                int(row["quest_id"]),
                str(row["source"]["entity_kind"]),
                int(row["source"]["entity_id"]),
            )
        )
    return result


def _collect_vendors(entities: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    vendors: dict[int, dict[str, Any]] = {}
    for entity in entities:
        if entity.get("entity_kind") != "creature":
            continue
        roles = entity.get("roles")
        if not isinstance(roles, Mapping):
            continue
        for item in roles.get("item_acquisition", []):
            if not isinstance(item, Mapping):
                continue
            vendor_paths = [
                dict(path)
                for path in item.get("acquisition_paths", [])
                if isinstance(path, Mapping) and path.get("path_kind") == "vendor"
            ]
            if not vendor_paths:
                continue
            entity_id = int(entity["entity_id"])
            vendor = vendors.setdefault(
                entity_id,
                {
                    "creature_id": entity_id,
                    "name": entity["name"],
                    "matching_spawns": list(entity["matching_spawns"]),
                    "items": [],
                    "geography_state": MATCH_KNOWN,
                    "geography_reason": "known_vendor_creature_spawn_in_zone",
                },
            )
            vendor["items"].append(
                {
                    "item_id": int(item["item_id"]),
                    "item_name": item.get("item_name"),
                    "paths": vendor_paths,
                }
            )
    for vendor in vendors.values():
        vendor["items"].sort(key=lambda item: int(item["item_id"]))
    return [vendors[entity_id] for entity_id in sorted(vendors)]


def _collect_trainers(entities: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    known: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    for entity in entities:
        if entity.get("entity_kind") != "creature":
            continue
        roles = entity.get("roles")
        if not isinstance(roles, Mapping):
            continue
        for trainer in roles.get("trainers", []):
            if not isinstance(trainer, Mapping):
                continue
            resolved_here = bool(trainer.get("resolved")) and (
                trainer.get("creature_id") == entity.get("entity_id")
            )
            projected = {
                **dict(trainer),
                "source": {
                    "entity_kind": "creature",
                    "entity_id": entity["entity_id"],
                    "name": entity["name"],
                },
                "matching_spawns": list(entity["matching_spawns"]),
                "geography_state": MATCH_KNOWN if resolved_here else MATCH_UNKNOWN,
                "geography_reason": (
                    "known_resolved_trainer_creature_spawn_in_zone"
                    if resolved_here
                    else "trainer_relation_unresolved_do_not_fabricate_geography"
                ),
            }
            (known if resolved_here else unknown).append(projected)
    def order(row: Mapping[str, Any]) -> tuple[int, int]:
        return int(row["recipe_id"]), int(row["native_trainer_entry"])

    known.sort(key=order)
    unknown.sort(key=order)
    return {"known": known, "unknown_relations": unknown}


def _recipe_projection(
    connection: sqlite3.Connection,
    *,
    zone_id: int,
    recipe_limit: int,
    items: Sequence[Mapping[str, Any]],
    quests: Mapping[str, Sequence[Mapping[str, Any]]],
    trainers: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Compose recipes from already computed positive zone evidence.

    P7-T06 must not re-run the complete P7-T04 geography evaluator five times.
    The compact zone projection keeps P7-T04 as the owner of full recipe detail.
    """

    return project_zone_recipes(
        connection,
        zone_id=zone_id,
        items=items,
        quests=quests,
        trainers=trainers,
        limit=recipe_limit,
    )

def _recipe_unknown_counts(recipes: Mapping[str, Any]) -> dict[str, int]:
    quest = recipes["quest_reward_spell"]
    return {
        "teaching_item": int(recipes["teaching_item"]["summary"]["unknown_count"]),
        "trainer": int(recipes["trainer"]["summary"]["unknown_count"]),
        "quest_giver": int(quest["giver"]["summary"]["unknown_count"]),
        "quest_finisher": int(quest["finisher"]["summary"]["unknown_count"]),
        "quest_objective": int(quest["objective"]["summary"]["unknown_count"]),
    }


def inspect_zone(
    connection: sqlite3.Connection,
    zone_id: int,
    *,
    entity_limit: int = 1000,
    recipe_limit: int = 100,
    include_recipes: bool = True,
) -> dict[str, Any]:
    """Inspect one canonical zone by composing validated P7 role/geography owners read-only."""

    _validate_nonnegative("zone_id", zone_id)
    _validate_limit("entity_limit", entity_limit)
    _validate_limit("recipe_limit", recipe_limit)
    if not isinstance(include_recipes, bool):
        raise TypeError("include_recipes must be a boolean")

    zone_page = query_zones(connection, zone_id=zone_id, limit=1)
    if not zone_page.results:
        raise ValueError(f"zone {zone_id} is not a canonical zone identity")
    zone = zone_page.results[0].zone

    world_page = query_world_entities(
        connection,
        zone_id=zone_id,
        include_states=(MATCH_KNOWN,),
        sort_by="entity_kind",
        limit=entity_limit,
    )
    world_payload = world_entity_query_page_to_dict(world_page)
    entities = _project_zone_entities(world_payload, zone_id)
    items = _collect_item_acquisition(entities)
    quests = _collect_quests(entities)
    vendors = _collect_vendors(entities)
    trainers = _collect_trainers(entities)

    if include_recipes:
        recipes = _recipe_projection(
            connection,
            zone_id=zone_id,
            recipe_limit=recipe_limit,
            items=items,
            quests=quests,
            trainers=trainers,
        )
        recipe_unknown: dict[str, int] | None = _recipe_unknown_counts(recipes)
    else:
        recipes = {
            "included": False,
            "reason": "recipe_projection_skipped_by_caller",
            "semantics": (
                "world/item/quest/vendor/trainer zone projections remain valid; "
                "no recipe absence claim is authorized"
            ),
        }
        recipe_unknown = None

    world_summary = dict(world_payload["summary"])
    known_matches = int(world_summary["known_match_count"])
    returned = int(world_summary["returned_count"])
    entity_truncated = known_matches > returned

    return {
        "zone": zone,
        "world_entities": {
            "summary": world_summary,
            "results": entities,
            "truncated_known_matches": entity_truncated,
            "detail_owner": "P7-T05",
        },
        "quests": {
            **quests,
            "detail_owner": "P7-T03",
            "semantics": "giver_finisher_objective_roles_remain_independent",
        },
        "items": {
            "results": items,
            "detail_owner": "P7-T02",
            "semantics": (
                "direct_reference_vendor_paths_remain_independent; vendor_max_count_is_not_chance; "
                "probabilities_are_not_combined"
            ),
        },
        "recipes": recipes,
        "vendors": vendors,
        "trainers": {
            **trainers,
            "detail_owner": "P7-T05/P7-T04",
        },
        "coverage": {
            "state": MATCH_UNKNOWN,
            "reason": "zone_contents_are_positive_evidence_projection_not_universal_complete_set",
            "world_entity_unknown_geography_count": int(world_summary["unknown_count"]),
            "world_entity_known_non_match_count": int(world_summary["known_non_match_count"]),
            "world_entity_projection_truncated": entity_truncated,
            "recipe_unknown_geography_counts": recipe_unknown,
            "unresolved_trainer_relation_count": len(trainers["unknown_relations"]),
            "negative_claim_authorized": False,
            "semantics": (
                "known concrete geography proves inclusion; missing, unresolved, or truncated "
                "geography remains unknown. P7-T06 defines no complete set of all zone contents."
            ),
        },
    }

