"""Provenance-aware P7 item acquisition/source exploration.

This module composes the validated P7-T01 item predicate evaluator with the P2
``find_item_sources()`` acquisition graph.  Acquisition predicates are positive-evidence
predicates: a known path can prove a match, while lack of a currently materialized path or
location remains unknown rather than becoming universal negative evidence.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from octogamedb.item_search import (
    _TEMPLATE_FIELDS,
    COVERAGE_MATERIALIZED,
    COVERAGE_UNKNOWN,
    ITEM_QUERY_SORT_FIELDS,
    MATCH_KNOWN,
    MATCH_UNKNOWN,
    NON_MATCH_KNOWN,
    QUERY_STATES,
    STAT_COVERAGE_COMPLETE,
    ItemCoverageState,
    ItemQueryPage,
    ItemQueryResult,
    ItemQuerySummary,
    _evaluate_item,
    _normalize_min_stats,
    _normalize_states,
    _sort_results,
    _template_value,
    _trace_for_item,
    _validate_nonnegative,
    item_query_page_to_dict,
    query_items,
)
from octogamedb.items import find_item_sources

ACQUISITION_NOT_FILTERED = "not_filtered"
ACQUISITION_PATH_KINDS = ("direct", "reference", "vendor")
ACQUISITION_SOURCE_KINDS = ("creature", "gameobject")


@dataclass(frozen=True)
class AcquisitionFilterState:
    state: str
    reason: str
    matching_source_count: int
    matching_path_count: int


@dataclass(frozen=True)
class ItemAcquisitionQueryResult:
    item: ItemQueryResult
    combined_match_state: str
    acquisition_filter: AcquisitionFilterState
    sources: tuple[dict[str, Any], ...]
    matching_sources: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ItemAcquisitionQuerySummary:
    total_item_identities: int
    materialized_templates: int
    unknown_templates: int
    materialized_acquisition_items: int
    known_match_count: int
    known_non_match_count: int
    unknown_count: int
    returned_count: int
    limit: int
    acquisition_filter_active: bool


@dataclass(frozen=True)
class ItemAcquisitionQueryPage:
    summary: ItemAcquisitionQuerySummary
    results: tuple[ItemAcquisitionQueryResult, ...]


@dataclass(frozen=True)
class _AcquisitionSpec:
    path_kinds: tuple[str, ...]
    source_kinds: tuple[str, ...]
    min_drop_chance: float | None
    zone_id: int | None
    map_id: int | None

    @property
    def active(self) -> bool:
        return bool(
            self.path_kinds
            or self.source_kinds
            or self.min_drop_chance is not None
            or self.zone_id is not None
            or self.map_id is not None
        )


def _normalize_choice_sequence(
    value: Sequence[str] | None,
    *,
    allowed: Sequence[str],
    name: str,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise TypeError(f"{name} must be a sequence")
    requested = set(value)
    invalid = sorted(requested - set(allowed))
    if invalid:
        raise ValueError(f"unsupported {name}: {', '.join(invalid)}")
    return tuple(entry for entry in allowed if entry in requested)


def _normalize_drop_chance(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("min_drop_chance must be a number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0.0 or normalized > 100.0:
        raise ValueError("min_drop_chance must be between 0 and 100")
    return normalized


def _build_acquisition_spec(
    *,
    path_kinds: Sequence[str] | None,
    source_kinds: Sequence[str] | None,
    min_drop_chance: float | None,
    zone_id: int | None,
    map_id: int | None,
) -> _AcquisitionSpec:
    _validate_nonnegative("zone_id", zone_id)
    _validate_nonnegative("map_id", map_id)
    return _AcquisitionSpec(
        path_kinds=_normalize_choice_sequence(
            path_kinds,
            allowed=ACQUISITION_PATH_KINDS,
            name="path kind(s)",
        ),
        source_kinds=_normalize_choice_sequence(
            source_kinds,
            allowed=ACQUISITION_SOURCE_KINDS,
            name="source kind(s)",
        ),
        min_drop_chance=_normalize_drop_chance(min_drop_chance),
        zone_id=zone_id,
        map_id=map_id,
    )


def _validate_common_query_options(
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
    min_holy_resistance: int | None,
    min_fire_resistance: int | None,
    min_nature_resistance: int | None,
    min_frost_resistance: int | None,
    min_shadow_resistance: int | None,
    min_arcane_resistance: int | None,
    include_states: Sequence[str],
    sort_by: str,
    descending: bool,
    limit: int,
) -> tuple[str | None, tuple[str, ...]]:
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

    normalized_name = name_contains
    if normalized_name is not None:
        if not isinstance(normalized_name, str):
            raise TypeError("name_contains must be a string")
        normalized_name = normalized_name.strip()
        if not normalized_name:
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

    return normalized_name, _normalize_states(include_states)


def _known_acquisition_item_ids(connection: sqlite3.Connection) -> set[int]:
    rows = connection.execute(
        """
        SELECT item_id FROM creature_loot
        UNION
        SELECT item_id FROM gameobject_loot
        UNION
        SELECT item_id FROM item_reference_loot
        UNION
        SELECT item_id FROM vendor_items
        """
    ).fetchall()
    return {int(row[0]) for row in rows}


def _all_item_evaluations(
    connection: sqlite3.Connection,
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
) -> tuple[list[ItemQueryResult], int]:
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

    materialized_templates = 0
    evaluated: list[ItemQueryResult] = []
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
        evaluated.append(
            ItemQueryResult(
                item_id=row_item_id,
                name=str(row["name"]),
                match_state=state,
                coverage=ItemCoverageState(
                    template=(
                        COVERAGE_MATERIALIZED if template_materialized else COVERAGE_UNKNOWN
                    ),
                    stat_slots=(
                        STAT_COVERAGE_COMPLETE if template_materialized else COVERAGE_UNKNOWN
                    ),
                ),
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
    return evaluated, materialized_templates


def _path_matches(path: Mapping[str, Any], spec: _AcquisitionSpec) -> bool:
    if spec.path_kinds and str(path["path_kind"]) not in spec.path_kinds:
        return False
    if spec.min_drop_chance is not None:
        chance = path.get("chance_percent")
        if chance is None or float(chance) < spec.min_drop_chance:
            return False
    return True


def _filter_sources(
    sources: Sequence[Mapping[str, Any]], spec: _AcquisitionSpec
) -> tuple[dict[str, Any], ...]:
    if not spec.active:
        return tuple(dict(source) for source in sources)

    matching: list[dict[str, Any]] = []
    for source in sources:
        if spec.source_kinds and str(source["source_kind"]) not in spec.source_kinds:
            continue
        if spec.zone_id is not None and source.get("zone_id") != spec.zone_id:
            continue
        if spec.map_id is not None and source.get("map_id") != spec.map_id:
            continue
        matched_paths = [
            dict(path)
            for path in source.get("acquisition_paths", ())
            if _path_matches(path, spec)
        ]
        if not matched_paths:
            continue
        copied = dict(source)
        copied["acquisition_paths"] = matched_paths
        distinct_chances = sorted(
            {
                float(path["chance_percent"])
                for path in matched_paths
                if path.get("chance_percent") is not None
            }
        )
        copied["chance_percent"] = distinct_chances[0] if len(distinct_chances) == 1 else None
        copied["relation_source"] = matched_paths[0].get("relation_source")
        matching.append(copied)
    return tuple(matching)


def _filter_state(
    sources: Sequence[Mapping[str, Any]], spec: _AcquisitionSpec
) -> tuple[AcquisitionFilterState, tuple[dict[str, Any], ...]]:
    matching = _filter_sources(sources, spec)
    if not spec.active:
        return (
            AcquisitionFilterState(
                state=ACQUISITION_NOT_FILTERED,
                reason="no_acquisition_filter_requested",
                matching_source_count=len(matching),
                matching_path_count=sum(len(source["acquisition_paths"]) for source in matching),
            ),
            matching,
        )
    if matching:
        return (
            AcquisitionFilterState(
                state=MATCH_KNOWN,
                reason="known_matching_acquisition_path",
                matching_source_count=len(matching),
                matching_path_count=sum(len(source["acquisition_paths"]) for source in matching),
            ),
            matching,
        )
    return (
        AcquisitionFilterState(
            state=MATCH_UNKNOWN,
            reason="no_known_matching_path_negative_not_proven",
            matching_source_count=0,
            matching_path_count=0,
        ),
        (),
    )


def _combined_state(item_state: str, acquisition_state: str, *, filter_active: bool) -> str:
    if not filter_active:
        return item_state
    if item_state == NON_MATCH_KNOWN:
        return NON_MATCH_KNOWN
    if item_state == MATCH_UNKNOWN:
        return MATCH_UNKNOWN
    return MATCH_KNOWN if acquisition_state == MATCH_KNOWN else MATCH_UNKNOWN


def _sources_for_item(connection: sqlite3.Connection, item_id: int) -> tuple[dict[str, Any], ...]:
    rows = find_item_sources(connection, item_id)
    if not rows:
        return ()
    return tuple(dict(source) for source in rows[0]["sources"])


def _item_result_to_dict(result: ItemQueryResult) -> dict[str, object]:
    materialized = result.coverage.template == COVERAGE_MATERIALIZED
    state_counts = {state: int(result.match_state == state) for state in QUERY_STATES}
    page = ItemQueryPage(
        summary=ItemQuerySummary(
            total_item_identities=1,
            materialized_templates=1 if materialized else 0,
            unknown_templates=0 if materialized else 1,
            known_match_count=state_counts[MATCH_KNOWN],
            known_non_match_count=state_counts[NON_MATCH_KNOWN],
            unknown_count=state_counts[MATCH_UNKNOWN],
            returned_count=1,
            limit=1,
        ),
        results=(result,),
    )
    return item_query_page_to_dict(page)["results"][0]  # type: ignore[index,return-value]


def query_item_acquisitions(
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
    path_kinds: Sequence[str] | None = None,
    source_kinds: Sequence[str] | None = None,
    min_drop_chance: float | None = None,
    zone_id: int | None = None,
    map_id: int | None = None,
    include_states: Sequence[str] = (MATCH_KNOWN,),
    sort_by: str = "item_id",
    descending: bool = False,
    limit: int = 100,
) -> ItemAcquisitionQueryPage:
    """Compose P7 item predicates with known P2 acquisition paths and P1 geography.

    Acquisition filters are existential positive-evidence filters over one known source/path pair.
    A matching path proves ``known_match``.  When no currently materialized path satisfies the
    requested acquisition/geography predicate, the acquisition state is ``unknown`` rather than
    ``known_non_match`` because P7-T02 does not claim universal P2/P1 completeness.
    """

    normalized_name, normalized_states = _validate_common_query_options(
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
        min_holy_resistance=min_holy_resistance,
        min_fire_resistance=min_fire_resistance,
        min_nature_resistance=min_nature_resistance,
        min_frost_resistance=min_frost_resistance,
        min_shadow_resistance=min_shadow_resistance,
        min_arcane_resistance=min_arcane_resistance,
        include_states=include_states,
        sort_by=sort_by,
        descending=descending,
        limit=limit,
    )
    spec = _build_acquisition_spec(
        path_kinds=path_kinds,
        source_kinds=source_kinds,
        min_drop_chance=min_drop_chance,
        zone_id=zone_id,
        map_id=map_id,
    )

    if not spec.active:
        item_page = query_items(
            connection,
            item_id=item_id,
            name_contains=normalized_name,
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
            min_holy_resistance=min_holy_resistance,
            min_fire_resistance=min_fire_resistance,
            min_nature_resistance=min_nature_resistance,
            min_frost_resistance=min_frost_resistance,
            min_shadow_resistance=min_shadow_resistance,
            min_arcane_resistance=min_arcane_resistance,
            min_stats=min_stats,
            include_states=normalized_states,
            sort_by=sort_by,
            descending=descending,
            limit=limit,
        )
        known_acquisition_items = _known_acquisition_item_ids(connection)
        wrapped: list[ItemAcquisitionQueryResult] = []
        for item in item_page.results:
            sources = _sources_for_item(connection, item.item_id)
            filter_state, matching = _filter_state(sources, spec)
            wrapped.append(
                ItemAcquisitionQueryResult(
                    item=item,
                    combined_match_state=item.match_state,
                    acquisition_filter=filter_state,
                    sources=sources,
                    matching_sources=matching,
                )
            )
        return ItemAcquisitionQueryPage(
            summary=ItemAcquisitionQuerySummary(
                total_item_identities=item_page.summary.total_item_identities,
                materialized_templates=item_page.summary.materialized_templates,
                unknown_templates=item_page.summary.unknown_templates,
                materialized_acquisition_items=len(known_acquisition_items),
                known_match_count=item_page.summary.known_match_count,
                known_non_match_count=item_page.summary.known_non_match_count,
                unknown_count=item_page.summary.unknown_count,
                returned_count=len(wrapped),
                limit=limit,
                acquisition_filter_active=False,
            ),
            results=tuple(wrapped),
        )

    normalized_stats = _normalize_min_stats(min_stats)
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
    evaluations, materialized_templates = _all_item_evaluations(
        connection,
        item_id=item_id,
        name_contains=normalized_name,
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
    known_acquisition_items = _known_acquisition_item_ids(connection)
    combined_by_item: dict[int, str] = {}
    counts = {state: 0 for state in QUERY_STATES}

    for item in evaluations:
        if item.match_state == MATCH_KNOWN and item.item_id in known_acquisition_items:
            sources = _sources_for_item(connection, item.item_id)
            acquisition_state, _ = _filter_state(sources, spec)
            acquisition_match_state = acquisition_state.state
        else:
            acquisition_match_state = MATCH_UNKNOWN
        combined = _combined_state(
            item.match_state,
            acquisition_match_state,
            filter_active=True,
        )
        combined_by_item[item.item_id] = combined
        counts[combined] += 1

    selected_items = [
        item for item in evaluations if combined_by_item[item.item_id] in normalized_states
    ]
    selected_items = _sort_results(
        selected_items,
        sort_by=sort_by,
        descending=descending,
    )[:limit]

    results: list[ItemAcquisitionQueryResult] = []
    for item in selected_items:
        traced_item = replace(
            item,
            trace=(
                _trace_for_item(connection, item.item_id)
                if item.coverage.template == COVERAGE_MATERIALIZED
                else ()
            ),
        )
        sources = (
            _sources_for_item(connection, item.item_id)
            if item.item_id in known_acquisition_items
            else ()
        )
        filter_state, matching = _filter_state(sources, spec)
        results.append(
            ItemAcquisitionQueryResult(
                item=traced_item,
                combined_match_state=combined_by_item[item.item_id],
                acquisition_filter=filter_state,
                sources=sources,
                matching_sources=matching,
            )
        )

    total = len(evaluations)
    return ItemAcquisitionQueryPage(
        summary=ItemAcquisitionQuerySummary(
            total_item_identities=total,
            materialized_templates=materialized_templates,
            unknown_templates=total - materialized_templates,
            materialized_acquisition_items=len(known_acquisition_items),
            known_match_count=counts[MATCH_KNOWN],
            known_non_match_count=counts[NON_MATCH_KNOWN],
            unknown_count=counts[MATCH_UNKNOWN],
            returned_count=len(results),
            limit=limit,
            acquisition_filter_active=True,
        ),
        results=tuple(results),
    )


def item_acquisition_page_to_dict(page: ItemAcquisitionQueryPage) -> dict[str, object]:
    """Return a stable JSON-friendly representation of a P7-T02 query page."""

    return {
        "summary": {
            "total_item_identities": page.summary.total_item_identities,
            "materialized_templates": page.summary.materialized_templates,
            "unknown_templates": page.summary.unknown_templates,
            "materialized_acquisition_items": page.summary.materialized_acquisition_items,
            "known_match_count": page.summary.known_match_count,
            "known_non_match_count": page.summary.known_non_match_count,
            "unknown_count": page.summary.unknown_count,
            "returned_count": page.summary.returned_count,
            "limit": page.summary.limit,
            "acquisition_filter_active": page.summary.acquisition_filter_active,
        },
        "results": [
            {
                "item": _item_result_to_dict(result.item),
                "combined_match_state": result.combined_match_state,
                "acquisition_filter": {
                    "state": result.acquisition_filter.state,
                    "reason": result.acquisition_filter.reason,
                    "matching_source_count": result.acquisition_filter.matching_source_count,
                    "matching_path_count": result.acquisition_filter.matching_path_count,
                },
                "sources": list(result.sources),
                "matching_sources": list(result.matching_sources),
            }
            for result in page.results
        ],
    }
