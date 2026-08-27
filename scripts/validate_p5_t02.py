"""Autonomous Level-2 validation for P5-T02 against the canonical migration-13 DB."""

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
EXPECTED_RESOLUTION = {
    "observation_group_count": 1_307_532,
    "selected_group_count": 1_297_652,
    "unselected_group_count": 9_880,
    "empty_observation_group_count": 0,
    "conflict_group_count": 64_512,
    "resolved_conflict_group_count": 64_512,
    "unresolved_conflict_group_count": 0,
    "unselected_single_value_group_count": 9_880,
}
EXPECTED_FAMILIES = {
    ("creature", "faction"): 4,
    ("creature", "level_max"): 1,
    ("creature", "level_min"): 1,
    ("creature", "name"): 1,
    ("creature", "spawn_set"): 1,
    ("creature", "world_presence"): 1,
    ("creature_spawn", "position"): 2_748,
    ("creature_spawn", "respawn_seconds"): 2_748,
    ("gameobject", "faction"): 5,
    ("gameobject", "name"): 2,
    ("gameobject", "spawn_set"): 2,
    ("gameobject", "world_presence"): 2,
    ("gameobject_spawn", "position"): 2_182,
    ("gameobject_spawn", "respawn_seconds"): 2_182,
}
EXPECTED_SPAWN_PATTERNS = {
    "creature_spawn": {"subject_count": 2_748, "group_count": 5_496},
    "gameobject_spawn": {"subject_count": 2_182, "group_count": 4_364},
}


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


def _run_json(project_root: Path, args: list[str], output_path: Path) -> dict[str, Any]:
    command = [sys.executable, "-m", "octogamedb", *args, "--json"]
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
        raise RuntimeError(
            f"Command did not emit valid JSON: {' '.join(command)}\n{completed.stdout}"
        ) from exc
    _write_json(output_path, payload)
    return payload


def _read_only_integrity(path: Path) -> None:
    uri = f"file:{path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        connection.close()
    _require(integrity == "ok", "snapshot PRAGMA integrity_check is ok")
    _require(foreign_keys == [], "snapshot PRAGMA foreign_key_check is empty")


def _validate_resolution(report: dict[str, Any]) -> None:
    _require(report.get("scope") == "provenance-resolution", "resolution scope is correct")
    for key, expected in EXPECTED_RESOLUTION.items():
        _require(report.get(key) == expected, f"resolution {key} == {expected}")


