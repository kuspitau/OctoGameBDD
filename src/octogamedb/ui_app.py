"""NiceGUI local/browser shell for the read-only P8 zone explorer."""

from __future__ import annotations

import argparse
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from nicegui import run, ui

from octogamedb.db import DEFAULT_DB_PATH
from octogamedb.ui_read import ZoneSearchRequest, ZoneUiConfig, ZoneUiService

APP_TITLE = "OctoGameDB — Zone Explorer"


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _columns(*definitions: tuple[str, str]) -> list[dict[str, Any]]:
    return [
        {"name": name, "label": label, "field": name, "align": "left"}
        for name, label in definitions
    ]


def _empty_note() -> None:
    ui.label(
        "No known positive evidence is returned by this bounded projection. "
        "This is not a universal negative claim."
    ).classes("text-caption text-grey-7")


def _render_table(
    *,
    title: str,
    rows: Sequence[Mapping[str, Any]],
    columns: list[dict[str, Any]],
    row_key: str,
) -> None:
    with ui.expansion(title, icon="table_view", value=bool(rows)).classes("w-full"):
        if not rows:
            _empty_note()
            return
        ui.table(
            columns=columns,
            rows=[dict(row) for row in rows],
            row_key=row_key,
            pagination={"rowsPerPage": 25},
        ).classes("w-full")


def _render_error(error: Exception, db_path: Path) -> None:
    with ui.card().classes("w-full"):
        ui.label("Database unavailable").classes("text-h6")
        ui.label(str(error)).classes("text-body2")
        ui.label(f"Configured path: {db_path}").classes("text-caption")
        ui.label(
            "The UI opens SQLite in read-only mode and will not create a missing database."
        ).classes("text-caption")


def _render_zone_list(view: Mapping[str, Any], container: Any) -> None:
    container.clear()
    with container:
        summary = view.get("summary")
        summary = summary if isinstance(summary, Mapping) else {}
        rows = view.get("rows")
        rows = rows if isinstance(rows, Sequence) else []
        with ui.row().classes("items-center gap-4"):
            ui.label(f"Returned: {summary.get('returned_count', len(rows))}")
            ui.label(f"Known matches: {summary.get('known_match_count', '?')}")
            ui.label(f"Unknown: {summary.get('unknown_count', '?')}")
        if not rows:
            ui.label("No rows matched the selected query states.").classes("text-body2")
            return

        table = ui.table(
            columns=_columns(
                ("zone_id", "Zone ID"),
                ("name", "Zone"),
                ("map_id", "Map ID"),
                ("map_name", "Map"),
                ("parent_zone_name", "Parent zone"),
                ("match_state", "State"),
                ("action", "Open"),
            ),
            rows=[dict(row) for row in rows],
            row_key="zone_id",
            pagination={"rowsPerPage": 25},
        ).classes("w-full")
        with table.add_slot("body-cell-action"), table.cell("action"):
            ui.button("Open", icon="open_in_new").props("flat dense").mark(
                "open-zone-action"
            ).on(
                "click",
                js_handler="() => emit(props.row.zone_id)",
                handler=lambda event: ui.navigate.to(f"/zone/{int(event.args)}"),
            )


def _render_coverage(view: Mapping[str, Any]) -> None:
    coverage = view.get("coverage")
    coverage = coverage if isinstance(coverage, Mapping) else {}
    world_summary = view.get("world_summary")
    world_summary = world_summary if isinstance(world_summary, Mapping) else {}

    with ui.card().classes("w-full"):
        ui.label(f"Coverage state: {coverage.get('state', 'unknown')}").classes("text-h6")
        ui.label(str(coverage.get("semantics", "Coverage is incomplete or unknown.")))
        with ui.row().classes("gap-4 flex-wrap"):
            ui.label(
                "Negative claim authorized: "
                f"{bool(coverage.get('negative_claim_authorized', False))}"
            )
            ui.label(
                "Unknown entity geography: "
                f"{coverage.get('world_entity_unknown_geography_count', '?')}"
            )
            ui.label(
                "Known non-matches: "
                f"{coverage.get('world_entity_known_non_match_count', '?')}"
            )
            ui.label(f"Returned entities: {world_summary.get('returned_count', '?')}")
        if bool(view.get("world_truncated", False)) or bool(
            coverage.get("world_entity_projection_truncated", False)
        ):
            ui.label(
                "World-entity projection is truncated by the configured entity limit."
            ).classes("text-body2")
        unresolved = int(coverage.get("unresolved_trainer_relation_count", 0) or 0)
        if unresolved:
            ui.label(f"Unresolved trainer relations: {unresolved}").classes("text-body2")
        recipe_unknown = coverage.get("recipe_unknown_geography_counts")
        if isinstance(recipe_unknown, Mapping):
            text = ", ".join(f"{key}={value}" for key, value in recipe_unknown.items())
            ui.label(f"Recipe geography remaining unknown: {text}").classes("text-body2")


