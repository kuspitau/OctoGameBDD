"""Command-line entry point for OctoGameDB."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from octogamedb.audit import (
    conflict_report,
    coverage_report,
    resolution_report,
    source_report,
    trace_report,
    unselected_report,
)
from octogamedb.db import DEFAULT_DB_PATH, apply_migrations, connect_database
from octogamedb.importers.pfquest_item_overlay_reconcile import (
    compute_pfquest_turtle_items_revision,
    reconcile_pfquest_turtle_items,
)
from octogamedb.importers.pfquest_items import (
    compute_pfquest_items_revision,
    import_pfquest_items,
)
from octogamedb.items import find_item_sources


def _add_db_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite database path (default: {DEFAULT_DB_PATH}).",
    )


def _add_json_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit deterministic machine-readable JSON instead of human-readable text.",
    )


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m octogamedb")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser(
        "status",
        help="Initialize the database if needed and report foundation status.",
    )
    _add_db_argument(status_parser)

    source_parser = subparsers.add_parser(
        "source",
        help="Audit registered data sources and persisted import summaries.",
    )
    source_parser.add_argument("source_key", nargs="?", help="Optional source key to inspect.")
    _add_db_argument(source_parser)
    _add_json_argument(source_parser)

    trace_parser = subparsers.add_parser(
        "trace",
        help="Trace provenance for one subject and its observed facts/relations.",
    )
    trace_parser.add_argument("subject_kind", help="Subject domain, for example item or quest.")
    trace_parser.add_argument("subject_key", help="Native/project subject key.")
    trace_parser.add_argument("--fact", dest="fact_key", help="Optional fact key filter.")
    _add_db_argument(trace_parser)
    _add_json_argument(trace_parser)

    conflict_parser = subparsers.add_parser(
        "conflict",
        help="List evidence groups containing competing source values.",
    )
    conflict_parser.add_argument("--subject-kind", help="Optional subject-domain filter.")
    conflict_parser.add_argument("--subject-key", help="Optional subject-key filter.")
    _add_db_argument(conflict_parser)
    _add_json_argument(conflict_parser)

    coverage_parser = subparsers.add_parser(
        "coverage",
        help="Report generic provenance coverage metrics.",
    )
    _add_db_argument(coverage_parser)
    _add_json_argument(coverage_parser)

    resolution_parser = subparsers.add_parser(
        "resolution",
        help="Summarize canonical selection coverage, policies, sources and unresolved groups.",
    )
    resolution_parser.add_argument("--subject-kind", help="Optional subject-domain filter.")
    resolution_parser.add_argument("--fact", dest="fact_key", help="Optional fact-key filter.")
    _add_db_argument(resolution_parser)
    _add_json_argument(resolution_parser)

    unselected_parser = subparsers.add_parser(
        "unselected",
        help="Audit unselected single-value provenance groups without selecting them.",
    )
    unselected_parser.add_argument("--subject-kind", help="Optional subject-domain filter.")
    unselected_parser.add_argument("--subject-key", help="Optional subject-key filter.")
    unselected_parser.add_argument("--fact", dest="fact_key", help="Optional fact-key filter.")
    unselected_parser.add_argument(
        "--source",
        dest="source_key",
        help="Keep groups containing at least one observation from this source key.",
    )
    unselected_parser.add_argument(
        "--limit",
        type=_nonnegative_int,
        default=100,
        help=(
            "Maximum detailed groups to include after exhaustive aggregates; "
            "0 emits summary aggregates only (default: 100)."
        ),
    )
    _add_db_argument(unselected_parser)
    _add_json_argument(unselected_parser)

    import_items_parser = subparsers.add_parser(
        "import-pfquest-items",
        help="Import the bounded P2 pfQuest item/loot/reference/vendor acquisition slice.",
    )
    import_items_parser.add_argument("source_root", type=Path, help="Installed pfQuest directory.")
    import_items_parser.add_argument(
        "--source-revision",
        help=(
            "Optional explicit source revision; otherwise hash the five item/reference/identity "
            "input files."
        ),
    )
    _add_db_argument(import_items_parser)
    _add_json_argument(import_items_parser)

    reconcile_items_parser = subparsers.add_parser(
        "reconcile-pfquest-turtle-items",
        help=(
            "Reconcile the bounded P2 canonical item/acquisition view against installed "
            "pfQuest-turtle top-entry patches."
        ),
    )
    reconcile_items_parser.add_argument(
        "pfquest_root", type=Path, help="Installed pfQuest directory."
    )
    reconcile_items_parser.add_argument(
        "pfquest_turtle_root", type=Path, help="Installed pfQuest-turtle directory."
    )
    reconcile_items_parser.add_argument(
        "--pfquest-revision",
        help="Optional explicit base revision; otherwise hash the five bounded pfQuest P2 inputs.",
    )
    reconcile_items_parser.add_argument(
        "--turtle-revision",
        help="Optional explicit Turtle revision; otherwise hash the validated bounded P2 inputs.",
    )
    _add_db_argument(reconcile_items_parser)
    _add_json_argument(reconcile_items_parser)

    item_sources_parser = subparsers.add_parser(
        "item-sources",
        help="Show loot/reference/vendor acquisition sources and derived spawn geography.",
    )
    item_sources_parser.add_argument("item_id", type=int, help="Native item ID.")
    _add_db_argument(item_sources_parser)
    _add_json_argument(item_sources_parser)

    return parser


def _status(db_path: Path) -> int:
    with connect_database(db_path) as connection:
        apply_migrations(connection)
        row = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM schema_migrations) AS migration_count,
                (SELECT COALESCE(MAX(version), 0) FROM schema_migrations) AS schema_version,
                (SELECT COUNT(*) FROM data_sources) AS source_count,
                (SELECT COUNT(*) FROM import_batches) AS import_batch_count
            """
        ).fetchone()

    print(f"Database: {db_path}")
    print(f"Schema version: {row['schema_version']}")
    print(f"Applied migrations: {row['migration_count']}")
    print(f"Registered sources: {row['source_count']}")
    print(f"Import batches: {row['import_batch_count']}")
    return 0


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _print_source(payload: dict[str, Any]) -> None:
    print(f"Sources: {payload['source_count']}")
    for source in payload["sources"]:
        print(f"- {source['source_key']}: {source['display_name']} ({source['source_kind']})")
        print(f"  Import batches: {source['batch_count']}")
        for batch in source["batches"]:
            revision = batch["source_revision"] or "<none>"
            print(
                "  - "
                f"{revision}: {batch['status']}, read={batch['rows_read']}, "
                f"accepted={batch['rows_accepted']}, skipped={batch['rows_skipped']}, "
                f"warnings={batch['warning_count']}, errors={batch['error_count']}"
            )


