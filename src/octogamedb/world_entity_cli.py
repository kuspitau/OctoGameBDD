"""Read-only CLI for P7-T05 creature/gameobject exploration."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from octogamedb.db import DEFAULT_DB_PATH
from octogamedb.world_entity_search import (
    ENTITY_KINDS,
    MATCH_KNOWN,
    MATCH_UNKNOWN,
    NON_MATCH_KNOWN,
    WORLD_ENTITY_QUERY_SORT_FIELDS,
    WorldEntityQueryPage,
    query_world_entities,
    world_entity_query_page_to_dict,
)


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _bounded_limit(value: str) -> int:
    parsed = int(value)
    if parsed < 1 or parsed > 1000:
        raise argparse.ArgumentTypeError("must be between 1 and 1000")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m octogamedb.world_entity_cli",
        description=(
            "Search canonical creature/gameobject templates and inspect independent P1 spawns plus "
            "validated item, quest and trainer roles."
        ),
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--kind", choices=ENTITY_KINDS)
    parser.add_argument("--entity-id", type=_positive_int)
    parser.add_argument("--name-contains")
    parser.add_argument("--zone", type=_nonnegative_int)
    parser.add_argument("--map", dest="map_id", type=_nonnegative_int)
    parser.add_argument(
        "--include-unknown",
        action="store_true",
        help="Return rows whose requested geography cannot be proven true or false.",
    )
    parser.add_argument(
        "--include-non-matches",
        action="store_true",
        help="Return known non-matches where validated complete evidence proves the negative.",
    )
    parser.add_argument("--sort-by", choices=WORLD_ENTITY_QUERY_SORT_FIELDS, default="entity_id")
    parser.add_argument("--desc", action="store_true")
    parser.add_argument("--limit", type=_bounded_limit, default=100)
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


def _query(args: argparse.Namespace) -> WorldEntityQueryPage:
    connection = _open_readonly_database(args.db)
    try:
        return query_world_entities(
            connection,
            entity_kind=args.kind,
            entity_id=args.entity_id,
            name_contains=args.name_contains,
            zone_id=args.zone,
            map_id=args.map_id,
            include_states=_include_states(args),
            sort_by=args.sort_by,
            descending=args.desc,
            limit=args.limit,
        )
    finally:
        connection.close()


def _print_human(page: WorldEntityQueryPage) -> None:
    summary = page.summary
    print(
        "Canonical entity identities: "
        f"{summary.total_entity_identities} "
        f"(creatures={summary.total_creature_identities}, "
        f"gameobjects={summary.total_gameobject_identities})"
    )
    print(
        "States: "
        f"known_match={summary.known_match_count}, "
        f"known_non_match={summary.known_non_match_count}, unknown={summary.unknown_count}"
    )
    print(f"Returned: {summary.returned_count} (limit={summary.limit})")
    for result in page.results:
        entity = result.entity
        role_summary = entity["roles"]["summary"]
        print(
            f"- {entity['entity_kind']}:{entity['entity_id']} — {entity['name']} — "
            f"{result.match_state} — spawns={len(entity['spawns'])}"
        )
        print(
            "  roles: "
            f"direct_loot={role_summary['direct_loot_path_count']} "
            f"reference_loot={role_summary['reference_loot_path_count']} "
            f"vendor={role_summary['vendor_path_count']} "
            f"trainer={role_summary['trainer_relation_count']} "
            f"quests={len(entity['roles']['quests'])}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        page = _query(args)
    except (FileNotFoundError, sqlite3.DatabaseError, ValueError, TypeError, RuntimeError) as exc:
        raise SystemExit(f"P7 world-entity query failed: {exc}") from exc

    if args.json:
        payload: Any = world_entity_query_page_to_dict(page)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_human(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
