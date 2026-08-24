"""Quest-domain read models for the bounded P3 vertical slices."""

from __future__ import annotations

import sqlite3
from typing import Any


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


def _named_members(
    connection: sqlite3.Connection, *, table: str, quest_id: int
) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"""
        SELECT members.member_quest_id AS quest_id, q.name
        FROM {table} AS members
        JOIN quests AS q ON q.quest_id = members.member_quest_id
        WHERE members.quest_id = ?
        ORDER BY members.member_quest_id
        """,
        (quest_id,),
    ).fetchall()
    return [{"quest_id": int(row["quest_id"]), "name": str(row["name"])} for row in rows]


def _set_read_model(
    connection: sqlite3.Connection,
    *,
    quest_id: int,
    set_table: str,
    member_table: str,
    mode_column: str,
    default_mode: str,
) -> dict[str, Any]:
    parent = connection.execute(
        f"SELECT {mode_column}, selected_set_present, selected_member_count "
        f"FROM {set_table} WHERE quest_id = ?",
        (quest_id,),
    ).fetchone()
    members = _named_members(connection, table=member_table, quest_id=quest_id)
    selected_count = 0 if parent is None else int(parent["selected_member_count"])
    mode = default_mode if parent is None else str(parent[mode_column])
    return {
        "semantics": mode,
        "declared": False if parent is None else bool(parent["selected_set_present"]),
        "selected_member_count": selected_count,
        "materialized_member_count": len(members),
        "is_complete": selected_count == len(members),
        "members": members,
    }


def _follow_ups(connection: sqlite3.Connection, quest_id: int) -> list[dict[str, Any]]:
    """Derive follow-ups as the reverse of selected prerequisite membership under D-008."""

    rows = connection.execute(
        """
        SELECT members.quest_id, q.name
        FROM quest_prerequisite_set_members AS members
        JOIN quests AS q ON q.quest_id = members.quest_id
        WHERE members.member_quest_id = ?
        ORDER BY members.quest_id
        """,
        (quest_id,),
    ).fetchall()
    return [{"quest_id": int(row["quest_id"]), "name": str(row["name"])} for row in rows]



def _selected_provenance(
    connection: sqlite3.Connection,
    *,
    quest_id: int,
    fact_key: str,
    fact_instance_key: str = "",
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT cs.observation_id, cs.selection_policy, ds.source_key, so.source_revision
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
    return {
        "source_key": str(row["source_key"]),
        "source_revision": str(row["source_revision"]),
        "observation_id": int(row["observation_id"]),
        "selection_policy": (
            None if row["selection_policy"] is None else str(row["selection_policy"])
        ),
    }


def _member_provenance(
    connection: sqlite3.Connection, *, quest_id: int, fact_key: str, members: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [
        {
            "quest_id": int(member["quest_id"]),
            "selection": _selected_provenance(
                connection,
                quest_id=quest_id,
                fact_key=fact_key,
                fact_instance_key=str(member["quest_id"]),
            ),
        }
        for member in members
    ]

def quest_by_id(connection: sqlite3.Connection, quest_id: int) -> dict[str, Any] | None:
    """Return quest identity, P3 progression, explicit endpoints, and derived geography."""

    quest = connection.execute(
        """
        SELECT quest_id, name, quest_level, minimum_level, race_mask, class_mask
        FROM quests WHERE quest_id = ?
        """,
        (quest_id,),
    ).fetchone()
    if quest is None:
        return None

    endpoints: list[dict[str, Any]] = []
    for row in connection.execute(
        """
        SELECT e.endpoint_kind, e.creature_id AS entity_id, c.name AS entity_name
        FROM quest_creature_endpoints AS e
        JOIN creatures AS c ON c.creature_id = e.creature_id
        WHERE e.quest_id = ?
        ORDER BY e.endpoint_kind, e.creature_id
        """,
        (quest_id,),
    ).fetchall():
        entity_id = int(row["entity_id"])
        endpoints.append(
            {
                "endpoint_kind": str(row["endpoint_kind"]),
                "entity_type": "creature",
                "entity_id": entity_id,
                "entity_name": str(row["entity_name"]),
                "locations": _locations_for_creature(connection, entity_id),
            }
        )

    for row in connection.execute(
        """
        SELECT e.endpoint_kind, e.gameobject_id AS entity_id, g.name AS entity_name
        FROM quest_gameobject_endpoints AS e
        JOIN gameobjects AS g ON g.gameobject_id = e.gameobject_id
        WHERE e.quest_id = ?
        ORDER BY e.endpoint_kind, e.gameobject_id
        """,
        (quest_id,),
    ).fetchall():
        entity_id = int(row["entity_id"])
        endpoints.append(
            {
                "endpoint_kind": str(row["endpoint_kind"]),
                "entity_type": "gameobject",
                "entity_id": entity_id,
                "entity_name": str(row["entity_name"]),
                "locations": _locations_for_gameobject(connection, entity_id),
            }
        )

    endpoints.sort(
        key=lambda item: (item["endpoint_kind"], item["entity_type"], item["entity_id"])
    )
    prerequisite_set = _set_read_model(
        connection,
        quest_id=quest_id,
        set_table="quest_prerequisite_sets",
        member_table="quest_prerequisite_set_members",
        mode_column="requirement_mode",
        default_mode="any_of",
    )
    close_set = _set_read_model(
        connection,
        quest_id=quest_id,
        set_table="quest_close_sets",
        member_table="quest_close_set_members",
        mode_column="set_semantics",
        default_mode="exclusive_group_member_set",
    )
    return {
        "quest_id": int(quest["quest_id"]),
        "name": str(quest["name"]),
        "progression": {
            "quest_level": quest["quest_level"],
            "minimum_level": quest["minimum_level"],
            "race_mask": quest["race_mask"],
            "class_mask": quest["class_mask"],
            "prerequisite_set": prerequisite_set,
            "follow_ups": _follow_ups(connection, quest_id),
            "close_set": close_set,
            "provenance": {
                "quest_level": _selected_provenance(
                    connection, quest_id=quest_id, fact_key="quest_level"
                ),
                "minimum_level": _selected_provenance(
                    connection, quest_id=quest_id, fact_key="minimum_level"
                ),
                "race_mask": _selected_provenance(
                    connection, quest_id=quest_id, fact_key="race_mask"
                ),
                "class_mask": _selected_provenance(
                    connection, quest_id=quest_id, fact_key="class_mask"
                ),
                "prerequisite_set": _selected_provenance(
                    connection, quest_id=quest_id, fact_key="quest_prerequisite_set"
                ),
                "prerequisite_members": _member_provenance(
                    connection,
                    quest_id=quest_id,
                    fact_key="prerequisite",
                    members=prerequisite_set["members"],
                ),
                "close_set": _selected_provenance(
                    connection, quest_id=quest_id, fact_key="quest_close_set"
                ),
                "close_members": _member_provenance(
                    connection,
                    quest_id=quest_id,
                    fact_key="close_group_member",
                    members=close_set["members"],
                ),
            },
        },
        "endpoints": endpoints,
    }
