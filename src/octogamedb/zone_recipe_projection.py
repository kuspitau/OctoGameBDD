"""Fast positive-evidence recipe projection for the P7-T06 zone view.

P7-T06 already owns a zone-scoped projection of item acquisition, quest roles and
trainer presence.  Re-running the complete P7-T04 search five times from that point
creates a pathological nested scan:

zone -> every recipe -> teaching item -> item acquisition -> provenance.

This module instead inverts the already computed zone-scoped positive evidence to
recipe identities.  Full recipe details remain owned by P7-T04.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

MATCH_KNOWN = "known_match"
MATCH_UNKNOWN = "unknown"

_CHUNK_SIZE = 400


def _validate_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")


def _chunks(values: Sequence[int]) -> list[tuple[int, ...]]:
    ordered = sorted(set(values))
    return [
        tuple(ordered[index : index + _CHUNK_SIZE])
        for index in range(0, len(ordered), _CHUNK_SIZE)
    ]


def _recipe_identities(
    connection: sqlite3.Connection,
    recipe_ids: Sequence[int],
) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for chunk in _chunks(recipe_ids):
        placeholders = ", ".join("?" for _ in chunk)
        rows = connection.execute(
            f"""
            SELECT r.recipe_id, r.crafting_spell_id, s.name, s.rank_text
            FROM recipes AS r
            JOIN spells AS s ON s.spell_id = r.crafting_spell_id
            WHERE r.recipe_id IN ({placeholders})
            ORDER BY r.recipe_id
            """,
            chunk,
        ).fetchall()
        for row in rows:
            recipe_id = int(row["recipe_id"])
            result[recipe_id] = {
                "recipe_id": recipe_id,
                "crafting_spell_id": int(row["crafting_spell_id"]),
                "name": None if row["name"] is None else str(row["name"]),
                "rank_text": None if row["rank_text"] is None else str(row["rank_text"]),
                "detail_owner": "P7-T04",
            }
    return result


def _page(
    connection: sqlite3.Connection,
    *,
    zone_id: int,
    evidence_by_recipe: Mapping[int, Sequence[Mapping[str, Any]]],
    predicate: str,
    reason: str,
    limit: int,
) -> dict[str, Any]:
    total = int(connection.execute("SELECT COUNT(*) FROM recipes").fetchone()[0])
    identities = _recipe_identities(connection, list(evidence_by_recipe))
    known_ids = sorted(identities)
    selected_ids = known_ids[:limit]

    results: list[dict[str, Any]] = []
    for recipe_id in selected_ids:
        recipe = dict(identities[recipe_id])
        evidence = [dict(row) for row in evidence_by_recipe[recipe_id]]
        recipe["zone_learning_evidence"] = evidence
        results.append(
            {
                "match_state": MATCH_KNOWN,
                "predicates": [
                    {
                        "predicate": predicate,
                        "state": MATCH_KNOWN,
                        "actual": {
                            "zone_id": zone_id,
                            "evidence_count": len(evidence),
                        },
                        "reason": reason,
                    }
                ],
                "recipe": recipe,
            }
        )

    known_count = len(known_ids)
    return {
        "summary": {
            "total_recipe_identities": total,
            "known_match_count": known_count,
            "known_non_match_count": 0,
            "unknown_count": max(0, total - known_count),
            "returned_count": len(results),
            "limit": limit,
        },
        "results": results,
        "truncated_known_matches": known_count > len(results),
        "projection_semantics": (
            "positive zone evidence only; absence remains unknown and is not a "
            "universal negative"
        ),
    }


def _teaching_evidence(
    connection: sqlite3.Connection,
    items: Sequence[Mapping[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    item_by_id = {int(item["item_id"]): dict(item) for item in items}
    evidence: dict[int, list[dict[str, Any]]] = {}
    for chunk in _chunks(list(item_by_id)):
        placeholders = ", ".join("?" for _ in chunk)
        rows = connection.execute(
            f"""
            SELECT recipe_id, native_item_id, item_id, item_spell_slot,
                   acquisition_spell_id, learning_proof_kind,
                   learn_effect_index, server_learn_active
            FROM recipe_teaching_items
            WHERE item_id IN ({placeholders})
            ORDER BY recipe_id, native_item_id, item_spell_slot, acquisition_spell_id
            """,
            chunk,
        ).fetchall()
        for row in rows:
            item_id = int(row["item_id"])
            evidence.setdefault(int(row["recipe_id"]), []).append(
                {
                    "learning_kind": "teaching_item",
                    "native_item_id": int(row["native_item_id"]),
                    "item_id": item_id,
                    "item_spell_slot": int(row["item_spell_slot"]),
                    "acquisition_spell_id": int(row["acquisition_spell_id"]),
                    "learning_proof_kind": str(row["learning_proof_kind"]),
                    "learn_effect_index": (
                        None
                        if row["learn_effect_index"] is None
                        else int(row["learn_effect_index"])
                    ),
                    "server_learn_active": (
                        None
                        if row["server_learn_active"] is None
                        else int(row["server_learn_active"])
                    ),
                    "zone_item_acquisition": item_by_id[item_id],
                }
            )
    return evidence


def _trainer_evidence(
    trainers: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[int, list[dict[str, Any]]]:
    evidence: dict[int, list[dict[str, Any]]] = {}
    for trainer in trainers.get("known", ()):
        recipe_id = int(trainer["recipe_id"])
        evidence.setdefault(recipe_id, []).append(
            {
                "learning_kind": "trainer",
                "trainer": dict(trainer),
            }
        )
    return evidence


def _quest_evidence(
    connection: sqlite3.Connection,
    quest_rows: Sequence[Mapping[str, Any]],
    *,
    role: str,
) -> dict[int, list[dict[str, Any]]]:
    rows_by_quest: dict[int, list[dict[str, Any]]] = {}
    for quest in quest_rows:
        rows_by_quest.setdefault(int(quest["quest_id"]), []).append(dict(quest))

    evidence: dict[int, list[dict[str, Any]]] = {}
    for chunk in _chunks(list(rows_by_quest)):
        placeholders = ", ".join("?" for _ in chunk)
        rows = connection.execute(
            f"""
            SELECT recipe_id, native_quest_id, quest_id, reward_spell_field,
                   acquisition_spell_id, learning_proof_kind,
                   learn_effect_index, server_learn_active
            FROM recipe_quest_learning_sources
            WHERE quest_id IN ({placeholders})
            ORDER BY recipe_id, native_quest_id, reward_spell_field, acquisition_spell_id
            """,
            chunk,
        ).fetchall()
        for row in rows:
            quest_id = int(row["quest_id"])
            evidence.setdefault(int(row["recipe_id"]), []).append(
                {
                    "learning_kind": "quest_reward_spell",
                    "quest_geography_role": role,
                    "native_quest_id": int(row["native_quest_id"]),
                    "quest_id": quest_id,
                    "reward_spell_field": str(row["reward_spell_field"]),
                    "acquisition_spell_id": int(row["acquisition_spell_id"]),
                    "learning_proof_kind": str(row["learning_proof_kind"]),
                    "learn_effect_index": (
                        None
                        if row["learn_effect_index"] is None
                        else int(row["learn_effect_index"])
                    ),
                    "server_learn_active": (
                        None
                        if row["server_learn_active"] is None
                        else int(row["server_learn_active"])
                    ),
                    "zone_quest_role_evidence": rows_by_quest[quest_id],
                }
            )
    return evidence


def project_zone_recipes(
    connection: sqlite3.Connection,
    *,
    zone_id: int,
    items: Sequence[Mapping[str, Any]],
    quests: Mapping[str, Sequence[Mapping[str, Any]]],
    trainers: Mapping[str, Sequence[Mapping[str, Any]]],
    limit: int,
) -> dict[str, Any]:
    """Project known recipe-learning evidence from one already-computed zone view."""

    _validate_limit(limit)
    if isinstance(zone_id, bool) or not isinstance(zone_id, int) or zone_id < 0:
        raise ValueError("zone_id must be a non-negative integer")

    teaching = _teaching_evidence(connection, items)
    trainer = _trainer_evidence(trainers)
    giver = _quest_evidence(connection, quests.get("given", ()), role="giver")
    finisher = _quest_evidence(
        connection,
        quests.get("finished", ()),
        role="finisher",
    )
    objective = _quest_evidence(
        connection,
        quests.get("objectives", ()),
        role="objective",
    )

    return {
        "included": True,
        "teaching_item": _page(
            connection,
            zone_id=zone_id,
            evidence_by_recipe=teaching,
            predicate=f"teaching_item_geography[zone={zone_id}]",
            reason="known_zone_item_acquisition_matches_recipe_teaching_item",
            limit=limit,
        ),
        "trainer": _page(
            connection,
            zone_id=zone_id,
            evidence_by_recipe=trainer,
            predicate=f"trainer_geography[zone={zone_id}]",
            reason="known_resolved_trainer_spawn_in_zone",
            limit=limit,
        ),
        "quest_reward_spell": {
            "giver": _page(
                connection,
                zone_id=zone_id,
                evidence_by_recipe=giver,
                predicate=f"quest_giver_geography[zone={zone_id}]",
                reason="known_quest_giver_role_in_zone",
                limit=limit,
            ),
            "finisher": _page(
                connection,
                zone_id=zone_id,
                evidence_by_recipe=finisher,
                predicate=f"quest_finisher_geography[zone={zone_id}]",
                reason="known_quest_finisher_role_in_zone",
                limit=limit,
            ),
            "objective": _page(
                connection,
                zone_id=zone_id,
                evidence_by_recipe=objective,
                predicate=f"quest_objective_geography[zone={zone_id}]",
                reason="known_creature_or_gameobject_quest_objective_role_in_zone",
                limit=limit,
            ),
        },
        "semantics": (
            "compact P7-T06 positive-evidence inversion of already computed zone roles; "
            "full recipe hydration and cross-domain recipe detail remain owned by P7-T04"
        ),
    }
