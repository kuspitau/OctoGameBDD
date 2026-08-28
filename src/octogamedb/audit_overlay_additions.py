"""Read-only P5-T06 overlay-addition coverage audit."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from typing import Any

from octogamedb.audit_comparison import P1_WORLD_COMPARISON_SOURCE_KEY, _open_read_only_database
from octogamedb.audit_spawn_attribution import (
    BASE_SOURCE_KEY,
    EXPECTED_BASE_REVISION,
    EXPECTED_COMPARISON_REVISION,
    PATTERNS,
    _attributed_members,
    _base_membership_contexts,
    _pattern_counts,
)
from octogamedb.audit_spawn_divergence import SPAWN_SUBJECT_KINDS, spawn_divergence_report

OVERLAY_ADDITION_SCOPE = "p5-t06-overlay-addition-coverage"
INCLUDED_PATTERNS = ("active_only_vs_base", "comparison_only_vs_base")
ADDITION_PARENT_CLASSES = (
    "parent_absent_from_base",
    "spawn_added_to_base_present_parent",
)
OVERLAY_COVERAGE_CLASSES = ("active_only", "comparison_only", "both")
OVERLAY_COVERAGE_SCOPES = ("parent", "zone")


def _percentage(count: int, total: int) -> float:
    return 0.0 if total == 0 else round(count * 100.0 / total, 6)


def _subject_key_sort(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


def _coverage_label(active_count: int, comparison_count: int) -> str:
    if active_count and comparison_count:
        return "both"
    if active_count:
        return "active_only"
    if comparison_count:
        return "comparison_only"
    raise ValueError("overlay coverage requires at least one addition")


def _classify_addition_member(member: dict[str, Any]) -> str:
    if member.get("three_way_pattern") not in INCLUDED_PATTERNS:
        raise ValueError("P5-T06 may classify only the two addition-relative-base patterns")
    if member.get("base_contains") is not False:
        raise ValueError(
            "P5-T06 addition members must be absent from the persisted base membership"
        )

    evidence = member.get("base_membership_evidence")
    if evidence == "absent_from_complete_base_view":
        return "parent_absent_from_base"
    if evidence == "spawn_set_observation":
        return "spawn_added_to_base_present_parent"
    raise ValueError(
        "P5-T06 could not classify base-parent evidence for "
        f"{member.get('subject_kind')}:{member.get('spawn_key')}: {evidence!r}"
    )


def _load_addition_population(
    connection: sqlite3.Connection,
    *,
    base_source_revision: str | None,
    comparison_source_revision: str | None,
) -> dict[str, Any]:
    """Reuse P5-T04 membership and P5-T05 attribution semantics for the bounded addition slice."""

    divergence = spawn_divergence_report(
        connection,
        source_key=P1_WORLD_COMPARISON_SOURCE_KEY,
        source_revision=comparison_source_revision,
        limit=1_000_000_000,
        top=0,
    )
    if divergence["members_truncated"]:
        raise RuntimeError("P5-T06 requires the complete P5-T04 one-sided membership population")

    source_members = list(divergence["members"])
    parents = {
        (str(member["parent_subject_kind"]), str(member["parent_subject_key"]))
        for member in source_members
    }
    base_revision, base_batches, base_contexts = _base_membership_contexts(
        connection,
        source_key=BASE_SOURCE_KEY,
        source_revision=base_source_revision,
        parents=parents,
    )
    attributed = _attributed_members(source_members, base_contexts)
    p5_t05_pattern_counts = _pattern_counts(attributed)
    if sum(p5_t05_pattern_counts.values()) != len(attributed):
        raise AssertionError("P5-T05 patterns must still partition the P5-T04 one-sided population")

    additions: list[dict[str, Any]] = []
    for source_member in attributed:
        if source_member["three_way_pattern"] not in INCLUDED_PATTERNS:
            continue
        member = dict(source_member)
        member["addition_parent_class"] = _classify_addition_member(member)
        member["coordinates"] = {
            "x": member.get("x"),
            "y": member.get("y"),
            "z": member.get("z"),
        }
        additions.append(member)

    additions.sort(
        key=lambda item: (
            str(item["subject_kind"]),
            _subject_key_sort(str(item["parent_subject_key"])),
            str(item["three_way_pattern"]),
            str(item["spawn_key"]),
        )
    )
    expected_total = sum(p5_t05_pattern_counts[pattern] for pattern in INCLUDED_PATTERNS)
    if len(additions) != expected_total:
        raise AssertionError(
            "P5-T06 included population must equal the two P5-T05 addition patterns"
        )

    return {
        "members": additions,
        "base_source": {
            "source_key": BASE_SOURCE_KEY,
            "source_revision": base_revision,
            "import_batches": base_batches,
        },
        "comparison_source": divergence["comparison_source"],
        "p5_t04_membership_baseline": divergence["membership_baseline"],
        "p5_t05_pattern_counts": p5_t05_pattern_counts,
        "p5_t05_one_sided_member_count": len(attributed),
    }


def _parent_key(member: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(member["subject_kind"]),
        str(member["parent_subject_kind"]),
        str(member["parent_subject_key"]),
    )


def _zone_key(member: dict[str, Any]) -> tuple[int | None, int | None]:
    zone_id = member.get("zone_id")
    map_id = member.get("map_id")
    return (
        None if zone_id is None else int(zone_id),
        None if map_id is None else int(map_id),
    )


def _coverage_maps(
    members: list[dict[str, Any]],
) -> tuple[dict[tuple[str, str, str], str], dict[tuple[int | None, int | None], str]]:
    parent_counts: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    zone_counts: dict[tuple[int | None, int | None], Counter[str]] = defaultdict(Counter)
    for member in members:
        overlay = (
            "active"
            if member["three_way_pattern"] == "active_only_vs_base"
            else "comparison"
        )
        parent_counts[_parent_key(member)][overlay] += 1
        zone_counts[_zone_key(member)][overlay] += 1
    parent_coverage = {
        key: _coverage_label(counter["active"], counter["comparison"])
        for key, counter in parent_counts.items()
    }
    zone_coverage = {
        key: _coverage_label(counter["active"], counter["comparison"])
        for key, counter in zone_counts.items()
    }
    return parent_coverage, zone_coverage


def _parent_rows(
    members: list[dict[str, Any]],
    *,
    included_total: int,
    filtered_total: int,
    global_coverage: dict[tuple[str, str, str], str],
) -> list[dict[str, Any]]:
    counters: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    for member in members:
        key = _parent_key(member)
        counters[key][str(member["three_way_pattern"])] += 1
        counters[key][str(member["addition_parent_class"])] += 1

    ordered = sorted(
        counters,
        key=lambda key: (
            -sum(counters[key][pattern] for pattern in INCLUDED_PATTERNS),
            key[0],
            _subject_key_sort(key[2]),
            key[1],
        ),
    )
    rows: list[dict[str, Any]] = []
    cumulative = 0
    for rank, key in enumerate(ordered, start=1):
        counter = counters[key]
        active_count = counter["active_only_vs_base"]
        comparison_count = counter["comparison_only_vs_base"]
        total = active_count + comparison_count
        cumulative += total
        rows.append(
            {
                "rank": rank,
                "subject_kind": key[0],
                "parent_subject_kind": key[1],
                "parent_subject_key": key[2],
                "overlay_coverage": global_coverage[key],
                "active_addition_count": active_count,
                "comparison_addition_count": comparison_count,
                "parent_absent_from_base_count": counter["parent_absent_from_base"],
                "spawn_added_to_base_present_parent_count": counter[
                    "spawn_added_to_base_present_parent"
                ],
                "total_addition_count": total,
                "cumulative_addition_count": cumulative,
                "cumulative_percentage_of_included_total": _percentage(cumulative, included_total),
                "cumulative_percentage_of_filtered_total": _percentage(cumulative, filtered_total),
            }
        )
    return rows


def _zone_rows(
    members: list[dict[str, Any]],
    *,
    included_total: int,
    filtered_total: int,
    global_coverage: dict[tuple[int | None, int | None], str],
) -> list[dict[str, Any]]:
    counters: dict[tuple[int | None, int | None], Counter[str]] = defaultdict(Counter)
    metadata: dict[tuple[int | None, int | None], dict[str, Any]] = {}
    for member in members:
        key = _zone_key(member)
        counter = counters[key]
        counter[str(member["three_way_pattern"])] += 1
        counter[str(member["addition_parent_class"])] += 1
        counter[str(member["subject_kind"])] += 1
        row = metadata.setdefault(
            key,
            {
                "zone_name": member.get("zone_name"),
                "map_name": member.get("map_name"),
                "coordinate_spaces": set(),
            },
        )
        if row["zone_name"] is None and member.get("zone_name") is not None:
            row["zone_name"] = member["zone_name"]
        if row["map_name"] is None and member.get("map_name") is not None:
            row["map_name"] = member["map_name"]
        coordinate_space = member.get("coordinate_space")
        if coordinate_space is not None:
            row["coordinate_spaces"].add(str(coordinate_space))

    ordered = sorted(
        counters,
        key=lambda key: (
            -sum(counters[key][pattern] for pattern in INCLUDED_PATTERNS),
            key[0] is None,
            -1 if key[0] is None else key[0],
            key[1] is None,
            -1 if key[1] is None else key[1],
            "" if metadata[key]["zone_name"] is None else str(metadata[key]["zone_name"]),
            "" if metadata[key]["map_name"] is None else str(metadata[key]["map_name"]),
        ),
    )
    rows: list[dict[str, Any]] = []
    cumulative = 0
    for rank, key in enumerate(ordered, start=1):
        counter = counters[key]
        active_count = counter["active_only_vs_base"]
        comparison_count = counter["comparison_only_vs_base"]
        total = active_count + comparison_count
        cumulative += total
        rows.append(
            {
                "rank": rank,
                "zone_id": key[0],
                "zone_name": metadata[key]["zone_name"],
                "map_id": key[1],
                "map_name": metadata[key]["map_name"],
                "coordinate_spaces": sorted(metadata[key]["coordinate_spaces"]),
                "overlay_coverage": global_coverage[key],
                "active_addition_count": active_count,
                "comparison_addition_count": comparison_count,
                "parent_absent_from_base_count": counter["parent_absent_from_base"],
                "spawn_added_to_base_present_parent_count": counter[
                    "spawn_added_to_base_present_parent"
                ],
                "creature_spawn_addition_count": counter["creature_spawn"],
                "gameobject_spawn_addition_count": counter["gameobject_spawn"],
                "total_addition_count": total,
                "cumulative_addition_count": cumulative,
                "cumulative_percentage_of_included_total": _percentage(cumulative, included_total),
                "cumulative_percentage_of_filtered_total": _percentage(cumulative, filtered_total),
            }
        )
    return rows


def _coverage_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    group_counts = Counter(str(row["overlay_coverage"]) for row in rows)
    member_counts = Counter()
    for row in rows:
        member_counts[str(row["overlay_coverage"])] += int(row["total_addition_count"])
    return [
        {
            "overlay_coverage": coverage,
            "group_count": group_counts[coverage],
            "member_count": member_counts[coverage],
        }
        for coverage in OVERLAY_COVERAGE_CLASSES
    ]


def overlay_addition_report(
    connection: sqlite3.Connection,
    *,
    base_source_revision: str | None = EXPECTED_BASE_REVISION,
    comparison_source_revision: str | None = EXPECTED_COMPARISON_REVISION,
    pattern: str | None = None,
    addition_parent_class: str | None = None,
    subject_kind: str | None = None,
    parent_key: str | int | None = None,
    zone_id: int | None = None,
    overlay_coverage: str | None = None,
    overlay_coverage_scope: str = "parent",
    limit: int = 100,
    top: int = 20,
) -> dict[str, Any]:
    """Explain only the P5-T05 additions relative to the complete base pfQuest view."""

    if pattern is not None and pattern not in INCLUDED_PATTERNS:
        raise ValueError(f"pattern must be one of {list(INCLUDED_PATTERNS)!r}")
    if addition_parent_class is not None and addition_parent_class not in ADDITION_PARENT_CLASSES:
        raise ValueError(
            f"addition_parent_class must be one of {list(ADDITION_PARENT_CLASSES)!r}"
        )
    if subject_kind is not None and subject_kind not in SPAWN_SUBJECT_KINDS:
        raise ValueError(f"subject_kind must be one of {list(SPAWN_SUBJECT_KINDS)!r}")
    if overlay_coverage is not None and overlay_coverage not in OVERLAY_COVERAGE_CLASSES:
        raise ValueError(
            f"overlay_coverage must be one of {list(OVERLAY_COVERAGE_CLASSES)!r}"
        )
    if overlay_coverage_scope not in OVERLAY_COVERAGE_SCOPES:
        raise ValueError(
            f"overlay_coverage_scope must be one of {list(OVERLAY_COVERAGE_SCOPES)!r}"
        )
    if limit < 0 or top < 0:
        raise ValueError("limit and top must be non-negative")

    population = _load_addition_population(
        connection,
        base_source_revision=base_source_revision,
        comparison_source_revision=comparison_source_revision,
    )
    members = list(population["members"])
    included_total = len(members)
    parent_coverage, zone_coverage = _coverage_maps(members)

    parent_rows = _parent_rows(
        members,
        included_total=included_total,
        filtered_total=included_total,
        global_coverage=parent_coverage,
    )
    zone_rows = _zone_rows(
        members,
        included_total=included_total,
        filtered_total=included_total,
        global_coverage=zone_coverage,
    )

    parent_filter = None if parent_key is None else str(parent_key)
    filtered = [
        member
        for member in members
        if (pattern is None or member["three_way_pattern"] == pattern)
        and (
            addition_parent_class is None
            or member["addition_parent_class"] == addition_parent_class
        )
        and (subject_kind is None or member["subject_kind"] == subject_kind)
        and (parent_filter is None or member["parent_subject_key"] == parent_filter)
        and (zone_id is None or member["zone_id"] == zone_id)
        and (
            overlay_coverage is None
            or (
                parent_coverage[_parent_key(member)]
                if overlay_coverage_scope == "parent"
                else zone_coverage[_zone_key(member)]
            )
            == overlay_coverage
        )
    ]
    filtered_total = len(filtered)
    filtered_parent_rows = _parent_rows(
        filtered,
        included_total=included_total,
        filtered_total=filtered_total,
        global_coverage=parent_coverage,
    )
    filtered_zone_rows = _zone_rows(
        filtered,
        included_total=included_total,
        filtered_total=filtered_total,
        global_coverage=zone_coverage,
    )

    class_counts = Counter(str(member["addition_parent_class"]) for member in members)
    pattern_counts = Counter(str(member["three_way_pattern"]) for member in members)
    filtered_class_counts = Counter(str(member["addition_parent_class"]) for member in filtered)
    filtered_pattern_counts = Counter(str(member["three_way_pattern"]) for member in filtered)

    by_pattern_class = Counter(
        (str(member["three_way_pattern"]), str(member["addition_parent_class"]))
        for member in members
    )
    by_kind_class = Counter(
        (str(member["subject_kind"]), str(member["addition_parent_class"]))
        for member in members
    )

    selected_contexts: dict[tuple[str, str, str | None], Counter[str]] = defaultdict(Counter)
    for member in members:
        key = (
            str(member["active_selected_source_key"]),
            str(member["active_selected_source_revision"]),
            member["active_selected_selection_policy"],
        )
        selected_contexts[key][str(member["addition_parent_class"])] += 1
        selected_contexts[key][str(member["three_way_pattern"])] += 1

    details = filtered[:limit] if limit else []
    return {
        "scope": OVERLAY_ADDITION_SCOPE,
        "filters": {
            "pattern": pattern,
            "addition_parent_class": addition_parent_class,
            "subject_kind": subject_kind,
            "parent_key": parent_filter,
            "zone_id": zone_id,
            "overlay_coverage": overlay_coverage,
            "overlay_coverage_scope": overlay_coverage_scope,
        },
        "base_source": population["base_source"],
        "comparison_source": population["comparison_source"],
        "p5_t04_membership_baseline": population["p5_t04_membership_baseline"],
        "p5_t05_pattern_baseline": {
            pattern_name: int(population["p5_t05_pattern_counts"][pattern_name])
            for pattern_name in PATTERNS
        },
        "p5_t05_one_sided_member_count": population["p5_t05_one_sided_member_count"],
        "included_patterns": list(INCLUDED_PATTERNS),
        "included_member_count": included_total,
        "pattern_counts": {name: pattern_counts[name] for name in INCLUDED_PATTERNS},
        "addition_parent_class_counts": {
            name: class_counts[name] for name in ADDITION_PARENT_CLASSES
        },
        "by_pattern_addition_parent_class": [
            {
                "pattern": pattern_name,
                "addition_parent_class": class_name,
                "member_count": by_pattern_class[(pattern_name, class_name)],
            }
            for pattern_name in INCLUDED_PATTERNS
            for class_name in ADDITION_PARENT_CLASSES
        ],
        "by_subject_kind_addition_parent_class": [
            {
                "subject_kind": kind,
                "addition_parent_class": class_name,
                "member_count": by_kind_class[(kind, class_name)],
            }
            for kind in SPAWN_SUBJECT_KINDS
            for class_name in ADDITION_PARENT_CLASSES
        ],
        "active_selected_contexts": [
            {
                "source_key": key[0],
                "source_revision": key[1],
                "selection_policy": key[2],
                "member_count": sum(
                    selected_contexts[key][pattern_name] for pattern_name in INCLUDED_PATTERNS
                ),
                "pattern_counts": {
                    pattern_name: selected_contexts[key][pattern_name]
                    for pattern_name in INCLUDED_PATTERNS
                },
                "addition_parent_class_counts": {
                    class_name: selected_contexts[key][class_name]
                    for class_name in ADDITION_PARENT_CLASSES
                },
            }
            for key in sorted(
                selected_contexts,
                key=lambda item: (item[0], item[1], "" if item[2] is None else str(item[2])),
            )
        ],
        "parent_template_counts": parent_rows,
        "zone_map_counts": zone_rows,
        "parent_overlay_coverage_counts": _coverage_summary(parent_rows),
        "zone_map_overlay_coverage_counts": _coverage_summary(zone_rows),
        "filtered_member_count": filtered_total,
        "filtered_pattern_counts": {
            name: filtered_pattern_counts[name] for name in INCLUDED_PATTERNS
        },
        "filtered_addition_parent_class_counts": {
            name: filtered_class_counts[name] for name in ADDITION_PARENT_CLASSES
        },
        "top_parent_concentrations": filtered_parent_rows[:top] if top else [],
        "top_zone_map_concentrations": filtered_zone_rows[:top] if top else [],
        "detail_limit": limit,
        "top_limit": top,
        "returned_member_count": len(details),
        "members_truncated": len(details) < filtered_total,
        "members": details,
    }


def _nonnegative_int(value: str) -> int:
    import argparse

    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def _print_human(payload: dict[str, Any]) -> None:
    print(f"Overlay addition scope: {payload['scope']}")
    print(f"Included additions: {payload['included_member_count']}")
    print("P5-T05 included patterns:")
    for pattern in INCLUDED_PATTERNS:
        print(f"- {pattern}: {payload['pattern_counts'][pattern]}")
    print("Base-parent classes:")
    for class_name in ADDITION_PARENT_CLASSES:
        print(f"- {class_name}: {payload['addition_parent_class_counts'][class_name]}")
    print(f"Filtered additions: {payload['filtered_member_count']}")
    print("Top zone/map concentrations:")
    for row in payload["top_zone_map_concentrations"]:
        zone_label = row["zone_name"] or f"zone={row['zone_id']}"
        map_label = row["map_name"] or f"map={row['map_id']}"
        print(
            f"- #{row['rank']} {zone_label} / {map_label}: {row['total_addition_count']} "
            f"(cum {row['cumulative_percentage_of_included_total']:.2f}% of included)"
        )
    for member in payload["members"]:
        print(
            f"- {member['subject_kind']} parent={member['parent_subject_key']} "
            f"{member['three_way_pattern']} {member['addition_parent_class']} "
            f"{member['spawn_key']}"
        )


def main(argv: list[str] | None = None) -> int:
    """Run the P5-T06 read-only overlay-addition coverage audit."""

    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        prog="python -m octogamedb.audit_overlay_additions",
        description=(
            "Explain only P5-T05 active/comparison additions relative to the persisted complete "
            "base pfQuest view, grouped by base-parent evidence and canonical geography."
        ),
    )
    parser.add_argument("--base-source-revision", default=EXPECTED_BASE_REVISION)
    parser.add_argument("--comparison-source-revision", default=EXPECTED_COMPARISON_REVISION)
    parser.add_argument("--pattern", choices=INCLUDED_PATTERNS)
    parser.add_argument("--addition-parent-class", choices=ADDITION_PARENT_CLASSES)
    parser.add_argument("--subject-kind", choices=SPAWN_SUBJECT_KINDS)
    parser.add_argument("--parent-key")
    parser.add_argument("--zone-id", type=int)
    parser.add_argument(
        "--overlay-coverage",
        choices=OVERLAY_COVERAGE_CLASSES,
        help="Filter by active/comparison/both overlay coverage.",
    )
    parser.add_argument(
        "--overlay-coverage-scope",
        choices=OVERLAY_COVERAGE_SCOPES,
        default="parent",
        help="Grouping level used by --overlay-coverage (default: parent).",
    )
    parser.add_argument("--limit", type=_nonnegative_int, default=100)
    parser.add_argument("--top", type=_nonnegative_int, default=20)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/generated/octogamedb.sqlite3"),
        help="SQLite database path (opened mode=ro).",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    connection = _open_read_only_database(str(args.db))
    try:
        payload = overlay_addition_report(
            connection,
            base_source_revision=args.base_source_revision,
            comparison_source_revision=args.comparison_source_revision,
            pattern=args.pattern,
            addition_parent_class=args.addition_parent_class,
            subject_kind=args.subject_kind,
            parent_key=args.parent_key,
            zone_id=args.zone_id,
            overlay_coverage=args.overlay_coverage,
            overlay_coverage_scope=args.overlay_coverage_scope,
            limit=args.limit,
            top=args.top,
        )
    finally:
        connection.close()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_human(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