def _print_trace(payload: dict[str, Any]) -> None:
    print(f"Subject: {payload['subject_kind']}:{payload['subject_key']}")
    print(f"Groups: {payload['group_count']}")
    for group in payload["groups"]:
        suffix = f" [{group['fact_instance_key']}]" if group["fact_instance_key"] else ""
        print(
            f"- {group['fact_key']}{suffix}: {group['observation_count']} observation(s), "
            f"{group['distinct_value_count']} distinct value(s)"
        )
        canonical = group["canonical_selection"]
        if canonical is not None:
            print(
                "  canonical: "
                f"observation {canonical['observation_id']} "
                f"({canonical['selection_policy'] or 'no-policy'})"
            )
        for observation in group["observations"]:
            print(
                "  - "
                f"{observation['source_key']}@{observation['source_revision'] or '<none>'}: "
                f"{json.dumps(observation['value'], ensure_ascii=False, sort_keys=True)}"
            )


def _print_conflicts(payload: dict[str, Any]) -> None:
    print(f"Conflicts: {payload['conflict_count']}")
    print(f"Unresolved: {payload['unresolved_conflict_count']}")
    for group in payload["conflicts"]:
        resolution = "resolved" if group["canonical_selection"] is not None else "unresolved"
        suffix = f" [{group['fact_instance_key']}]" if group["fact_instance_key"] else ""
        print(
            f"- {group['subject_kind']}:{group['subject_key']} {group['fact_key']}{suffix}: "
            f"{group['distinct_value_count']} values ({resolution})"
        )


def _print_coverage(payload: dict[str, Any]) -> None:
    print(f"Coverage scope: {payload['scope']}")
    print(f"Sources: {payload['source_count']}")
    print(f"Import batches: {payload['import_batch_count']}")
    print(f"Subjects: {payload['subject_count']}")
    print(f"Observation groups: {payload['observation_group_count']}")
    print(f"Observations: {payload['observation_count']}")
    print(f"Canonical selections: {payload['canonical_selection_count']}")
    print(f"Conflicts: {payload['conflict_count']}")
    print(f"Unresolved conflicts: {payload['unresolved_conflict_count']}")
    for kind in payload["subject_kinds"]:
        print(
            f"- {kind['subject_kind']}: subjects={kind['subject_count']}, "
            f"groups={kind['observation_group_count']}, observations={kind['observation_count']}, "
            f"conflicts={kind['conflict_count']}"
        )


