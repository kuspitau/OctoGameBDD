"""Autonomous Level-2 validation for P5-T04 against canonical migration-13 data."""

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
EXPECTED_P5_T03_STATE_COUNTS = {
    "comparison_only": 12_600,
    "active_only": 32_078,
    "same_value": 394_970,
    "different_value": 2_759,
    "not_directly_comparable": 8_252,
}
EXPECTED_P5_T03_RECORD_COUNT = 450_659


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


def _validate_divergence(report: dict[str, Any]) -> None:
    _require(
        report.get("scope") == "p5-t04-pfquest-octo-spawn-membership-divergence",
        "P5-T04 scope is correct",
    )
    source = report["comparison_source"]
    _require(source["source_key"] == "pfquest-octo", "comparison source is pfquest-octo")
    _require(
        source["source_revision"] == EXPECTED_COMPARISON_REVISION,
        "comparison revision matches the validated P5 baseline",
    )
    baseline = report["membership_baseline"]
    by_kind = {row["subject_kind"]: row for row in baseline["by_subject_kind"]}
    print(
        "[INFO] Observed P5-T04 membership baseline: "
        + json.dumps(baseline, sort_keys=True, separators=(",", ":"))
    )
    for kind, expected in EXPECTED_MEMBERSHIP.items():
        _require(kind in by_kind, f"{kind} membership aggregate is present")
        for key, value in expected.items():
            actual = by_kind[kind][key]
            _require(
                actual == value,
                f"{kind} {key}: expected {value}, observed {actual}",
            )
    _require(
        baseline["one_sided_member_count"] == EXPECTED_ONE_SIDED,
        "unique one-sided membership baseline is exactly 22,295",
    )
    _require(
        baseline["active_only_member_count"] + baseline["comparison_only_member_count"]
        == EXPECTED_ONE_SIDED,
        "active-only + comparison-only sums exactly to 22,295",
    )

    topology = report["parent_topology"]
    _require(
        sum(topology["class_counts"].values()) == topology["directly_comparable_parent_count"],
        "parent topology classes partition directly comparable parents",
    )
    _require(
        sum(row["parent_count"] for row in topology["one_sided_member_count_distribution"])
        == topology["directly_comparable_parent_count"],
        "one-sided-per-parent distribution covers every directly comparable parent",
    )
    _require(
        sum(row["one_sided_member_count"] for row in report["active_membership_contexts"])
        == EXPECTED_ONE_SIDED,
        "active complete-set source/revision/policy aggregate covers all one-sided members",
    )
    expected_active_only = report["membership_baseline"]["active_only_member_count"]
    _require(
        sum(row["member_count"] for row in report["active_only_selected_position_contexts"])
        == expected_active_only,
        "selected position provenance covers every active-only member",
    )
    _require(
        all(
            row["source_key"] is not None
            for row in report["active_only_selected_position_contexts"]
        ),
        "every active-only member has a selected position source",
    )

    candidates = report["relocation_candidate_analysis"]
    cardinality = candidates["member_candidate_cardinality"]
    _require(
        cardinality["zero"] + cardinality["one"] + cardinality["multiple"]
        == EXPECTED_ONE_SIDED,
        "candidate cardinality partitions all one-sided members",
    )
    _require(
        candidates["members_without_compatible_opposite_count"] == cardinality["zero"],
        "zero-candidate count equals residual coordinate-incompatible/no-opposite population",
    )
    nearest_ties = candidates["member_nearest_tie_cardinality"]
    _require(
        nearest_ties["zero"] + nearest_ties["one"] + nearest_ties["multiple"]
        == EXPECTED_ONE_SIDED,
        "nearest-neighbour tie cardinality partitions all one-sided members",
    )
    _require(report["returned_member_count"] == 0, "summary run returns no member details")
    _require(report["returned_candidate_pair_count"] == 0, "summary run returns no pair details")


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
        "P5-T03 creature membership counts are unchanged",
    )
    _require(
        patterns["gameobject"]["active_only_member_count"] == 5_750
        and patterns["gameobject"]["comparison_only_member_count"] == 2_362,
        "P5-T03 gameobject membership counts are unchanged",
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
    with tempfile.TemporaryDirectory(prefix="P5-T04_", dir=temp_parent) as temp_name:
        snapshot = Path(temp_name) / "octogamedb_snapshot.sqlite3"
        shutil.copy2(canonical_db, snapshot)
        snapshot_before = _sha256(snapshot)
        _require(snapshot_before == canonical_before, "snapshot is byte-identical to canonical DB")
        _read_only_integrity(snapshot)

        summary_path = output_dir / f"P5-T04_summary_{stamp}.json"
        summary = _run_json(
            project_root,
            module="octogamedb.audit_spawn_divergence",
            args=["pfquest-octo", "--limit", "0", "--top", "25", "--db", str(snapshot)],
            output=summary_path,
        )
        _validate_divergence(summary)

        example_paths: dict[str, str] = {}
        for kind in ("creature_spawn", "gameobject_spawn"):
            for direction in ("active_only", "comparison_only"):
                label = f"{kind}_{direction}"
                path = output_dir / f"P5-T04_examples_{label}_{stamp}.json"
                example = _run_json(
                    project_root,
                    module="octogamedb.audit_spawn_divergence",
                    args=[
                        "pfquest-octo",
                        "--subject-kind",
                        kind,
                        "--direction",
                        direction,
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
                    f"bounded {label} examples are emitted",
                )
                example_paths[label] = str(path)

        if summary["relocation_candidate_analysis"]["unique_nearest_candidate_pair_count"] > 0:
            path = output_dir / f"P5-T04_relocation_candidates_{stamp}.json"
            candidates = _run_json(
                project_root,
                module="octogamedb.audit_spawn_divergence",
                args=["pfquest-octo", "--limit", "12", "--top", "12", "--db", str(snapshot)],
                output=path,
            )
            _require(
                candidates["returned_candidate_pair_count"] > 0,
                "bounded relocation-candidate examples are emitted",
            )
            example_paths["relocation_candidates"] = str(path)

        if summary["relocation_candidate_analysis"]["member_candidate_cardinality"]["multiple"] > 0:
            path = output_dir / f"P5-T04_ambiguous_candidates_{stamp}.json"
            ambiguous = _run_json(
                project_root,
                module="octogamedb.audit_spawn_divergence",
                args=[
                    "pfquest-octo",
                    "--candidate-cardinality",
                    "multiple",
                    "--limit",
                    "12",
                    "--top",
                    "12",
                    "--db",
                    str(snapshot),
                ],
                output=path,
            )
            _require(
                ambiguous["returned_member_count"] > 0,
                "bounded ambiguous nearest-candidate members are emitted",
            )
            example_paths["ambiguous_candidates"] = str(path)

        p5_t03_path = output_dir / f"P5-T04_p5_t03_regression_{stamp}.json"
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
        "task": "P5-T04",
        "status": "LEVEL_2_VALIDATION_PASSED",
        "canonical_sha256_before": canonical_before,
        "canonical_sha256_after": canonical_after,
        "comparison_revision": summary["comparison_source"]["source_revision"],
        "membership_baseline": summary["membership_baseline"],
        "parent_topology": summary["parent_topology"],
        "relocation_candidate_analysis": summary["relocation_candidate_analysis"],
        "active_membership_contexts": summary["active_membership_contexts"],
        "active_only_selected_position_contexts": summary[
            "active_only_selected_position_contexts"
        ],
        "top_parent_concentrations": summary["top_parent_concentrations"],
        "top_zone_map_concentrations": summary["top_zone_map_concentrations"],
        "p5_t03_state_counts": p5_t03["state_counts"],
        "example_paths": example_paths,
    }
    evidence_path = output_dir / f"P5-T04_validation_{stamp}.json"
    _write_json(evidence_path, evidence)
    print(f"[PASS] P5-T04 Level-2 validation passed: {evidence_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
