"""Provenance-aware item-template query surfaces for P6/P7 consumers."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

MATCH_KNOWN = "known_match"
NON_MATCH_KNOWN = "known_non_match"
MATCH_UNKNOWN = "unknown"
QUERY_STATES = (MATCH_KNOWN, NON_MATCH_KNOWN, MATCH_UNKNOWN)

COVERAGE_MATERIALIZED = "materialized"
COVERAGE_UNKNOWN = "unknown_not_materialized"
STAT_COVERAGE_COMPLETE = "complete_within_materialized_template"

RESISTANCE_FIELDS = (
    "holy_resistance",
    "fire_resistance",
    "nature_resistance",
    "frost_resistance",
    "shadow_resistance",
    "arcane_resistance",
)

ITEM_QUERY_SORT_FIELDS = (
    "item_id",
    "name",
    "quality",
    "class_id",
    "subclass_id",
    "inventory_type",
    "item_level",
    "required_level",
    "armor",
    "max_durability",
    *RESISTANCE_FIELDS,
)

_TEMPLATE_FIELDS = (
    "class_id",
    "subclass_id",
    "quality",
    "inventory_type",
    "item_level",
    "required_level",
    "armor",
    *RESISTANCE_FIELDS,
    "max_durability",
)


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
    """Compatibility result returned by the original P6 query proof."""

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


@dataclass(frozen=True)
class ItemPredicateState:
    """Evaluation of one query predicate for one canonical item identity."""

    predicate: str
    state: str
    actual: object | None


@dataclass(frozen=True)
class ItemCoverageState:
    """Coverage interpretation for the bounded migration-14 projection."""

    template: str
    stat_slots: str


@dataclass(frozen=True)
class ItemQueryResult:
    """One bounded P7 item query result, including coverage and provenance."""

    item_id: int
    name: str
    match_state: str
    coverage: ItemCoverageState
    class_id: int | None
    subclass_id: int | None
    quality: int | None
    inventory_type: int | None
    item_level: int | None
    required_level: int | None
    armor: int | None
    holy_resistance: int | None
    fire_resistance: int | None
    nature_resistance: int | None
    frost_resistance: int | None
    shadow_resistance: int | None
    arcane_resistance: int | None
    max_durability: int | None
    stats: tuple[tuple[int, int, int], ...]
    predicates: tuple[ItemPredicateState, ...]
    trace: tuple[ItemFactTrace, ...]


@dataclass(frozen=True)
class ItemQuerySummary:
    total_item_identities: int
    materialized_templates: int
    unknown_templates: int
    known_match_count: int
    known_non_match_count: int
    unknown_count: int
    returned_count: int
    limit: int


@dataclass(frozen=True)
class ItemQueryPage:
    summary: ItemQuerySummary
    results: tuple[ItemQueryResult, ...]


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


def _validate_nonnegative(name: str, value: int | None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _normalize_min_stats(min_stats: Mapping[int, int] | None) -> tuple[tuple[int, int], ...]:
    if not min_stats:
        return ()
    entries: list[tuple[int, int]] = []
    for stat_type, minimum in min_stats.items():
        if isinstance(stat_type, bool) or not isinstance(stat_type, int) or stat_type < 0:
            raise ValueError("stat type IDs must be non-negative integers")
        if isinstance(minimum, bool) or not isinstance(minimum, int):
            raise TypeError("stat minima must be integers")
        entries.append((stat_type, minimum))
    return tuple(sorted(entries))


def _normalize_states(include_states: Sequence[str]) -> tuple[str, ...]:
    if isinstance(include_states, str):
        raise TypeError("include_states must be a sequence of query states")
    if not include_states:
        raise ValueError("include_states must contain at least one query state")
    invalid = sorted(set(include_states) - set(QUERY_STATES))
    if invalid:
        raise ValueError(f"unsupported query state(s): {', '.join(invalid)}")
    return tuple(state for state in QUERY_STATES if state in include_states)


def _predicate_state(predicate: str, matches: bool, actual: object) -> ItemPredicateState:
    return ItemPredicateState(
        predicate=predicate,
        state=MATCH_KNOWN if matches else NON_MATCH_KNOWN,
        actual=actual,
    )


def _unknown_predicate(predicate: str) -> ItemPredicateState:
    return ItemPredicateState(predicate=predicate, state=MATCH_UNKNOWN, actual=None)


def _combined_state(predicates: Sequence[ItemPredicateState]) -> str:
    if any(predicate.state == NON_MATCH_KNOWN for predicate in predicates):
        return NON_MATCH_KNOWN
    if any(predicate.state == MATCH_UNKNOWN for predicate in predicates):
        return MATCH_UNKNOWN
    return MATCH_KNOWN


def _template_value(row: sqlite3.Row, field: str) -> int | None:
    value = row[field]
    return None if value is None else int(value)


def _evaluate_item(
    row: sqlite3.Row,
    stats: tuple[tuple[int, int, int], ...],
    *,
    item_id: int | None,
    name_contains: str | None,
    quality: int | None,
    class_id: int | None,
    subclass_id: int | None,
    inventory_type: int | None,
    min_item_level: int | None,
    max_item_level: int | None,
    min_required_level: int | None,
    max_required_level: int | None,
    min_armor: int | None,
    min_max_durability: int | None,
    resistance_minima: Mapping[str, int],
    normalized_stats: tuple[tuple[int, int], ...],
) -> tuple[str, tuple[ItemPredicateState, ...]]:
    predicates: list[ItemPredicateState] = []
    row_item_id = int(row["item_id"])
    row_name = str(row["name"])
    template_materialized = row["template_item_id"] is not None

    if item_id is not None:
        predicates.append(
            _predicate_state(f"item_id={item_id}", row_item_id == item_id, row_item_id)
        )
    if name_contains is not None:
        predicates.append(
            _predicate_state(
                f"name_contains={name_contains!r}",
                name_contains.casefold() in row_name.casefold(),
                row_name,
            )
        )

    scalar_predicates = (
        ("quality", quality, "eq"),
        ("class_id", class_id, "eq"),
        ("subclass_id", subclass_id, "eq"),
        ("inventory_type", inventory_type, "eq"),
        ("item_level", min_item_level, "min"),
        ("item_level", max_item_level, "max"),
        ("required_level", min_required_level, "min"),
        ("required_level", max_required_level, "max"),
        ("armor", min_armor, "min"),
        ("max_durability", min_max_durability, "min"),
    )
    for field, expected, operator in scalar_predicates:
        if expected is None:
            continue
        if operator == "eq":
            label = f"{field}={expected}"
        elif operator == "min":
            label = f"{field}>={expected}"
        else:
            label = f"{field}<={expected}"
        if not template_materialized:
            predicates.append(_unknown_predicate(label))
            continue
        actual = int(row[field])
        if operator == "eq":
            matches = actual == expected
        elif operator == "min":
            matches = actual >= expected
        else:
            matches = actual <= expected
        predicates.append(_predicate_state(label, matches, actual))

    for field in RESISTANCE_FIELDS:
        minimum = resistance_minima.get(field)
        if minimum is None:
            continue
        label = f"{field}>={minimum}"
        if not template_materialized:
            predicates.append(_unknown_predicate(label))
        else:
            actual = int(row[field])
            predicates.append(_predicate_state(label, actual >= minimum, actual))

    stats_by_type: dict[int, list[tuple[int, int]]] = {}
    for slot_index, stat_type, stat_value in stats:
        stats_by_type.setdefault(stat_type, []).append((slot_index, stat_value))
    for stat_type, minimum in normalized_stats:
        label = f"stat[{stat_type}]>={minimum}"
        if not template_materialized:
            predicates.append(_unknown_predicate(label))
            continue
        values = stats_by_type.get(stat_type, [])
        actual: object = tuple(values)
        matches = any(stat_value >= minimum for _, stat_value in values)
        predicates.append(_predicate_state(label, matches, actual))

    return _combined_state(predicates), tuple(predicates)


def _sort_results(
    results: list[ItemQueryResult], *, sort_by: str, descending: bool
) -> list[ItemQueryResult]:
    """Sort deterministically while keeping unknown sort values after known values."""

    known = [result for result in results if getattr(result, sort_by) is not None]
    unknown = [result for result in results if getattr(result, sort_by) is None]

    if sort_by == "name":
        known.sort(key=lambda result: (result.name.casefold(), result.item_id), reverse=descending)
    else:
        known.sort(
            key=lambda result: (getattr(result, sort_by), result.item_id),
            reverse=descending,
        )
    unknown.sort(key=lambda result: result.item_id)
    return known + unknown


def query_items(
    connection: sqlite3.Connection,
    *,
    item_id: int | None = None,
    name_contains: str | None = None,
    quality: int | None = None,
    class_id: int | None = None,
    subclass_id: int | None = None,
    inventory_type: int | None = None,
    min_item_level: int | None = None,
    max_item_level: int | None = None,
    min_required_level: int | None = None,
    max_required_level: int | None = None,
    min_armor: int | None = None,
    min_max_durability: int | None = None,
    min_holy_resistance: int | None = None,
    min_fire_resistance: int | None = None,
    min_nature_resistance: int | None = None,
    min_frost_resistance: int | None = None,
    min_shadow_resistance: int | None = None,
    min_arcane_resistance: int | None = None,
    min_stats: Mapping[int, int] | None = None,
    include_states: Sequence[str] = (MATCH_KNOWN,),
    sort_by: str = "item_id",
    descending: bool = False,
    limit: int = 100,
) -> ItemQueryPage:
    """Evaluate a bounded P7 item query with explicit three-state coverage semantics.

    A materialized ``item_templates`` row makes the bounded migration-14 scalar family known and its
    stat-slot set complete. If that row is absent, template/stat predicates are ``unknown`` rather
    than false. Identity/name predicates remain evaluable from the canonical ``items`` surface.

    Combined predicate semantics are conservative: any known-false predicate yields
    ``known_non_match``; otherwise any unknown predicate yields ``unknown``; otherwise the item is a
    ``known_match``. The summary counts all canonical item identities, while ``limit`` bounds
    only the
    returned states. Provenance traces are loaded only for returned materialized templates.
    """

    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    if sort_by not in ITEM_QUERY_SORT_FIELDS:
        raise ValueError(f"unsupported sort field: {sort_by}")
    if not isinstance(descending, bool):
        raise TypeError("descending must be a boolean")

    for name, value in (
        ("item_id", item_id),
        ("quality", quality),
        ("class_id", class_id),
        ("subclass_id", subclass_id),
        ("inventory_type", inventory_type),
        ("min_item_level", min_item_level),
        ("max_item_level", max_item_level),
        ("min_required_level", min_required_level),
        ("max_required_level", max_required_level),
        ("min_armor", min_armor),
        ("min_max_durability", min_max_durability),
        ("min_holy_resistance", min_holy_resistance),
        ("min_fire_resistance", min_fire_resistance),
        ("min_nature_resistance", min_nature_resistance),
        ("min_frost_resistance", min_frost_resistance),
        ("min_shadow_resistance", min_shadow_resistance),
        ("min_arcane_resistance", min_arcane_resistance),
    ):
        _validate_nonnegative(name, value)

    if name_contains is not None:
        if not isinstance(name_contains, str):
            raise TypeError("name_contains must be a string")
        name_contains = name_contains.strip()
        if not name_contains:
            raise ValueError("name_contains must not be empty")

    for low_name, low_value, high_name, high_value in (
        ("min_item_level", min_item_level, "max_item_level", max_item_level),
        (
            "min_required_level",
            min_required_level,
            "max_required_level",
            max_required_level,
        ),
    ):
        if low_value is not None and high_value is not None and low_value > high_value:
            raise ValueError(f"{low_name} must not exceed {high_name}")

    normalized_stats = _normalize_min_stats(min_stats)
    normalized_states = _normalize_states(include_states)
    resistance_minima = {
        field: value
        for field, value in (
            ("holy_resistance", min_holy_resistance),
            ("fire_resistance", min_fire_resistance),
            ("nature_resistance", min_nature_resistance),
            ("frost_resistance", min_frost_resistance),
            ("shadow_resistance", min_shadow_resistance),
            ("arcane_resistance", min_arcane_resistance),
        )
        if value is not None
    }

    rows = connection.execute(
        f"""
        SELECT
            i.item_id,
            i.name,
            t.item_id AS template_item_id,
            {', '.join(f't.{field} AS {field}' for field in _TEMPLATE_FIELDS)}
        FROM items AS i
        LEFT JOIN item_templates AS t ON t.item_id = i.item_id
        ORDER BY i.item_id
        """
    ).fetchall()

    stats_rows = connection.execute(
        """
        SELECT item_id, slot_index, stat_type, stat_value
        FROM item_stat_modifiers
        ORDER BY item_id, slot_index
        """
    ).fetchall()
    stats_by_item: dict[int, list[tuple[int, int, int]]] = {}
    for stat in stats_rows:
        stats_by_item.setdefault(int(stat["item_id"]), []).append(
            (int(stat["slot_index"]), int(stat["stat_type"]), int(stat["stat_value"]))
        )

    counts = {state: 0 for state in QUERY_STATES}
    materialized_templates = 0
    selected: list[ItemQueryResult] = []

    for row in rows:
        row_item_id = int(row["item_id"])
        stats = tuple(stats_by_item.get(row_item_id, ()))
        template_materialized = row["template_item_id"] is not None
        if template_materialized:
            materialized_templates += 1

        state, predicates = _evaluate_item(
            row,
            stats,
            item_id=item_id,
            name_contains=name_contains,
            quality=quality,
            class_id=class_id,
            subclass_id=subclass_id,
            inventory_type=inventory_type,
            min_item_level=min_item_level,
            max_item_level=max_item_level,
            min_required_level=min_required_level,
            max_required_level=max_required_level,
            min_armor=min_armor,
            min_max_durability=min_max_durability,
            resistance_minima=resistance_minima,
            normalized_stats=normalized_stats,
        )
        counts[state] += 1
        if state not in normalized_states:
            continue

        coverage = ItemCoverageState(
            template=COVERAGE_MATERIALIZED if template_materialized else COVERAGE_UNKNOWN,
            stat_slots=STAT_COVERAGE_COMPLETE if template_materialized else COVERAGE_UNKNOWN,
        )
        selected.append(
            ItemQueryResult(
                item_id=row_item_id,
                name=str(row["name"]),
                match_state=state,
                coverage=coverage,
                class_id=_template_value(row, "class_id"),
                subclass_id=_template_value(row, "subclass_id"),
                quality=_template_value(row, "quality"),
                inventory_type=_template_value(row, "inventory_type"),
                item_level=_template_value(row, "item_level"),
                required_level=_template_value(row, "required_level"),
                armor=_template_value(row, "armor"),
                holy_resistance=_template_value(row, "holy_resistance"),
                fire_resistance=_template_value(row, "fire_resistance"),
                nature_resistance=_template_value(row, "nature_resistance"),
                frost_resistance=_template_value(row, "frost_resistance"),
                shadow_resistance=_template_value(row, "shadow_resistance"),
                arcane_resistance=_template_value(row, "arcane_resistance"),
                max_durability=_template_value(row, "max_durability"),
                stats=stats,
                predicates=predicates,
                trace=(),
            )
        )

    selected = _sort_results(selected, sort_by=sort_by, descending=descending)[:limit]

    results = tuple(
        replace(
            result,
            trace=(
                _trace_for_item(connection, result.item_id)
                if result.coverage.template == COVERAGE_MATERIALIZED
                else ()
            ),
        )
        for result in selected
    )
    summary = ItemQuerySummary(
        total_item_identities=len(rows),
        materialized_templates=materialized_templates,
        unknown_templates=len(rows) - materialized_templates,
        known_match_count=counts[MATCH_KNOWN],
        known_non_match_count=counts[NON_MATCH_KNOWN],
        unknown_count=counts[MATCH_UNKNOWN],
        returned_count=len(results),
        limit=limit,
    )
    return ItemQueryPage(summary=summary, results=results)


def item_query_page_to_dict(page: ItemQueryPage) -> dict[str, object]:
    """Return a stable JSON-friendly representation of a P7 item query page."""

    return {
        "summary": {
            "total_item_identities": page.summary.total_item_identities,
            "materialized_templates": page.summary.materialized_templates,
            "unknown_templates": page.summary.unknown_templates,
            "known_match_count": page.summary.known_match_count,
            "known_non_match_count": page.summary.known_non_match_count,
            "unknown_count": page.summary.unknown_count,
            "returned_count": page.summary.returned_count,
            "limit": page.summary.limit,
        },
        "results": [
            {
                "item_id": result.item_id,
                "name": result.name,
                "match_state": result.match_state,
                "coverage": {
                    "template": result.coverage.template,
                    "stat_slots": result.coverage.stat_slots,
                },
                "template": {
                    field: getattr(result, field)
                    for field in (
                        "class_id",
                        "subclass_id",
                        "quality",
                        "inventory_type",
                        "item_level",
                        "required_level",
                        "armor",
                        *RESISTANCE_FIELDS,
                        "max_durability",
                    )
                },
                "stats": [
                    {
                        "slot_index": slot_index,
                        "stat_type": stat_type,
                        "stat_value": stat_value,
                    }
                    for slot_index, stat_type, stat_value in result.stats
                ],
                "predicates": [
                    {
                        "predicate": predicate.predicate,
                        "state": predicate.state,
                        "actual": predicate.actual,
                    }
                    for predicate in result.predicates
                ],
                "trace": [
                    {
                        "fact_key": fact.fact_key,
                        "value": fact.value,
                        "source_key": fact.source_key,
                        "source_revision": fact.source_revision,
                        "selection_policy": fact.selection_policy,
                        "selection_reason": fact.selection_reason,
                    }
                    for fact in result.trace
                ],
            }
            for result in page.results
        ],
    }


def query_item_templates(
    connection: sqlite3.Connection,
    *,
    max_required_level: int | None = None,
    inventory_type: int | None = None,
    min_stats: dict[int, int] | None = None,
    limit: int = 100,
) -> tuple[ItemTemplateSearchResult, ...]:
    """Query canonical P6 item-template facts without assigning guessed stat labels.

    ``min_stats`` maps raw source stat type IDs to minimum canonical values. Stat type labels
    remain a
    separate semantic concern; callers can map them only through a validated enum/DBC contract.

    This compatibility surface preserves the original P6 behavior. New consumers should use
    :func:`query_items` to receive explicit coverage and three-state predicate evaluation.
    """

    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    if max_required_level is not None and max_required_level < 0:
        raise ValueError("max_required_level must be non-negative")
    if inventory_type is not None and inventory_type < 0:
        raise ValueError("inventory_type must be non-negative")

    normalized_stats = _normalize_min_stats(min_stats)

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
        row_item_id = int(row["item_id"])
        stats = tuple(
            (int(stat["slot_index"]), int(stat["stat_type"]), int(stat["stat_value"]))
            for stat in connection.execute(
                """
                SELECT slot_index, stat_type, stat_value
                FROM item_stat_modifiers
                WHERE item_id = ?
                ORDER BY slot_index
                """,
                (row_item_id,),
            ).fetchall()
        )
        results.append(
            ItemTemplateSearchResult(
                item_id=row_item_id,
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
                trace=_trace_for_item(connection, row_item_id),
            )
        )
    return tuple(results)
