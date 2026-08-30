"""Provenance-aware read-only recipe/reagent/acquisition exploration for P7-T04."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from octogamedb.item_acquisition_search import (
    item_acquisition_page_to_dict,
    query_item_acquisitions,
)
from octogamedb.item_search import MATCH_KNOWN, MATCH_UNKNOWN, NON_MATCH_KNOWN, QUERY_STATES
from octogamedb.quest_search import query_quests
from octogamedb.world import find_world_locations

LEARNING_KINDS = ("teaching_item", "trainer", "quest_reward_spell")
RECIPE_QUERY_SORT_FIELDS = ("recipe_id", "name")


@dataclass(frozen=True)
class RecipePredicateState:
    predicate: str
    state: str
    actual: object | None
    reason: str


@dataclass(frozen=True)
class RecipeQueryResult:
    recipe: dict[str, Any]
    match_state: str
    predicates: tuple[RecipePredicateState, ...]


@dataclass(frozen=True)
class RecipeQuerySummary:
    total_recipe_identities: int
    known_match_count: int
    known_non_match_count: int
    unknown_count: int
    returned_count: int
    limit: int


@dataclass(frozen=True)
class RecipeQueryPage:
    summary: RecipeQuerySummary
    results: tuple[RecipeQueryResult, ...]


@dataclass(frozen=True)
class _RecipeCandidate:
    recipe_id: int
    name: str | None
    state: str
    predicates: tuple[RecipePredicateState, ...]


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


def _normalize_learning_kinds(value: Sequence[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise TypeError("learning_kinds must be a sequence")
    invalid = sorted(set(value) - set(LEARNING_KINDS))
    if invalid:
        raise ValueError(f"unsupported learning kind(s): {', '.join(invalid)}")
    return tuple(kind for kind in LEARNING_KINDS if kind in set(value))


def _known_predicate(
    predicate: str, matches: bool, actual: object, reason: str
) -> RecipePredicateState:
    return RecipePredicateState(
        predicate=predicate,
        state=MATCH_KNOWN if matches else NON_MATCH_KNOWN,
        actual=actual,
        reason=reason,
    )


def _unknown_predicate(
    predicate: str, reason: str, actual: object | None = None
) -> RecipePredicateState:
    return RecipePredicateState(
        predicate=predicate,
        state=MATCH_UNKNOWN,
        actual=actual,
        reason=reason,
    )


def _combined_state(predicates: Sequence[RecipePredicateState]) -> str:
    if any(predicate.state == NON_MATCH_KNOWN for predicate in predicates):
        return NON_MATCH_KNOWN
    if any(predicate.state == MATCH_UNKNOWN for predicate in predicates):
        return MATCH_UNKNOWN
    return MATCH_KNOWN


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


def _selected_provenance(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_key: int,
    fact_key: str,
    fact_instance_key: str = "",
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
          AND og.fact_key = ? AND og.fact_instance_key = ?
        """,
        (subject_kind, str(subject_key), fact_key, fact_instance_key),
    ).fetchone()
    return None if row is None else _provenance_from_row(row)


def _selected_relation_provenance(
    connection: sqlite3.Connection,
    *,
    recipe_id: int,
    fact_key: str,
    instance_key: str,
    target_kind: str,
    target_id: int,
    expected_attributes: Mapping[str, object],
) -> dict[str, Any] | None:
    exact = _selected_provenance(
        connection,
        subject_kind="recipe",
        subject_key=recipe_id,
        fact_key=fact_key,
        fact_instance_key=instance_key,
    )
    if exact is not None:
        return exact

    rows = connection.execute(
        """
        SELECT cs.observation_id, cs.selection_policy, cs.selection_reason,
               ds.source_key, so.source_revision, so.source_record_type,
               so.raw_identifier, so.authority_tier, so.value_json
        FROM observation_groups AS og
        JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        JOIN source_observations AS so ON so.id = cs.observation_id
        JOIN data_sources AS ds ON ds.id = so.source_id
        WHERE og.subject_kind = 'recipe' AND og.subject_key = ?
          AND og.fact_key = ?
        ORDER BY og.fact_instance_key
        """,
        (str(recipe_id), fact_key),
    ).fetchall()
    candidates: list[dict[str, Any]] = []
    for row in rows:
        provenance = _provenance_from_row(row)
        value = provenance["selected_value"]
        if not isinstance(value, dict):
            continue
        target = value.get("target")
        attributes = value.get("attributes", {})
        if not isinstance(target, dict) or not isinstance(attributes, dict):
            continue
        if target.get("kind") != target_kind:
            continue
        try:
            selected_target_id = int(str(target.get("key")))
        except (TypeError, ValueError):
            continue
        if selected_target_id != target_id:
            continue
        if any(
            key in attributes and attributes[key] != expected
            for key, expected in expected_attributes.items()
        ):
            continue
        candidates.append(provenance)
    return candidates[0] if len(candidates) == 1 else None


