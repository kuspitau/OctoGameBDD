"""Versioned SQL migration discovery and application."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
import re
import sqlite3

_MIGRATION_NAME_RE = re.compile(r"^(?P<version>[0-9]{4})_(?P<name>[a-z0-9_]+)\.sql$")
_MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""


@dataclass(frozen=True, order=True)
class Migration:
    """A packaged, versioned SQL migration."""

    version: int
    name: str
    sql: str


def discover_migrations() -> tuple[Migration, ...]:
    """Load packaged SQL migrations in deterministic version order."""

    migration_root = resources.files("octogamedb.db").joinpath("migrations")
    migrations: list[Migration] = []

    for entry in migration_root.iterdir():
        if not entry.is_file():
            continue

        match = _MIGRATION_NAME_RE.fullmatch(entry.name)
        if match is None:
            continue

        migrations.append(
            Migration(
                version=int(match.group("version")),
                name=entry.name,
                sql=entry.read_text(encoding="utf-8"),
            )
        )

    migrations.sort(key=lambda migration: migration.version)

    versions = [migration.version for migration in migrations]
    if len(versions) != len(set(versions)):
        raise RuntimeError("Duplicate migration versions detected")

    return tuple(migrations)


def _ensure_migration_table(connection: sqlite3.Connection) -> None:
    connection.execute(_MIGRATION_TABLE_SQL)
    connection.commit()


def get_applied_migrations(connection: sqlite3.Connection) -> tuple[tuple[int, str], ...]:
    """Return applied migrations as ``(version, name)`` tuples."""

    _ensure_migration_table(connection)
    rows = connection.execute(
        "SELECT version, name FROM schema_migrations ORDER BY version"
    ).fetchall()
    return tuple((int(row["version"]), str(row["name"])) for row in rows)


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def apply_migrations(connection: sqlite3.Connection) -> tuple[Migration, ...]:
    """Apply every pending migration atomically and return those applied now."""

    _ensure_migration_table(connection)
    migrations = discover_migrations()
    applied = dict(get_applied_migrations(connection))
    available = {migration.version: migration for migration in migrations}

    unknown_versions = sorted(set(applied) - set(available))
    if unknown_versions:
        joined = ", ".join(str(version) for version in unknown_versions)
        raise RuntimeError(f"Database contains unknown migration version(s): {joined}")

    for version, name in applied.items():
        expected_name = available[version].name
        if name != expected_name:
            raise RuntimeError(
                f"Migration version {version} is recorded as {name!r}, "
                f"expected {expected_name!r}"
            )

    newly_applied: list[Migration] = []
    for migration in migrations:
        if migration.version in applied:
            continue

        record_sql = (
            "INSERT INTO schema_migrations(version, name) VALUES "
            f"({migration.version}, {_sql_literal(migration.name)});"
        )
        script = f"BEGIN IMMEDIATE;\n{migration.sql}\n{record_sql}\nCOMMIT;"

        try:
            connection.executescript(script)
        except Exception:
            connection.rollback()
            raise

        newly_applied.append(migration)

    return tuple(newly_applied)
