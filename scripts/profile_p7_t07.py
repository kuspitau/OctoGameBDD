from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import statistics
import time
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from octogamedb import world_entity_search as wes
from octogamedb import zone_search as zs

CANONICAL_SHA256 = "60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23"
DEFAULT_ZONES = (1, 12, 14)
LIVE_PHASES = frozenset(
    {
        "zone.query_zones",
        "zone.query_world_entities",
        "world.template_rows",
        "world.geography_rows",
        "world.selected_spawn_sets",
        "world.sort_candidates",
        "zone.project_entities",
        "zone.collect_items",
        "zone.collect_quests",
        "zone.collect_vendors",
        "zone.collect_trainers",
        "zone.recipe_projection",
    }
)
MILESTONE_INTERVALS = {
    "world.evaluate_candidate": 2000,
    "world.entity_detail": 100,
}


class Progress:
    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.started = time.perf_counter()

    def __call__(self, message: str) -> None:
        if not self.enabled:
            return
        elapsed = time.perf_counter() - self.started
        print(f"[P7-T07 +{elapsed:8.2f}s] {message}", flush=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _connect_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _timed_call(func: Callable[..., Any], *args: Any, **kwargs: Any) -> tuple[Any, float]:
    started = time.perf_counter()
    result = func(*args, **kwargs)
    return result, time.perf_counter() - started


@contextmanager
def _phase_profiling(
    progress: Progress,
) -> Iterator[dict[str, dict[str, float | int]]]:
    timings: dict[str, list[float]] = defaultdict(list)
    calls: dict[str, int] = defaultdict(int)
    patches: list[tuple[object, str, Any]] = []

    def patch(module: object, name: str, label: str) -> None:
        original = getattr(module, name)

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if label in LIVE_PHASES:
                progress(f"    phase {label} START")
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - started
                timings[label].append(elapsed)
                calls[label] += 1
                if label in LIVE_PHASES:
                    progress(f"    phase {label} DONE ({elapsed:.3f}s)")
                interval = MILESTONE_INTERVALS.get(label)
                if interval is not None and calls[label] % interval == 0:
                    progress(f"    phase {label}: {calls[label]} calls completed")

        patches.append((module, name, original))
        setattr(module, name, wrapped)

    # P7-T05 major phases.
    patch(wes, "_template_rows", "world.template_rows")
    patch(wes, "_geography_rows", "world.geography_rows")
    patch(wes, "_selected_spawn_sets", "world.selected_spawn_sets")
    patch(wes, "_evaluate_candidate", "world.evaluate_candidate")
    patch(wes, "_sort_candidates", "world.sort_candidates")
    patch(wes, "_entity_detail", "world.entity_detail")
    patch(wes, "_full_spawns", "detail.full_spawns")
    patch(wes, "_item_roles", "detail.item_roles")
    patch(wes, "_quest_roles", "detail.quest_roles")
    patch(wes, "_trainer_roles", "detail.trainer_roles")
    patch(wes, "_template_provenance", "detail.template_provenance")
    patch(wes, "_selected_fact", "detail.selected_fact")
    patch(wes, "_selected_relation_rows", "detail.selected_relation_rows")
    if hasattr(wes, "_selected_quest_relation_index"):
        patch(
            wes,
            "_selected_quest_relation_index",
            "detail.selected_quest_relation_index",
        )

    # P7-T06 composition phases. Patch the imported alias, not only WES.
    patch(zs, "query_zones", "zone.query_zones")
    patch(zs, "query_world_entities", "zone.query_world_entities")
    patch(zs, "_project_zone_entities", "zone.project_entities")
    patch(zs, "_collect_item_acquisition", "zone.collect_items")
    patch(zs, "_collect_quests", "zone.collect_quests")
    patch(zs, "_collect_vendors", "zone.collect_vendors")
    patch(zs, "_collect_trainers", "zone.collect_trainers")
    patch(zs, "_recipe_projection", "zone.recipe_projection")

    try:
        summary: dict[str, dict[str, float | int]] = {}
        yield summary
    finally:
        for module, name, original in reversed(patches):
            setattr(module, name, original)
        for label in sorted(timings):
            values = timings[label]
            summary[label] = {
                "calls": calls[label],
                "total_seconds": round(sum(values), 6),
                "max_seconds": round(max(values), 6),
                "mean_seconds": round(statistics.fmean(values), 6),
            }


def _table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = (
        "creatures",
        "gameobjects",
        "creature_spawns",
        "gameobject_spawns",
        "observation_groups",
        "canonical_selections",
        "source_observations",
        "creature_loot",
        "gameobject_loot",
        "vendor_items",
        "quest_creature_endpoints",
        "quest_gameobject_endpoints",
        "quest_creature_objectives",
        "quest_gameobject_objectives",
        "recipe_trainer_sources",
    )
    return {
        table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in tables
    }


def _indexes(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT name, tbl_name, sql
        FROM sqlite_master
        WHERE type = 'index' AND sql IS NOT NULL
        ORDER BY tbl_name, name
        """
    ).fetchall()
    return [
        {"name": str(row["name"]), "table": str(row["tbl_name"]), "sql": str(row["sql"])}
        for row in rows
    ]


def _plan(connection: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[str]:
    return [str(row["detail"]) for row in connection.execute("EXPLAIN QUERY PLAN " + sql, params)]


def _query_plans(connection: sqlite3.Connection, zone_id: int) -> dict[str, list[str]]:
    return {
        "zone_positive_creatures": _plan(
            connection,
            """
            SELECT DISTINCT s.creature_id
            FROM creature_spawns AS s
            WHERE s.zone_id = ?
            ORDER BY s.creature_id
            """,
            (zone_id,),
        ),
        "zone_positive_gameobjects": _plan(
            connection,
            """
            SELECT DISTINCT s.gameobject_id
            FROM gameobject_spawns AS s
            WHERE s.zone_id = ?
            ORDER BY s.gameobject_id
            """,
            (zone_id,),
        ),
        "selected_fact_lookup": _plan(
            connection,
            """
            SELECT cs.observation_id
            FROM observation_groups AS og
            JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
            WHERE og.subject_kind = ? AND og.subject_key = ?
              AND og.fact_key = ? AND og.fact_instance_key = ?
            """,
            ("creature", "1", "name", ""),
        ),
        "selected_spawn_sets": _plan(
            connection,
            """
            SELECT og.subject_kind, og.subject_key
            FROM observation_groups AS og
            JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
            WHERE og.fact_key = 'spawn_set' AND og.fact_instance_key = ''
              AND og.subject_kind IN ('creature', 'gameobject')
            ORDER BY og.subject_kind, og.subject_key
            """,
        ),
        "legacy_selected_quest_relation_lookup": _plan(
            connection,
            """
            SELECT og.subject_key, og.fact_instance_key
            FROM observation_groups AS og
            JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
            WHERE og.subject_kind = 'quest' AND og.fact_key = 'endpoint'
              AND og.fact_instance_key IN (?, ?)
            ORDER BY og.subject_key, og.fact_instance_key
            """,
            ("giver:creature:1", "finisher:creature:1"),
        ),
        "batched_selected_quest_relations": _plan(
            connection,
            """
            SELECT og.subject_key, og.fact_key, og.fact_instance_key
            FROM observation_groups AS og
            JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
            WHERE og.subject_kind = 'quest'
              AND og.fact_key IN (
                  'endpoint', 'objective_creature', 'objective_gameobject'
              )
            ORDER BY og.fact_key, og.fact_instance_key, og.subject_key
            """,
        ),
        "full_creature_spawns": _plan(
            connection,
            """
            SELECT s.spawn_id, s.spawn_key, s.zone_id, COALESCE(s.map_id, z.map_id) AS map_id
            FROM creature_spawns AS s
            LEFT JOIN zones AS z ON z.zone_id = s.zone_id
            WHERE s.creature_id = ?
            ORDER BY s.spawn_key
            """,
            (1,),
        ),
    }


def _run_zone(
    connection: sqlite3.Connection,
    zone_id: int,
    include_recipes: bool,
    progress: Progress,
) -> dict[str, Any]:
    with _phase_profiling(progress) as phases:
        payload, elapsed = _timed_call(
            zs.inspect_zone,
            connection,
            zone_id,
            include_recipes=include_recipes,
        )
    summary = payload["world_entities"]["summary"]
    return {
        "zone_id": zone_id,
        "include_recipes": include_recipes,
        "elapsed_seconds": round(elapsed, 6),
        "world_summary": summary,
        "projected_entity_count": len(payload["world_entities"]["results"]),
        "item_count": len(payload["items"]["results"]),
        "quest_role_count": sum(
            len(payload["quests"][key]) for key in ("given", "finished", "objectives")
        ),
        "vendor_count": len(payload["vendors"]),
        "trainer_known_count": len(payload["trainers"]["known"]),
        "trainer_unknown_count": len(payload["trainers"]["unknown_relations"]),
        "phases": phases,
    }


def _run_label(
    *,
    kind: str,
    current: int,
    total: int,
    zone_id: int,
    iteration: int | None = None,
    repeat: int | None = None,
) -> str:
    label = f"[{kind} {current}/{total}] zone={zone_id}"
    if iteration is not None and repeat is not None:
        label += f" iteration={iteration}/{repeat}"
    return label


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only P7-T07 zone/world query profiler")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/generated/octogamedb.sqlite3"),
        help="accepted canonical SQLite DB",
    )
    parser.add_argument("--zones", nargs="+", type=int, default=list(DEFAULT_ZONES))
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--include-recipes", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("p7_t07_profile.json"))
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress incremental progress output; final summary is still printed",
    )
    args = parser.parse_args()

    if args.repeat < 1:
        parser.error("--repeat must be >= 1")
    if not args.db.is_file():
        parser.error(f"database not found: {args.db}")

    progress = Progress(enabled=not args.quiet)
    progress(
        "START "
        f"db={args.db} zones={','.join(str(zone) for zone in args.zones)} "
        f"repeat={args.repeat} include_recipes={args.include_recipes} output={args.output}"
    )

    progress("[setup 1/3] hashing canonical DB before profiling...")
    before_sha = _sha256(args.db)
    if before_sha != CANONICAL_SHA256:
        raise SystemExit(
            "canonical SHA mismatch: "
            f"expected {CANONICAL_SHA256}, got {before_sha}; "
            "refusing to profile a different baseline"
        )
    progress(f"[setup 1/3] canonical SHA verified: {before_sha}")

    progress("[setup 2/3] starting cold-run group")
    cold_runs: list[dict[str, Any]] = []
    cold_total = len(args.zones)
    for current, zone_id in enumerate(args.zones, start=1):
        label = _run_label(kind="cold", current=current, total=cold_total, zone_id=zone_id)
        progress(f"{label} START (fresh read-only connection)")
        connection = _connect_read_only(args.db)
        try:
            result = _run_zone(connection, zone_id, args.include_recipes, progress)
            cold_runs.append(result)
        finally:
            connection.close()
        progress(
            f"{label} DONE ({result['elapsed_seconds']:.3f}s; "
            f"entities={result['projected_entity_count']}; items={result['item_count']})"
        )

    progress("[setup 3/3] collecting schema/cardinality/index/query-plan metadata...")
    connection = _connect_read_only(args.db)
    try:
        schema_version = int(
            connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        )
        counts = _table_counts(connection)
        indexes = _indexes(connection)
        plans = _query_plans(connection, args.zones[0])
        progress(
            f"[setup 3/3] metadata collected: schema_version={schema_version}; "
            f"tables={len(counts)}; indexes={len(indexes)}; plans={len(plans)}"
        )

        repeated_runs: list[dict[str, Any]] = []
        repeated_total = args.repeat * len(args.zones)
        current = 0
        for iteration in range(1, args.repeat + 1):
            for zone_id in args.zones:
                current += 1
                label = _run_label(
                    kind="repeat",
                    current=current,
                    total=repeated_total,
                    zone_id=zone_id,
                    iteration=iteration,
                    repeat=args.repeat,
                )
                progress(f"{label} START (shared read-only connection)")
                result = _run_zone(connection, zone_id, args.include_recipes, progress)
                result["iteration"] = iteration
                repeated_runs.append(result)
                progress(
                    f"{label} DONE ({result['elapsed_seconds']:.3f}s; "
                    f"entities={result['projected_entity_count']}; items={result['item_count']})"
                )

        progress("[checks 1/2] PRAGMA integrity_check START")
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        progress(f"[checks 1/2] PRAGMA integrity_check DONE: {integrity}")

        progress("[checks 2/2] PRAGMA foreign_key_check START")
        foreign_keys = [list(row) for row in connection.execute("PRAGMA foreign_key_check")]
        progress(f"[checks 2/2] PRAGMA foreign_key_check DONE: {len(foreign_keys)} violation(s)")
    finally:
        connection.close()

    progress("[finalize 1/3] hashing canonical DB after profiling...")
    after_sha = _sha256(args.db)
    unchanged = before_sha == after_sha
    progress(f"[finalize 1/3] post-run SHA={after_sha}; unchanged={unchanged}")

    report = {
        "task": "P7-T07",
        "database": str(args.db),
        "canonical_sha256_before": before_sha,
        "canonical_sha256_after": after_sha,
        "canonical_db_unchanged": unchanged,
        "schema_version": schema_version,
        "zones": args.zones,
        "include_recipes": args.include_recipes,
        "repeat": args.repeat,
        "table_counts": counts,
        "indexes": indexes,
        "query_plans": plans,
        "cold_runs": cold_runs,
        "repeated_runs": repeated_runs,
        "integrity_check": integrity,
        "foreign_key_check": foreign_keys,
    }

    progress(f"[finalize 2/3] writing JSON report: {args.output}")
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    progress(f"[finalize 2/3] report written: {args.output}")
    progress("[finalize 3/3] profiling complete")

    print(f"P7_T07_PROFILE_OK output={args.output}", flush=True)
    print(f"canonical_sha256={after_sha}", flush=True)
    for run in cold_runs:
        print(
            f"cold zone={run['zone_id']} elapsed={run['elapsed_seconds']:.3f}s "
            f"entities={run['projected_entity_count']}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