def _print_resolution(payload: dict[str, Any]) -> None:
    print(f"Resolution scope: {payload['scope']}")
    if payload["subject_kind"] is not None:
        print(f"Subject kind filter: {payload['subject_kind']}")
    if payload["fact_key"] is not None:
        print(f"Fact filter: {payload['fact_key']}")
    print(f"Observation groups: {payload['observation_group_count']}")
    print(f"Selected groups: {payload['selected_group_count']}")
    print(f"Unselected groups: {payload['unselected_group_count']}")
    print(f"Empty observation groups: {payload['empty_observation_group_count']}")
    print(f"Conflicts: {payload['conflict_group_count']}")
    print(f"Resolved conflicts: {payload['resolved_conflict_group_count']}")
    print(f"Unresolved conflicts: {payload['unresolved_conflict_group_count']}")
    print(
        "Unselected single-value groups: "
        f"{payload['unselected_single_value_group_count']}"
    )
    if payload["selection_policies"]:
        print("Selection policies:")
        for policy in payload["selection_policies"]:
            label = policy["selection_policy"] or "<none>"
            print(
                f"- {label}: selected={policy['selected_group_count']}, "
                f"conflicts={policy['conflict_group_count']}"
            )
    if payload["selected_sources"]:
        print("Selected sources:")
        for source in payload["selected_sources"]:
            print(
                f"- {source['source_key']}: selected={source['selected_group_count']}, "
                f"conflicts={source['conflict_group_count']}"
            )
    if payload["fact_families"]:
        print("Fact families:")
        for family in payload["fact_families"]:
            print(
                f"- {family['subject_kind']}.{family['fact_key']} ({family['fact_kind']}): "
                f"groups={family['observation_group_count']}, "
                f"selected={family['selected_group_count']}, "
                f"conflicts={family['conflict_group_count']}, "
                f"unresolved={family['unresolved_conflict_group_count']}"
            )


def _print_unselected(payload: dict[str, Any]) -> None:
    print(f"Unselected scope: {payload['scope']}")
    filters = payload["filters"]
    active_filters = [f"{key}={value}" for key, value in filters.items() if value is not None]
    if active_filters:
        print("Filters: " + ", ".join(active_filters))
    print(f"Matched single-value unselected groups: {payload['group_count']}")
    print(f"Detailed groups returned: {payload['returned_group_count']}")
    print(f"Details truncated: {'yes' if payload['details_truncated'] else 'no'}")
    print(f"Unresolved classification: {payload['classification_counts']['unresolved']}")
    if payload["fact_families"]:
        print("Fact families:")
        for family in payload["fact_families"]:
            print(
                f"- {family['subject_kind']}.{family['fact_key']} ({family['fact_kind']}): "
                f"groups={family['group_count']}"
            )
    if payload["sources"]:
        print("Observed sources:")
        for source in payload["sources"]:
            print(
                f"- {source['source_key']}: groups={source['group_count']}, "
                f"observations={source['observation_count']}"
            )
    if payload["subject_fact_patterns"]:
        print("Subject/fact patterns:")
        for pattern in payload["subject_fact_patterns"]:
            facts = ",".join(pattern["fact_keys"])
            print(
                f"- {pattern['subject_kind']} [{facts}]: subjects={pattern['subject_count']}, "
                f"groups={pattern['group_count']}"
            )
    for group in payload["groups"]:
        suffix = f" [{group['fact_instance_key']}]" if group["fact_instance_key"] else ""
        value = json.dumps(group["sole_value"], ensure_ascii=False, sort_keys=True)
        print(
            f"- {group['subject_kind']}:{group['subject_key']} "
            f"{group['fact_key']}{suffix}: {value} ({group['classification']['label']})"
        )
        evidence = group["classification_evidence"]
        print(
            "  siblings: "
            f"selected={evidence['selected_sibling_count']}, "
            f"single-value-unselected={evidence['single_value_unselected_sibling_count']}, "
            f"conflict-unselected={evidence['conflict_unselected_sibling_count']}"
        )


def _audit_command(args: argparse.Namespace) -> int:
    with connect_database(args.db) as connection:
        apply_migrations(connection)
        if args.command == "source":
            payload = source_report(connection, args.source_key)
            printer = _print_source
        elif args.command == "trace":
            payload = trace_report(
                connection,
                subject_kind=args.subject_kind,
                subject_key=args.subject_key,
                fact_key=args.fact_key,
            )
            printer = _print_trace
        elif args.command == "conflict":
            payload = conflict_report(
                connection,
                subject_kind=args.subject_kind,
                subject_key=args.subject_key,
            )
            printer = _print_conflicts
        elif args.command == "coverage":
            payload = coverage_report(connection)
            printer = _print_coverage
        elif args.command == "resolution":
            payload = resolution_report(
                connection,
                subject_kind=args.subject_kind,
                fact_key=args.fact_key,
            )
            printer = _print_resolution
        elif args.command == "unselected":
            payload = unselected_report(
                connection,
                subject_kind=args.subject_kind,
                subject_key=args.subject_key,
                fact_key=args.fact_key,
                source_key=args.source_key,
                limit=args.limit,
            )
            printer = _print_unselected
        else:
            raise AssertionError(f"Unhandled audit command: {args.command}")

    if args.json:
        _print_json(payload)
    else:
        printer(payload)
    return 0


