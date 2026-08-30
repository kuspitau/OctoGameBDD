"""Read-only CLI for P7-T03 quest search and progression exploration."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from octogamedb.db import DEFAULT_DB_PATH
from octogamedb.quest_search import (
    MATCH_KNOWN,
    MATCH_UNKNOWN,
    NON_MATCH_KNOWN,
    QUEST_QUERY_SORT_FIELDS,
    TRAVERSAL_DIRECTIONS,
    QuestQueryPage,
    query_quests,
    quest_query_page_to_dict,
    traverse_quest_progression,
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


def _bounded_depth(value: str) -> int:
    parsed = int(value)
    if parsed < 0 or parsed > 20:
        raise argparse.ArgumentTypeError("must be between 0 and 20")
    return parsed


def _bounded_nodes(value: str) -> int:
    parsed = int(value)
    if parsed < 1 or parsed > 500:
        raise argparse.ArgumentTypeError("must be between 1 and 500")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m octogamedb.quest_cli",
        description=(
            "Search canonical quests with relation-specific geography or traverse selected "
            "prerequisite/derived follow-up edges without inventing a universal quest zone "
            "or chain step."
        ),
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--quest-id", type=_positive_int)
    parser.add_argument("--title-contains")
    parser.add_argument("--min-quest-level", type=_nonnegative_int)
    parser.add_argument("--max-quest-level", type=_nonnegative_int)
    parser.add_argument("--min-minimum-level", type=_nonnegative_int)
    parser.add_argument("--max-minimum-level", type=_nonnegative_int)
    parser.add_argument("--giver-zone", type=_nonnegative_int)
    parser.add_argument("--giver-map", type=_nonnegative_int)
    parser.add_argument("--finisher-zone", type=_nonnegative_int)
    parser.add_argument("--finisher-map", type=_nonnegative_int)
    parser.add_argument("--objective-zone", type=_nonnegative_int)
    parser.add_argument("--objective-map", type=_nonnegative_int)
    parser.add_argument(
        "--include-unknown",
        action="store_true",
        help="Return filters that remain unknown/not-proven, especially unmatched geography.",
    )
    parser.add_argument(
        "--include-non-matches",
        action="store_true",
        help="Return rows already known not to match identity/title/known-level predicates.",
    )
    parser.add_argument("--sort-by", choices=QUEST_QUERY_SORT_FIELDS, default="quest_id")
    parser.add_argument("--desc", action="store_true")
    parser.add_argument("--limit", type=_bounded_limit, default=100)
    parser.add_argument(
        "--traverse",
        choices=TRAVERSAL_DIRECTIONS,
        help="Traverse from --quest-id instead of running a search.",
    )
    parser.add_argument("--max-depth", type=_bounded_depth, default=5)
    parser.add_argument("--max-nodes", type=_bounded_nodes, default=100)
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


def _search(args: argparse.Namespace) -> QuestQueryPage:
    connection = _open_readonly_database(args.db)
    try:
        return query_quests(
            connection,
            quest_id=args.quest_id,
            title_contains=args.title_contains,
            min_quest_level=args.min_quest_level,
            max_quest_level=args.max_quest_level,
            min_minimum_level=args.min_minimum_level,
            max_minimum_level=args.max_minimum_level,
            giver_zone_id=args.giver_zone,
            giver_map_id=args.giver_map,
            finisher_zone_id=args.finisher_zone,
            finisher_map_id=args.finisher_map,
            objective_zone_id=args.objective_zone,
            objective_map_id=args.objective_map,
            include_states=_include_states(args),
            sort_by=args.sort_by,
            descending=args.desc,
            limit=args.limit,
        )
    finally:
        connection.close()


def _traverse(args: argparse.Namespace) -> dict[str, Any]:
    if args.quest_id is None:
        raise ValueError("--traverse requires --quest-id")
    connection = _open_readonly_database(args.db)
    try:
        result = traverse_quest_progression(
            connection,
            args.quest_id,
            direction=args.traverse,
            max_depth=args.max_depth,
            max_nodes=args.max_nodes,
        )
    finally:
        connection.close()
    if result is None:
        raise ValueError(f"quest {args.quest_id} not found")
    return result


def _print_search(page: QuestQueryPage) -> None:
    summary = page.summary
    print(f"Canonical quest identities: {summary.total_quest_identities}")
    print(
        "States: "
        f"known_match={summary.known_match_count}, "
        f"known_non_match={summary.known_non_match_count}, unknown={summary.unknown_count}"
    )
    print(f"Returned: {summary.returned_count} (limit={summary.limit})")
    for result in page.results:
        quest = result.quest
        progression = quest["progression"]
        print(
            f"- {quest['quest_id']} — {quest['name']} — {result.match_state} — "
            f"level={progression['quest_level']} min={progression['minimum_level']}"
        )
        print(
            "  endpoints="
            f"{len(quest['endpoints'])} objectives={len(quest['objectives']['objectives'])} "
            f"prerequisites={progression['prerequisite_set']['selected_member_count']} "
            f"followups={len(progression['follow_ups'])}"
        )


def _print_traversal(result: dict[str, Any]) -> None:
    print(
        f"Quest traversal root={result['root_quest_id']} direction={result['direction']} "
        f"nodes={len(result['nodes'])} edges={len(result['edges'])}"
    )
    print(
        f"ambiguous={str(result['ambiguous']).lower()} "
        f"truncated={str(result['truncated']).lower()} cycles={result['cycle_edge_count']}"
    )
    for edge in result["edges"]:
        suffix = " unresolved" if not edge["target_resolved"] else ""
        if edge["cycle"]:
            suffix += " cycle"
        print(
            f"- depth {edge['depth']}: {edge['from_quest_id']} -> {edge['to_quest_id']}"
            f"{suffix}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.traverse is not None:
            payload: Any = _traverse(args)
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                _print_traversal(payload)
        else:
            page = _search(args)
            if args.json:
                print(
                    json.dumps(
                        quest_query_page_to_dict(page),
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                _print_search(page)
    except (FileNotFoundError, sqlite3.DatabaseError, ValueError, TypeError, RuntimeError) as exc:
        raise SystemExit(f"P7 quest query failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
