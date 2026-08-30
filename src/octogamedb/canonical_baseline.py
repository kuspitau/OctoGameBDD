"""Accepted canonical SQLite baselines used by guarded P6 tooling.

Tracked code owns the expected migration/hash contract; the large canonical database itself remains
local.  Callers must fail closed on any other migration/hash pair and on SQLite sidecars.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CanonicalBaseline:
    migration: int
    sha256: str
    label: str

    def __post_init__(self) -> None:
        digest = self.sha256.lower()
        if self.migration < 0:
            raise ValueError("canonical migration must be non-negative")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("canonical sha256 must be a 64-character hexadecimal digest")
        object.__setattr__(self, "sha256", digest)


# Current accepted cumulative local baseline after validated P6-T05.
ACCEPTED_CANONICAL_BASELINE = CanonicalBaseline(
    migration=14,
    sha256="60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23",
    label="P6-T05 accepted migration-14 canonical baseline",
)

# Historical immediate input/rollback baseline for replaying the one-time P6-T05 path.
P6_T05_INPUT_BASELINE = CanonicalBaseline(
    migration=14,
    sha256="d57e0c79ac44d4fa0436b8c25e854a1d2b579d72dea1c327b23e9fe0fc4d1a8b",
    label="P6-T05 historical migration-14 input baseline",
)

# Historical input baseline retained only for validating/replaying the one-time P6-T04 path and its
# evidence artifacts.  It is not accepted by current P6 acquisition/promotion tooling.
P6_T04_INPUT_BASELINE = CanonicalBaseline(
    migration=13,
    sha256="623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7",
    label="P6-T04 historical migration-13 input baseline",
)

DEFAULT_CANONICAL_CANDIDATES = (
    Path("data/generated/octogamedb.sqlite3"),
    Path("data/octogamedb.sqlite3"),
)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sqlite_sidecars(path: str | Path) -> tuple[Path, ...]:
    database = Path(path)
    return tuple(
        candidate
        for suffix in ("-wal", "-shm", "-journal")
        if (candidate := Path(str(database) + suffix)).exists()
    )


def assert_no_sqlite_sidecars(path: str | Path) -> None:
    sidecars = sqlite_sidecars(path)
    if sidecars:
        raise RuntimeError(
            "SQLite sidecar(s) exist; close all writers/clients before continuing: "
            + ", ".join(str(candidate) for candidate in sidecars)
        )


def read_schema_migration(path: str | Path) -> int:
    database = Path(path).resolve()
    uri = f"file:{database.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        row = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()
    return int(row[0])


def assert_canonical_baseline(
    path: str | Path,
    *,
    baseline: CanonicalBaseline = ACCEPTED_CANONICAL_BASELINE,
    reject_sidecars: bool = True,
) -> str:
    database = Path(path)
    if not database.is_file():
        raise FileNotFoundError(database)
    if reject_sidecars:
        assert_no_sqlite_sidecars(database)

    digest = sha256_file(database)
    if digest != baseline.sha256:
        raise RuntimeError(
            f"Canonical DB hash drift from {baseline.label}: "
            f"expected={baseline.sha256} actual={digest}"
        )
    migration = read_schema_migration(database)
    if migration != baseline.migration:
        raise RuntimeError(
            f"Canonical DB migration drift from {baseline.label}: "
            f"expected={baseline.migration} actual={migration}"
        )
    return digest


def resolve_canonical_db(
    explicit: str | Path | None = None,
    *,
    baseline: CanonicalBaseline = ACCEPTED_CANONICAL_BASELINE,
    candidates: Iterable[str | Path] = DEFAULT_CANONICAL_CANDIDATES,
) -> Path:
    raw_candidates = (explicit,) if explicit is not None else tuple(candidates)
    existing = [
        Path(candidate).resolve()
        for candidate in raw_candidates
        if Path(candidate).is_file()
    ]
    if not existing:
        raise FileNotFoundError(
            "Canonical DB not found. Expected data/generated/octogamedb.sqlite3 "
            "(or legacy data/octogamedb.sqlite3), or pass --db."
        )

    exact = [path for path in existing if sha256_file(path) == baseline.sha256]
    if len(exact) == 1:
        # Hash match is not enough: enforce migration + no-sidecar contract before returning.
        assert_canonical_baseline(exact[0], baseline=baseline)
        return exact[0]
    if len(exact) > 1:
        raise RuntimeError(
            f"Multiple candidates match {baseline.label}; pass --db explicitly: {exact}"
        )
    details = ", ".join(f"{path}={sha256_file(path)}" for path in existing)
    raise RuntimeError(
        f"No canonical candidate matches {baseline.label} ({baseline.sha256}); {details}"
    )