def _load_index(
    connection: sqlite3.Connection,
) -> tuple[
    list[sqlite3.Row],
    dict[int, list[sqlite3.Row]],
    dict[int, list[sqlite3.Row]],
    dict[int, list[sqlite3.Row]],
    dict[int, set[str]],
]:
    recipes = connection.execute(
        """
        SELECT r.recipe_id, r.crafting_spell_id, s.name, s.rank_text
        FROM recipes AS r
        JOIN spells AS s ON s.spell_id = r.crafting_spell_id
        ORDER BY r.recipe_id
        """
    ).fetchall()

    def grouped(sql: str) -> dict[int, list[sqlite3.Row]]:
        result: dict[int, list[sqlite3.Row]] = {}
        for row in connection.execute(sql).fetchall():
            result.setdefault(int(row["recipe_id"]), []).append(row)
        return result

    skills = grouped(
        """
        SELECT rsl.recipe_id, rsl.skill_line_ability_id, rsl.skill_line_id,
               sl.name AS skill_line_name, rsl.required_skill_value
        FROM recipe_skill_lines AS rsl
        JOIN skill_lines AS sl ON sl.skill_line_id = rsl.skill_line_id
        ORDER BY rsl.recipe_id, rsl.skill_line_ability_id
        """
    )
    outputs = grouped(
        """
        SELECT recipe_id, effect_index, native_item_id, item_id
        FROM recipe_outputs
        ORDER BY recipe_id, effect_index
        """
    )
    reagents = grouped(
        """
        SELECT recipe_id, reagent_index, native_item_id, item_id, required_quantity
        FROM recipe_reagents
        ORDER BY recipe_id, reagent_index
        """
    )
    learning: dict[int, set[str]] = {}
    for table, kind in (
        ("recipe_teaching_items", "teaching_item"),
        ("recipe_trainer_sources", "trainer"),
        ("recipe_quest_learning_sources", "quest_reward_spell"),
    ):
        for row in connection.execute(f"SELECT DISTINCT recipe_id FROM {table}").fetchall():
            learning.setdefault(int(row["recipe_id"]), set()).add(kind)
    return recipes, skills, outputs, reagents, learning


def _skill_predicate(
    rows: Sequence[sqlite3.Row],
    *,
    skill_line_id: int | None,
    skill_line_name: str | None,
    min_required_skill: int | None,
    max_required_skill: int | None,
) -> RecipePredicateState | None:
    if all(
        value is None
        for value in (skill_line_id, skill_line_name, min_required_skill, max_required_skill)
    ):
        return None
    parts: list[str] = []
    if skill_line_id is not None:
        parts.append(f"id={skill_line_id}")
    if skill_line_name is not None:
        parts.append(f"name~={skill_line_name!r}")
    if min_required_skill is not None:
        parts.append(f"required>={min_required_skill}")
    if max_required_skill is not None:
        parts.append(f"required<={max_required_skill}")
    label = f"skill_line[{','.join(parts)}]"
    if not rows:
        return _unknown_predicate(label, "recipe_skill_membership_not_materialized")

    actual = [
        {
            "skill_line_id": int(row["skill_line_id"]),
            "skill_line_name": (
                None if row["skill_line_name"] is None else str(row["skill_line_name"])
            ),
            "required_skill_value": int(row["required_skill_value"]),
        }
        for row in rows
    ]
    name_unknown_on_otherwise_matching_row = False
    for row in rows:
        if skill_line_id is not None and int(row["skill_line_id"]) != skill_line_id:
            continue
        required = int(row["required_skill_value"])
        if min_required_skill is not None and required < min_required_skill:
            continue
        if max_required_skill is not None and required > max_required_skill:
            continue
        if skill_line_name is not None:
            name = row["skill_line_name"]
            if name is None:
                name_unknown_on_otherwise_matching_row = True
                continue
            if skill_line_name.casefold() not in str(name).casefold():
                continue
        return _known_predicate(label, True, actual, "known_matching_recipe_skill_row")

    if name_unknown_on_otherwise_matching_row:
        return _unknown_predicate(
            label,
            "matching_recipe_skill_row_name_not_materialized",
            actual,
        )
    return _known_predicate(label, False, actual, "known_recipe_skill_rows")


def _item_relation_predicate(
    rows: Sequence[sqlite3.Row], *, item_id: int | None, relation: str
) -> RecipePredicateState | None:
    if item_id is None:
        return None
    label = f"{relation}_item_id={item_id}"
    native_ids = [int(row["native_item_id"]) for row in rows]
    return _known_predicate(
        label,
        item_id in native_ids,
        native_ids,
        f"known_recipe_{relation}_rows",
    )


def _learning_kind_predicate(
    known_kinds: set[str], requested: tuple[str, ...]
) -> RecipePredicateState | None:
    if not requested:
        return None
    label = f"learning_kind in {list(requested)!r}"
    matched = [kind for kind in requested if kind in known_kinds]
    if matched:
        return RecipePredicateState(
            predicate=label,
            state=MATCH_KNOWN,
            actual=sorted(known_kinds),
            reason="known_matching_learning_source_kind",
        )
    return _unknown_predicate(
        label,
        "no_known_matching_learning_source_negative_not_proven",
        sorted(known_kinds),
    )


