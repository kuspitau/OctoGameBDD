from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from octogamedb.canonical_baseline import (
    ACCEPTED_CANONICAL_BASELINE,
    P6_T05_INPUT_BASELINE,
)
from octogamedb.itemcache_incremental_promotion import IncrementalPromotionPlan

SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_p6_t05.py"


def _load():
    spec = importlib.util.spec_from_file_location("p6_t05_validator_test_module", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _baseline_db(path: Path) -> bytes:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)"
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, name) VALUES (14, ?)",
            ("0014_item_template_facts.sql",),
        )
        connection.execute("CREATE TABLE sentinel(value TEXT NOT NULL)")
        connection.execute("INSERT INTO sentinel(value) VALUES ('baseline')")
    return path.read_bytes()


def _plan(module, revision: str = "sha256:fixture") -> IncrementalPromotionPlan:
    return IncrementalPromotionPlan(
        canonical_sha256=module.EXPECTED_BASELINE_SHA256,
        canonical_migration=14,
        itemcache_sha256="a" * 64,
        itemcache_locale="enUS",
        itemcache_client_version=5875,
        evidence_artifacts=(),
        evidence_class_counts={},
        campaign_counts={"refresh_proven_items": 10, "attempted_unique_items": 10},
        eligible_items=(
            {
                "item_id": 1,
                "current_record_sha256": "b" * 64,
                "matching_proofs": [],
            },
        ),
        already_current_noops=(),
        excluded_refresh_proven=(),
        noneligible_class_item_counts={},
        plan_revision=revision,
    )


def test_incremental_validator_rejects_any_new_schema_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    module = _load()
    db = tmp_path / "copy.sqlite3"
    _baseline_db(db)
    connection = module.open_connection(db)
    monkeypatch.setattr(
        module,
        "get_applied_migrations",
        lambda connection: [(14, "0014_item_template_facts.sql")],
    )
    monkeypatch.setattr(
        module,
        "apply_migrations",
        lambda connection: [SimpleNamespace(version=15)],
    )
    try:
        with pytest.raises(RuntimeError, match="must not re-apply migration 14 or advance schema"):
            module.validate_incremental_database(
                connection,
                plan=_plan(module),
                cache_path=tmp_path / "itemcache.wdb",
                phase="fixture",
            )
    finally:
        connection.close()


def test_guarded_backup_is_exact_migration14_and_restore_removes_sidecars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    module = _load()
    canonical = tmp_path / "canonical.sqlite3"
    baseline = _baseline_db(canonical)
    digest = module.sha256_file(canonical)
    monkeypatch.setattr(module, "EXPECTED_BASELINE_SHA256", digest)
    backup = tmp_path / "canonical_bak.sqlite3"

    connection = module.create_guarded_backup(canonical, backup)
    try:
        assert backup.read_bytes() == baseline
        connection.execute("CREATE TABLE promoted(value INTEGER)")
        connection.commit()
    finally:
        connection.close()
    assert canonical.read_bytes() != baseline

    journal = Path(str(canonical) + "-journal")
    journal.write_bytes(b"failed-write-sidecar")
    module.restore_backup(canonical, backup)
    assert canonical.read_bytes() == baseline
    assert backup.read_bytes() == baseline
    assert not journal.exists()


def test_shadow_validation_mutates_only_disposable_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    module = _load()
    canonical = tmp_path / "canonical.sqlite3"
    baseline = _baseline_db(canonical)
    digest = module.sha256_file(canonical)
    monkeypatch.setattr(module, "EXPECTED_BASELINE_SHA256", digest)
    validation_db = tmp_path / "shadow.sqlite3"
    args = SimpleNamespace(db=canonical, validation_db=validation_db)
    plan = _plan(module)

    def fake_validate(connection, *, plan, cache_path, phase):
        assert phase == "shadow_validation"
        connection.execute("CREATE TABLE shadow_only(value INTEGER)")
        return {"migration": 14, "integrity_check": "ok"}

    monkeypatch.setattr(module, "validate_incremental_database", fake_validate)
    result = module.validate_shadow(args, plan, tmp_path / "itemcache.wdb")
    assert result["canonical_db_unchanged"] is True
    assert canonical.read_bytes() == baseline
    with sqlite3.connect(validation_db) as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='shadow_only'"
        ).fetchone() == (1,)


def test_failed_post_backup_promotion_restores_committed_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    module = _load()
    canonical = tmp_path / "canonical.sqlite3"
    baseline = _baseline_db(canonical)
    digest = module.sha256_file(canonical)
    monkeypatch.setattr(module, "EXPECTED_BASELINE_SHA256", digest)
    backup = tmp_path / "canonical_bak.sqlite3"
    args = SimpleNamespace(db=canonical, backup=backup)
    plan = _plan(module)
    shadow = {"plan_revision": plan.plan_revision, "canonical_db_unchanged": True}

    def fail_after_commit(connection, *, plan, cache_path, phase):
        assert phase == "canonical_promotion"
        connection.execute("CREATE TABLE committed_failure(value INTEGER)")
        connection.commit()
        raise RuntimeError("forced post-write failure")

    monkeypatch.setattr(module, "validate_incremental_database", fail_after_commit)
    with pytest.raises(RuntimeError, match="forced post-write failure"):
        module.promote_canonical(args, plan, tmp_path / "itemcache.wdb", shadow)

    assert canonical.read_bytes() == baseline
    assert backup.read_bytes() == baseline
    with sqlite3.connect(canonical) as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='committed_failure'"
        ).fetchone() is None


def test_runtime_baseline_defaults_current_and_can_replay_historical_p6_t05():
    module = _load()
    assert module.EXPECTED_BASELINE_SHA256 == ACCEPTED_CANONICAL_BASELINE.sha256

    module.configure_runtime_baseline(P6_T05_INPUT_BASELINE)
    assert module.EXPECTED_BASELINE_SHA256 == P6_T05_INPUT_BASELINE.sha256
    assert module.EXPECTED_BASELINE_MIGRATION == 14
    assert module._current_baseline().label == P6_T05_INPUT_BASELINE.label


def test_parse_args_uses_current_artifacts_by_default_and_historical_on_replay():
    module = _load()
    current = module.parse_args(["verify-baseline"])
    assert current.baseline == "current"
    assert current.campaign == module.DEFAULT_CURRENT_CAMPAIGN
    assert current.plan == module.DEFAULT_CURRENT_PLAN
    assert current.validation_db == module.DEFAULT_CURRENT_VALIDATION_DB

    replay = module.parse_args(["plan", "--baseline", "p6-t05-input"])
    assert replay.campaign == module.DEFAULT_HISTORICAL_CAMPAIGN
    assert replay.plan == module.DEFAULT_HISTORICAL_PLAN
    assert replay.validation_db == module.DEFAULT_HISTORICAL_VALIDATION_DB


def test_verify_baseline_is_read_only_and_checks_migration_integrity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    module = _load()
    canonical = tmp_path / "canonical.sqlite3"
    baseline = _baseline_db(canonical)
    digest = module.sha256_file(canonical)
    monkeypatch.setattr(module, "EXPECTED_BASELINE_SHA256", digest)
    monkeypatch.setattr(module, "EXPECTED_BASELINE_MIGRATION", 14)
    monkeypatch.setattr(module, "EXPECTED_BASELINE_LABEL", "fixture")
    args = SimpleNamespace(db=canonical)

    result = module.verify_baseline(args)
    assert result == {
        "canonical_sha256": digest,
        "canonical_migration": 14,
        "foreign_key_check": [],
        "integrity_check": "ok",
    }
    assert canonical.read_bytes() == baseline