def _validate_unselected(report: dict[str, Any]) -> dict[str, Any]:
    _require(report.get("scope") == "unselected-single-value", "unselected scope is correct")
    _require(report.get("group_count") == 9_880, "unselected report contains exactly 9,880 groups")
    _require(
        report.get("returned_group_count") == 0,
        "summary-only report returns no drill-down rows",
    )
    _require(report.get("groups") == [], "summary-only report omits detailed groups")
    _require(
        report.get("classification_counts") == {"unresolved": 9_880},
        "audit does not silently classify or select any real group",
    )

    actual_families = {
        (str(item["subject_kind"]), str(item["fact_key"])): int(item["group_count"])
        for item in report["fact_families"]
    }
    _require(actual_families == EXPECTED_FAMILIES, "fact-family distribution matches P5-T01")
    _require(sum(actual_families.values()) == 9_880, "fact-family counts sum to 9,880")

    spawn_patterns: dict[str, dict[str, int]] = {}
    for item in report["subject_fact_patterns"]:
        kind = str(item["subject_kind"])
        if kind not in EXPECTED_SPAWN_PATTERNS:
            continue
        if item["fact_keys"] != ["position", "respawn_seconds"]:
            continue
        spawn_patterns[kind] = {
            "subject_count": int(item["subject_count"]),
            "group_count": int(item["group_count"]),
        }
    _require(
        spawn_patterns == EXPECTED_SPAWN_PATTERNS,
        "spawn gaps are exact paired position+respawn patterns for 2,748/2,182 subjects",
    )

    template_remainder = sum(
        count
        for (subject_kind, _fact_key), count in actual_families.items()
        if subject_kind in {"creature", "gameobject"}
    )
    _require(template_remainder == 20, "template-level unselected remainder is exactly 20 groups")
    _require(bool(report["sources"]), "source aggregate is populated")
    _require(bool(report["source_revisions"]), "source/revision aggregate is populated")
    _require(bool(report["fact_sources"]), "fact/source cross-tab is populated")
    _require(bool(report["import_batch_statuses"]), "import-batch status aggregate is populated")

    return {
        "group_count": report["group_count"],
        "fact_families": report["fact_families"],
        "subject_kinds": report["subject_kinds"],
        "subject_fact_patterns": report["subject_fact_patterns"],
        "sources": report["sources"],
        "source_revisions": report["source_revisions"],
        "fact_sources": report["fact_sources"],
        "import_batch_statuses": report["import_batch_statuses"],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    project_root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--db",
        type=Path,
        default=project_root / "data" / "generated" / "octogamedb.sqlite3",
        help="Canonical migration-13 database to inspect read-only via an isolated snapshot.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "data" / "generated" / "validation_logs",
        help="Directory receiving deterministic JSON validation evidence.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    project_root = Path(__file__).resolve().parents[1]
    canonical_db = args.db.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)

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
    with tempfile.TemporaryDirectory(prefix="P5-T02_", dir=temp_parent) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        snapshot = temp_dir / "octogamedb_snapshot.sqlite3"
        shutil.copy2(canonical_db, snapshot)
        snapshot_before = _sha256(snapshot)
        _require(snapshot_before == canonical_before, "snapshot is byte-identical to canonical DB")
        _read_only_integrity(snapshot)

        resolution_path = output_dir / f"P5-T02_resolution_{stamp}.json"
        unselected_path = output_dir / f"P5-T02_unselected_summary_{stamp}.json"
        resolution = _run_json(
            project_root,
            ["resolution", "--db", str(snapshot)],
            resolution_path,
        )
        unselected = _run_json(
            project_root,
            ["unselected", "--limit", "0", "--db", str(snapshot)],
            unselected_path,
        )
        _validate_resolution(resolution)
        evidence_summary = _validate_unselected(unselected)

        example_paths: dict[str, str] = {}
        for subject_kind in ("creature_spawn", "gameobject_spawn", "creature", "gameobject"):
            path = output_dir / f"P5-T02_examples_{subject_kind}_{stamp}.json"
            example = _run_json(
                project_root,
                [
                    "unselected",
                    "--subject-kind",
                    subject_kind,
                    "--limit",
                    "12",
                    "--db",
                    str(snapshot),
                ],
                path,
            )
            _require(
                example["group_count"] > 0,
                f"drill-down returns evidence for {subject_kind}",
            )
            _require(
                all(
                    group["classification"]["label"] == "unresolved"
                    for group in example["groups"]
                ),
                f"{subject_kind} drill-down remains classification-neutral",
            )
            example_paths[subject_kind] = str(path)

        snapshot_after = _sha256(snapshot)
        _require(snapshot_after == snapshot_before, "audit leaves snapshot byte-identical")

    canonical_after = _sha256(canonical_db)
    _require(canonical_after == canonical_before, "validation leaves canonical DB byte-identical")

    final_summary = {
        "task": "P5-T02",
        "status": "LEVEL_2_VALIDATION_PASSED",
        "canonical_db": str(canonical_db),
        "canonical_sha256_before": canonical_before,
        "canonical_sha256_after": canonical_after,
        "resolution": EXPECTED_RESOLUTION,
        "unselected": evidence_summary,
        "evidence_files": {
            "resolution": str(resolution_path),
            "unselected_summary": str(unselected_path),
            "examples": example_paths,
        },
        "interpretation_required": (
            "Review source/fact aggregates and drill-down siblings to assign the four domain "
            "classes. The validator intentionally does not choose a class or canonical winner."
        ),
    }
    final_path = output_dir / f"P5-T02_validation_{stamp}.json"
    _write_json(final_path, final_summary)
    print(f"[PASS] P5-T02 Level-2 structural validation passed: {final_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
