"""Autonomous Level-2 validation for P5-T08 against exact canonical/raw inputs."""

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
EXPECTED_REVISIONS = {
    "base": "sha256:5087d2d0a5b1c2706b7fc7ccb5ffd447c91aa24d91a23f102f2c7ac1d7440147",
    "active": "sha256:7fd719cac7a7a26e80c6865fa62b6100ccfa2301dabe3b2a399c0f1551372d8c",
    "comparison": "sha256:eddd325a9a0eab2616c7b70d03e23d55f1a0c4127a293426ea07a17c0f2421db",
}
EXPECTED_ZONE_COUNTS = {406: 5_145, 5602: 5_062, 5581: 2_872, 1584: 2_528}
EXPECTED_P5_T06_TOTAL = 20_707
EXPECTED_ROUTED_TOTAL = 15_607
EXPECTED_FIXED_PARENTS = 1_085
EXPECTED_DIFFERENT_PAYLOADS = 1_085
EXPECTED_SHARED_EXACT_ADDED = 3


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


def _run_report(
    project_root: Path,
    *,
    db: Path,
    config: Path,
    output: Path,
    extra_args: list[str] | None = None,
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "octogamedb.audit_spawn_replacement_semantics",
        "--db",
        str(db),
        "--config",
        str(config),
        "--limit",
        "0",
        "--json",
    ]
    if extra_args:
        command.extend(extra_args)
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
            "P5-T08 audit command failed:\n"
            + " ".join(command)
            + "\nSTDOUT:\n"
            + completed.stdout
            + "\nSTDERR:\n"
            + completed.stderr
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("P5-T08 audit emitted invalid JSON") from exc
    _write_json(output, payload)
    return payload


def _combo(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        int(row["zone_id"]),
        str(row["parent_subject_kind"]),
        str(row["base_parent_class"]),
        str(row["source_contribution_class"]),
        str(row["set_relation_class"]),
        str(row["raw_payload_difference_class"]),
    )


def _example_combo(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        int(row["zone_id"]),
        str(row["parent_subject_kind"]),
        str(row["base_parent_class"]),
        str(row["source_contribution_class"]),
        str(row["set_relation_class"]),
        str(row["raw_payload_difference"]["difference_class"]),
    )


def _validate_report(report: dict[str, Any]) -> None:
    _require(
        report.get("scope")
        == "p5-t08-shared-parent-overlay-replacement-semantic-divergence",
        "P5-T08 scope is exact",
    )
    _require(report.get("read_only") is True, "P5-T08 declares the audit read-only")
    regression = report["p5_t07_regression"]
    _require(
        regression["p5_t06_global_included_member_count"] == EXPECTED_P5_T06_TOTAL,
        "P5-T06 global addition regression remains exactly 20,707",
    )
    _require(
        regression["routed_four_zone_member_count"] == EXPECTED_ROUTED_TOTAL,
        "P5-T07 routed four-zone regression remains exactly 15,607",
    )
    measured_zones = {int(k): int(v) for k, v in regression["routed_zone_counts"].items()}
    _require(
        measured_zones == EXPECTED_ZONE_COUNTS,
        "all four routed zone counts reproduce exactly",
    )
    _require(
        regression["both_whole_entry_replacement_parent_count"] == EXPECTED_FIXED_PARENTS,
        "fixed common whole-entry replacement population is exactly 1,085 parents",
    )
    _require(
        regression["different_whole_entry_replacement_payload_parent_count"]
        == EXPECTED_DIFFERENT_PAYLOADS,
        "all 1,085 fixed parents retain different replacement payload hashes",
    )
    _require(
        regression["shared_exact_added_member_count_in_routed_zones"]
        == EXPECTED_SHARED_EXACT_ADDED,
        "shared exact overlay-added routed membership remains exactly 3",
    )
    _require(report["fixed_parent_count"] == EXPECTED_FIXED_PARENTS, "1,085 parents classified")

    for side, revision in EXPECTED_REVISIONS.items():
        _require(
            report["source_revisions"][side]["source_revision"] == revision,
            f"{side} raw source revision is exact",
        )

    set_counts = report["set_relation_counts"]
    raw_counts = report["raw_payload_difference_counts"]
    _require(
        sum(int(value) for value in set_counts.values()) == EXPECTED_FIXED_PARENTS,
        "A/C set relation classes reconcile exactly to 1,085",
    )
    _require(
        sum(int(value) for value in raw_counts.values()) == EXPECTED_FIXED_PARENTS,
        "raw payload difference classes reconcile exactly to 1,085",
    )
    _require(
        int(raw_counts["unsupported_unclassified"]) == 0,
        "no unsupported/unclassified raw semantic divergence remains",
    )
    _require(
        set(report["reconciliation"].values()) == {EXPECTED_FIXED_PARENTS},
        "independent P5-T08 parent reconciliations all equal 1,085",
    )

    bulk = report["bulk_load_diagnostics"]
    _require(bulk["base_membership_bulk_loads"] == 1, "base membership is bulk-loaded once")
    _require(
        bulk["active_persisted_spawn_set_bulk_loads"] == 1,
        "active persisted spawn sets are bulk-loaded once",
    )
    _require(
        bulk["comparison_persisted_spawn_set_bulk_loads"] == 1,
        "comparison persisted spawn sets are bulk-loaded once",
    )
    _require(
        bulk["per_parent_provenance_query_loop"] is False,
        "no per-parent provenance query loop is used",
    )

    zone_rows = [
        row for row in report["stratification"]["by_routed_zone"] if int(row["parent_count"]) > 0
    ]
    examples = report["representative_examples"]
    _require(
        {_combo(row) for row in zone_rows} <= {_example_combo(row) for row in examples},
        "every non-empty routed-zone semantic combination has deterministic evidence",
    )
    _require(
        all(
            all(not Path(path).is_absolute() for path in example[side]["raw_source_relative_paths"])
            for example in examples
            for side in ("active_evidence", "comparison_evidence")
        ),
        "representative raw evidence contains source-relative paths only",
    )
    _require(
        all(
            example[side]["persisted_spawn_set"]["raw_matches_persisted"] is True
            for example in examples
            for side in ("active_evidence", "comparison_evidence")
        ),
        "representative effective memberships exactly match persisted spawn_set evidence",
    )


