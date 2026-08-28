"""Autonomous Level-2 validation for P5-T05 against canonical migration-13 data."""

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
EXPECTED_TURTLE_REVISION = (
    "sha256:7fd719cac7a7a26e80c6865fa62b6100ccfa2301dabe3b2a399c0f1551372d8c"
)
EXPECTED_COMPARISON_REVISION = (
    "sha256:eddd325a9a0eab2616c7b70d03e23d55f1a0c4127a293426ea07a17c0f2421db"
)
EXPECTED_MEMBERSHIP = {
    "creature_spawn": {
        "shared_member_count": 85_551,
        "active_only_member_count": 10_255,
        "comparison_only_member_count": 3_928,
    },
    "gameobject_spawn": {
        "shared_member_count": 59_896,
        "active_only_member_count": 5_750,
        "comparison_only_member_count": 2_362,
    },
}
EXPECTED_ONE_SIDED = 22_295
EXPECTED_ACTIVE_ONLY = 16_005
EXPECTED_COMPARISON_ONLY = 6_290
EXPECTED_PARENT_CLASSES = {
    "shared_only": 22_428,
    "active_only_members": 1_274,
    "comparison_only_members": 154,
    "mixed_one_sided_members": 1_136,
}
EXPECTED_P5_T04_CANDIDATE_CARDINALITY = {"zero": 12_103, "one": 1_539, "multiple": 8_653}
EXPECTED_P5_T04_NEAREST_TIES = {"zero": 12_103, "one": 10_146, "multiple": 46}
EXPECTED_P5_T04_COMPATIBLE_PAIRS = 148_050
EXPECTED_P5_T04_NEAREST_PAIRS = 8_416
EXPECTED_P5_T03_STATE_COUNTS = {
    "comparison_only": 12_600,
    "active_only": 32_078,
    "same_value": 394_970,
    "different_value": 2_759,
    "not_directly_comparable": 8_252,
}
EXPECTED_P5_T03_RECORD_COUNT = 450_659
PATTERNS = (
    "base_active_not_comparison",
    "active_only_vs_base",
    "base_comparison_not_active",
    "comparison_only_vs_base",
)


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


def _validate_p5_t05(report: dict[str, Any]) -> dict[str, int]:
    _require(
        report.get("scope") == "p5-t05-three-way-base-active-octo-spawn-attribution",
        "P5-T05 scope is correct",
    )
    _require(report["base_source"]["source_key"] == "pfquest", "base source is pfquest")
    _require(
        report["base_source"]["source_revision"] == EXPECTED_BASE_REVISION,
        "base revision matches the validated P5-T05 contract",
    )
    _require(
        report["comparison_source"]["source_key"] == "pfquest-octo",
        "comparison source is pfquest-octo",
    )
    _require(
        report["comparison_source"]["source_revision"] == EXPECTED_COMPARISON_REVISION,
        "comparison revision matches the validated P5 baseline",
    )

    baseline = report["p5_t04_membership_baseline"]
    by_kind = {row["subject_kind"]: row for row in baseline["by_subject_kind"]}
    for kind, expected in EXPECTED_MEMBERSHIP.items():
        _require(kind in by_kind, f"{kind} membership aggregate is present")
        for key, value in expected.items():
            _require(
                by_kind[kind][key] == value,
                f"{kind} {key}: expected {value}, observed {by_kind[kind][key]}",
            )
    _require(report["one_sided_member_count"] == EXPECTED_ONE_SIDED, "one-sided total is 22,295")
    _require(
        report["active_only_member_count"] == EXPECTED_ACTIVE_ONLY,
        "active-only total is 16,005",
    )
    _require(
        report["comparison_only_member_count"] == EXPECTED_COMPARISON_ONLY,
        "comparison-only total is 6,290",
    )

    pattern_counts = {row["pattern"]: int(row["member_count"]) for row in report["patterns"]}
    _require(set(pattern_counts) == set(PATTERNS), "all four three-way pattern labels are present")
    _require(
        sum(pattern_counts.values()) == EXPECTED_ONE_SIDED,
        "four patterns sum exactly to 22,295",
    )
    _require(
        pattern_counts["base_active_not_comparison"] + pattern_counts["active_only_vs_base"]
        == EXPECTED_ACTIVE_ONLY,
        "active-only attribution patterns sum exactly to 16,005",
    )
    _require(
        pattern_counts["base_comparison_not_active"] + pattern_counts["comparison_only_vs_base"]
        == EXPECTED_COMPARISON_ONLY,
        "comparison-only attribution patterns sum exactly to 6,290",
    )
    print("[INFO] Measured P5-T05 pattern counts: " + json.dumps(pattern_counts, sort_keys=True))

    contexts: dict[tuple[str, str], int] = {}
    for row in report["active_selected_contexts"]:
        key = (str(row["source_key"]), str(row["source_revision"]))
        contexts[key] = contexts.get(key, 0) + int(row["member_count"])
    _require(
        contexts.get(("pfquest", EXPECTED_BASE_REVISION), 0) == 31,
        "base active complete-set context still covers exactly 31 one-sided members",
    )
    _require(
        contexts.get(("pfquest-turtle", EXPECTED_TURTLE_REVISION), 0) == 22_264,
        "Turtle active complete-set context still covers exactly 22,264 one-sided members",
    )
    _require(
        sum(contexts.values()) == EXPECTED_ONE_SIDED,
        "active contexts cover all one-sided members",
    )

    _require(
        sum(int(row["one_sided_member_count"]) for row in report["parent_pattern_counts"])
        == EXPECTED_ONE_SIDED,
        "parent-template aggregates cover all one-sided members",
    )
    _require(
        sum(int(value) for value in report["base_membership_evidence_counts"].values())
        == EXPECTED_ONE_SIDED,
        "base membership evidence modes cover all one-sided members",
    )
    _require(
        sum(int(row["member_count"]) for row in report["zone_map_pattern_counts"])
        == EXPECTED_ONE_SIDED,
        "zone/map pattern aggregates cover all one-sided members",
    )
    _require(
        sum(
            int(row["member_count"])
            for row in report["by_subject_kind_pattern"]
        )
        == EXPECTED_ONE_SIDED,
        "subject-kind pattern aggregates cover all one-sided members",
    )
    _require(report["returned_member_count"] == 0, "summary run returns no member details")
    _require(report["returned_candidate_pair_count"] == 0, "summary run returns no pair details")

    pair_classes = report["source_local_replacement_analysis"]["pair_classes"]
    _require(
        sum(int(row["eligible_member_count"]) for row in pair_classes) == EXPECTED_ONE_SIDED,
        "source-local pair classes partition all four attribution patterns",
    )
    for row in pair_classes:
        cardinality = row["member_candidate_cardinality"]
        _require(
            sum(int(cardinality[label]) for label in ("zero", "one", "multiple"))
            == int(row["eligible_member_count"]),
            f"{row['pair_class']} candidate cardinality partitions its eligible members",
        )
        ties = row["member_nearest_tie_cardinality"]
        _require(
            sum(int(ties[label]) for label in ("zero", "one", "multiple"))
            == int(row["eligible_member_count"]),
            f"{row['pair_class']} nearest-tie cardinality partitions its eligible members",
        )
    return pattern_counts


