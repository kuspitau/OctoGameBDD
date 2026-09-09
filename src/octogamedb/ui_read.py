"""Read-only P8 UI adapter over the validated P7 zone query contract."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from octogamedb.db import DEFAULT_DB_PATH
from octogamedb.zone_search import (
    MATCH_KNOWN,
    MATCH_UNKNOWN,
    NON_MATCH_KNOWN,
    inspect_zone,
    query_zones,
    zone_query_page_to_dict,
)


@dataclass(frozen=True)
class ZoneSearchRequest:
    """Presentation-facing search request delegated unchanged to P7 semantics."""

    zone_id: int | None = None
    name_contains: str | None = None
    map_id: int | None = None
    map_name_contains: str | None = None
    include_unknown: bool = False
    include_non_matches: bool = False
    sort_by: str = "zone_id"
    descending: bool = False
    limit: int = 100


@dataclass(frozen=True)
class ZoneUiConfig:
    """Runtime-only UI configuration; no local absolute path is tracked in the repository."""

    db_path: Path = DEFAULT_DB_PATH
    entity_limit: int = 1000
    recipe_limit: int = 100


@contextmanager
def open_readonly_database(path: Path) -> Iterator[sqlite3.Connection]:
    """Open an existing SQLite file without creating or mutating it."""

    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"database not found: {path}")

    connection = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA schema_version").fetchone()
    try:
        yield connection
    finally:
        connection.close()


def _include_states(request: ZoneSearchRequest) -> tuple[str, ...]:
    states = [MATCH_KNOWN]
    if request.include_non_matches:
        states.append(NON_MATCH_KNOWN)
    if request.include_unknown:
        states.append(MATCH_UNKNOWN)
    return tuple(states)


def _source_label(row: Mapping[str, Any]) -> str:
    source = row.get("source")
    if not isinstance(source, Mapping):
        return ""
    name = source.get("name")
    kind = source.get("entity_kind")
    entity_id = source.get("entity_id")
    if name:
        return f"{name} ({kind}:{entity_id})"
    if kind is None or entity_id is None:
        return ""
    return f"{kind}:{entity_id}"


def project_zone_list(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Convert P7 zone search output into scalar-only NiceGUI table rows."""

    rows: list[dict[str, Any]] = []
    for result in payload.get("results", []):
        if not isinstance(result, Mapping):
            continue
        zone = result.get("zone")
        if not isinstance(zone, Mapping):
            continue
        map_info = zone.get("map")
        map_info = map_info if isinstance(map_info, Mapping) else {}
        parent = zone.get("parent_zone")
        parent = parent if isinstance(parent, Mapping) else {}
        rows.append(
            {
                "zone_id": int(zone["zone_id"]),
                "name": str(zone["name"]),
                "map_id": map_info.get("map_id"),
                "map_name": map_info.get("name") or "",
                "parent_zone_id": parent.get("zone_id"),
                "parent_zone_name": parent.get("name") or "",
                "match_state": str(result.get("match_state", MATCH_UNKNOWN)),
            }
        )
    summary = payload.get("summary")
    return {
        "summary": dict(summary) if isinstance(summary, Mapping) else {},
        "rows": rows,
    }


def _project_entities(detail: Mapping[str, Any]) -> list[dict[str, Any]]:
    world = detail.get("world_entities")
    if not isinstance(world, Mapping):
        return []
    rows: list[dict[str, Any]] = []
    for entity in world.get("results", []):
        if not isinstance(entity, Mapping):
            continue
        matching_spawns = entity.get("matching_spawns")
        matching_count = len(matching_spawns) if isinstance(matching_spawns, Sequence) else 0
        spawn_set = entity.get("spawn_set")
        spawn_set = spawn_set if isinstance(spawn_set, Mapping) else {}
        rows.append(
            {
                "entity_kind": str(entity.get("entity_kind", "")),
                "entity_id": int(entity["entity_id"]),
                "name": str(entity.get("name", "")),
                "matching_spawn_count": matching_count,
                "all_materialized_spawn_count": int(
                    entity.get("all_materialized_spawn_count", matching_count)
                ),
                "spawn_set_complete": bool(
                    spawn_set.get("is_complete_for_canonical_view", False)
                ),
            }
        )
    return rows


