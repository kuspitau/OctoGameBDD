"""Small provenance-aware item-template query surface introduced by P6-T01."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ItemFactTrace:
    fact_key: str
    value: object
    source_key: str
    source_revision: str
    selection_policy: str | None
    selection_reason: str


@dataclass(frozen=True)
class ItemTemplateSearchResult:
    item_id: int
    name: str
    required_level: int
    item_level: int
    quality: int
    class_id: int
    subclass_id: int
    inventory_type: int
    armor: int
    max_durability: int
    stats: tuple[tuple[int, int, int], ...]
    trace: tuple[ItemFactTrace, ...]


def _trace_for_item(connection: sqlite3.Connection, item_id: int) -> tuple[ItemFactTrace, ...]:
    rows = connection.execute(
        """
        SELECT
            og.fact_key,
            so.value_json,
            ds.source_key,
            so.source_revision,
            cs.selection_policy,
            cs.selection_reason
        FROM observation_groups AS og
        JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
        JOIN source_observations AS so ON so.id = cs.observation_id
        JOIN data_sources AS ds ON ds.id = so.source_id
        WHERE og.subject_kind = 'item'
          AND og.subject_key = ?
          AND og.fact_key LIKE 'template.%'
        ORDER BY og.fact_key
        """,
        (str(item_id),),
    ).fetchall()
    return tuple(
        ItemFactTrace(
            fact_key=str(row["fact_key"]),
            value=json.loads(str(row["value_json"])),
            source_key=str(row["source_key"]),
            source_revision=str(row["source_revision"]),
            selection_policy=None
            if row["selection_policy"] is None
            else str(row["selection_policy"]),
            selection_reason=str(row["selection_reason"]),
        )
        for row in rows
    )


def query_item_templates(
    connection: sqlite3.Connection,
    *,
    max_required_level: int | None = None,
    inventory_type: int | None = None,
    min_stats: dict[int, int] | None = None,
    limit: int = 100,
) -> tuple[ItemTemplateSearchResult, ...]:
    """Query canonical P6 item-template facts without assigning guessed stat labels.

    ``min_stats`` maps raw source stat type IDs to minimum canonical values. Stat type labels remain a
    separate semantic concern; callers can map them only through a validated enum/DBC contract.
    """

    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    if max_required_level is not None and max_required_level < 0:
        raise ValueError("max_required_level must be non-negative")
    if inventory_type is not None and inventory_type < 0:
        raise ValueError("inventory_type must be non-negative")

    normalized_stats: tuple[tuple[int, int], ...] = ()
    if min_stats:
        entries: list[tuple[int, int]] = []
        for stat_type, minimum in min_stats.items():
            if isinstance(stat_type, bool) or not isinstance(stat_type, int) or stat_type < 0:
                raise ValueError("stat type IDs must be non-negative integers")
            if isinstance(minimum, bool) or not isinstance(minimum, int):
                raise TypeError("stat minima must be integers")
            entries.append((stat_type, minimum))
        normalized_stats = tuple(sorted(entries))

    clauses = ["1=1"]
    params: list[int] = []
    if max_required_level is not None:
        clauses.append("t.required_level <= ?")
        params.append(max_required_level)
    if inventory_type is not None:
        clauses.append("t.inventory_type = ?")
        params.append(inventory_type)
    for stat_type, minimum in normalized_stats:
        clauses.append(
            """
            EXISTS (
                SELECT 1
                FROM item_stat_modifiers AS sm
                WHERE sm.item_id = t.item_id
                  AND sm.stat_type = ?
                  AND sm.stat_value >= ?
            )
            """
        )
        params.extend((stat_type, minimum))
    params.append(limit)

    rows = connection.execute(
        f"""
        SELECT
            i.item_id, i.name,
            t.required_level, t.item_level, t.quality,
            t.class_id, t.subclass_id, t.inventory_type,
            t.armor, t.max_durability
        FROM item_templates AS t
        JOIN items AS i ON i.item_id = t.item_id
        WHERE {' AND '.join(clauses)}
        ORDER BY t.required_level, t.item_level, i.item_id
        LIMIT ?
        """,
        params,
    ).fetchall()

    results: list[ItemTemplateSearchResult] = []
    for row in rows:
        item_id = int(row["item_id"])
        stats = tuple(
            (int(stat["slot_index"]), int(stat["stat_type"]), int(stat["stat_value"]))
            for stat in connection.execute(
                """
                SELECT slot_index, stat_type, stat_value
                FROM item_stat_modifiers
                WHERE item_id = ?
                ORDER BY slot_index
                """,
                (item_id,),
            ).fetchall()
        )
        results.append(
            ItemTemplateSearchResult(
                item_id=item_id,
                name=str(row["name"]),
                required_level=int(row["required_level"]),
                item_level=int(row["item_level"]),
                quality=int(row["quality"]),
                class_id=int(row["class_id"]),
                subclass_id=int(row["subclass_id"]),
                inventory_type=int(row["inventory_type"]),
                armor=int(row["armor"]),
                max_durability=int(row["max_durability"]),
                stats=stats,
                trace=_trace_for_item(connection, item_id),
            )
        )
    return tuple(results)