def _validate_p5_t04(report: dict[str, Any]) -> None:
    _require(
        report.get("scope") == "p5-t04-pfquest-octo-spawn-membership-divergence",
        "P5-T04 scope is unchanged",
    )
    baseline = report["membership_baseline"]
    by_kind = {row["subject_kind"]: row for row in baseline["by_subject_kind"]}
    for kind, expected in EXPECTED_MEMBERSHIP.items():
        _require(kind in by_kind, f"P5-T04 {kind} membership aggregate is present")
        for key, value in expected.items():
            _require(
                by_kind[kind][key] == value,
                f"P5-T04 {kind} {key} is unchanged at {value}",
            )
    _require(
        baseline["one_sided_member_count"] == EXPECTED_ONE_SIDED,
        "P5-T04 one-sided membership total is unchanged at 22,295",
    )
    _require(
        report["parent_topology"]["class_counts"] == EXPECTED_PARENT_CLASSES,
        "P5-T04 parent classes are unchanged",
    )
    contexts: dict[tuple[str, str], int] = {}
    for row in report["active_membership_contexts"]:
        key = (str(row["source_key"]), str(row["source_revision"]))
        contexts[key] = contexts.get(key, 0) + int(row["one_sided_member_count"])
    _require(
        contexts.get(("pfquest", EXPECTED_BASE_REVISION), 0) == 31,
        "P5-T04 base membership context remains exactly 31 one-sided members",
    )
    _require(
        contexts.get(("pfquest-turtle", EXPECTED_TURTLE_REVISION), 0) == 22_264,
        "P5-T04 Turtle membership context remains exactly 22,264 one-sided members",
    )
    analysis = report["relocation_candidate_analysis"]
    _require(
        analysis["member_candidate_cardinality"] == EXPECTED_P5_T04_CANDIDATE_CARDINALITY,
        "P5-T04 candidate cardinality is unchanged",
    )
    _require(
        analysis["member_nearest_tie_cardinality"] == EXPECTED_P5_T04_NEAREST_TIES,
        "P5-T04 nearest-tie cardinality is unchanged",
    )
    _require(
        analysis["compatible_candidate_pair_count"] == EXPECTED_P5_T04_COMPATIBLE_PAIRS,
        "P5-T04 compatible pair count is unchanged",
    )
    _require(
        analysis["unique_nearest_candidate_pair_count"] == EXPECTED_P5_T04_NEAREST_PAIRS,
        "P5-T04 nearest candidate pair count is unchanged",
    )