def _project_items(detail: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = detail.get("items")
    if not isinstance(items, Mapping):
        return []
    rows: list[dict[str, Any]] = []
    for item in items.get("results", []):
        if not isinstance(item, Mapping):
            continue
        paths = [path for path in item.get("paths", []) if isinstance(path, Mapping)]
        kinds = sorted({str(path.get("path_kind", "")) for path in paths})
        sources = sorted({_source_label(path) for path in paths if _source_label(path)})
        rows.append(
            {
                "item_id": int(item["item_id"]),
                "item_name": str(item.get("item_name") or ""),
                "path_count": len(paths),
                "path_kinds": ", ".join(kinds),
                "sources": "; ".join(sources),
            }
        )
    return rows


def _project_quests(detail: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    quests = detail.get("quests")
    quests = quests if isinstance(quests, Mapping) else {}
    result: dict[str, list[dict[str, Any]]] = {}
    for bucket in ("given", "finished", "objectives"):
        rows: list[dict[str, Any]] = []
        for quest in quests.get(bucket, []):
            if not isinstance(quest, Mapping):
                continue
            rows.append(
                {
                    "quest_id": int(quest["quest_id"]),
                    "quest_name": str(quest.get("quest_name") or ""),
                    "source": _source_label(quest),
                    "objective_kind": str(quest.get("objective_kind") or ""),
                    "relation_materialized": bool(quest.get("relation_materialized", True)),
                }
            )
        result[bucket] = rows
    return result


def _project_vendors(detail: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for vendor in detail.get("vendors", []):
        if not isinstance(vendor, Mapping):
            continue
        items = [item for item in vendor.get("items", []) if isinstance(item, Mapping)]
        rows.append(
            {
                "creature_id": int(vendor["creature_id"]),
                "name": str(vendor.get("name", "")),
                "item_count": len(items),
                "matching_spawn_count": len(vendor.get("matching_spawns", [])),
            }
        )
    return rows


def _project_trainers(detail: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    trainers = detail.get("trainers")
    trainers = trainers if isinstance(trainers, Mapping) else {}
    result: dict[str, list[dict[str, Any]]] = {"known": [], "unknown_relations": []}
    for bucket, rows in result.items():
        for trainer in trainers.get(bucket, []):
            if not isinstance(trainer, Mapping):
                continue
            rows.append(
                {
                    "recipe_id": int(trainer["recipe_id"]),
                    "recipe_name": str(trainer.get("recipe_name") or ""),
                    "trainer_kind": str(trainer.get("trainer_kind") or ""),
                    "native_trainer_entry": int(trainer["native_trainer_entry"]),
                    "source": _source_label(trainer),
                    "resolved": bool(trainer.get("resolved", False)),
                }
            )
    return result


def _project_recipe_page(key: str, label: str, page: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for result in page.get("results", []):
        if not isinstance(result, Mapping):
            continue
        recipe = result.get("recipe")
        if not isinstance(recipe, Mapping):
            continue
        rows.append(
            {
                "recipe_id": int(recipe["recipe_id"]),
                "name": str(recipe.get("name") or ""),
                "rank_text": str(recipe.get("rank_text") or ""),
                "match_state": str(result.get("match_state", MATCH_UNKNOWN)),
            }
        )
    summary = page.get("summary")
    return {
        "key": key,
        "label": label,
        "summary": dict(summary) if isinstance(summary, Mapping) else {},
        "rows": rows,
        "truncated_known_matches": bool(page.get("truncated_known_matches", False)),
    }


def _project_recipes(detail: Mapping[str, Any]) -> dict[str, Any]:
    recipes = detail.get("recipes")
    if not isinstance(recipes, Mapping):
        return {"included": False, "reason": "missing_recipe_projection", "sections": []}
    if not recipes.get("included", False):
        return {
            "included": False,
            "reason": str(recipes.get("reason", "recipe_projection_not_included")),
            "sections": [],
        }

    sections: list[dict[str, Any]] = []
    for key, label in (
        ("teaching_item", "Teaching item"),
        ("trainer", "Trainer"),
    ):
        page = recipes.get(key)
        if isinstance(page, Mapping):
            sections.append(_project_recipe_page(key, label, page))

    quest_pages = recipes.get("quest_reward_spell")
    quest_pages = quest_pages if isinstance(quest_pages, Mapping) else {}
    for role, label in (
        ("giver", "Quest reward spell — giver geography"),
        ("finisher", "Quest reward spell — finisher geography"),
        ("objective", "Quest reward spell — objective geography"),
    ):
        page = quest_pages.get(role)
        if isinstance(page, Mapping):
            sections.append(_project_recipe_page(f"quest_{role}", label, page))

    return {"included": True, "sections": sections}


def project_zone_detail(detail: Mapping[str, Any]) -> dict[str, Any]:
    """Build deterministic scalar table projections while preserving coverage semantics."""

    zone = detail.get("zone")
    zone = zone if isinstance(zone, Mapping) else {}
    world = detail.get("world_entities")
    world = world if isinstance(world, Mapping) else {}
    coverage = detail.get("coverage")
    coverage = coverage if isinstance(coverage, Mapping) else {}

    return {
        "zone": dict(zone),
        "coverage": dict(coverage),
        "world_summary": dict(world.get("summary", {})),
        "world_truncated": bool(world.get("truncated_known_matches", False)),
        "entities": _project_entities(detail),
        "items": _project_items(detail),
        "quests": _project_quests(detail),
        "vendors": _project_vendors(detail),
        "trainers": _project_trainers(detail),
        "recipes": _project_recipes(detail),
    }


class ZoneUiService:
    """Synchronous read service intended to run through NiceGUI ``run.io_bound``."""

    def __init__(self, config: ZoneUiConfig) -> None:
        self.config = config

    def search_zones(self, request: ZoneSearchRequest) -> dict[str, Any]:
        with open_readonly_database(self.config.db_path) as connection:
            page = query_zones(
                connection,
                zone_id=request.zone_id,
                name_contains=request.name_contains,
                map_id=request.map_id,
                map_name_contains=request.map_name_contains,
                include_states=_include_states(request),
                sort_by=request.sort_by,
                descending=request.descending,
                limit=request.limit,
            )
            return project_zone_list(zone_query_page_to_dict(page))

    def load_zone_detail(self, zone_id: int) -> dict[str, Any]:
        with open_readonly_database(self.config.db_path) as connection:
            detail = inspect_zone(
                connection,
                zone_id,
                entity_limit=self.config.entity_limit,
                recipe_limit=self.config.recipe_limit,
            )
            return project_zone_detail(detail)
