from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from octogamedb.itemcache_promotion import PromotionPlan

SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_p6_t04.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location("p6_t04_validator_test_module", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _baseline_db(path: Path) -> bytes:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            )
            """
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, name) VALUES (13, ?)",
            ("0013_recipe_acquisition_sources.sql",),
        )
        connection.execute("CREATE TABLE sentinel(value TEXT NOT NULL)")
        connection.execute("INSERT INTO sentinel(value) VALUES ('baseline')")
    return path.read_bytes()


def _plan(module, revision: str = "sha256:fixture") -> PromotionPlan:
    return PromotionPlan(
        canonical_sha256=module.EXPECTED_BASELINE_SHA256,
        canonical_migration=13,
        target_migration=14,
        itemcache_sha256="a" * 64,
        itemcache_locale="enUS",
        itemcache_client_version=5875,
        evidence_artifacts=(),
        evidence_class_counts={},
        eligible_items=(),
        excluded_refresh_proven=(),
        noneligible_class_item_counts={},
        plan_revision=revision,
    )


def test_baseline_guard_rejects_sqlite_sidecars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    module = _load_validator()
    canonical = tmp_path / "canonical.sqlite3"
    _baseline_db(canonical)
    digest = module.sha256_file(canonical)
    monkeypatch.setattr(module, "EXPECTED_BASELINE_SHA256", digest)

    assert module.assert_canonical_baseline(canonical) == digest
    wal = Path(str(canonical) + "-wal")
    wal.write_bytes(b"unexpected")
    with pytest.raises(RuntimeError, match="SQLite sidecar"):
        module.assert_canonical_baseline(canonical)


def test_guarded_backup_is_exact_and_restore_removes_failed_sidecars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    module = _load_validator()
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
    restored_connection = module.open_connection(canonical)
    try:
        assert module.schema_version(restored_connection) == 13
    finally:
        restored_connection.close()


def test_shadow_validation_mutates_only_disposable_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    module = _load_validator()
    canonical = tmp_path / "canonical.sqlite3"
    baseline = _baseline_db(canonical)
    digest = module.sha256_file(canonical)
    monkeypatch.setattr(module, "EXPECTED_BASELINE_SHA256", digest)
    validation_db = tmp_path / "shadow.sqlite3"
    args = SimpleNamespace(db=canonical, validation_db=validation_db)
    plan = _plan(module)

    def fake_validate(connection, *, plan, cache_path, phase):
        assert phase == "shadow_validation"
        assert plan.plan_revision == "sha256:fixture"
        connection.execute("CREATE TABLE shadow_only(value INTEGER)")
        return {"migration": 14, "integrity_check": "ok"}

    monkeypatch.setattr(module, "validate_promoted_database", fake_validate)
    result = module.validate_shadow(args, plan, tmp_path / "itemcache.wdb")
    assert result["canonical_db_unchanged"] is True
    assert canonical.read_bytes() == baseline
    with sqlite3.connect(validation_db) as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='shadow_only'"
        ).fetchone() == (1,)


def test_failed_post_backup_promotion_restores_even_committed_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    module = _load_validator()
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

    monkeypatch.setattr(module, "validate_promoted_database", fail_after_commit)
    with pytest.raises(RuntimeError, match="forced post-write failure"):
        module.promote_canonical(args, plan, tmp_path / "itemcache.wdb", shadow)

    assert canonical.read_bytes() == baseline
    assert backup.read_bytes() == baseline
    with sqlite3.connect(canonical) as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='committed_failure'"
        ).fetchone() is None
