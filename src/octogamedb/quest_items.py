"""Read model and shared semantics for P3-T05 quest/item facts."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

POLICY_PREFIX = "p3-t05-d033-"
PARTIAL_POSITIVE_SOURCES = frozenset({"octo-live-quest-query", "octodb"})

FAMILY_FACT_KEYS = {
    "required_item": "quest_required_item",
    "required_source": "quest_required_source",
    "source_item_id": "quest_provided_item",
    "source_item_count": "quest_provided_item_count",
    "reward_item": "quest_reward_item",
    "choice_reward_item": "quest_choice_reward_item",
}

FAMILY_SET_FACT_KEYS = {
    "required_item": "quest_required_item_set",
    "required_source": "quest_required_source_set",
    "source_item_id": "quest_provided_item_set",
    "reward_item": "quest_reward_item_set",
    "choice_reward_item": "quest_choice_reward_item_set",
}



def is_managed_policy(policy: str | None) -> bool:
    return policy is not None and policy.startswith(POLICY_PREFIX)


def _selected_fact(
    connection: sqlite3.Connection,
    *,
    quest_id: int,
    fact_key: str,
    fact_instance_key: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT og.id AS observation_group_id, cs.observation_id, cs.selection_policy,
               ds.source_key, so.source_revision, so.value_json
        FROM observation_groups AS og
        JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        JOIN source_observations AS so ON so.id = cs.observation_id
        JOIN data_sources AS ds ON ds.id = so.source_id
        WHERE og.subject_kind = 'quest'
          AND og.subject_key = ?
          AND og.fact_key = ?
          AND og.fact_instance_key = ?
        """,
        (str(quest_id), fact_key, fact_instance_key),
    ).fetchone()
    if row is None:
        return None
    return {
        "observation_group_id": int(row["observation_group_id"]),
        "observation_id": int(row["observation_id"]),
        "selection_policy": None
        if row["selection_policy"] is None
        else str(row["selection_policy"]),
        "source_key": str(row["source_key"]),
        "source_revision": str(row["source_revision"]),
        "value": json.loads(str(row["value_json"])),
    }


def _selected_set(
    connection: sqlite3.Connection, *, quest_id: int, family: str
) -> dict[str, Any] | None:
    fact_key = FAMILY_SET_FACT_KEYS[family]
    selected = _selected_fact(
        connection,
        quest_id=quest_id,
        fact_key=fact_key,
        fact_instance_key="",
    )
    if selected is None:
        return None
    value = selected["value"]
    if not isinstance(value, dict):
        return None
    return selected


def _complete_member_ids(selected_set: dict[str, Any] | None) -> set[int] | None:
    if selected_set is None:
        return None
    value = selected_set.get("value")
    if not isinstance(value, dict) or value.get("completeness") != "complete":
        return None
    members = value.get("members")
    if not isinstance(members, list):
        return set()
    result: set[int] = set()
    for member in members:
        if not isinstance(member, dict):
            continue
        item_id = member.get("item_id")
        if isinstance(item_id, int) and not isinstance(item_id, bool) and item_id > 0:
            result.add(item_id)
    return result


def selected_relation_is_active(
    selection: dict[str, Any], *, item_id: int, complete_member_ids: set[int] | None
) -> bool:
    """Apply P3-T05 complete-set vs partial-positive membership semantics."""

    policy = selection.get("selection_policy")
    if not is_managed_policy(None if policy is None else str(policy)):
        return True
    if complete_member_ids is None or item_id in complete_member_ids:
        return True
    return str(selection.get("source_key")) in PARTIAL_POSITIVE_SOURCES


def _target_and_attributes(selection: dict[str, Any]) -> tuple[int, dict[str, Any]] | None:
    value = selection.get("value")
    if not isinstance(value, dict):
        return None
    target = value.get("target")
    attributes = value.get("attributes", {})
    if not isinstance(target, dict) or not isinstance(attributes, dict):
        return None
    if target.get("kind") != "item":
        return None
    key = target.get("key")
    if not isinstance(key, str) or not key.isdigit() or int(key) <= 0:
        return None
    return int(key), attributes


