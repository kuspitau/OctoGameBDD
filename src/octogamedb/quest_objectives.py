"""Read model for P3-T04 quest objectives and their primitive/derived geography."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from octogamedb.importers.pfquest_quest_objectives import (
    AREA_TRIGGER_SET_FACT,
    AREA_TRIGGER_ZONE_FACT,
    ITEM_USE_CREATURE_FACT,
    ITEM_USE_GAMEOBJECT_FACT,
    ITEM_USE_TARGET_SET_FACT,
    OBJECTIVE_FACTS,
    OBJECTIVE_SUBTYPES,
    QUEST_SET_FACT,
)


def _selected(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_key: int,
    fact_key: str,
    fact_instance_key: str = "",
) -> tuple[Any, dict[str, Any]] | None:
    row = connection.execute(
        """
        SELECT so.value_json, cs.observation_id, cs.selection_policy,
               ds.source_key, so.source_revision
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


def _locations_for_creature(
    connection: sqlite3.Connection, creature_id: int
) -> list[dict[str, Any]]:
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
        (creature_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _locations_for_gameobject(
    connection: sqlite3.Connection, gameobject_id: int
) -> list[dict[str, Any]]:
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
        (gameobject_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _area_trigger_locations(
    connection: sqlite3.Connection, area_trigger_id: int
) -> dict[str, Any]:
    parent = connection.execute(
        """
        SELECT selected_entry_present, selected_coords_present, selected_location_count
        FROM area_triggers WHERE area_trigger_id = ?
        """,
        (area_trigger_id,),
    ).fetchone()
    rows = connection.execute(
        """
        SELECT l.source_index, l.zone_id, z.name AS zone_name, z.map_id,
               m.name AS map_name, l.coordinate_space, l.x, l.y
        FROM area_trigger_locations AS l
        JOIN zones AS z ON z.zone_id = l.zone_id
        LEFT JOIN maps AS m ON m.map_id = z.map_id
        WHERE l.area_trigger_id = ?
        ORDER BY l.source_index
        """,
        (area_trigger_id,),
    ).fetchall()
    locations: list[dict[str, Any]] = []
    for row in rows:
        entry = dict(row)
        selected = _selected(
            connection,
            subject_kind="area_trigger",
            subject_key=area_trigger_id,
            fact_key=AREA_TRIGGER_ZONE_FACT,
            fact_instance_key=str(row["source_index"]),
        )
        entry["provenance"] = None if selected is None else selected[1]
        locations.append(entry)
    set_selection = _selected(
        connection,
        subject_kind="area_trigger",
        subject_key=area_trigger_id,
        fact_key=AREA_TRIGGER_SET_FACT,
    )
    if parent is None:
        return {
            "entry_present": False,
            "coords_present": False,
            "selected_location_count": 0,
            "materialized_location_count": 0,
            "is_complete": False,
            "locations": [],
            "provenance": None if set_selection is None else set_selection[1],
        }
    selected_count = int(parent["selected_location_count"])
    return {
        "entry_present": bool(parent["selected_entry_present"]),
        "coords_present": bool(parent["selected_coords_present"]),
        "selected_location_count": selected_count,
        "materialized_location_count": len(locations),
        "is_complete": selected_count == len(locations),
        "locations": locations,
        "provenance": None if set_selection is None else set_selection[1],
    }


def _item_use_targets(connection: sqlite3.Connection, item_id: int) -> dict[str, Any]:
    set_selection = _selected(
        connection,
        subject_kind="item",
        subject_key=item_id,
        fact_key=ITEM_USE_TARGET_SET_FACT,
    )
    if set_selection is None:
        return {
            "declared": False,
            "selected_target_count": 0,
            "materialized_target_count": 0,
            "is_complete": True,
            "targets": [],
            "provenance": None,
        }
    value, provenance = set_selection
    if not isinstance(value, dict):
        raise TypeError(f"selected {ITEM_USE_TARGET_SET_FACT} for item {item_id} has invalid shape")
    raw_targets = value.get("targets")
    if not isinstance(raw_targets, list):
        raise TypeError(f"selected {ITEM_USE_TARGET_SET_FACT} for item {item_id} has invalid targets")

    desired: list[tuple[str, int, int]] = []
    for row in raw_targets:
        if not isinstance(row, dict):
            raise TypeError("selected item-use target member must be an object")
        kind = row.get("target_kind")
        target_id = row.get("target_id")
        spell_id = row.get("spell_id")
        if kind not in {"creature", "gameobject"}:
            raise TypeError("selected item-use target member has invalid target_kind")
        if any(isinstance(v, bool) or not isinstance(v, int) for v in (target_id, spell_id)):
            raise TypeError("selected item-use target member has invalid IDs")
        desired.append((kind, target_id, spell_id))

    targets: list[dict[str, Any]] = []
    for kind, target_id, expected_spell in sorted(desired):
        if kind == "creature":
            fact = ITEM_USE_CREATURE_FACT
            row = connection.execute(
                """
                SELECT t.spell_id, c.name
                FROM item_use_creature_targets AS t
                JOIN creatures AS c ON c.creature_id = t.creature_id
                WHERE t.item_id = ? AND t.creature_id = ?
                """,
                (item_id, target_id),
            ).fetchone()
            locations = _locations_for_creature(connection, target_id) if row is not None else []
        else:
            fact = ITEM_USE_GAMEOBJECT_FACT
            row = connection.execute(
                """
                SELECT t.spell_id, g.name
                FROM item_use_gameobject_targets AS t
                JOIN gameobjects AS g ON g.gameobject_id = t.gameobject_id
                WHERE t.item_id = ? AND t.gameobject_id = ?
                """,
                (item_id, target_id),
            ).fetchone()
            locations = _locations_for_gameobject(connection, target_id) if row is not None else []
        primitive = _selected(
            connection,
            subject_kind="item",
            subject_key=item_id,
            fact_key=fact,
            fact_instance_key=str(target_id),
        )
        targets.append(
            {
                "target_kind": kind,
                "target_id": target_id,
                "target_name": None if row is None else str(row["name"]),
                "spell_id": expected_spell if row is None else int(row["spell_id"]),
                "resolved": row is not None,
                "unresolved_reason": None if row is not None else "target_not_materialized",
                "geography_origin": f"derived_from_{kind}_spawns",
                "geography_resolved": bool(locations) if row is not None else False,
                "geography_unresolved_reason": (
                    None
                    if locations
                    else ("no_canonical_spawns" if row is not None else "target_not_materialized")
                ),
                "locations": locations,
                "provenance": None if primitive is None else primitive[1],
            }
        )

    # Include protected/custom materialized targets outside the selected complete set.
    desired_keys = {(kind, target_id) for kind, target_id, _ in desired}
    for kind, fact, table, column, name_table, name_column in (
        ("creature", ITEM_USE_CREATURE_FACT, "item_use_creature_targets", "creature_id", "creatures", "creature_id"),
        ("gameobject", ITEM_USE_GAMEOBJECT_FACT, "item_use_gameobject_targets", "gameobject_id", "gameobjects", "gameobject_id"),
    ):
        rows = connection.execute(
            f"""
            SELECT t.{column} AS target_id, t.spell_id, n.name
            FROM {table} AS t JOIN {name_table} AS n ON n.{name_column} = t.{column}
            WHERE t.item_id = ? ORDER BY t.{column}
            """,
            (item_id,),
        ).fetchall()
        for row in rows:
            target_id = int(row["target_id"])
            if (kind, target_id) in desired_keys:
                continue
            primitive = _selected(
                connection,
                subject_kind="item",
                subject_key=item_id,
                fact_key=fact,
                fact_instance_key=str(target_id),
            )
            targets.append(
                {
                    "target_kind": kind,
                    "target_id": target_id,
                    "target_name": str(row["name"]),
                    "spell_id": int(row["spell_id"]),
                    "resolved": True,
                    "selected_by_complete_set": False,
                    "geography_origin": f"derived_from_{kind}_spawns",
                    "locations": (
                        _locations_for_creature(connection, target_id)
                        if kind == "creature"
                        else _locations_for_gameobject(connection, target_id)
                    ),
                    "provenance": None if primitive is None else primitive[1],
                }
            )
    for target in targets:
        if "geography_resolved" not in target:
            locations = target.get("locations", [])
            target["geography_resolved"] = bool(locations)
            target["geography_unresolved_reason"] = (
                None if locations else "no_canonical_spawns"
            )
    targets.sort(key=lambda target: (target["target_kind"], target["target_id"]))
    materialized = sum(1 for target in targets if target.get("resolved"))
    return {
        "declared": bool(value.get("entry_present")),
        "selected_target_count": len(desired),
        "materialized_target_count": materialized,
        "is_complete": len(desired) == sum(
            1 for target in targets if target.get("resolved") and target.get("selected_by_complete_set", True)
        ),
        "targets": targets,
        "provenance": provenance,
    }


def _target_identity(
    connection: sqlite3.Connection, *, subtype: str, target_id: int
) -> tuple[bool, str | None]:
    if subtype == "U":
        row = connection.execute("SELECT name FROM creatures WHERE creature_id = ?", (target_id,)).fetchone()
    elif subtype == "O":
        row = connection.execute("SELECT name FROM gameobjects WHERE gameobject_id = ?", (target_id,)).fetchone()
    elif subtype in {"I", "IR"}:
        row = connection.execute("SELECT name FROM items WHERE item_id = ?", (target_id,)).fetchone()
    elif subtype == "Z":
        row = connection.execute("SELECT name FROM zones WHERE zone_id = ?", (target_id,)).fetchone()
    elif subtype == "A":
        row = connection.execute(
            "SELECT selected_entry_present FROM area_triggers WHERE area_trigger_id = ?",
            (target_id,),
        ).fetchone()
        return (row is not None and bool(row["selected_entry_present"]), None)
    else:
        raise AssertionError(subtype)
    return (row is not None, None if row is None else str(row["name"]))


def _is_materialized(
    connection: sqlite3.Connection, *, subtype: str, quest_id: int, target_id: int
) -> bool:
    _, _, table, column, _ = OBJECTIVE_FACTS[subtype]
    return connection.execute(
        f"SELECT 1 FROM {table} WHERE quest_id = ? AND {column} = ?",
        (quest_id, target_id),
    ).fetchone() is not None


def _zone_context(connection: sqlite3.Connection, zone_id: int) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT z.zone_id, z.name AS zone_name, z.map_id, m.name AS map_name
        FROM zones AS z LEFT JOIN maps AS m ON m.map_id = z.map_id
        WHERE z.zone_id = ?
        """,
        (zone_id,),
    ).fetchone()
    return None if row is None else dict(row)


def _entry(
    connection: sqlite3.Connection,
    *,
    quest_id: int,
    subtype: str,
    target_id: int,
    selected_by_complete_set: bool,
) -> dict[str, Any]:
    fact_key, target_kind, *_ = OBJECTIVE_FACTS[subtype]
    identity_exists, name = _target_identity(connection, subtype=subtype, target_id=target_id)
    materialized = _is_materialized(
        connection, subtype=subtype, quest_id=quest_id, target_id=target_id
    )
    primitive = _selected(
        connection,
        subject_kind="quest",
        subject_key=quest_id,
        fact_key=fact_key,
        fact_instance_key=str(target_id),
    )
    row: dict[str, Any] = {
        "source_subtype": subtype,
        "target_kind": target_kind,
        "target_id": target_id,
        "target_name": name,
        "selected_by_complete_set": selected_by_complete_set,
        "resolved": materialized,
        "unresolved_reason": None,
        "provenance": None if primitive is None else primitive[1],
    }
    if not materialized:
        row["unresolved_reason"] = (
            f"missing_{target_kind}_identity" if not identity_exists else "primitive_relation_not_materialized"
        )

    if subtype == "U":
        row["geography_origin"] = "derived_from_creature_spawns"
        locations = _locations_for_creature(connection, target_id) if identity_exists else []
        row["locations"] = locations
        row["geography_resolved"] = bool(locations)
        row["geography_unresolved_reason"] = (
            None if locations else ("no_canonical_spawns" if identity_exists else "missing_identity")
        )
    elif subtype == "O":
        row["geography_origin"] = "derived_from_gameobject_spawns"
        locations = _locations_for_gameobject(connection, target_id) if identity_exists else []
        row["locations"] = locations
        row["geography_resolved"] = bool(locations)
        row["geography_unresolved_reason"] = (
            None if locations else ("no_canonical_spawns" if identity_exists else "missing_identity")
        )
    elif subtype == "A":
        row["geography_origin"] = "source_backed_area_trigger_coordinates"
        area = _area_trigger_locations(connection, target_id)
        row["area_trigger"] = area
        row["geography_resolved"] = bool(area["is_complete"])
        row["geography_unresolved_reason"] = (
            None if area["is_complete"] else "area_trigger_locations_incomplete"
        )
    elif subtype == "Z":
        row["geography_origin"] = "direct_zone_objective_context"
        zone = _zone_context(connection, target_id)
        row["zone"] = zone
        row["geography_resolved"] = zone is not None
        row["geography_unresolved_reason"] = None if zone is not None else "missing_zone_identity"
    elif subtype == "IR":
        row["geography_origin"] = "item_use_targets_then_derived_target_spawns"
        item_use = _item_use_targets(connection, target_id) if identity_exists else None
        row["item_use_targets"] = item_use
        row["geography_resolved"] = bool(item_use and item_use["is_complete"])
        row["geography_unresolved_reason"] = (
            None if row["geography_resolved"] else "item_use_targets_incomplete_or_missing"
        )
    else:
        row["geography_origin"] = "none"
        row["geography_resolved"] = None
        row["geography_unresolved_reason"] = None
    return row


def quest_objectives_by_id(connection: sqlite3.Connection, quest_id: int) -> dict[str, Any] | None:
    """Return P3-T04 objectives, unresolved members, provenance, and objective geography."""

    if connection.execute("SELECT 1 FROM quests WHERE quest_id = ?", (quest_id,)).fetchone() is None:
        return None
    set_selection = _selected(
        connection,
        subject_kind="quest",
        subject_key=quest_id,
        fact_key=QUEST_SET_FACT,
    )
    if set_selection is None:
        return {
            "declared": False,
            "selected_member_count": 0,
            "materialized_member_count": 0,
            "is_complete": True,
            "source_lists": {subtype: None for subtype in OBJECTIVE_SUBTYPES},
            "objectives": [],
            "provenance": None,
        }
    value, provenance = set_selection
    if not isinstance(value, dict) or not isinstance(value.get("obj_present"), bool):
        raise TypeError(f"selected {QUEST_SET_FACT} for quest {quest_id} has invalid shape")
    subtypes = value.get("subtypes")
    if not isinstance(subtypes, dict):
        raise TypeError(f"selected {QUEST_SET_FACT} for quest {quest_id} has invalid subtypes")

    desired: dict[str, tuple[int, ...]] = {}
    source_lists: dict[str, list[int] | None] = {}
    for subtype in OBJECTIVE_SUBTYPES:
        raw = subtypes.get(subtype)
        if raw is None:
            source_lists[subtype] = None
            desired[subtype] = ()
            continue
        if not isinstance(raw, list) or any(
            isinstance(target_id, bool) or not isinstance(target_id, int) or target_id <= 0
            for target_id in raw
        ):
            raise TypeError(f"selected {QUEST_SET_FACT}.{subtype} for quest {quest_id} is invalid")
        source_lists[subtype] = list(raw)
        desired[subtype] = tuple(sorted(set(raw)))

    objectives = [
        _entry(
            connection,
            quest_id=quest_id,
            subtype=subtype,
            target_id=target_id,
            selected_by_complete_set=True,
        )
        for subtype in OBJECTIVE_SUBTYPES
        for target_id in desired[subtype]
    ]

    # Protected primitive selections may intentionally remain materialized even when not present in
    # the selected pfQuest/Turtle complete set. Surface them explicitly rather than hiding them.
    for subtype in OBJECTIVE_SUBTYPES:
        _, _, table, column, _ = OBJECTIVE_FACTS[subtype]
        rows = connection.execute(
            f"SELECT {column} FROM {table} WHERE quest_id = ? ORDER BY {column}", (quest_id,)
        ).fetchall()
        desired_ids = set(desired[subtype])
        for materialized_row in rows:
            target_id = int(materialized_row[0])
            if target_id in desired_ids:
                continue
            objectives.append(
                _entry(
                    connection,
                    quest_id=quest_id,
                    subtype=subtype,
                    target_id=target_id,
                    selected_by_complete_set=False,
                )
            )
    objectives.sort(key=lambda row: (OBJECTIVE_SUBTYPES.index(row["source_subtype"]), row["target_id"]))
    selected_count = sum(len(ids) for ids in desired.values())
    selected_materialized = sum(
        1
        for row in objectives
        if row["selected_by_complete_set"] and row["resolved"]
    )
    materialized_count = sum(1 for row in objectives if row["resolved"])
    return {
        "declared": bool(value["obj_present"]),
        "selected_member_count": selected_count,
        "materialized_member_count": materialized_count,
        "selected_materialized_member_count": selected_materialized,
        "is_complete": selected_count == selected_materialized,
        "source_lists": source_lists,
        "objectives": objectives,
        "provenance": provenance,
    }
