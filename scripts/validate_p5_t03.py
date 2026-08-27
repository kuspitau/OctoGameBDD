"""Autonomous Level-2 validation for P5-T03 against the canonical migration-13 DB."""

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
EXPECTED_COMPARISON_REVISION = (
    "sha256:eddd325a9a0eab2616c7b70d03e23d55f1a0c4127a293426ea07a17c0f2421db"
)
EXPECTED_UNSELECTED_GROUPS = 9_880
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
EXPECTED_UNSELECTED_SUBJECT_KINDS = {
    "creature": {"subject_count": 4, "group_count": 9},
    "creature_spawn": {"subject_count": 2_748, "group_count": 5_496},
    "gameobject": {"subject_count": 5, "group_count": 11},
    "gameobject_spawn": {"subject_count": 2_182, "group_count": 4_364},
}
P1_SUBJECT_KINDS = ("creature", "creature_spawn", "gameobject", "gameobject_spawn")
COMPARISON_STATES = (
    "comparison_only",
    "active_only",
    "same_value",
    "different_value",
    "not_directly_comparable",
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


def _run_json(
    project_root: Path,
    *,
    module: str,
    args: list[str],
    output_path: Path,
) -> dict[str, Any]:
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
        raise RuntimeError(
            f"Command did not emit valid JSON: {' '.join(command)}\n{completed.stdout}"
        ) from exc
    _write_json(output_path, payload)
    return payload


def _read_only_integrity(path: Path) -> None:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
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


def _validate_unselected(report: dict[str, Any]) -> None:
    _require(report.get("scope") == "unselected-single-value", "unselected scope is correct")
    _require(
        report.get("group_count") == EXPECTED_UNSELECTED_GROUPS,
        "P5-T02 9,880 baseline is preserved",
    )
    _require(report.get("returned_group_count") == 0, "P5-T02 baseline check is summary-only")
    actual_kinds = {
        str(item["subject_kind"]): {
            "subject_count": int(item["subject_count"]),
            "group_count": int(item["group_count"]),
        }
        for item in report["subject_kinds"]
    }
    _require(
        actual_kinds == EXPECTED_UNSELECTED_SUBJECT_KINDS,
        "P5-T02 subject-kind distribution is unchanged",
    )
    revisions = report.get("source_revisions", [])
    _require(len(revisions) == 1, "unselected comparison evidence uses one source revision")
    _require(revisions[0]["source_key"] == "pfquest-octo", "unselected source is pfquest-octo")
    _require(
        revisions[0]["source_revision"] == EXPECTED_COMPARISON_REVISION,
        "unselected source revision matches validated P5 baseline",
    )


def _validate_comparison(report: dict[str, Any]) -> dict[str, Any]:
    _require(
        report.get("scope") == "p1-world-selected-vs-comparison-source",
        "comparison scope is correct",
    )
    source = report["comparison_source"]
    _require(source["source_key"] == "pfquest-octo", "comparison source is pfquest-octo")
    _require(
        source["source_revision"] == EXPECTED_COMPARISON_REVISION,
        "comparison uses the validated pfquest-octo revision",
    )
    _require(
        source["unselected_group_count"] == EXPECTED_UNSELECTED_GROUPS,
        "comparison accounts for all 9,880 P5-T02 unselected groups",
    )
    _require(
        source["group_count"] >= EXPECTED_UNSELECTED_GROUPS,
        "comparison includes source groups with active counterparts too",
    )
    _require(
        source["observation_count"] >= source["group_count"],
        "comparison observation count covers all source groups",
    )
    _require(report["record_count"] > 0, "comparison produces at least one audited record")
    _require(report["returned_record_count"] == 0, "primary comparison run is summary-only")
    _require(report["records"] == [], "summary-only comparison omits drill-down rows")
    _require(
        set(report["state_counts"]) == set(COMPARISON_STATES),
        "all five comparison states are represented in the schema",
    )
    _require(
        sum(int(value) for value in report["state_counts"].values()) == report["record_count"],
        "state counts sum exactly to audited records",
    )
    actual_kinds = {str(item["subject_kind"]) for item in report["subject_kinds"]}
    _require(
        set(P1_SUBJECT_KINDS).issubset(actual_kinds),
        "comparison aggregate covers all four bounded P1 subject kinds",
    )
    _require(bool(report["fact_families"]), "fact-family state cross-tab is populated")
    _require(
        bool(report["active_selected_contexts"]),
        "active source/policy aggregate is populated",
    )
    _require(
        bool(report["template_presence_patterns"]),
        "world_presence template membership aggregate is populated",
    )
    _require(
        bool(report["spawn_membership_patterns"]),
        "complete-set spawn membership aggregate is populated",
    )

    presence_kinds = {str(item["template_kind"]) for item in report["template_presence_patterns"]}
    _require("creature" in presence_kinds, "creature world_presence context is measured")
    _require("gameobject" in presence_kinds, "gameobject world_presence context is measured")

    pattern_kinds = {str(item["template_kind"]) for item in report["spawn_membership_patterns"]}
    _require("creature" in pattern_kinds, "creature spawn_set context is measured")
    _require("gameobject" in pattern_kinds, "gameobject spawn_set context is measured")

    return {
        "record_count": report["record_count"],
        "compared_subject_count": report["compared_subject_count"],
        "comparison_observation_count": report["comparison_observation_count"],
        "active_selected_observation_count": report["active_selected_observation_count"],
        "comparison_source": source,
        "state_counts": report["state_counts"],
        "subject_kinds": report["subject_kinds"],
        "fact_families": report["fact_families"],
        "active_selected_contexts": report["active_selected_contexts"],
        "template_presence_patterns": report["template_presence_patterns"],
        "spawn_membership_patterns": report["spawn_membership_patterns"],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    project_root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--db",
        type=Path,
        default=project_root / "data" / "generated" / "octogamedb.sqlite3",
        help="Canonical migration-13 database to inspect through an isolated snapshot.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "data" / "generated" / "validation_logs",
        help="Directory receiving JSON validation evidence.",
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
    with tempfile.TemporaryDirectory(prefix="P5-T03_", dir=temp_parent) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        snapshot = temp_dir / "octogamedb_snapshot.sqlite3"
        shutil.copy2(canonical_db, snapshot)
        snapshot_before = _sha256(snapshot)
        _require(snapshot_before == canonical_before, "snapshot is byte-identical to canonical DB")
        _read_only_integrity(snapshot)

        resolution_path = output_dir / f"P5-T03_resolution_{stamp}.json"
        unselected_path = output_dir / f"P5-T03_unselected_baseline_{stamp}.json"
        comparison_path = output_dir / f"P5-T03_comparison_summary_{stamp}.json"
        resolution = _run_json(
            project_root,
            module="octogamedb",
            args=["resolution", "--db", str(snapshot)],
            output_path=resolution_path,
        )
        unselected = _run_json(
            project_root,
            module="octogamedb",
            args=[
                "unselected",
                "--source",
                "pfquest-octo",
                "--limit",
                "0",
                "--db",
                str(snapshot),
            ],
            output_path=unselected_path,
        )
        comparison = _run_json(
            project_root,
            module="octogamedb.audit_comparison",
            args=["pfquest-octo", "--limit", "0", "--db", str(snapshot)],
            output_path=comparison_path,
        )
        _validate_resolution(resolution)
        _validate_unselected(unselected)
        comparison_summary = _validate_comparison(comparison)

        kind_examples: dict[str, str] = {}
        for kind in P1_SUBJECT_KINDS:
            path = output_dir / f"P5-T03_examples_{kind}_{stamp}.json"
            example = _run_json(
                project_root,
                module="octogamedb.audit_comparison",
                args=[
                    "pfquest-octo",
                    "--subject-kind",
                    kind,
                    "--limit",
                    "12",
                    "--db",
                    str(snapshot),
                ],
                output_path=path,
            )
            _require(example["record_count"] > 0, f"drill-down returns {kind} comparison records")
            _require(
                example["returned_record_count"] > 0,
                f"drill-down returns bounded {kind} details",
            )
            if kind.endswith("_spawn"):
                _require(
                    any(
                        record.get("complete_set_context") is not None
                        for record in example["records"]
                    ),
                    f"{kind} drill-down preserves parent complete-set context",
                )
            kind_examples[kind] = str(path)

        state_examples: dict[str, str] = {}
        for state, count in comparison["state_counts"].items():
            if int(count) == 0:
                continue
            path = output_dir / f"P5-T03_examples_state_{state}_{stamp}.json"
            example = _run_json(
                project_root,
                module="octogamedb.audit_comparison",
                args=[
                    "pfquest-octo",
                    "--state",
                    state,
                    "--limit",
                    "8",
                    "--db",
                    str(snapshot),
                ],
                output_path=path,
            )
            _require(
                example["record_count"] == int(count),
                f"state filter reproduces {state} aggregate count",
            )
            _require(
                all(record["state"] == state for record in example["records"]),
                f"state drill-down contains only {state}",
            )
            state_examples[state] = str(path)

        snapshot_after = _sha256(snapshot)
        _require(
            snapshot_after == snapshot_before,
            "all P5-T03 audits leave snapshot byte-identical",
        )

    canonical_after = _sha256(canonical_db)
    _require(canonical_after == canonical_before, "validation leaves canonical DB byte-identical")

    final_summary = {
        "task": "P5-T03",
        "status": "LEVEL_2_VALIDATION_PASSED",
        "canonical_db": str(canonical_db),
        "canonical_sha256_before": canonical_before,
        "canonical_sha256_after": canonical_after,
        "resolution": EXPECTED_RESOLUTION,
        "comparison": comparison_summary,
        "evidence_files": {
            "resolution": str(resolution_path),
            "unselected_baseline": str(unselected_path),
            "comparison_summary": str(comparison_path),
            "subject_kind_examples": kind_examples,
            "state_examples": state_examples,
        },
        "next_action": (
            "Use the measured state/fact/source/spawn-set aggregates to close P5-T03 and decide "
            "whether any tightly scoped follow-up policy/source task is justified."
        ),
    }
    final_path = output_dir / f"P5-T03_validation_{stamp}.json"
    _write_json(final_path, final_summary)
    print(f"[PASS] P5-T03 Level-2 validation passed: {final_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
