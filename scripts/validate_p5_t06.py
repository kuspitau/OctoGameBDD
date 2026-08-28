"""Autonomous Level-2 validation for P5-T06 against canonical migration-13 data."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EXPECTED_CANONICAL_SHA256 = (
    "623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7"
)
EXPECTED_BASE_REVISION = (
    "sha256:5087d2d0a5b1c2706b7fc7ccb5ffd447c91aa24d91a23f102f2c7ac1d7440147"
)
EXPECTED_COMPARISON_REVISION = (
    "sha256:eddd325a9a0eab2616c7b70d03e23d55f1a0c4127a293426ea07a17c0f2421db"
)
EXPECTED_P5_T05_PATTERNS = {
    "base_active_not_comparison": 17,
    "active_only_vs_base": 15_988,
    "base_comparison_not_active": 1_571,
    "comparison_only_vs_base": 4_719,
}
EXPECTED_INCLUDED_TOTAL = 20_707
ADDITION_PARENT_CLASSES = (
    "parent_absent_from_base",
    "spawn_added_to_base_present_parent",
)
OVERLAY_COVERAGE_CLASSES = ("active_only", "comparison_only", "both")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)
    print(f"[PASS] {message}")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run_json(project_root: Path, *, module: str, args: list[str], output: Path) -> dict[str, Any]:
    command = [sys.executable, "-m", module, *args, "--json"]
    completed = subprocess.run(
        command,
        cwd=project_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(command)
            + "\nSTDOUT:\n"
            + completed.stdout
            + "\nSTDERR:\n"
            + completed.stderr
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from {' '.join(command)}") from exc
    _write_json(output, payload)
    return payload


def _read_only_integrity(path: Path) -> None:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        migration = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    finally:
        connection.close()
    _require(integrity == "ok", "snapshot PRAGMA integrity_check is ok")
    _require(foreign_keys == [], "snapshot PRAGMA foreign_key_check is empty")
    _require(int(migration) == 13, "snapshot is canonical migration 13")


def _validate_p5_t05_regression(report: dict[str, Any]) -> None:
    _require(
        report.get("scope") == "p5-t05-three-way-base-active-octo-spawn-attribution",
        "P5-T05 scope is unchanged",
    )
    measured = {row["pattern"]: int(row["member_count"]) for row in report["patterns"]}
    _require(
        measured == EXPECTED_P5_T05_PATTERNS,
        "P5-T05 four-pattern baseline is exactly unchanged",
    )
    _require(report["one_sided_member_count"] == 22_295, "P5-T05 one-sided total remains 22,295")
    _require(
        report["base_source"]["source_revision"] == EXPECTED_BASE_REVISION,
        "P5-T05 base revision is unchanged",
    )
    _require(
        report["comparison_source"]["source_revision"] == EXPECTED_COMPARISON_REVISION,
        "P5-T05 comparison revision is unchanged",
    )


def _validate_concentration(rows: list[dict[str, Any]], *, total: int, label: str) -> None:
    cumulative = 0
    valid = True
    for expected_rank, row in enumerate(rows, start=1):
        cumulative += int(row["total_addition_count"])
        valid = valid and int(row["rank"]) == expected_rank
        valid = valid and int(row["cumulative_addition_count"]) == cumulative
    valid = valid and cumulative == total
    valid = valid and (not rows or rows[-1]["cumulative_percentage_of_included_total"] == 100.0)
    _require(valid, f"full {label} ranking/cumulative coverage reconciles deterministically")


def _validate_coverage_summary(
    summary: list[dict[str, Any]],
    *,
    group_count: int,
    member_count: int,
    label: str,
) -> None:
    by_class = {row["overlay_coverage"]: row for row in summary}
    _require(
        set(by_class) == set(OVERLAY_COVERAGE_CLASSES),
        f"{label} overlay coverage exposes all three deterministic classes",
    )
    _require(
        sum(int(row["group_count"]) for row in summary) == group_count,
        f"{label} overlay group counts reconcile",
    )
    _require(
        sum(int(row["member_count"]) for row in summary) == member_count,
        f"{label} overlay member counts reconcile to {member_count}",
    )


def _validate_p5_t06(report: dict[str, Any]) -> dict[str, int]:
    _require(
        report.get("scope") == "p5-t06-overlay-addition-coverage",
        "P5-T06 scope is correct",
    )
    _require(
        report["p5_t05_pattern_baseline"] == EXPECTED_P5_T05_PATTERNS,
        "P5-T06 embeds the exact P5-T05 four-pattern regression baseline",
    )
    _require(
        report["base_source"]["source_key"] == "pfquest"
        and report["base_source"]["source_revision"] == EXPECTED_BASE_REVISION,
        "P5-T06 preserves the exact persisted base source/revision",
    )
    _require(
        report["comparison_source"]["source_key"] == "pfquest-octo"
        and report["comparison_source"]["source_revision"] == EXPECTED_COMPARISON_REVISION,
        "P5-T06 preserves the exact comparison source/revision",
    )
    _require(
        report["included_patterns"]
        == ["active_only_vs_base", "comparison_only_vs_base"],
        "P5-T06 included-pattern contract is exact and ordered",
    )
    _require(report["included_member_count"] == EXPECTED_INCLUDED_TOTAL, "included total is 20,707")
    _require(
        report["pattern_counts"]
        == {
            "active_only_vs_base": 15_988,
            "comparison_only_vs_base": 4_719,
        },
        "P5-T06 contains exactly the two addition-relative-base patterns",
    )

    class_counts = {
        key: int(report["addition_parent_class_counts"][key])
        for key in ADDITION_PARENT_CLASSES
    }
    _require(
        sum(class_counts.values()) == EXPECTED_INCLUDED_TOTAL,
        "the two base-parent classes partition all 20,707 included members",
    )
    _require(
        sum(int(row["member_count"]) for row in report["by_pattern_addition_parent_class"])
        == EXPECTED_INCLUDED_TOTAL,
        "pattern x base-parent-class aggregates reconcile",
    )
    _require(
        sum(int(row["member_count"]) for row in report["by_subject_kind_addition_parent_class"])
        == EXPECTED_INCLUDED_TOTAL,
        "subject-kind x base-parent-class aggregates reconcile",
    )
    contexts = report["active_selected_contexts"]
    _require(
        sum(int(row["member_count"]) for row in contexts) == EXPECTED_INCLUDED_TOTAL,
        "active selected source/revision/policy contexts reconcile",
    )
    _require(
        all(
            sum(int(value) for value in row["pattern_counts"].values())
            == int(row["member_count"])
            and sum(int(value) for value in row["addition_parent_class_counts"].values())
            == int(row["member_count"])
            for row in contexts
        ),
        "every active selected context reconciles pattern and base-parent classes",
    )

    def aggregate_class_counts(rows: list[dict[str, Any]], count_key: str) -> dict[str, int]:
        return {
            class_name: sum(
                int(row[count_key][class_name])
                if isinstance(row[count_key], dict)
                else int(row[class_name])
                for row in rows
            )
            for class_name in ADDITION_PARENT_CLASSES
        }

    context_class_counts = aggregate_class_counts(contexts, "addition_parent_class_counts")
    _require(
        context_class_counts == class_counts,
        "active selected context class totals equal the global base-parent split",
    )

    by_pattern_class = report["by_pattern_addition_parent_class"]
    measured_by_pattern = {
        pattern: sum(
            int(row["member_count"])
            for row in by_pattern_class
            if row["pattern"] == pattern
        )
        for pattern in ("active_only_vs_base", "comparison_only_vs_base")
    }
    _require(
        measured_by_pattern == report["pattern_counts"],
        "pattern x base-parent-class rows reconcile to both included patterns",
    )

    parent_rows = report["parent_template_counts"]
    zone_rows = report["zone_map_counts"]
    _validate_concentration(parent_rows, total=EXPECTED_INCLUDED_TOTAL, label="parent")
    _validate_concentration(zone_rows, total=EXPECTED_INCLUDED_TOTAL, label="zone/map")
    _validate_coverage_summary(
        report["parent_overlay_coverage_counts"],
        group_count=len(parent_rows),
        member_count=EXPECTED_INCLUDED_TOTAL,
        label="parent",
    )
    _validate_coverage_summary(
        report["zone_map_overlay_coverage_counts"],
        group_count=len(zone_rows),
        member_count=EXPECTED_INCLUDED_TOTAL,
        label="zone/map",
    )

    by_kind_class = report["by_subject_kind_addition_parent_class"]
    kind_class_counts = {
        class_name: sum(
            int(row["member_count"])
            for row in by_kind_class
            if row["addition_parent_class"] == class_name
        )
        for class_name in ADDITION_PARENT_CLASSES
    }
    parent_class_counts = {
        "parent_absent_from_base": sum(
            int(row["parent_absent_from_base_count"]) for row in parent_rows
        ),
        "spawn_added_to_base_present_parent": sum(
            int(row["spawn_added_to_base_present_parent_count"]) for row in parent_rows
        ),
    }
    zone_class_counts = {
        "parent_absent_from_base": sum(
            int(row["parent_absent_from_base_count"]) for row in zone_rows
        ),
        "spawn_added_to_base_present_parent": sum(
            int(row["spawn_added_to_base_present_parent_count"]) for row in zone_rows
        ),
    }
    _require(
        kind_class_counts == class_counts
        and parent_class_counts == class_counts
        and zone_class_counts == class_counts,
        "kind, parent and zone/map class totals equal the global base-parent split",
    )

    parent_rows_reconcile = all(
        int(row["active_addition_count"]) + int(row["comparison_addition_count"])
        == int(row["total_addition_count"])
        and int(row["parent_absent_from_base_count"])
        + int(row["spawn_added_to_base_present_parent_count"])
        == int(row["total_addition_count"])
        for row in parent_rows
    )
    _require(parent_rows_reconcile, "every parent row reconciles overlay and base-parent classes")

    zone_rows_reconcile = all(
        int(row["active_addition_count"]) + int(row["comparison_addition_count"])
        == int(row["total_addition_count"])
        and int(row["parent_absent_from_base_count"])
        + int(row["spawn_added_to_base_present_parent_count"])
        == int(row["total_addition_count"])
        and int(row["creature_spawn_addition_count"])
        + int(row["gameobject_spawn_addition_count"])
        == int(row["total_addition_count"])
        for row in zone_rows
    )
    _require(zone_rows_reconcile, "every zone/map row reconciles overlay, class and kind counts")

    _require(report["returned_member_count"] == 0, "summary run returns no detailed members")
    print("[INFO] Measured P5-T06 base-parent split: " + json.dumps(class_counts, sort_keys=True))
    print(
        "[INFO] Measured parent overlay coverage: "
        + json.dumps(report["parent_overlay_coverage_counts"], sort_keys=True)
    )
    print(
        "[INFO] Measured zone/map overlay coverage: "
        + json.dumps(report["zone_map_overlay_coverage_counts"], sort_keys=True)
    )
    return class_counts


def _validate_example_member(member: dict[str, Any]) -> None:
    required = (
        "subject_kind",
        "spawn_key",
        "parent_subject_kind",
        "parent_subject_key",
        "three_way_pattern",
        "base_contains",
        "active_contains",
        "comparison_contains",
        "base_membership_evidence",
        "base_source_key",
        "base_source_revision",
        "base_import_batches",
        "addition_parent_class",
        "active_selected_source_key",
        "active_selected_source_revision",
        "active_selected_selection_policy",
        "comparison_source_key",
        "comparison_source_revision",
        "comparison_import_batches",
        "coordinate_space",
        "zone_id",
        "map_id",
        "coordinates",
    )
    missing = [key for key in required if key not in member]
    _require(not missing, f"example retains required member provenance fields: missing={missing}")
    _require(member["base_contains"] is False, "example is absent from exact base membership")
    _require(member["base_source_key"] == "pfquest", "example base source is pfquest")
    _require(
        member["base_source_revision"] == EXPECTED_BASE_REVISION,
        "example base revision is exact",
    )
    _require(
        member["comparison_source_revision"] == EXPECTED_COMPARISON_REVISION,
        "example comparison revision is exact",
    )
    _require(bool(member["base_import_batches"]), "example retains base import-batch evidence")
    _require(
        bool(member["comparison_import_batches"]),
        "example retains comparison import evidence",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    project_root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--db",
        type=Path,
        default=project_root / "data" / "generated" / "octogamedb.sqlite3",
        help="Canonical migration-13 database; validation runs against an isolated byte copy.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "data" / "generated" / "validation_logs",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    project_root = Path(__file__).resolve().parents[1]
    canonical_db = args.db.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    print(f"[INFO] Project root: {project_root}")
    print(f"[INFO] Canonical DB: {canonical_db}")
    print(f"[INFO] Evidence directory: {output_dir}")
    _require(canonical_db.is_file(), "canonical migration-13 DB exists")
    _require(not Path(str(canonical_db) + "-wal").exists(), "canonical DB has no -wal sidecar")
    _require(not Path(str(canonical_db) + "-shm").exists(), "canonical DB has no -shm sidecar")

    canonical_before = _sha256(canonical_db)
    _require(
        canonical_before == EXPECTED_CANONICAL_SHA256,
        "canonical SHA-256 matches the validated migration-13 baseline",
    )

    temp_parent = project_root / ".validation_tmp"
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="P5-T06_", dir=temp_parent) as temp_name:
        snapshot = Path(temp_name) / "octogamedb_snapshot.sqlite3"
        shutil.copy2(canonical_db, snapshot)
        snapshot_before = _sha256(snapshot)
        _require(snapshot_before == canonical_before, "snapshot is byte-identical to canonical DB")
        _read_only_integrity(snapshot)

        p5_t05_path = output_dir / f"P5-T06_p5_t05_regression_{stamp}.json"
        p5_t05 = _run_json(
            project_root,
            module="octogamedb.audit_spawn_attribution",
            args=["--limit", "0", "--top", "0", "--db", str(snapshot)],
            output=p5_t05_path,
        )
        _validate_p5_t05_regression(p5_t05)

        summary_path = output_dir / f"P5-T06_summary_{stamp}.json"
        summary = _run_json(
            project_root,
            module="octogamedb.audit_overlay_additions",
            args=["--limit", "0", "--top", "25", "--db", str(snapshot)],
            output=summary_path,
        )
        class_counts = _validate_p5_t06(summary)

        repeat_path = output_dir / f"P5-T06_summary_repeat_{stamp}.json"
        repeat = _run_json(
            project_root,
            module="octogamedb.audit_overlay_additions",
            args=["--limit", "0", "--top", "25", "--db", str(snapshot)],
            output=repeat_path,
        )
        _require(repeat == summary, "P5-T06 full summary is deterministic across repeated runs")

        example_paths: dict[str, str] = {}
        for class_name, count in class_counts.items():
            if count <= 0:
                continue
            path = output_dir / f"P5-T06_examples_{class_name}_{stamp}.json"
            example = _run_json(
                project_root,
                module="octogamedb.audit_overlay_additions",
                args=[
                    "--addition-parent-class",
                    class_name,
                    "--limit",
                    "8",
                    "--top",
                    "8",
                    "--db",
                    str(snapshot),
                ],
                output=path,
            )
            _require(
                example["returned_member_count"] > 0,
                f"bounded real examples emitted for {class_name}",
            )
            for member in example["members"]:
                _validate_example_member(member)
                _require(
                    member["addition_parent_class"] == class_name,
                    f"example is classified as {class_name}",
                )
            example_paths[class_name] = str(path)

        parent_coverage = {
            row["overlay_coverage"]: int(row["group_count"])
            for row in summary["parent_overlay_coverage_counts"]
        }
        for coverage, group_count in parent_coverage.items():
            if group_count <= 0:
                continue
            path = output_dir / f"P5-T06_parent_coverage_{coverage}_{stamp}.json"
            example = _run_json(
                project_root,
                module="octogamedb.audit_overlay_additions",
                args=[
                    "--overlay-coverage",
                    coverage,
                    "--limit",
                    "8",
                    "--top",
                    "8",
                    "--db",
                    str(snapshot),
                ],
                output=path,
            )
            _require(
                example["returned_member_count"] > 0,
                f"bounded real examples emitted for parent overlay coverage {coverage}",
            )
            for member in example["members"]:
                _validate_example_member(member)
            example_paths[f"parent_coverage_{coverage}"] = str(path)

        for row in summary["zone_map_overlay_coverage_counts"]:
            coverage = str(row["overlay_coverage"])
            if int(row["group_count"]) <= 0:
                continue
            path = output_dir / f"P5-T06_zone_coverage_{coverage}_{stamp}.json"
            example = _run_json(
                project_root,
                module="octogamedb.audit_overlay_additions",
                args=[
                    "--overlay-coverage",
                    coverage,
                    "--overlay-coverage-scope",
                    "zone",
                    "--limit",
                    "8",
                    "--top",
                    "8",
                    "--db",
                    str(snapshot),
                ],
                output=path,
            )
            _require(
                example["returned_member_count"] > 0,
                f"bounded real examples emitted for zone overlay coverage {coverage}",
            )
            _require(
                example["filters"]["overlay_coverage_scope"] == "zone",
                f"zone coverage example uses zone grouping for {coverage}",
            )
            for member in example["members"]:
                _validate_example_member(member)
            example_paths[f"zone_coverage_{coverage}"] = str(path)

        snapshot_after = _sha256(snapshot)
        _require(
            snapshot_after == snapshot_before,
            "validation snapshot is byte-identical after audit",
        )

    canonical_after = _sha256(canonical_db)
    _require(canonical_after == canonical_before, "canonical DB is byte-identical after validation")

    evidence = {
        "task": "P5-T06",
        "status": "LEVEL_2_VALIDATION_PASSED",
        "canonical_sha256_before": canonical_before,
        "canonical_sha256_after": canonical_after,
        "base_revision": summary["base_source"]["source_revision"],
        "comparison_revision": summary["comparison_source"]["source_revision"],
        "p5_t05_pattern_baseline": summary["p5_t05_pattern_baseline"],
        "addition_parent_class_counts": summary["addition_parent_class_counts"],
        "by_pattern_addition_parent_class": summary["by_pattern_addition_parent_class"],
        "by_subject_kind_addition_parent_class": summary[
            "by_subject_kind_addition_parent_class"
        ],
        "active_selected_contexts": summary["active_selected_contexts"],
        "parent_overlay_coverage_counts": summary["parent_overlay_coverage_counts"],
        "zone_map_overlay_coverage_counts": summary["zone_map_overlay_coverage_counts"],
        "top_parent_concentrations": summary["top_parent_concentrations"],
        "top_zone_map_concentrations": summary["top_zone_map_concentrations"],
        "parent_template_counts": summary["parent_template_counts"],
        "zone_map_counts": summary["zone_map_counts"],
        "example_paths": example_paths,
    }
    evidence_path = output_dir / f"P5-T06_validation_{stamp}.json"
    _write_json(evidence_path, evidence)
    print(f"[PASS] P5-T06 Level-2 validation passed: {evidence_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