def _item_acquisition_dict(
    connection: sqlite3.Connection,
    item_id: int,
    *,
    zone_id: int | None = None,
    map_id: int | None = None,
) -> dict[str, Any] | None:
    page = query_item_acquisitions(
        connection,
        item_id=item_id,
        zone_id=zone_id,
        map_id=map_id,
        include_states=(MATCH_KNOWN, MATCH_UNKNOWN),
        limit=1,
    )
    payload = item_acquisition_page_to_dict(page)
    results = payload.get("results", [])
    return None if not results else dict(results[0])


def _trainer_locations(
    connection: sqlite3.Connection,
    creature_id: int,
    cache: dict[int, tuple[dict[str, Any], ...]],
) -> tuple[dict[str, Any], ...]:
    cached = cache.get(creature_id)
    if cached is not None:
        return cached
    row = connection.execute(
        "SELECT name FROM creatures WHERE creature_id = ?", (creature_id,)
    ).fetchone()
    if row is None:
        cache[creature_id] = ()
        return ()
    locations = tuple(
        location
        for location in find_world_locations(connection, str(row["name"]))
        if location.get("entity_kind") == "creature"
        and int(location.get("entity_id", -1)) == creature_id
    )
    cache[creature_id] = locations
    return locations


def _location_matches(
    location: Mapping[str, Any], *, zone_id: int | None, map_id: int | None
) -> bool:
    if zone_id is not None and location.get("zone_id") != zone_id:
        return False
    return map_id is None or location.get("map_id") == map_id


def _teaching_geography_predicate(
    connection: sqlite3.Connection,
    recipe_id: int,
    *,
    zone_id: int | None,
    map_id: int | None,
    cache: dict[tuple[int, int | None, int | None], dict[str, Any] | None],
) -> RecipePredicateState | None:
    if zone_id is None and map_id is None:
        return None
    label = f"teaching_item_geography[zone={zone_id},map={map_id}]"
    rows = connection.execute(
        """
        SELECT DISTINCT native_item_id, item_id
        FROM recipe_teaching_items
        WHERE recipe_id = ?
        ORDER BY native_item_id
        """,
        (recipe_id,),
    ).fetchall()
    known_items = [int(row["item_id"]) for row in rows if row["item_id"] is not None]
    for item_id in known_items:
        key = (item_id, zone_id, map_id)
        if key not in cache:
            cache[key] = _item_acquisition_dict(
                connection, item_id, zone_id=zone_id, map_id=map_id
            )
        result = cache[key]
        if result is not None and result.get("combined_match_state") == MATCH_KNOWN:
            return RecipePredicateState(
                predicate=label,
                state=MATCH_KNOWN,
                actual={"item_id": item_id},
                reason="known_matching_teaching_item_acquisition_geography",
            )
    return _unknown_predicate(
        label,
        "no_known_matching_teaching_item_acquisition_negative_not_proven",
        {"known_teaching_item_ids": known_items},
    )


def _trainer_geography_predicate(
    connection: sqlite3.Connection,
    recipe_id: int,
    *,
    zone_id: int | None,
    map_id: int | None,
    cache: dict[int, tuple[dict[str, Any], ...]],
) -> RecipePredicateState | None:
    if zone_id is None and map_id is None:
        return None
    label = f"trainer_geography[zone={zone_id},map={map_id}]"
    rows = connection.execute(
        """
        SELECT DISTINCT native_trainer_entry, creature_id
        FROM recipe_trainer_sources
        WHERE recipe_id = ?
        ORDER BY native_trainer_entry
        """,
        (recipe_id,),
    ).fetchall()
    resolved_ids = [int(row["creature_id"]) for row in rows if row["creature_id"] is not None]
    for creature_id in resolved_ids:
        if any(
            _location_matches(location, zone_id=zone_id, map_id=map_id)
            for location in _trainer_locations(connection, creature_id, cache)
        ):
            return RecipePredicateState(
                predicate=label,
                state=MATCH_KNOWN,
                actual={"creature_id": creature_id},
                reason="known_matching_trainer_location",
            )
    return _unknown_predicate(
        label,
        "no_known_matching_trainer_location_negative_not_proven",
        {"resolved_trainer_ids": resolved_ids},
    )


def _quest_geography_predicate(
    connection: sqlite3.Connection,
    recipe_id: int,
    *,
    role: str,
    zone_id: int | None,
    map_id: int | None,
    cache: dict[tuple[int, str, int | None, int | None], str],
) -> RecipePredicateState | None:
    if zone_id is None and map_id is None:
        return None
    label = f"quest_{role}_geography[zone={zone_id},map={map_id}]"
    rows = connection.execute(
        """
        SELECT DISTINCT native_quest_id, quest_id
        FROM recipe_quest_learning_sources
        WHERE recipe_id = ?
        ORDER BY native_quest_id
        """,
        (recipe_id,),
    ).fetchall()
    resolved_ids = [int(row["quest_id"]) for row in rows if row["quest_id"] is not None]
    for quest_id in resolved_ids:
        key = (quest_id, role, zone_id, map_id)
        if key not in cache:
            kwargs: dict[str, Any] = {
                "quest_id": quest_id,
                f"{role}_zone_id": zone_id,
                f"{role}_map_id": map_id,
                "include_states": (MATCH_KNOWN, MATCH_UNKNOWN),
                "limit": 1,
            }
            page = query_quests(connection, **kwargs)
            cache[key] = page.results[0].match_state if page.results else MATCH_UNKNOWN
        if cache[key] == MATCH_KNOWN:
            return RecipePredicateState(
                predicate=label,
                state=MATCH_KNOWN,
                actual={"quest_id": quest_id},
                reason=f"known_matching_quest_{role}_location",
            )
    return _unknown_predicate(
        label,
        f"no_known_matching_quest_{role}_location_negative_not_proven",
        {"resolved_quest_ids": resolved_ids},
    )


