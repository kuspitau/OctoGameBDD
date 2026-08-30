"""Read-only CLI for P7-T04 recipe/reagent/acquisition exploration."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from octogamedb.db import DEFAULT_DB_PATH
from octogamedb.item_search import MATCH_KNOWN, MATCH_UNKNOWN, NON_MATCH_KNOWN
from octogamedb.recipe_search import (
    LEARNING_KINDS,
    RECIPE_QUERY_SORT_FIELDS,
    RecipeQueryPage,
    query_recipes,
    recipe_query_page_to_dict,
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
        prog="python -m octogamedb.recipe_cli",
        description=(
            "Search P4 recipes and compose teaching-item acquisition, trainer geography and "
            "quest-learning context without inventing a universal recipe zone."
        ),
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--recipe-id", type=_positive_int)
    parser.add_argument("--name-contains")
    parser.add_argument("--skill-line-id", type=_nonnegative_int)
    parser.add_argument("--skill-line-name")
    parser.add_argument("--min-required-skill", type=_nonnegative_int)
    parser.add_argument("--max-required-skill", type=_nonnegative_int)
    parser.add_argument(
        "--output-item-id",
        type=_positive_int,
        help="Match the preserved native output item ID; canonical resolution is shown separately.",
    )
    parser.add_argument(
        "--reagent-item-id",
        type=_positive_int,
        help=(
            "Match the preserved native reagent item ID; canonical resolution is shown "
            "separately."
        ),
    )
    parser.add_argument(
        "--learning-kind",
        action="append",
        choices=LEARNING_KINDS,
        default=[],
        help="Positive-evidence learning kind filter. Repeat to allow several kinds.",
    )
    parser.add_argument("--teaching-zone", type=_nonnegative_int)
    parser.add_argument("--teaching-map", type=_nonnegative_int)
    parser.add_argument("--trainer-zone", type=_nonnegative_int)
    parser.add_argument("--trainer-map", type=_nonnegative_int)
    parser.add_argument("--quest-giver-zone", type=_nonnegative_int)
    parser.add_argument("--quest-giver-map", type=_nonnegative_int)
    parser.add_argument("--quest-finisher-zone", type=_nonnegative_int)
    parser.add_argument("--quest-finisher-map", type=_nonnegative_int)
    parser.add_argument("--quest-objective-zone", type=_nonnegative_int)
    parser.add_argument("--quest-objective-map", type=_nonnegative_int)
    parser.add_argument(
        "--include-unknown",
        action="store_true",
        help=(
            "Return unknown rows too. Missing learning/acquisition/geography evidence is not a "
            "universal negative."
        ),
    )
    parser.add_argument(
        "--include-non-matches",
        action="store_true",
        help="Return known non-matches for complete P4 identity/skill/output/reagent predicates.",
    )
    parser.add_argument("--sort-by", choices=RECIPE_QUERY_SORT_FIELDS, default="recipe_id")
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


def _query(args: argparse.Namespace) -> RecipeQueryPage:
    connection = _open_readonly_database(args.db)
    try:
        return query_recipes(
            connection,
            recipe_id=args.recipe_id,
            name_contains=args.name_contains,
            skill_line_id=args.skill_line_id,
            skill_line_name=args.skill_line_name,
            min_required_skill=args.min_required_skill,
            max_required_skill=args.max_required_skill,
            output_item_id=args.output_item_id,
            reagent_item_id=args.reagent_item_id,
            learning_kinds=args.learning_kind,
            teaching_zone_id=args.teaching_zone,
            teaching_map_id=args.teaching_map,
            trainer_zone_id=args.trainer_zone,
            trainer_map_id=args.trainer_map,
            quest_giver_zone_id=args.quest_giver_zone,
            quest_giver_map_id=args.quest_giver_map,
            quest_finisher_zone_id=args.quest_finisher_zone,
            quest_finisher_map_id=args.quest_finisher_map,
            quest_objective_zone_id=args.quest_objective_zone,
            quest_objective_map_id=args.quest_objective_map,
            include_states=_include_states(args),
            sort_by=args.sort_by,
            descending=args.desc,
            limit=args.limit,
        )
    finally:
        connection.close()


def _print_human(page: RecipeQueryPage) -> None:
    summary = page.summary
    print(f"Canonical recipe identities: {summary.total_recipe_identities}")
    print(
        "States: "
        f"known_match={summary.known_match_count}, "
        f"known_non_match={summary.known_non_match_count}, unknown={summary.unknown_count}"
    )
    print(f"Returned: {summary.returned_count} (limit={summary.limit})")
    for result in page.results:
        recipe = result.recipe
        print(
            f"- {recipe['recipe_id']} — {recipe['name']} — {result.match_state} — "
            f"skills={len(recipe['skill_lines'])} outputs={len(recipe['outputs'])} "
            f"reagents={len(recipe['reagents'])}"
        )
        learning = recipe["learning"]
        print(
            "  learning: "
            f"items={len(learning['teaching_items'])} "
            f"trainers={len(learning['trainers'])} "
            f"quests={len(learning['quest_reward_spells'])}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        page = _query(args)
    except (FileNotFoundError, sqlite3.DatabaseError, ValueError, TypeError, RuntimeError) as exc:
        raise SystemExit(f"P7 recipe query failed: {exc}") from exc

    if args.json:
        payload: Any = recipe_query_page_to_dict(page)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_human(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