def _render_recipe_sections(recipes: Mapping[str, Any]) -> None:
    if not recipes.get("included", False):
        with ui.expansion("Recipe evidence", icon="restaurant", value=True).classes("w-full"):
            ui.label(f"Recipe projection not included: {recipes.get('reason', 'unknown reason')}")
        return

    for section in recipes.get("sections", []):
        if not isinstance(section, Mapping):
            continue
        label = str(section.get("label", "Recipe evidence"))
        rows = section.get("rows")
        rows = rows if isinstance(rows, Sequence) else []
        summary = section.get("summary")
        summary = summary if isinstance(summary, Mapping) else {}
        with ui.expansion(label, icon="restaurant", value=bool(rows)).classes("w-full"):
            ui.label(
                "Known matches: "
                f"{summary.get('known_match_count', '?')} · "
                f"unknown: {summary.get('unknown_count', '?')} · "
                f"returned: {summary.get('returned_count', len(rows))}"
            ).classes("text-caption")
            if bool(section.get("truncated_known_matches", False)):
                ui.label("Known recipe matches are truncated by the recipe limit.").classes(
                    "text-caption"
                )
            if not rows:
                _empty_note()
                continue
            ui.table(
                columns=_columns(
                    ("recipe_id", "Recipe ID"),
                    ("name", "Recipe"),
                    ("rank_text", "Rank"),
                    ("match_state", "State"),
                ),
                rows=[dict(row) for row in rows],
                row_key="recipe_id",
                pagination={"rowsPerPage": 25},
            ).classes("w-full")


def _render_zone_detail(view: Mapping[str, Any], container: Any) -> None:
    container.clear()
    zone = view.get("zone")
    zone = zone if isinstance(zone, Mapping) else {}
    with container:
        ui.label(f"{zone.get('name', 'Zone')} · ID {zone.get('zone_id', '?')}").classes("text-h4")
        map_info = zone.get("map")
        map_info = map_info if isinstance(map_info, Mapping) else {}
        parent = zone.get("parent_zone")
        parent = parent if isinstance(parent, Mapping) else {}
        ui.label(
            f"Map: {map_info.get('name', 'unknown')} ({map_info.get('map_id', 'unknown')}) · "
            f"Parent: {parent.get('name', 'none')}"
        ).classes("text-subtitle2")

        _render_coverage(view)
        _render_table(
            title="World entities",
            rows=view.get("entities", []),
            columns=_columns(
                ("entity_kind", "Kind"),
                ("entity_id", "ID"),
                ("name", "Name"),
                ("matching_spawn_count", "Spawns here"),
                ("all_materialized_spawn_count", "All materialized spawns"),
                ("spawn_set_complete", "Complete selected spawn set"),
            ),
            row_key="entity_id",
        )
        _render_table(
            title="Obtainable item evidence",
            rows=view.get("items", []),
            columns=_columns(
                ("item_id", "Item ID"),
                ("item_name", "Item"),
                ("path_count", "Paths"),
                ("path_kinds", "Kinds"),
                ("sources", "Sources"),
            ),
            row_key="item_id",
        )

        quests = view.get("quests")
        quests = quests if isinstance(quests, Mapping) else {}
        for bucket, label in (
            ("given", "Quests given here"),
            ("finished", "Quests finished here"),
            ("objectives", "Quest objectives here"),
        ):
            _render_table(
                title=label,
                rows=quests.get(bucket, []),
                columns=_columns(
                    ("quest_id", "Quest ID"),
                    ("quest_name", "Quest"),
                    ("source", "Source entity"),
                    ("objective_kind", "Objective kind"),
                    ("relation_materialized", "Relation materialized"),
                ),
                row_key="quest_id",
            )

        _render_table(
            title="Vendors",
            rows=view.get("vendors", []),
            columns=_columns(
                ("creature_id", "Creature ID"),
                ("name", "Vendor"),
                ("item_count", "Known items"),
                ("matching_spawn_count", "Spawns here"),
            ),
            row_key="creature_id",
        )

        trainers = view.get("trainers")
        trainers = trainers if isinstance(trainers, Mapping) else {}
        for bucket, label in (
            ("known", "Resolved trainers"),
            ("unknown_relations", "Unresolved trainer relations"),
        ):
            _render_table(
                title=label,
                rows=trainers.get(bucket, []),
                columns=_columns(
                    ("recipe_id", "Recipe ID"),
                    ("recipe_name", "Recipe"),
                    ("trainer_kind", "Trainer kind"),
                    ("native_trainer_entry", "Native trainer entry"),
                    ("source", "Source entity"),
                    ("resolved", "Resolved"),
                ),
                row_key="recipe_id",
            )

        recipes = view.get("recipes")
        recipes = recipes if isinstance(recipes, Mapping) else {}
        _render_recipe_sections(recipes)