def _parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path, default=project_root / "data" / "generated" / "octogamedb.sqlite3"
    )
    parser.add_argument("--config", type=Path, default=project_root / "config.local.toml")
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
    config = args.config.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    print(f"[INFO] Project root: {project_root}")
    print(f"[INFO] Canonical DB: {canonical_db}")
    print(f"[INFO] Local config: {config}")
    _require(canonical_db.is_file(), "canonical migration-13 DB exists")
    _require(config.is_file(), "config.local.toml exists")
    _require(not Path(str(canonical_db) + "-wal").exists(), "canonical DB has no -wal sidecar")
    _require(not Path(str(canonical_db) + "-shm").exists(), "canonical DB has no -shm sidecar")

    canonical_before = _sha256(canonical_db)
    _require(
        canonical_before == EXPECTED_CANONICAL_SHA256,
        "canonical SHA-256 matches the validated migration-13 baseline",
    )

    from octogamedb.audit_spawn_replacement_semantics import (
        RAW_PAYLOAD_DIFFERENCE_CLASSES,
        _read_source_paths,
        classify_raw_payload_difference,
    )

    roots = _read_source_paths(
        config_path=config,
        pfquest_root=None,
        pfquest_turtle_root=None,
        pfquest_octo_root=None,
    )
    for label, root in zip(("pfquest", "pfquest_turtle", "pfquest_octo"), roots, strict=True):
        _require(root.expanduser().is_dir(), f"configured {label} source root exists")
    _require(
        classify_raw_payload_difference(
            spawn_membership_differs=False,
            localization_differs=False,
            other_top_entry_fields_differ=False,
            unsupported_reasons=["synthetic unsupported semantic"],
        )
        == "unsupported_unclassified",
        "unsupported raw semantic input is explicitly classified fail-closed",
    )
    _require(
        "unsupported_unclassified" in RAW_PAYLOAD_DIFFERENCE_CLASSES,
        "unsupported/unclassified remains an explicit contract class",
    )

    temp_parent = project_root / ".validation_tmp"
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="P5-T08_", dir=temp_parent) as temp_name:
        snapshot = Path(temp_name) / "octogamedb_snapshot.sqlite3"
        shutil.copy2(canonical_db, snapshot)
        snapshot_before = _sha256(snapshot)
        _require(snapshot_before == canonical_before, "snapshot is byte-identical to canonical DB")
        _read_only_integrity(snapshot)

        summary_path = output_dir / f"P5-T08_summary_{stamp}.json"
        summary = _run_report(
            project_root,
            db=snapshot,
            config=config,
            output=summary_path,
        )
        _validate_report(summary)

        repeat_path = output_dir / f"P5-T08_summary_repeat_{stamp}.json"
        repeat = _run_report(
            project_root,
            db=snapshot,
            config=config,
            output=repeat_path,
        )
        _require(repeat == summary, "P5-T08 JSON is deterministic across repeated runs")

        snapshot_after = _sha256(snapshot)
        _require(
            snapshot_after == snapshot_before,
            "validation snapshot is byte-identical after audit",
        )

    canonical_after = _sha256(canonical_db)
    _require(canonical_after == canonical_before, "canonical DB is byte-identical after validation")

    evidence = {
        "task": "P5-T08",
        "status": "LEVEL_2_VALIDATION_PASSED",
        "canonical_sha256_before": canonical_before,
        "canonical_sha256_after": canonical_after,
        "source_revisions": summary["source_revisions"],
        "p5_t07_regression": summary["p5_t07_regression"],
        "fixed_parent_count": summary["fixed_parent_count"],
        "set_relation_counts": summary["set_relation_counts"],
        "raw_payload_difference_counts": summary["raw_payload_difference_counts"],
        "stratification": summary["stratification"],
        "bulk_load_diagnostics": summary["bulk_load_diagnostics"],
        "representative_example_count": summary["representative_example_count"],
        "summary_json": str(summary_path),
    }
    evidence_path = output_dir / f"P5-T08_validation_{stamp}.json"
    _write_json(evidence_path, evidence)
    print(f"[PASS] P5-T08 Level-2 validation passed: {evidence_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