def _import_pfquest_items_command(args: argparse.Namespace) -> int:
    revision = args.source_revision or compute_pfquest_items_revision(args.source_root)
    with connect_database(args.db) as connection:
        apply_migrations(connection)
        summary = import_pfquest_items(
            connection,
            source_root=args.source_root,
            source_revision=revision,
        )
    payload = summary.to_dict()
    if args.json:
        _print_json(payload)
    else:
        print(f"Source: {payload['source_key']}@{payload['source_revision']}")
        print(f"Status: {payload['status']}")
        print(
            f"Rows: read={payload['rows_read']}, accepted={payload['rows_accepted']}, "
            f"skipped={payload['rows_skipped']}"
        )
        print(
            f"Canonical changes: inserted={payload['rows_inserted']}, "
            f"updated={payload['rows_updated']}"
        )
        print(json.dumps(payload["details"], ensure_ascii=False, sort_keys=True))
    return 0


def _reconcile_pfquest_turtle_items_command(args: argparse.Namespace) -> int:
    pfquest_revision = args.pfquest_revision or compute_pfquest_items_revision(args.pfquest_root)
    turtle_revision = args.turtle_revision or compute_pfquest_turtle_items_revision(
        args.pfquest_turtle_root
    )
    with connect_database(args.db) as connection:
        apply_migrations(connection)
        summary = reconcile_pfquest_turtle_items(
            connection,
            pfquest_root=args.pfquest_root,
            pfquest_turtle_root=args.pfquest_turtle_root,
            pfquest_revision=pfquest_revision,
            turtle_revision=turtle_revision,
        )
    payload = summary.to_dict()
    if args.json:
        _print_json(payload)
    else:
        print(f"Source: {payload['source_key']}@{payload['source_revision']}")
        print(f"Status: {payload['status']}")
        print(
            f"Rows: read={payload['rows_read']}, accepted={payload['rows_accepted']}, "
            f"warnings={payload['warning_count']}"
        )
        print(
            f"Canonical changes: inserted={payload['rows_inserted']}, "
            f"updated={payload['rows_updated']}, "
            f"deleted={payload['details']['canonical_relations_or_identities_deleted']}"
        )
        print(json.dumps(payload["details"], ensure_ascii=False, sort_keys=True))
    return 0


def _print_item_sources(payload: list[dict[str, Any]]) -> None:
    if not payload:
        print("Item not found.")
        return
    item = payload[0]
    print(f"Item: {item['item_id']} — {item['item_name']}")
    print(f"Sources: {len(item['sources'])}")
    for source in item["sources"]:
        location = "unlocated"
        if source["spawn_key"] is not None:
            zone = source["zone_name"] or source["zone_id"] or "unknown zone"
            location = f"{zone} @ {source['x']},{source['y']} ({source['coordinate_space']})"
        chance = source["chance_percent"]
        chance_text = f"{chance}%" if chance is not None else "no single loot chance"
        path_labels = []
        for path in source.get("acquisition_paths", []):
            if path["path_kind"] == "reference":
                path_labels.append(f"reference:{path['reference_loot_id']}")
            elif path["path_kind"] == "vendor":
                path_labels.append(f"vendor:maxcount={path['vendor_max_count']}")
            else:
                path_labels.append("direct")
        path_text = ",".join(path_labels) if path_labels else "unknown"
        print(
            f"- {source['source_kind']}:{source['source_id']} {source['source_name']} — "
            f"{chance_text} — {location} — paths={path_text}"
        )


def _item_sources_command(args: argparse.Namespace) -> int:
    with connect_database(args.db) as connection:
        apply_migrations(connection)
        payload = find_item_sources(connection, args.item_id)
    if args.json:
        _print_json(payload)
    else:
        _print_item_sources(payload)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "status":
        return _status(args.db)
    if args.command in {"source", "trace", "conflict", "coverage", "resolution", "unselected"}:
        return _audit_command(args)
    if args.command == "import-pfquest-items":
        return _import_pfquest_items_command(args)
    if args.command == "reconcile-pfquest-turtle-items":
        return _reconcile_pfquest_turtle_items_command(args)
    if args.command == "item-sources":
        return _item_sources_command(args)

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
