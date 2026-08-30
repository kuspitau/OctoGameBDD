"""Read-only CLI for P7-T02 item acquisition/source exploration."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from octogamedb.db import DEFAULT_DB_PATH
from octogamedb.item_acquisition_search import (
    ACQUISITION_PATH_KINDS,
    ACQUISITION_SOURCE_KINDS,
    ItemAcquisitionQueryPage,
    item_acquisition_page_to_dict,
    query_item_acquisitions,
)
from octogamedb.item_search import (
    ITEM_QUERY_SORT_FIELDS,
    MATCH_KNOWN,
    MATCH_UNKNOWN,
    NON_MATCH_KNOWN,
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


def _drop_chance(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0 or parsed > 100.0:
        raise argparse.ArgumentTypeError("must be between 0 and 100")
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
        prog="python -m octogamedb.item_acquisition_cli",
        description=(
            "Compose P7 item predicates with known P2 direct/reference/vendor sources and P1 "
            "derived geography without treating missing source evidence as a universal negative."
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
    )
    parser.add_argument(
        "--path-kind",
        action="append",
        choices=ACQUISITION_PATH_KINDS,
        default=[],
        help="Known acquisition path kind. Repeat to allow several kinds.",
    )
    parser.add_argument(
        "--source-kind",
        action="append",
        choices=ACQUISITION_SOURCE_KINDS,
        default=[],
        help="Known source template kind. Repeat to allow several kinds.",
    )
    parser.add_argument("--min-drop-chance", type=_drop_chance)
    parser.add_argument("--zone-id", type=_nonnegative_int)
    parser.add_argument("--map-id", type=_nonnegative_int)
    parser.add_argument(
        "--include-unknown",
        action="store_true",
        help=(
            "Return unknown combined rows too. For acquisition filters, lack of a known matching "
            "path is unknown rather than a proven non-match."
        ),
    )
    parser.add_argument(
        "--include-non-matches",
        action="store_true",
        help="Return rows already known not to match the P7 item predicates.",
    )
    parser.add_argument("--sort-by", choices=ITEM_QUERY_SORT_FIELDS, default="item_id")
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


def _query(args: argparse.Namespace) -> ItemAcquisitionQueryPage:
    connection = _open_readonly_database(args.db)
    try:
        return query_item_acquisitions(
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
            path_kinds=args.path_kind,
            source_kinds=args.source_kind,
            min_drop_chance=args.min_drop_chance,
            zone_id=args.zone_id,
            map_id=args.map_id,
            include_states=_include_states(args),
            sort_by=args.sort_by,
            descending=args.desc,
            limit=args.limit,
        )
    finally:
        connection.close()


def _print_human(page: ItemAcquisitionQueryPage) -> None:
    summary = page.summary
    print(f"Canonical item identities: {summary.total_item_identities}")
    print(
        "Template coverage: "
        f"materialized={summary.materialized_templates}, unknown={summary.unknown_templates}"
    )
    print(f"Items with materialized P2 acquisition rows: {summary.materialized_acquisition_items}")
    print(
        "Combined states: "
        f"known_match={summary.known_match_count}, "
        f"known_non_match={summary.known_non_match_count}, unknown={summary.unknown_count}"
    )
    print(f"Returned: {summary.returned_count} (limit={summary.limit})")
    for result in page.results:
        item = result.item
        print(
            f"- {item.item_id} — {item.name} — item_state={item.match_state} — "
            f"combined={result.combined_match_state} — "
            f"acquisition={result.acquisition_filter.state}"
        )
        print(
            "  known-sources="
            f"{len(result.sources)} matching-sources={len(result.matching_sources)} "
            f"matching-paths={result.acquisition_filter.matching_path_count}"
        )
        for source in result.matching_sources:
            location = (
                "unknown"
                if source.get("zone_id") is None
                else f"zone={source['zone_id']} map={source.get('map_id')}"
            )
            paths = ", ".join(
                f"{path['path_kind']}"
                + (
                    ""
                    if path.get("chance_percent") is None
                    else f"@{float(path['chance_percent']):g}%"
                )
                for path in source["acquisition_paths"]
            )
            print(
                f"  * {source['source_kind']}:{source['source_id']} {source['source_name']} — "
                f"{location} — {paths}"
            )


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        page = _query(args)
    except (FileNotFoundError, sqlite3.DatabaseError, ValueError, TypeError, RuntimeError) as exc:
        raise SystemExit(f"P7 item acquisition query failed: {exc}") from exc

    if args.json:
        payload: Any = item_acquisition_page_to_dict(page)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_human(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
