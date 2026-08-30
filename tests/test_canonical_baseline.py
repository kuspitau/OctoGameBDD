from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from octogamedb.canonical_baseline import (
    CanonicalBaseline,
    assert_canonical_baseline,
    resolve_canonical_db,
    sha256_file,
)


def _db(path: Path, migration: int) -> str:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, name TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
            (migration, f"00{migration}_fixture.sql"),
        )
        connection.execute("CREATE TABLE sentinel(value TEXT NOT NULL)")
        connection.execute("INSERT INTO sentinel(value) VALUES ('baseline')")
    return sha256_file(path)


def test_exact_hash_and_migration_are_both_required(tmp_path: Path):
    path = tmp_path / "canonical.sqlite3"
    digest = _db(path, 14)
    accepted = CanonicalBaseline(14, digest, "fixture migration 14")
    assert assert_canonical_baseline(path, baseline=accepted) == digest

    old_migration = CanonicalBaseline(13, digest, "stale migration 13")
    with pytest.raises(RuntimeError, match="migration drift"):
        assert_canonical_baseline(path, baseline=old_migration)


def test_sidecars_fail_closed(tmp_path: Path):
    path = tmp_path / "canonical.sqlite3"
    digest = _db(path, 14)
    baseline = CanonicalBaseline(14, digest, "fixture")
    Path(str(path) + "-wal").write_bytes(b"unexpected")
    with pytest.raises(RuntimeError, match="SQLite sidecar"):
        assert_canonical_baseline(path, baseline=baseline)


def test_resolver_requires_exact_accepted_candidate(tmp_path: Path):
    accepted_path = tmp_path / "accepted.sqlite3"
    rejected_path = tmp_path / "rejected.sqlite3"
    digest = _db(accepted_path, 14)
    _db(rejected_path, 14)
    with sqlite3.connect(rejected_path) as connection:
        connection.execute("UPDATE sentinel SET value = 'different'")
    baseline = CanonicalBaseline(14, digest, "fixture")

    resolved = resolve_canonical_db(
        baseline=baseline,
        candidates=(rejected_path, accepted_path),
    )
    assert resolved == accepted_path.resolve()


def test_named_p6_baselines_keep_current_and_historical_states_distinct():
    from octogamedb.canonical_baseline import (
        ACCEPTED_CANONICAL_BASELINE,
        P6_T04_INPUT_BASELINE,
        P6_T05_INPUT_BASELINE,
    )

    assert ACCEPTED_CANONICAL_BASELINE.migration == 14
    assert ACCEPTED_CANONICAL_BASELINE.sha256.startswith("60aeb409")
    assert P6_T05_INPUT_BASELINE.migration == 14
    assert P6_T05_INPUT_BASELINE.sha256.startswith("d57e0c79")
    assert P6_T04_INPUT_BASELINE.migration == 13
    assert P6_T04_INPUT_BASELINE.sha256.startswith("623e29d8")
    assert len(
        {
            ACCEPTED_CANONICAL_BASELINE.sha256,
            P6_T05_INPUT_BASELINE.sha256,
            P6_T04_INPUT_BASELINE.sha256,
        }
    ) == 3