def register_pages(config: ZoneUiConfig, service: ZoneUiService | None = None) -> None:
    """Register the bounded P8 zone-explorer pages for runtime and UI simulation tests."""

    zone_service = service or ZoneUiService(config)

    @ui.page("/", title=APP_TITLE, response_timeout=15.0)
    async def zone_index() -> None:
        ui.label(APP_TITLE).classes("text-h3")
        ui.label(f"Read-only database: {config.db_path}").classes("text-caption")

        with ui.card().classes("w-full"):
            ui.label("Zone search").classes("text-h6")
            with ui.row().classes("gap-3 flex-wrap items-end"):
                zone_id = ui.number("Zone ID", min=0, step=1).mark("zone-id-input")
                name = ui.input("Zone name contains").mark("zone-name-input")
                map_id = ui.number("Map ID", min=0, step=1).mark("map-id-input")
                map_name = ui.input("Map name contains").mark("map-name-input")
                sort_by = ui.select(
                    {
                        "zone_id": "Zone ID",
                        "name": "Zone name",
                        "map_id": "Map ID",
                        "map_name": "Map name",
                    },
                    value="zone_id",
                    label="Sort by",
                ).mark("sort-by-control")
                descending = ui.switch("Descending").mark("descending-control")
                include_unknown = ui.switch("Include unknown").mark("include-unknown-control")
                include_non_matches = ui.switch("Include known non-matches").mark(
                    "include-non-matches-control"
                )
                limit = ui.number("Limit", value=100, min=1, max=1000, step=1)

            ui.label(
                "Search fields and limit apply with Enter/Search; sort and state controls apply "
                "immediately."
            ).classes("text-caption text-grey-7")
            status = ui.row().classes("items-center gap-2")
            results = ui.column().classes("w-full")

            async def search() -> None:
                status.clear()
                with status:
                    ui.spinner(size="sm")
                    ui.label("Loading zone list…")
                try:
                    request = ZoneSearchRequest(
                        zone_id=_optional_int(zone_id.value),
                        name_contains=_optional_text(name.value),
                        map_id=_optional_int(map_id.value),
                        map_name_contains=_optional_text(map_name.value),
                        include_unknown=bool(include_unknown.value),
                        include_non_matches=bool(include_non_matches.value),
                        sort_by=str(sort_by.value),
                        descending=bool(descending.value),
                        limit=int(limit.value or 100),
                    )
                    view = await run.io_bound(zone_service.search_zones, request)
                except (FileNotFoundError, sqlite3.DatabaseError, TypeError, ValueError) as error:
                    results.clear()
                    with results:
                        _render_error(error, config.db_path)
                else:
                    _render_zone_list(view, results)
                finally:
                    status.clear()

            for field in (zone_id, name, map_id, map_name):
                field.on("keydown.enter", search)
            for control in (sort_by, descending, include_unknown, include_non_matches):
                control.on_value_change(search)

            ui.button("Search", icon="search", on_click=search).mark("zone-search")
            await search()

    @ui.page("/zone/{zone_id}", title=APP_TITLE, response_timeout=15.0)
    def zone_detail(zone_id: int) -> None:
        ui.link("← Back to zones", "/")
        ui.label(f"Zone {zone_id}").classes("text-h3")
        ui.label(f"Read-only database: {config.db_path}").classes("text-caption")
        loading = ui.row().classes("items-center gap-2")
        detail = ui.column().classes("w-full")
        with loading:
            ui.spinner(size="lg")
            ui.label("Loading zone detail…").mark("zone-detail-loading")
            ui.label("The validated P7 detail read can take several seconds.").classes(
                "text-caption text-grey-7"
            )

        async def load_detail() -> None:
            try:
                view = await run.io_bound(zone_service.load_zone_detail, zone_id)
            except (FileNotFoundError, sqlite3.DatabaseError, TypeError, ValueError) as error:
                detail.clear()
                with detail:
                    _render_error(error, config.db_path)
            else:
                _render_zone_detail(view, detail)
            finally:
                loading.clear()

        ui.timer(0.05, load_detail, once=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the read-only OctoGameDB zone explorer")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="existing SQLite database")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--entity-limit", type=int, default=1000)
    parser.add_argument("--recipe-limit", type=int, default=100)
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = ZoneUiConfig(
        db_path=args.db,
        entity_limit=args.entity_limit,
        recipe_limit=args.recipe_limit,
    )
    register_pages(config)
    ui.run(
        host=args.host,
        port=args.port,
        title=APP_TITLE,
        show=not args.no_browser,
        reload=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
