"""Read-only CLI for P7-T06 zone-centric exploration."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from octogamedb.db import DEFAULT_DB_PATH
from octogamedb.zone_search import (
    MATCH_KNOWN,
    MATCH_UNKNOWN,
    NON_MATCH_KNOWN,
    ZONE_QUERY_SORT_FIELDS,
    inspect_zone,
    query_zones,
    zone_query_page_to_dict,
)


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def _bounded_limit(value: str) -> int:
    parsed = int(value)
    if parsed < 1 or parsed > 1000:
        raise argparse.ArgumentTypeError("must be between 1 and 1000")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m octogamedb.zone_cli",
        description=(
            "Search canonical zones/maps and optionally inspect one zone through validated P7 "
            "world, item, quest, recipe, vendor and trainer projections."
        ),
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--zone-id", type=_nonnegative_int)
    parser.add_argument("--name-contains")
    parser.add_argument("--map-id", type=_nonnegative_int)
    parser.add_argument("--map-name-contains")
    parser.add_argument(
        "--include-unknown",
        action="store_true",
        help="Return zone identities whose requested map predicate is not materialized.",
    )
    parser.add_argument(
        "--include-non-matches",
        action="store_true",
        help="Return canonical identity predicates proven false.",
    )
    parser.add_argument("--sort-by", choices=ZONE_QUERY_SORT_FIELDS, default="zone_id")
    parser.add_argument("--desc", action="store_true")
    parser.add_argument("--limit", type=_bounded_limit, default=100)
    parser.add_argument(
        "--details",
        action="store_true",
        help="Inspect contents when the zone search returns exactly one result.",
    )
    parser.add_argument("--entity-limit", type=_bounded_limit, default=1000)
    parser.add_argument("--recipe-limit", type=_bounded_limit, default=100)
    parser.add_argument("--json", action="store_true")
    return parser


def _open_readonly_database(path: Path) -> sqlite3.Connection:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"database not found: {path}")
    connection = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _include_states(args: argparse.Namespace) -> tuple[str, ...]:
    states = [MATCH_KNOWN]
    if args.include_non_matches:
        states.append(NON_MATCH_KNOWN)
    if args.include_unknown:
        states.append(MATCH_UNKNOWN)
    return tuple(states)


def _query(args: argparse.Namespace) -> dict[str, Any]:
    connection = _open_readonly_database(args.db)
    try:
        page = query_zones(
            connection,
            zone_id=args.zone_id,
            name_contains=args.name_contains,
            map_id=args.map_id,
            map_name_contains=args.map_name_contains,
            include_states=_include_states(args),
            sort_by=args.sort_by,
            descending=args.desc,
            limit=args.limit,
        )
        payload: dict[str, Any] = {"query": zone_query_page_to_dict(page)}
        if args.details:
            if len(page.results) != 1:
                raise ValueError("--details requires the zone search to return exactly one result")
            payload["detail"] = inspect_zone(
                connection,
                int(page.results[0].zone["zone_id"]),
                entity_limit=args.entity_limit,
                recipe_limit=args.recipe_limit,
            )
        return payload
    finally:
        connection.close()


def _print_human(payload: Mapping[str, Any]) -> None:
    query = payload["query"]
    summary = query["summary"]
    print(
        "Canonical zone identities: "
        f"{summary['total_zone_identities']} — known_match={summary['known_match_count']}, "
        f"known_non_match={summary['known_non_match_count']}, unknown={summary['unknown_count']}"
    )
    print(f"Returned: {summary['returned_count']} (limit={summary['limit']})")
    for result in query["results"]:
        zone = result["zone"]
        map_info = zone["map"]
        print(
            f"- zone:{zone['zone_id']} — {zone['name']} — {result['match_state']} — "
            f"map={map_info['map_id']}:{map_info['name']}"
        )
    detail = payload.get("detail")
    if isinstance(detail, Mapping):
        world = detail["world_entities"]
        recipes = detail["recipes"]
        quest_count = sum(
            len(detail["quests"][key]) for key in ("given", "finished", "objectives")
        )
        print(
            "Detail: "
            f"entities={len(world['results'])}/{world['summary']['known_match_count']} "
            f"items={len(detail['items']['results'])} quests={quest_count} "
            f"vendors={len(detail['vendors'])} "
            f"trainers={len(detail['trainers']['known'])}"
        )
        quest_recipes = recipes["quest_reward_spell"]
        print(
            "Recipe known matches: "
            f"teaching={recipes['teaching_item']['summary']['known_match_count']} "
            f"trainer={recipes['trainer']['summary']['known_match_count']} "
            f"quest_giver={quest_recipes['giver']['summary']['known_match_count']} "
            f"quest_finisher={quest_recipes['finisher']['summary']['known_match_count']} "
            f"quest_objective={quest_recipes['objective']['summary']['known_match_count']}"
        )
        print(
            "Coverage: "
            f"{detail['coverage']['state']} — {detail['coverage']['reason']}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        payload = _query(args)
    except (FileNotFoundError, sqlite3.DatabaseError, ValueError, TypeError, RuntimeError) as exc:
        raise SystemExit(f"P7 zone query failed: {exc}") from exc

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_human(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