def _relation_provenance(
    connection: sqlite3.Connection,
    recipe_id: int,
    fact_key: str,
    instance_key: str,
    *,
    target_kind: str,
    target_id: int,
    expected_attributes: Mapping[str, object],
) -> dict[str, Any] | None:
    return _selected_relation_provenance(
        connection,
        recipe_id=recipe_id,
        fact_key=fact_key,
        instance_key=instance_key,
        target_kind=target_kind,
        target_id=target_id,
        expected_attributes=expected_attributes,
    )


def _recipe_detail(
    connection: sqlite3.Connection,
    recipe_id: int,
    *,
    trainer_cache: dict[int, tuple[dict[str, Any], ...]],
    item_cache: dict[tuple[int, int | None, int | None], dict[str, Any] | None],
    quest_detail_cache: dict[int, dict[str, Any] | None],
) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT r.recipe_id, r.crafting_spell_id, s.name, s.rank_text
        FROM recipes AS r
        JOIN spells AS s ON s.spell_id = r.crafting_spell_id
        WHERE r.recipe_id = ?
        """,
        (recipe_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"recipe {recipe_id} disappeared during query")

    skills: list[dict[str, Any]] = []
    for skill in connection.execute(
        """
        SELECT rsl.skill_line_ability_id, rsl.skill_line_id, sl.name,
               rsl.required_skill_value
        FROM recipe_skill_lines AS rsl
        JOIN skill_lines AS sl ON sl.skill_line_id = rsl.skill_line_id
        WHERE rsl.recipe_id = ?
        ORDER BY rsl.skill_line_ability_id
        """,
        (recipe_id,),
    ).fetchall():
        ability_id = int(skill["skill_line_ability_id"])
        skills.append(
            {
                "skill_line_ability_id": ability_id,
                "skill_line_id": int(skill["skill_line_id"]),
                "skill_line_name": None if skill["name"] is None else str(skill["name"]),
                "required_skill_value": int(skill["required_skill_value"]),
                "provenance": _relation_provenance(
                    connection,
                    recipe_id,
                    "skill_line_membership",
                    f"skill-line-ability:{ability_id}",
                    target_kind="skill_line",
                    target_id=int(skill["skill_line_id"]),
                    expected_attributes={"skill_line_ability_id": ability_id},
                ),
            }
        )

    outputs: list[dict[str, Any]] = []
    for output in connection.execute(
        """
        SELECT ro.effect_index, ro.native_item_id, ro.item_id, i.name AS item_name
        FROM recipe_outputs AS ro
        LEFT JOIN items AS i ON i.item_id = ro.item_id
        WHERE ro.recipe_id = ?
        ORDER BY ro.effect_index
        """,
        (recipe_id,),
    ).fetchall():
        effect_index = int(output["effect_index"])
        resolved = output["item_id"] is not None
        outputs.append(
            {
                "effect_index": effect_index,
                "native_item_id": int(output["native_item_id"]),
                "item_id": None if output["item_id"] is None else int(output["item_id"]),
                "item_name": None if output["item_name"] is None else str(output["item_name"]),
                "resolved": resolved,
                "unresolved_reason": None if resolved else "missing_canonical_item_identity",
                "provenance": _relation_provenance(
                    connection,
                    recipe_id,
                    "crafted_output",
                    f"effect:{effect_index}",
                    target_kind="item",
                    target_id=int(output["native_item_id"]),
                    expected_attributes={"effect_index": effect_index},
                ),
            }
        )

    reagents: list[dict[str, Any]] = []
    for reagent in connection.execute(
        """
        SELECT rr.reagent_index, rr.native_item_id, rr.item_id, rr.required_quantity,
               i.name AS item_name
        FROM recipe_reagents AS rr
        LEFT JOIN items AS i ON i.item_id = rr.item_id
        WHERE rr.recipe_id = ?
        ORDER BY rr.reagent_index
        """,
        (recipe_id,),
    ).fetchall():
        reagent_index = int(reagent["reagent_index"])
        resolved = reagent["item_id"] is not None
        reagents.append(
            {
                "reagent_index": reagent_index,
                "native_item_id": int(reagent["native_item_id"]),
                "item_id": None if reagent["item_id"] is None else int(reagent["item_id"]),
                "item_name": None if reagent["item_name"] is None else str(reagent["item_name"]),
                "required_quantity": int(reagent["required_quantity"]),
                "resolved": resolved,
                "unresolved_reason": None if resolved else "missing_canonical_item_identity",
                "provenance": _relation_provenance(
                    connection,
                    recipe_id,
                    "reagent",
                    f"slot:{reagent_index}",
                    target_kind="item",
                    target_id=int(reagent["native_item_id"]),
                    expected_attributes={"reagent_index": reagent_index},
                ),
            }
        )

    teaching_items: list[dict[str, Any]] = []
    teaching_rows = connection.execute(
        """
        SELECT ti.native_item_id, ti.item_id, i.name AS item_name, ti.item_spell_slot,
               ti.spell_trigger, ti.spell_charges, ti.acquisition_spell_id,
               s.name AS acquisition_spell_name, ti.learning_proof_kind,
               ti.learn_effect_index, ti.server_learn_active
        FROM recipe_teaching_items AS ti
        LEFT JOIN items AS i ON i.item_id = ti.item_id
        JOIN spells AS s ON s.spell_id = ti.acquisition_spell_id
        WHERE ti.recipe_id = ?
        ORDER BY ti.native_item_id, ti.item_spell_slot, ti.acquisition_spell_id
        """,
        (recipe_id,),
    ).fetchall()
    for teaching in teaching_rows:
        native_item_id = int(teaching["native_item_id"])
        item_id = None if teaching["item_id"] is None else int(teaching["item_id"])
        slot = int(teaching["item_spell_slot"])
        acquisition_spell_id = int(teaching["acquisition_spell_id"])
        acquisition: dict[str, Any] | None = None
        if item_id is not None:
            key = (item_id, None, None)
            if key not in item_cache:
                item_cache[key] = _item_acquisition_dict(connection, item_id)
            acquisition = item_cache[key]
        known_paths = (
            []
            if acquisition is None
            else list(acquisition.get("sources", []))
        )
        teaching_items.append(
            {
                "native_item_id": native_item_id,
                "item_id": item_id,
                "item_name": None if teaching["item_name"] is None else str(teaching["item_name"]),
                "resolved": item_id is not None,
                "unresolved_reason": (
                    None if item_id is not None else "missing_canonical_item_identity"
                ),
                "item_spell_slot": slot,
                "spell_trigger": (
                    None if teaching["spell_trigger"] is None else int(teaching["spell_trigger"])
                ),
                "spell_charges": (
                    None if teaching["spell_charges"] is None else int(teaching["spell_charges"])
                ),
                "acquisition_spell_id": acquisition_spell_id,
                "acquisition_spell_name": (
                    None
                    if teaching["acquisition_spell_name"] is None
                    else str(teaching["acquisition_spell_name"])
                ),
                "learning_proof_kind": str(teaching["learning_proof_kind"]),
                "learn_effect_index": (
                    None
                    if teaching["learn_effect_index"] is None
                    else int(teaching["learn_effect_index"])
                ),
                "server_learn_active": (
                    None
                    if teaching["server_learn_active"] is None
                    else int(teaching["server_learn_active"])
                ),
                "provenance": _relation_provenance(
                    connection,
                    recipe_id,
                    "teaching_item",
                    f"item:{native_item_id}:slot:{slot}:spell:{acquisition_spell_id}",
                    target_kind="item",
                    target_id=native_item_id,
                    expected_attributes={
                        "item_spell_slot": slot,
                        "acquisition_spell_id": acquisition_spell_id,
                    },
                ),
                "acquisition_composition": acquisition,
                "acquisition_coverage_state": MATCH_KNOWN if known_paths else MATCH_UNKNOWN,
                "acquisition_coverage_reason": (
                    "known_item_acquisition_paths"
                    if known_paths
                    else "no_known_item_acquisition_path_negative_not_proven"
                ),
            }
        )

    trainers: list[dict[str, Any]] = []
    trainer_rows = connection.execute(
        """
        SELECT ts.trainer_kind, ts.native_trainer_entry, ts.creature_id, c.name AS creature_name,
               ts.trainer_template_id, ts.acquisition_spell_id,
               s.name AS acquisition_spell_name, ts.learning_proof_kind,
               ts.learn_effect_index, ts.server_learn_active, ts.spell_cost,
               ts.required_skill_line_id, sl.name AS required_skill_line_name,
               ts.required_skill_value, ts.required_character_level
        FROM recipe_trainer_sources AS ts
        LEFT JOIN creatures AS c ON c.creature_id = ts.creature_id
        JOIN spells AS s ON s.spell_id = ts.acquisition_spell_id
        LEFT JOIN skill_lines AS sl ON sl.skill_line_id = ts.required_skill_line_id
        WHERE ts.recipe_id = ?
        ORDER BY ts.trainer_kind, ts.native_trainer_entry, ts.acquisition_spell_id
        """,
        (recipe_id,),
    ).fetchall()
    for trainer in trainer_rows:
        kind = str(trainer["trainer_kind"])
        native_entry = int(trainer["native_trainer_entry"])
        creature_id = None if trainer["creature_id"] is None else int(trainer["creature_id"])
        acquisition_spell_id = int(trainer["acquisition_spell_id"])
        template_id = (
            None if trainer["trainer_template_id"] is None else int(trainer["trainer_template_id"])
        )
        locations = () if creature_id is None else _trainer_locations(
            connection, creature_id, trainer_cache
        )
        trainers.append(
            {
                "trainer_kind": kind,
                "native_trainer_entry": native_entry,
                "creature_id": creature_id,
                "creature_name": (
                    None if trainer["creature_name"] is None else str(trainer["creature_name"])
                ),
                "resolved": creature_id is not None,
                "unresolved_reason": (
                    None if creature_id is not None else "missing_canonical_creature_identity"
                ),
                "trainer_template_id": template_id,
                "acquisition_spell_id": acquisition_spell_id,
                "acquisition_spell_name": (
                    None
                    if trainer["acquisition_spell_name"] is None
                    else str(trainer["acquisition_spell_name"])
                ),
                "learning_proof_kind": str(trainer["learning_proof_kind"]),
                "learn_effect_index": (
                    None
                    if trainer["learn_effect_index"] is None
                    else int(trainer["learn_effect_index"])
                ),
                "server_learn_active": (
                    None
                    if trainer["server_learn_active"] is None
                    else int(trainer["server_learn_active"])
                ),
                "spell_cost": int(trainer["spell_cost"]),
                "required_skill_line_id": (
                    None
                    if trainer["required_skill_line_id"] is None
                    else int(trainer["required_skill_line_id"])
                ),
                "required_skill_line_name": (
                    None
                    if trainer["required_skill_line_name"] is None
                    else str(trainer["required_skill_line_name"])
                ),
                "required_skill_value": int(trainer["required_skill_value"]),
                "required_character_level": int(trainer["required_character_level"]),
                "locations": list(locations),
                "geography_state": MATCH_KNOWN if locations else MATCH_UNKNOWN,
                "geography_reason": (
                    "known_trainer_locations"
                    if locations
                    else "no_known_trainer_location_negative_not_proven"
                ),
                "provenance": _relation_provenance(
                    connection,
                    recipe_id,
                    "trainer_source",
                    (
                        f"{kind}:creature:{native_entry}:template:{template_id or 0}:"
                        f"spell:{acquisition_spell_id}"
                    ),
                    target_kind="creature",
                    target_id=native_entry,
                    expected_attributes={
                        "trainer_kind": kind,
                        "trainer_template_id": template_id,
                        "acquisition_spell_id": acquisition_spell_id,
                    },
                ),
            }
        )

    quest_sources: list[dict[str, Any]] = []
    quest_rows = connection.execute(
        """
        SELECT qs.native_quest_id, qs.quest_id, q.name AS quest_name, qs.reward_spell_field,
               qs.acquisition_spell_id, s.name AS acquisition_spell_name,
               qs.learning_proof_kind, qs.learn_effect_index, qs.server_learn_active
        FROM recipe_quest_learning_sources AS qs
        LEFT JOIN quests AS q ON q.quest_id = qs.quest_id
        JOIN spells AS s ON s.spell_id = qs.acquisition_spell_id
        WHERE qs.recipe_id = ?
        ORDER BY qs.native_quest_id, qs.reward_spell_field, qs.acquisition_spell_id
        """,
        (recipe_id,),
    ).fetchall()
    for quest in quest_rows:
        native_quest_id = int(quest["native_quest_id"])
        quest_id = None if quest["quest_id"] is None else int(quest["quest_id"])
        acquisition_spell_id = int(quest["acquisition_spell_id"])
        reward_field = str(quest["reward_spell_field"])
        if quest_id is not None and quest_id not in quest_detail_cache:
            page = query_quests(connection, quest_id=quest_id, limit=1)
            quest_detail_cache[quest_id] = page.results[0].quest if page.results else None
        context = None if quest_id is None else quest_detail_cache[quest_id]
        quest_sources.append(
            {
                "native_quest_id": native_quest_id,
                "quest_id": quest_id,
                "quest_name": None if quest["quest_name"] is None else str(quest["quest_name"]),
                "resolved": quest_id is not None,
                "unresolved_reason": (
                    None if quest_id is not None else "missing_canonical_quest_identity"
                ),
                "reward_spell_field": reward_field,
                "acquisition_spell_id": acquisition_spell_id,
                "acquisition_spell_name": (
                    None
                    if quest["acquisition_spell_name"] is None
                    else str(quest["acquisition_spell_name"])
                ),
                "learning_proof_kind": str(quest["learning_proof_kind"]),
                "learn_effect_index": (
                    None
                    if quest["learn_effect_index"] is None
                    else int(quest["learn_effect_index"])
                ),
                "server_learn_active": (
                    None
                    if quest["server_learn_active"] is None
                    else int(quest["server_learn_active"])
                ),
                "provenance": _relation_provenance(
                    connection,
                    recipe_id,
                    "quest_learning_source",
                    (
                        f"quest:{native_quest_id}:{reward_field}:"
                        f"spell:{acquisition_spell_id}"
                    ),
                    target_kind="quest",
                    target_id=native_quest_id,
                    expected_attributes={
                        "reward_spell_field": reward_field,
                        "acquisition_spell_id": acquisition_spell_id,
                    },
                ),
                "quest_context": context,
                "quest_context_state": MATCH_KNOWN if context is not None else MATCH_UNKNOWN,
                "quest_context_reason": (
                    "resolved_p7_quest_context"
                    if context is not None
                    else "quest_context_unresolved_negative_not_proven"
                ),
            }
        )

    return {
        "recipe_id": int(row["recipe_id"]),
        "crafting_spell_id": int(row["crafting_spell_id"]),
        "name": None if row["name"] is None else str(row["name"]),
        "rank_text": None if row["rank_text"] is None else str(row["rank_text"]),
        "provenance": {
            "recipe_presence": _selected_provenance(
                connection,
                subject_kind="recipe",
                subject_key=recipe_id,
                fact_key="presence",
            ),
            "spell_name": _selected_provenance(
                connection,
                subject_kind="spell",
                subject_key=recipe_id,
                fact_key="name",
            ),
        },
        "skill_lines": skills,
        "outputs": outputs,
        "reagents": reagents,
        "learning": {
            "teaching_items": teaching_items,
            "trainers": trainers,
            "quest_reward_spells": quest_sources,
            "coverage_semantics": "positive_evidence_only_absence_is_not_universal_negative",
        },
    }


def _sort_candidates(
    candidates: list[_RecipeCandidate], *, sort_by: str, descending: bool
) -> list[_RecipeCandidate]:
    if sort_by == "recipe_id":
        return sorted(candidates, key=lambda row: row.recipe_id, reverse=descending)
    known = [candidate for candidate in candidates if candidate.name is not None]
    unknown = [candidate for candidate in candidates if candidate.name is None]
    known.sort(
        key=lambda candidate: (str(candidate.name).casefold(), candidate.recipe_id),
        reverse=descending,
    )
    unknown.sort(key=lambda candidate: candidate.recipe_id)
    return known + unknown


def query_recipes(
    connection: sqlite3.Connection,
    *,
    recipe_id: int | None = None,
    name_contains: str | None = None,
    skill_line_id: int | None = None,
    skill_line_name: str | None = None,
    min_required_skill: int | None = None,
    max_required_skill: int | None = None,
    output_item_id: int | None = None,
    reagent_item_id: int | None = None,
    learning_kinds: Sequence[str] | None = None,
    teaching_zone_id: int | None = None,
    teaching_map_id: int | None = None,
    trainer_zone_id: int | None = None,
    trainer_map_id: int | None = None,
    quest_giver_zone_id: int | None = None,
    quest_giver_map_id: int | None = None,
    quest_finisher_zone_id: int | None = None,
    quest_finisher_map_id: int | None = None,
    quest_objective_zone_id: int | None = None,
    quest_objective_map_id: int | None = None,
    include_states: Sequence[str] = (MATCH_KNOWN,),
    sort_by: str = "recipe_id",
    descending: bool = False,
    limit: int = 100,
) -> RecipeQueryPage:
    """Search P4 recipes and compose bounded P7 acquisition/geography evidence read-only."""

    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    if sort_by not in RECIPE_QUERY_SORT_FIELDS:
        raise ValueError(f"unsupported sort field: {sort_by}")
    if not isinstance(descending, bool):
        raise TypeError("descending must be a boolean")
    for name, value in (
        ("recipe_id", recipe_id),
        ("skill_line_id", skill_line_id),
        ("min_required_skill", min_required_skill),
        ("max_required_skill", max_required_skill),
        ("output_item_id", output_item_id),
        ("reagent_item_id", reagent_item_id),
        ("teaching_zone_id", teaching_zone_id),
        ("teaching_map_id", teaching_map_id),
        ("trainer_zone_id", trainer_zone_id),
        ("trainer_map_id", trainer_map_id),
        ("quest_giver_zone_id", quest_giver_zone_id),
        ("quest_giver_map_id", quest_giver_map_id),
        ("quest_finisher_zone_id", quest_finisher_zone_id),
        ("quest_finisher_map_id", quest_finisher_map_id),
        ("quest_objective_zone_id", quest_objective_zone_id),
        ("quest_objective_map_id", quest_objective_map_id),
    ):
        _validate_nonnegative(name, value)
    if recipe_id is not None and recipe_id <= 0:
        raise ValueError("recipe_id must be positive")
    if output_item_id is not None and output_item_id <= 0:
        raise ValueError("output_item_id must be positive")
    if reagent_item_id is not None and reagent_item_id <= 0:
        raise ValueError("reagent_item_id must be positive")
    if (
        min_required_skill is not None
        and max_required_skill is not None
        and min_required_skill > max_required_skill
    ):
        raise ValueError("min_required_skill must not exceed max_required_skill")

    normalized_name = _normalize_text("name_contains", name_contains)
    normalized_skill_name = _normalize_text("skill_line_name", skill_line_name)
    states = _normalize_states(include_states)
    requested_learning = _normalize_learning_kinds(learning_kinds)
    recipe_rows, skills, outputs, reagents, learning = _load_index(connection)

    trainer_cache: dict[int, tuple[dict[str, Any], ...]] = {}
    item_filter_cache: dict[
        tuple[int, int | None, int | None], dict[str, Any] | None
    ] = {}
    quest_filter_cache: dict[tuple[int, str, int | None, int | None], str] = {}
    candidates: list[_RecipeCandidate] = []
    counts = {state: 0 for state in QUERY_STATES}

    for row in recipe_rows:
        current_id = int(row["recipe_id"])
        current_name = None if row["name"] is None else str(row["name"])
        predicates: list[RecipePredicateState] = []
        if recipe_id is not None:
            predicates.append(
                _known_predicate(
                    f"recipe_id={recipe_id}",
                    current_id == recipe_id,
                    current_id,
                    "canonical_recipe_identity",
                )
            )
        if normalized_name is not None:
            if current_name is None:
                predicates.append(
                    _unknown_predicate("name_contains", "spell_name_not_materialized")
                )
            else:
                predicates.append(
                    _known_predicate(
                        f"name_contains={normalized_name!r}",
                        normalized_name.casefold() in current_name.casefold(),
                        current_name,
                        "known_crafting_spell_name",
                    )
                )
        skill = _skill_predicate(
            skills.get(current_id, ()),
            skill_line_id=skill_line_id,
            skill_line_name=normalized_skill_name,
            min_required_skill=min_required_skill,
            max_required_skill=max_required_skill,
        )
        if skill is not None:
            predicates.append(skill)
        output = _item_relation_predicate(
            outputs.get(current_id, ()), item_id=output_item_id, relation="output"
        )
        if output is not None:
            predicates.append(output)
        reagent = _item_relation_predicate(
            reagents.get(current_id, ()), item_id=reagent_item_id, relation="reagent"
        )
        if reagent is not None:
            predicates.append(reagent)
        learning_predicate = _learning_kind_predicate(
            learning.get(current_id, set()), requested_learning
        )
        if learning_predicate is not None:
            predicates.append(learning_predicate)

        if not any(predicate.state == NON_MATCH_KNOWN for predicate in predicates):
            for predicate in (
                _teaching_geography_predicate(
                    connection,
                    current_id,
                    zone_id=teaching_zone_id,
                    map_id=teaching_map_id,
                    cache=item_filter_cache,
                ),
                _trainer_geography_predicate(
                    connection,
                    current_id,
                    zone_id=trainer_zone_id,
                    map_id=trainer_map_id,
                    cache=trainer_cache,
                ),
                _quest_geography_predicate(
                    connection,
                    current_id,
                    role="giver",
                    zone_id=quest_giver_zone_id,
                    map_id=quest_giver_map_id,
                    cache=quest_filter_cache,
                ),
                _quest_geography_predicate(
                    connection,
                    current_id,
                    role="finisher",
                    zone_id=quest_finisher_zone_id,
                    map_id=quest_finisher_map_id,
                    cache=quest_filter_cache,
                ),
                _quest_geography_predicate(
                    connection,
                    current_id,
                    role="objective",
                    zone_id=quest_objective_zone_id,
                    map_id=quest_objective_map_id,
                    cache=quest_filter_cache,
                ),
            ):
                if predicate is not None:
                    predicates.append(predicate)

        state = _combined_state(predicates)
        counts[state] += 1
        candidates.append(
            _RecipeCandidate(
                recipe_id=current_id,
                name=current_name,
                state=state,
                predicates=tuple(predicates),
            )
        )

    selected = [candidate for candidate in candidates if candidate.state in states]
    selected = _sort_candidates(selected, sort_by=sort_by, descending=descending)[:limit]

    item_detail_cache: dict[
        tuple[int, int | None, int | None], dict[str, Any] | None
    ] = dict(item_filter_cache)
    quest_detail_cache: dict[int, dict[str, Any] | None] = {}
    results = tuple(
        RecipeQueryResult(
            recipe=_recipe_detail(
                connection,
                candidate.recipe_id,
                trainer_cache=trainer_cache,
                item_cache=item_detail_cache,
                quest_detail_cache=quest_detail_cache,
            ),
            match_state=candidate.state,
            predicates=candidate.predicates,
        )
        for candidate in selected
    )
    return RecipeQueryPage(
        summary=RecipeQuerySummary(
            total_recipe_identities=len(recipe_rows),
            known_match_count=counts[MATCH_KNOWN],
            known_non_match_count=counts[NON_MATCH_KNOWN],
            unknown_count=counts[MATCH_UNKNOWN],
            returned_count=len(results),
            limit=limit,
        ),
        results=results,
    )


def recipe_query_page_to_dict(page: RecipeQueryPage) -> dict[str, Any]:
    """Return a stable JSON-friendly representation of a P7-T04 recipe query page."""

    return {
        "summary": asdict(page.summary),
        "results": [
            {
                "match_state": result.match_state,
                "predicates": [asdict(predicate) for predicate in result.predicates],
                "recipe": result.recipe,
            }
            for result in page.results
        ],
    }
