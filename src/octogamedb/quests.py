"""Quest-domain read models for the bounded P3 vertical slice."""

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


def quest_by_id(connection: sqlite3.Connection, quest_id: int) -> dict[str, Any] | None:
    """Return quest identity, explicit endpoints, and geography derived from P1 spawns."""

    quest = connection.execute(
        "SELECT quest_id, name FROM quests WHERE quest_id = ?", (quest_id,)
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
    return {
        "quest_id": int(quest["quest_id"]),
        "name": str(quest["name"]),
        "endpoints": endpoints,
    }
