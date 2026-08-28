"""Autonomous Level-2 validation for P5-T07 against exact canonical/raw inputs."""

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
EXPECTED_ZONE_COUNTS = {
    406: 5_145,
    5602: 5_062,
    5581: 2_872,
    1584: 2_528,
}
EXPECTED_P5_T06_TOTAL = 20_707
EXPECTED_P5_T07_TOTAL = 15_607


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
        "octogamedb.audit_spawn_raw_semantics",
        "--db",
        str(db),
        "--config",
        str(config),
        "--limit",
        "0",
        "--top",
        "25",
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
            "P5-T07 audit command failed:\n"
            + " ".join(command)
            + "\nSTDOUT:\n"
            + completed.stdout
            + "\nSTDERR:\n"
            + completed.stderr
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("P5-T07 audit emitted invalid JSON") from exc
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


def _validate_report(report: dict[str, Any]) -> None:
    _require(
        report.get("scope") == "p5-t07-concentrated-spawn-addition-raw-semantics",
        "P5-T07 scope is exact",
    )
    _require(report.get("read_only") is True, "P5-T07 declares the audit read-only")
    _require(
        report["p5_t06_global_included_member_count"] == EXPECTED_P5_T06_TOTAL,
        "P5-T06 global addition regression remains exactly 20,707",
    )
    _require(
        report["audited_zone_member_count"] == EXPECTED_P5_T07_TOTAL,
        "P5-T07 four-zone population is exactly 15,607",
    )
    _require(
        set(report["audited_zone_ids"]) == set(EXPECTED_ZONE_COUNTS),
        "P5-T07 audits exactly the four routed zones",
    )

    revisions = report["source_revisions"]
    for side, expected_revision in EXPECTED_REVISIONS.items():
        _require(
            revisions[side]["source_revision"] == expected_revision,
            f"{side} raw source revision is exact",
        )

    measured_zones = {
        int(row["zone_id"]): int(row["addition_member_count"])
        for row in report["zone_summary"]
    }
    _require(
        measured_zones == EXPECTED_ZONE_COUNTS,
        "all four P5-T06 zone counts reproduce exactly",
    )

    reconciliation = report["reconciliation"]
    _require(
        {int(value) for value in reconciliation.values()} == {EXPECTED_P5_T07_TOTAL},
        "all four-zone member aggregates independently reconcile to 15,607",
    )
    _require(
        sum(int(row["member_count"]) for row in report["zone_by_addition_parent_class"])
        == EXPECTED_P5_T07_TOTAL,
        "zone x addition-parent-class aggregate reconciles",
    )
    _require(
        sum(int(row["member_count"]) for row in report["zone_by_source_side"])
        == EXPECTED_P5_T07_TOTAL,
        "zone x source-side aggregate reconciles",
    )
    _require(
        sum(int(row["member_count"]) for row in report["zone_by_raw_transformation_class"])
        == EXPECTED_P5_T07_TOTAL,
        "zone x contributing raw transformation aggregate reconciles",
    )

    _require(report["parent_count"] > 0, "P5-T07 has relevant parent templates")
    _require(
        len(report["zone_parent_counts"]) >= report["parent_count"],
        "full zone-parent table is present",
    )
    _require(
        bool(report["base_present_parent_member_composition"]),
        "base-present parents retain exact inherited/added/removed member composition",
    )
    _require(
        report["duplicate_diagnostics"]["duplicate_rows_collapse_by_spawn_key"] is True,
        "raw duplicate coordinate rows explicitly collapse by deterministic spawn_key",
    )

    measured_classes = {
        (str(row["source_side"]), str(row["raw_transformation_class"]))
        for row in report["zone_parent_transformation_counts"]
        if int(row["distinct_parent_count"]) > 0
    }
    example_classes = {
        (str(row["source_side"]), str(row["raw_transformation_class"]))
        for row in report["source_file_top_entry_examples"]
    }
    _require(
        measured_classes <= example_classes,
        "every non-empty source-side transformation class has a bounded "
        "source-file/top-entry example",
    )
    _require(
        all(
            all(not Path(path).is_absolute() for path in row["raw_source_relative_paths"])
            for row in report["source_file_top_entry_examples"]
        ),
        "raw provenance examples retain source-relative paths only",
    )

    parent_audits = report["parent_audits"]
    _require(bool(parent_audits), "bounded detailed parent audits are emitted")
    _require(
        all(
            audit[side]["persisted_spawn_set"]["raw_matches_persisted"] is True
            for audit in parent_audits
            for side in ("active", "comparison")
        ),
        "bounded parent examples prove raw effective membership equals persisted spawn_set",
    )
    _require(
        all(
            "interpretive_boundary" in row and bool(row["signals"])
            for row in report["descriptive_zone_signals"]
        ),
        "each zone has bounded descriptive evidence without an authority decision",
    )