def _validate_p5_t03(report: dict[str, Any]) -> None:
    _require(
        report.get("scope") == "p1-world-selected-vs-comparison-source",
        "P5-T03 comparison scope is unchanged",
    )
    _require(
        report["record_count"] == EXPECTED_P5_T03_RECORD_COUNT,
        "P5-T03 record count is unchanged",
    )
    _require(
        report["state_counts"] == EXPECTED_P5_T03_STATE_COUNTS,
        "P5-T03 five-state baseline is unchanged",
    )
    patterns = {row["template_kind"]: row for row in report["spawn_membership_patterns"]}
    _require(
        patterns["creature"]["active_only_member_count"] == 10_255
        and patterns["creature"]["comparison_only_member_count"] == 3_928,
        "P5-T03 creature spawn membership counts are unchanged",
    )
    _require(
        patterns["gameobject"]["active_only_member_count"] == 5_750
        and patterns["gameobject"]["comparison_only_member_count"] == 2_362,
        "P5-T03 gameobject spawn membership counts are unchanged",
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
    with tempfile.TemporaryDirectory(prefix="P5-T05_", dir=temp_parent) as temp_name:
        snapshot = Path(temp_name) / "octogamedb_snapshot.sqlite3"
        shutil.copy2(canonical_db, snapshot)
        snapshot_before = _sha256(snapshot)
        _require(snapshot_before == canonical_before, "snapshot is byte-identical to canonical DB")
        _read_only_integrity(snapshot)

        summary_path = output_dir / f"P5-T05_summary_{stamp}.json"
        summary = _run_json(
            project_root,
            module="octogamedb.audit_spawn_attribution",
            args=["--limit", "0", "--top", "25", "--db", str(snapshot)],
            output=summary_path,
        )
        pattern_counts = _validate_p5_t05(summary)

        example_paths: dict[str, str] = {}
        for pattern, count in pattern_counts.items():
            if count <= 0:
                continue
            path = output_dir / f"P5-T05_examples_{pattern}_{stamp}.json"
            example = _run_json(
                project_root,
                module="octogamedb.audit_spawn_attribution",
                args=["--pattern", pattern, "--limit", "8", "--top", "8", "--db", str(snapshot)],
                output=path,
            )
            _require(
                example["returned_member_count"] > 0,
                f"bounded examples emitted for {pattern}",
            )
            example_paths[pattern] = str(path)

        for row in summary["source_local_replacement_analysis"]["pair_classes"]:
            if int(row["compatible_candidate_pair_count"]) <= 0:
                continue
            path = output_dir / f"P5-T05_replacement_examples_{row['pair_class']}_{stamp}.json"
            example = _run_json(
                project_root,
                module="octogamedb.audit_spawn_attribution",
                args=[
                    "--pair-class",
                    str(row["pair_class"]),
                    "--limit",
                    "20",
                    "--top",
                    "10",
                    "--db",
                    str(snapshot),
                ],
                output=path,
            )
            _require(
                example["returned_candidate_pair_count"] > 0,
                f"bounded replacement candidates emitted for non-empty class {row['pair_class']}",
            )
            example_paths[row["pair_class"]] = str(path)

        p5_t04_path = output_dir / f"P5-T05_p5_t04_regression_{stamp}.json"
        p5_t04 = _run_json(
            project_root,
            module="octogamedb.audit_spawn_divergence",
            args=["pfquest-octo", "--limit", "0", "--top", "25", "--db", str(snapshot)],
            output=p5_t04_path,
        )
        _validate_p5_t04(p5_t04)

        p5_t03_path = output_dir / f"P5-T05_p5_t03_regression_{stamp}.json"
        p5_t03 = _run_json(
            project_root,
            module="octogamedb.audit_comparison",
            args=["pfquest-octo", "--limit", "0", "--db", str(snapshot)],
            output=p5_t03_path,
        )
        _validate_p5_t03(p5_t03)

        snapshot_after = _sha256(snapshot)
        _require(
            snapshot_after == snapshot_before,
            "validation snapshot is byte-identical after audit",
        )

    canonical_after = _sha256(canonical_db)
    _require(canonical_after == canonical_before, "canonical DB is byte-identical after validation")

    evidence = {
        "task": "P5-T05",
        "status": "LEVEL_2_VALIDATION_PASSED",
        "canonical_sha256_before": canonical_before,
        "canonical_sha256_after": canonical_after,
        "base_revision": summary["base_source"]["source_revision"],
        "comparison_revision": summary["comparison_source"]["source_revision"],
        "pattern_counts": pattern_counts,
        "patterns": summary["patterns"],
        "active_selected_contexts": summary["active_selected_contexts"],
        "source_local_replacement_analysis": summary["source_local_replacement_analysis"],
        "top_parent_concentrations": summary["top_parent_concentrations"],
        "top_zone_map_concentrations": summary["top_zone_map_concentrations"],
        "p5_t04_parent_topology": p5_t04["parent_topology"],
        "p5_t04_relocation_candidate_analysis": p5_t04["relocation_candidate_analysis"],
        "p5_t03_state_counts": p5_t03["state_counts"],
        "example_paths": example_paths,
    }
    evidence_path = output_dir / f"P5-T05_validation_{stamp}.json"
    _write_json(evidence_path, evidence)
    print(f"[PASS] P5-T05 Level-2 validation passed: {evidence_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
