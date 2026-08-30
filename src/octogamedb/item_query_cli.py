"""Read-only CLI for the P7 provenance-aware item query contract."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from octogamedb.db import DEFAULT_DB_PATH
from octogamedb.item_search import (
    ITEM_QUERY_SORT_FIELDS,
    MATCH_KNOWN,
    MATCH_UNKNOWN,
    NON_MATCH_KNOWN,
    ItemQueryPage,
    item_query_page_to_dict,
    query_items,
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


def _stat_filter(value: str) -> tuple[int, int]:
    try:
        stat_type_text, minimum_text = value.split(":", 1)
        stat_type = int(stat_type_text)
        minimum = int(minimum_text)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("must use STAT_TYPE:MINIMUM") from exc
    if stat_type < 0:
        raise argparse.ArgumentTypeError("stat type must be non-negative")
    return stat_type, minimum


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m octogamedb.item_query_cli",
        description=(
            "Query canonical item identities and the partial migration-14 template/stat projection "
            "without treating unmaterialized templates as negative evidence."
        ),
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--item-id", type=_nonnegative_int)
    parser.add_argument("--name-contains")
    parser.add_argument("--quality", type=_nonnegative_int)
    parser.add_argument("--class-id", type=_nonnegative_int)
    parser.add_argument("--subclass-id", type=_nonnegative_int)
    parser.add_argument("--inventory-type", type=_nonnegative_int)
    parser.add_argument("--min-item-level", type=_nonnegative_int)
    parser.add_argument("--max-item-level", type=_nonnegative_int)
    parser.add_argument("--min-required-level", type=_nonnegative_int)
    parser.add_argument("--max-required-level", type=_nonnegative_int)
    parser.add_argument("--min-armor", type=_nonnegative_int)
    parser.add_argument("--min-durability", type=_nonnegative_int)
    for resistance in ("holy", "fire", "nature", "frost", "shadow", "arcane"):
        parser.add_argument(f"--min-{resistance}-resistance", type=_nonnegative_int)
    parser.add_argument(
        "--stat",
        dest="stats",
        action="append",
        type=_stat_filter,
        default=[],
        metavar="STAT_TYPE:MINIMUM",
        help=(
            "Require a raw stat type to have at least the given value. Repeat for multiple types; "
            "duplicates keep the strongest minimum."
        ),
    )
    parser.add_argument(
        "--include-unknown",
        action="store_true",
        help="Return unknown rows in addition to known matches.",
    )
    parser.add_argument(
        "--include-non-matches",
        action="store_true",
        help="Return known non-matches in addition to known matches.",
    )
    parser.add_argument("--sort-by", choices=ITEM_QUERY_SORT_FIELDS, default="item_id")
    parser.add_argument("--desc", action="store_true", help="Sort known values descending.")
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


def _normalized_stats(entries: Sequence[tuple[int, int]]) -> dict[int, int]:
    result: dict[int, int] = {}
    for stat_type, minimum in entries:
        result[stat_type] = max(minimum, result.get(stat_type, minimum))
    return result


def _include_states(args: argparse.Namespace) -> tuple[str, ...]:
    states = [MATCH_KNOWN]
    if args.include_non_matches:
        states.append(NON_MATCH_KNOWN)
    if args.include_unknown:
        states.append(MATCH_UNKNOWN)
    return tuple(states)


def _query(args: argparse.Namespace) -> ItemQueryPage:
    connection = _open_readonly_database(args.db)
    try:
        return query_items(
            connection,
            item_id=args.item_id,
            name_contains=args.name_contains,
            quality=args.quality,
            class_id=args.class_id,
            subclass_id=args.subclass_id,
            inventory_type=args.inventory_type,
            min_item_level=args.min_item_level,
            max_item_level=args.max_item_level,
            min_required_level=args.min_required_level,
            max_required_level=args.max_required_level,
            min_armor=args.min_armor,
            min_max_durability=args.min_durability,
            min_holy_resistance=args.min_holy_resistance,
            min_fire_resistance=args.min_fire_resistance,
            min_nature_resistance=args.min_nature_resistance,
            min_frost_resistance=args.min_frost_resistance,
            min_shadow_resistance=args.min_shadow_resistance,
            min_arcane_resistance=args.min_arcane_resistance,
            min_stats=_normalized_stats(args.stats),
            include_states=_include_states(args),
            sort_by=args.sort_by,
            descending=args.desc,
            limit=args.limit,
        )
    finally:
        connection.close()


def _print_human(page: ItemQueryPage) -> None:
    summary = page.summary
    print(f"Canonical item identities: {summary.total_item_identities}")
    print(
        "Template coverage: "
        f"materialized={summary.materialized_templates}, unknown={summary.unknown_templates}"
    )
    print(
        "Predicate states: "
        f"known_match={summary.known_match_count}, "
        f"known_non_match={summary.known_non_match_count}, unknown={summary.unknown_count}"
    )
    print(f"Returned: {summary.returned_count} (limit={summary.limit})")
    for result in page.results:
        template = result.coverage.template
        required_level = "?" if result.required_level is None else str(result.required_level)
        item_level = "?" if result.item_level is None else str(result.item_level)
        stats = ", ".join(
            f"slot{slot}:type{stat_type}={value}" for slot, stat_type, value in result.stats
        ) or "none"
        source_labels = sorted(
            {
                f"{fact.source_key}@{fact.source_revision or '<none>'}"
                for fact in result.trace
            }
        )
        sources = ", ".join(source_labels) if source_labels else "none/unknown"
        print(
            f"- {result.item_id} — {result.name} — state={result.match_state} — "
            f"template={template} — req={required_level} ilvl={item_level} — stats={stats}"
        )
        print(f"  selected-template-provenance: {len(result.trace)} fact(s); sources={sources}")


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        page = _query(args)
    except (FileNotFoundError, sqlite3.DatabaseError, ValueError, TypeError) as exc:
        raise SystemExit(f"P7 item query failed: {exc}") from exc

    if args.json:
        payload: Any = item_query_page_to_dict(page)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_human(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