def _selected_relations(
    connection: sqlite3.Connection, *, quest_id: int, family: str
) -> list[dict[str, Any]]:
    fact_key = FAMILY_FACT_KEYS[family]
    rows = connection.execute(
        """
        SELECT og.fact_instance_key, og.id AS observation_group_id,
               cs.observation_id, cs.selection_policy, ds.source_key,
               so.source_revision, so.value_json
        FROM observation_groups AS og
        JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        JOIN source_observations AS so ON so.id = cs.observation_id
        JOIN data_sources AS ds ON ds.id = so.source_id
        WHERE og.subject_kind = 'quest' AND og.subject_key = ? AND og.fact_key = ?
        ORDER BY og.fact_instance_key
        """,
        (str(quest_id), fact_key),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        selection = {
            "fact_instance_key": str(row["fact_instance_key"]),
            "observation_group_id": int(row["observation_group_id"]),
            "observation_id": int(row["observation_id"]),
            "selection_policy": None
            if row["selection_policy"] is None
            else str(row["selection_policy"]),
            "source_key": str(row["source_key"]),
            "source_revision": str(row["source_revision"]),
            "value": json.loads(str(row["value_json"])),
        }
        parsed = _target_and_attributes(selection)
        if parsed is None:
            continue
        item_id, attributes = parsed
        selection["item_id"] = item_id
        selection["attributes"] = attributes
        result.append(selection)
    return result


def _source_slot(raw_identifier: Any) -> int | None:
    if not isinstance(raw_identifier, str):
        return None
    marker = ":slot:"
    if marker not in raw_identifier:
        return None
    raw_slot = raw_identifier.rsplit(marker, 1)[1]
    return int(raw_slot) if raw_slot.isdigit() and int(raw_slot) > 0 else None


def _matching_source_evidence(
    connection: sqlite3.Connection, selection: dict[str, Any]
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT so.id, ds.source_key, so.source_revision, so.raw_identifier, so.value_json,
               CASE WHEN cs.observation_id = so.id THEN 1 ELSE 0 END AS selected
        FROM source_observations AS so
        JOIN data_sources AS ds ON ds.id = so.source_id
        LEFT JOIN canonical_selections AS cs ON cs.observation_group_id = so.observation_group_id
        WHERE so.observation_group_id = ?
        ORDER BY ds.source_key, so.source_revision, so.raw_identifier, so.id
        """,
        (int(selection["observation_group_id"]),),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        if str(row["source_key"]) != str(selection["source_key"]):
            continue
        if str(row["source_revision"]) != str(selection["source_revision"]):
            continue
        value = json.loads(str(row["value_json"]))
        if value != selection["value"]:
            continue
        raw_identifier = None if row["raw_identifier"] is None else str(row["raw_identifier"])
        result.append(
            {
                "observation_id": int(row["id"]),
                "raw_identifier": raw_identifier,
                "source_slot": _source_slot(raw_identifier),
                "selected": bool(row["selected"]),
            }
        )
    return result


def _item_name(connection: sqlite3.Connection, item_id: int) -> str | None:
    row = connection.execute("SELECT name FROM items WHERE item_id = ?", (item_id,)).fetchone()
    return None if row is None else str(row["name"])


def _selection_public(selection: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_key": selection["source_key"],
        "source_revision": selection["source_revision"],
        "observation_id": selection["observation_id"],
        "selection_policy": selection["selection_policy"],
    }


def _quantity_status(family: str, value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        return "invalid"
    if family == "required_source":
        return "known" if value >= 0 else "invalid"
    return "known" if value > 0 else "invalid"


def _relation_rows(
    connection: sqlite3.Connection, *, quest_id: int, family: str
) -> list[dict[str, Any]]:
    selected_set = _selected_set(connection, quest_id=quest_id, family=family)
    complete_ids = _complete_member_ids(selected_set)
    rows: list[dict[str, Any]] = []
    for selection in _selected_relations(connection, quest_id=quest_id, family=family):
        item_id = int(selection["item_id"])
        if not selected_relation_is_active(
            selection, item_id=item_id, complete_member_ids=complete_ids
        ):
            continue
        attributes = selection["attributes"]
        value_key = "raw_source_count" if family == "required_source" else "quantity"
        value = attributes.get(value_key)
        name = _item_name(connection, item_id)
        source_evidence = _matching_source_evidence(connection, selection)
        source_slots = {
            int(slot)
            for slot in attributes.get("source_slots", [])
            if isinstance(slot, int) and not isinstance(slot, bool) and slot > 0
        }
        source_slots.update(
            int(evidence["source_slot"])
            for evidence in source_evidence
            if isinstance(evidence.get("source_slot"), int)
        )
        row = {
            "item_id": item_id,
            "item_name": name,
            "resolved": name is not None,
            value_key: value,
            "value_status": _quantity_status(family, value),
            "source_slots": sorted(source_slots),
            "selection": _selection_public(selection),
            "source_evidence": source_evidence,
        }
        if family == "required_item":
            row["objective_membership"] = (
                connection.execute(
                    "SELECT 1 FROM quest_item_objectives WHERE quest_id = ? AND item_id = ?",
                    (quest_id, item_id),
                ).fetchone()
                is not None
            )
        rows.append(row)
    rows.sort(key=lambda row: int(row["item_id"]))
    return rows


def _provided_item(connection: sqlite3.Connection, quest_id: int) -> dict[str, Any] | None:
    selected_set = _selected_set(connection, quest_id=quest_id, family="source_item_id")
    complete_ids = _complete_member_ids(selected_set)
    selection = _selected_fact(
        connection,
        quest_id=quest_id,
        fact_key=FAMILY_FACT_KEYS["source_item_id"],
        fact_instance_key="provided",
    )
    if selection is None:
        return None
    parsed = _target_and_attributes(selection)
    if parsed is None:
        return None
    item_id, attributes = parsed
    if not selected_relation_is_active(
        selection, item_id=item_id, complete_member_ids=complete_ids
    ):
        return None
    count_selection = _selected_fact(
        connection,
        quest_id=quest_id,
        fact_key=FAMILY_FACT_KEYS["source_item_count"],
        fact_instance_key=str(item_id),
    )
    quantity = None
    count_public = None
    if count_selection is not None:
        count_parsed = _target_and_attributes(count_selection)
        if count_parsed is not None and count_parsed[0] == item_id:
            quantity = count_parsed[1].get("quantity")
            count_public = _selection_public(count_selection)
    name = _item_name(connection, item_id)
    source_evidence = _matching_source_evidence(connection, selection)
    source_slots = {
        int(slot)
        for slot in attributes.get("source_slots", [])
        if isinstance(slot, int) and not isinstance(slot, bool) and slot > 0
    }
    source_slots.update(
        int(evidence["source_slot"])
        for evidence in source_evidence
        if isinstance(evidence.get("source_slot"), int)
    )
    return {
        "item_id": item_id,
        "item_name": name,
        "resolved": name is not None,
        "quantity": quantity if isinstance(quantity, int) and quantity > 0 else None,
        "quantity_status": "known" if isinstance(quantity, int) and quantity > 0 else "unknown",
        "source_slots": sorted(source_slots),
        "selection": _selection_public(selection),
        "source_evidence": source_evidence,
        "count_selection": count_public,
    }


def _conflicts(connection: sqlite3.Connection, quest_id: int) -> list[dict[str, Any]]:
    fact_keys = tuple(FAMILY_FACT_KEYS.values())
    placeholders = ",".join("?" for _ in fact_keys)
    rows = connection.execute(
        f"""
        SELECT og.id, og.fact_key, og.fact_instance_key,
               COUNT(DISTINCT so.value_json) AS distinct_value_count
        FROM observation_groups AS og
        JOIN source_observations AS so ON so.observation_group_id = og.id
        WHERE og.subject_kind = 'quest' AND og.subject_key = ?
          AND og.fact_key IN ({placeholders})
        GROUP BY og.id, og.fact_key, og.fact_instance_key
        HAVING COUNT(DISTINCT so.value_json) > 1
        ORDER BY og.fact_key, og.fact_instance_key
        """,
        (str(quest_id), *fact_keys),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        observations = connection.execute(
            """
            SELECT so.id, ds.source_key, so.source_revision, so.raw_identifier, so.value_json,
                   CASE WHEN cs.observation_id = so.id THEN 1 ELSE 0 END AS selected
            FROM source_observations AS so
            JOIN data_sources AS ds ON ds.id = so.source_id
            LEFT JOIN canonical_selections AS cs ON cs.observation_group_id = so.observation_group_id
            WHERE so.observation_group_id = ?
            ORDER BY ds.source_key, so.source_revision, so.id
            """,
            (int(row["id"]),),
        ).fetchall()
        result.append(
            {
                "fact_key": str(row["fact_key"]),
                "fact_instance_key": str(row["fact_instance_key"]),
                "distinct_value_count": int(row["distinct_value_count"]),
                "evidence": [
                    {
                        "observation_id": int(obs["id"]),
                        "source_key": str(obs["source_key"]),
                        "source_revision": str(obs["source_revision"]),
                        "raw_identifier": None
                        if obs["raw_identifier"] is None
                        else str(obs["raw_identifier"]),
                        "source_slot": _source_slot(obs["raw_identifier"]),
                        "selected": bool(obs["selected"]),
                        "value": json.loads(str(obs["value_json"])),
                    }
                    for obs in observations
                ],
            }
        )
    return result


def quest_item_facts_by_id(connection: sqlite3.Connection, quest_id: int) -> dict[str, Any]:
    """Return P3-T05 quest/item facts, resolution state, provenance and conflicts."""

    required_items = _relation_rows(connection, quest_id=quest_id, family="required_item")
    required_sources = _relation_rows(connection, quest_id=quest_id, family="required_source")
    rewards = _relation_rows(connection, quest_id=quest_id, family="reward_item")
    choices = _relation_rows(connection, quest_id=quest_id, family="choice_reward_item")
    objective_ids = {
        int(row[0])
        for row in connection.execute(
            "SELECT item_id FROM quest_item_objectives WHERE quest_id = ?", (quest_id,)
        ).fetchall()
    }
    required_ids = {int(row["item_id"]) for row in required_items}
    choice_parent = connection.execute(
        "SELECT choice_semantics, selected_member_count FROM quest_choice_reward_sets WHERE quest_id = ?",
        (quest_id,),
    ).fetchone()
    return {
        "required_items": required_items,
        "required_sources": required_sources,
        "provided_item": _provided_item(connection, quest_id),
        "guaranteed_rewards": rewards,
        "choice_rewards": {
            "semantics": "choose_one"
            if choice_parent is None
            else str(choice_parent["choice_semantics"]),
            "selected_member_count": len(choices)
            if choice_parent is None
            else int(choice_parent["selected_member_count"]),
            "materialized_member_count": int(
                connection.execute(
                    "SELECT COUNT(*) FROM quest_choice_reward_items WHERE quest_id = ?", (quest_id,)
                ).fetchone()[0]
            ),
            "items": choices,
        },
        "objective_membership": {
            "item_ids": sorted(objective_ids),
            "objective_only_item_ids": sorted(objective_ids - required_ids),
            "required_item_ids_not_in_objectives": sorted(required_ids - objective_ids),
            "equivalence_assumed": False,
        },
        "conflicts": _conflicts(connection, quest_id),
    }