def _parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=project_root / "data" / "generated" / "octogamedb.sqlite3",
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

    # Import only after the project source tree has been selected by the invoking shell/BAT.
    from octogamedb.audit_spawn_raw_semantics import (
        RawSemanticAuditError,
        _classify_parent_transform,
        _read_source_paths,
    )

    roots = _read_source_paths(
        config_path=config,
        pfquest_root=None,
        pfquest_turtle_root=None,
        pfquest_octo_root=None,
    )
    for label, root in zip(("pfquest", "pfquest_turtle", "pfquest_octo"), roots, strict=True):
        _require(root.expanduser().is_dir(), f"configured {label} source root exists")

    try:
        _classify_parent_transform(base_present=True, patch_value=42)
    except RawSemanticAuditError:
        print("[PASS] unsupported top-entry transformation fails closed")
    else:
        raise RuntimeError("unsupported top-entry transformation was not rejected")

    temp_parent = project_root / ".validation_tmp"
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="P5-T07_", dir=temp_parent) as temp_name:
        snapshot = Path(temp_name) / "octogamedb_snapshot.sqlite3"
        shutil.copy2(canonical_db, snapshot)
        snapshot_before = _sha256(snapshot)
        _require(snapshot_before == canonical_before, "snapshot is byte-identical to canonical DB")
        _read_only_integrity(snapshot)

        summary_path = output_dir / f"P5-T07_summary_{stamp}.json"
        summary = _run_report(
            project_root,
            db=snapshot,
            config=config,
            output=summary_path,
        )
        _validate_report(summary)

        repeat_path = output_dir / f"P5-T07_summary_repeat_{stamp}.json"
        repeat = _run_report(
            project_root,
            db=snapshot,
            config=config,
            output=repeat_path,
        )
        _require(repeat == summary, "P5-T07 JSON is deterministic across repeated runs")

        for class_name in sorted(
            {
                str(row["raw_transformation_class"])
                for row in summary["zone_by_raw_transformation_class"]
                if int(row["member_count"]) > 0
            }
        ):
            path = output_dir / f"P5-T07_members_{class_name}_{stamp}.json"
            example = _run_report(
                project_root,
                db=snapshot,
                config=config,
                output=path,
                extra_args=[
                    "--raw-transformation-class",
                    class_name,
                    "--limit",
                    "8",
                    "--top",
                    "8",
                ],
            )
            _require(
                example["returned_member_count"] > 0,
                f"bounded real members emitted for contributing transformation {class_name}",
            )
            _require(
                all(
                    member["raw_transformation_class"] == class_name
                    for member in example["members"]
                ),
                f"bounded filter is exact for {class_name}",
            )

        snapshot_after = _sha256(snapshot)
        _require(
            snapshot_after == snapshot_before,
            "validation snapshot is byte-identical after raw-source audit",
        )

    canonical_after = _sha256(canonical_db)
    _require(canonical_after == canonical_before, "canonical DB is byte-identical after validation")

    evidence = {
        "task": "P5-T07",
        "status": "LEVEL_2_VALIDATION_PASSED",
        "canonical_sha256_before": canonical_before,
        "canonical_sha256_after": canonical_after,
        "source_revisions": summary["source_revisions"],
        "p5_t06_global_included_member_count": summary["p5_t06_global_included_member_count"],
        "audited_zone_member_count": summary["audited_zone_member_count"],
        "zone_summary": summary["zone_summary"],
        "zone_parent_transformation_counts": summary["zone_parent_transformation_counts"],
        "cross_overlay_membership": summary["cross_overlay_membership"],
        "duplicate_diagnostics": summary["duplicate_diagnostics"],
        "descriptive_zone_signals": summary["descriptive_zone_signals"],
        "summary_json": str(summary_path),
    }
    evidence_path = output_dir / f"P5-T07_validation_{stamp}.json"
    _write_json(evidence_path, evidence)
    print(f"[PASS] P5-T07 Level-2 validation passed: {evidence_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
