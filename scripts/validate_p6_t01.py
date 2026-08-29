"""Level-2 validator for P6-T01 against the user's real Octo itemcache.wdb.

The validator never writes the canonical DB. It requires the documented P4-T04/P5 analysis baseline,
copies it to a disposable validation DB, applies migration 14 there, imports a bounded representative
slice twice, and checks provenance/integrity/idempotency invariants.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sqlite3
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError as exc:  # pragma: no cover - project requires Python >=3.11
    raise SystemExit("Python 3.11+ is required (tomllib missing).") from exc

from octogamedb.db import apply_migrations
from octogamedb.importers.octo_itemcache import import_octo_itemcache_slice, parse_itemcache_wdb

EXPECTED_BASELINE_SHA256 = "623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7"
DEFAULT_DB = Path("data/generated/octogamedb.sqlite3")
DEFAULT_VALIDATION_DB = Path("data/generated/p6_t01_validation.sqlite3")
DEFAULT_CONFIG = Path("config.local.toml")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_wow_root(config_path: Path) -> Path | None:
    if not config_path.is_file():
        return None
    with config_path.open("rb") as handle:
        data = tomllib.load(handle)
    raw = data.get("source_paths", {}).get("wow_root")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Path(raw).expanduser()


def find_itemcache(wow_root: Path, locale: str | None) -> Path:
    roots = (wow_root / "WDB", wow_root / "Cache" / "WDB")
    candidates: list[Path] = []
    if locale:
        for root in roots:
            candidates.append(root / locale / "itemcache.wdb")
    for root in roots:
        if root.is_dir():
            candidates.extend(sorted(root.glob("*/itemcache.wdb")))
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key not in seen and candidate.is_file():
            unique.append(candidate)
            seen.add(key)
    if not unique:
        raise FileNotFoundError(
            f"No itemcache.wdb found below {wow_root / 'WDB'} or {wow_root / 'Cache' / 'WDB'}"
        )
    if locale:
        exact = [path for path in unique if path.parent.name.lower() == locale.lower()]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise RuntimeError(f"Ambiguous {locale} itemcache candidates: {exact}")
    if len(unique) != 1:
        raise RuntimeError(
            "Multiple itemcache.wdb files found; rerun with --locale or --itemcache: "
            + ", ".join(str(path) for path in unique)
        )
    return unique[0]


def choose_representative_ids(connection: sqlite3.Connection, cache_path: Path, limit: int) -> list[int]:
    snapshot = parse_itemcache_wdb(cache_path)
    canonical_ids = {int(row[0]) for row in connection.execute("SELECT item_id FROM items")}
    candidates = [record for record in snapshot.records if record.item_id in canonical_ids]
    if not candidates:
        raise RuntimeError("itemcache.wdb contains no item IDs present in the canonical items table")
    candidates.sort(key=lambda record: record.item_id)

    predicates = (
        lambda record: any(slot.stat_type or slot.stat_value for slot in record.stat_slots),
        lambda record: record.armor > 0,
        lambda record: record.max_durability > 0,
        lambda record: record.required_level > 0,
        lambda record: (
            record.required_skill_id > 0
            or record.required_spell_id > 0
            or record.required_reputation_faction_id > 0
        ),
        lambda record: record.allowable_class_mask == -1 or record.allowable_race_mask == -1,
    )
    selected: list[int] = []
    for predicate in predicates:
        match = next(
            (
                record.item_id
                for record in candidates
                if predicate(record) and record.item_id not in selected
            ),
            None,
        )
        if match is not None:
            selected.append(match)
        if len(selected) >= limit:
            return selected[:limit]
    for record in candidates:
        if record.item_id not in selected:
            selected.append(record.item_id)
        if len(selected) >= limit:
            break
    return selected


def table_count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def validate(args: argparse.Namespace) -> None:
    canonical = args.db.resolve()
    if not canonical.is_file():
        raise FileNotFoundError(f"Canonical DB not found: {canonical}")
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(canonical) + suffix)
        if sidecar.exists():
            raise RuntimeError(f"Canonical DB has forbidden SQLite sidecar: {sidecar}")
    baseline_hash = sha256_file(canonical)
    if baseline_hash != EXPECTED_BASELINE_SHA256:
        raise RuntimeError(
            "Canonical DB hash does not match CURRENT_STATE.md P4-T04/P5 baseline. "
            f"expected={EXPECTED_BASELINE_SHA256} actual={baseline_hash}. "
            "Do not advance the canonical DB from this validator."
        )

    with sqlite3.connect(f"file:{canonical.as_posix()}?mode=ro", uri=True) as baseline:
        version = baseline.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]
        if int(version) != 13:
            raise RuntimeError(f"Expected canonical schema migration 13, found {version}")
        wow_root = args.wow_root or read_wow_root(args.config)
        cache_path = args.itemcache
        if cache_path is None:
            if wow_root is None:
                raise RuntimeError(
                    "No --itemcache/--wow-root supplied and [source_paths].wow_root is missing from config.local.toml"
                )
            cache_path = find_itemcache(wow_root, args.locale)
        cache_path = cache_path.resolve()
        selected_ids = choose_representative_ids(baseline, cache_path, args.limit)

    validation_db = args.validation_db.resolve()
    validation_db.parent.mkdir(parents=True, exist_ok=True)
    if validation_db.exists():
        validation_db.unlink()
    shutil.copy2(canonical, validation_db)

    connection = sqlite3.connect(str(validation_db))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        applied = apply_migrations(connection)
        if [migration.version for migration in applied] != [14]:
            raise RuntimeError(
                "Expected only migration 14 on validation copy, got "
                f"{[migration.version for migration in applied]}"
            )

        first = import_octo_itemcache_slice(
            connection,
            source_path=cache_path,
            item_ids=selected_ids,
        )
        connection.commit()
        templates_after_first = table_count(connection, "item_templates")
        stats_after_first = table_count(connection, "item_stat_modifiers")
        observations_after_first = table_count(connection, "source_observations")

        second = import_octo_itemcache_slice(
            connection,
            source_path=cache_path,
            item_ids=selected_ids,
        )
        connection.commit()
        if second.rows_inserted != 0 or second.rows_updated != 0:
            raise RuntimeError(
                f"Idempotency failed: second run inserted={second.rows_inserted} updated={second.rows_updated}"
            )
        if table_count(connection, "item_templates") != templates_after_first:
            raise RuntimeError("item_templates changed on the idempotency rerun")
        if table_count(connection, "item_stat_modifiers") != stats_after_first:
            raise RuntimeError("item_stat_modifiers changed on the idempotency rerun")
        if table_count(connection, "source_observations") != observations_after_first:
            raise RuntimeError("source_observations duplicated on the idempotency rerun")

        missing_templates = connection.execute(
            "SELECT COUNT(*) FROM items AS i "
            "LEFT JOIN item_templates AS t ON t.item_id = i.item_id "
            f"WHERE i.item_id IN ({','.join('?' for _ in selected_ids)}) "
            "AND t.item_id IS NULL",
            selected_ids,
        ).fetchone()[0]
        if int(missing_templates) != 0:
            raise RuntimeError(f"{missing_templates} selected canonical items lack item_templates rows")

        missing_selections = connection.execute(
            f"""
            SELECT COUNT(*)
            FROM observation_groups AS og
            LEFT JOIN canonical_selections AS cs ON cs.observation_group_id = og.id
            WHERE og.subject_kind='item'
              AND og.subject_key IN ({','.join('?' for _ in selected_ids)})
              AND og.fact_key LIKE 'template.%'
              AND cs.observation_id IS NULL
            """,
            [str(item_id) for item_id in selected_ids],
        ).fetchone()[0]
        if int(missing_selections) != 0:
            raise RuntimeError(f"{missing_selections} P6 observations have no canonical selection")

        fk_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
        if fk_rows:
            raise RuntimeError(f"foreign_key_check failed: {fk_rows[:5]}")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"integrity_check failed: {integrity}")

        print("P6_T01_LOCAL_VALIDATION_OK")
        print(f"canonical_sha256={baseline_hash}")
        print(f"itemcache={cache_path}")
        print(f"selected_item_count={len(selected_ids)}")
        print("selected_item_ids=" + ",".join(str(item_id) for item_id in selected_ids))
        print(f"first_rows_inserted={first.rows_inserted}")
        print(f"first_rows_updated={first.rows_updated}")
        print(f"item_templates={templates_after_first}")
        print(f"item_stat_modifiers={stats_after_first}")
        print(f"source_observations={observations_after_first}")
        print(f"validation_db={validation_db}")
        canonical_after = sha256_file(canonical)
        if canonical_after != baseline_hash:
            raise RuntimeError(
                "Canonical DB changed during validation: "
                f"before={baseline_hash} after={canonical_after}"
            )
        print("canonical_db_unchanged=true")
    finally:
        connection.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--validation-db", type=Path, default=DEFAULT_VALIDATION_DB)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--wow-root", type=Path)
    parser.add_argument("--itemcache", type=Path)
    parser.add_argument("--locale", default="enUS")
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 100:
        parser.error("--limit must be between 1 and 100")
    return args


if __name__ == "__main__":
    validate(parse_args())
