"""Read-only Level-2 validator for P7-T01 against the accepted migration-14 canonical DB."""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from pathlib import Path

from octogamedb.item_search import (
    MATCH_KNOWN,
    MATCH_UNKNOWN,
    NON_MATCH_KNOWN,
    query_items,
)

EXPECTED_CANONICAL_SHA256 = "60aeb4093fa68e6b3a7a8c513e5a127862d88db8bc9aab4f6f3e4a0f4c0d5a23"
EXPECTED_SCHEMA_VERSION = 14


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open_readonly(path: Path) -> sqlite3.Connection:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"canonical database not found: {path}")
    connection = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def validate(
    db_path: Path, *, expected_sha256: str = EXPECTED_CANONICAL_SHA256
) -> dict[str, object]:
    before_sha = _sha256(db_path)
    if before_sha != expected_sha256:
        raise RuntimeError(
            f"unexpected canonical SHA-256: expected {expected_sha256}, observed {before_sha}"
        )

    connection = _open_readonly(db_path)
    try:
        schema_version = int(
            connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
        )
        if schema_version != EXPECTED_SCHEMA_VERSION:
            raise RuntimeError(
                "unexpected schema version: "
                f"expected {EXPECTED_SCHEMA_VERSION}, observed {schema_version}"
            )

        item_count = int(connection.execute("SELECT COUNT(*) FROM items").fetchone()[0])
        template_count = int(
            connection.execute("SELECT COUNT(*) FROM item_templates").fetchone()[0]
        )
        if item_count <= 0 or template_count <= 0 or template_count >= item_count:
            raise RuntimeError(
                "expected a non-empty partial item-template projection over a larger "
                "item identity set"
            )

        template_sample = connection.execute(
            """
            SELECT item_id, quality, class_id, subclass_id, inventory_type,
                   item_level, required_level, armor, max_durability
            FROM item_templates
            ORDER BY item_id
            LIMIT 1
            """
        ).fetchone()
        assert template_sample is not None
        template_item_id = int(template_sample["item_id"])

        match_page = query_items(
            connection,
            item_id=template_item_id,
            quality=int(template_sample["quality"]),
            class_id=int(template_sample["class_id"]),
            subclass_id=int(template_sample["subclass_id"]),
            inventory_type=int(template_sample["inventory_type"]),
            min_item_level=int(template_sample["item_level"]),
            max_required_level=int(template_sample["required_level"]),
            min_armor=int(template_sample["armor"]),
            min_max_durability=int(template_sample["max_durability"]),
            include_states=(MATCH_KNOWN,),
            limit=10,
        )
        if [result.item_id for result in match_page.results] != [template_item_id]:
            raise RuntimeError(
                "representative materialized-template match query did not round-trip"
            )
        trace = match_page.results[0].trace
        if not trace or any(not fact.fact_key.startswith("template.") for fact in trace):
            raise RuntimeError(
                "representative materialized item lacks selected template provenance"
            )

        unknown_row = connection.execute(
            """
            SELECT i.item_id
            FROM items AS i
            LEFT JOIN item_templates AS t ON t.item_id = i.item_id
            WHERE t.item_id IS NULL
            ORDER BY i.item_id
            LIMIT 1
            """
        ).fetchone()
        assert unknown_row is not None
        unknown_item_id = int(unknown_row["item_id"])
        unknown_page = query_items(
            connection,
            item_id=unknown_item_id,
            quality=int(template_sample["quality"]),
            include_states=(MATCH_UNKNOWN,),
            limit=10,
        )
        if [result.item_id for result in unknown_page.results] != [unknown_item_id]:
            raise RuntimeError("unmaterialized template was not classified as unknown")
        if unknown_page.results[0].quality is not None:
            raise RuntimeError("unknown template exposed a fabricated quality value")

        nonmatch_page = query_items(
            connection,
            quality=2_147_483_647,
            include_states=(NON_MATCH_KNOWN,),
            sort_by="item_id",
            limit=1,
        )
        if not nonmatch_page.results:
            raise RuntimeError("expected at least one known non-match from materialized templates")
        nonmatch_item_id = nonmatch_page.results[0].item_id

        stat_row = connection.execute(
            """
            SELECT item_id, stat_type, stat_value
            FROM item_stat_modifiers
            ORDER BY item_id, slot_index
            LIMIT 1
            """
        ).fetchone()
        stat_sample: str | None = None
        if stat_row is not None:
            stat_item_id = int(stat_row["item_id"])
            stat_type = int(stat_row["stat_type"])
            stat_value = int(stat_row["stat_value"])
            stat_page = query_items(
                connection,
                item_id=stat_item_id,
                min_stats={stat_type: stat_value},
                include_states=(MATCH_KNOWN,),
                limit=10,
            )
            if [result.item_id for result in stat_page.results] != [stat_item_id]:
                raise RuntimeError("representative stat predicate did not match its source row")
            stat_sample = f"{stat_item_id}:type{stat_type}>={stat_value}"

        missing_stat_page = query_items(
            connection,
            min_stats={2_147_483_647: 1},
            include_states=(NON_MATCH_KNOWN,),
            sort_by="item_id",
            limit=1,
        )
        if not missing_stat_page.results:
            raise RuntimeError(
                "materialized complete stat slots did not yield a known non-match for "
                "absent stat type"
            )

        sorted_page = query_items(
            connection,
            sort_by="required_level",
            descending=True,
            limit=min(5, template_count),
        )
        known_levels = [
            result.required_level
            for result in sorted_page.results
            if result.required_level is not None
        ]
        if known_levels != sorted(known_levels, reverse=True):
            raise RuntimeError("descending required-level sort is not deterministic")

        foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_violations:
            raise RuntimeError(f"foreign_key_check failed: {foreign_key_violations[:5]}")
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise RuntimeError(f"integrity_check failed: {integrity}")
    finally:
        connection.close()

    after_sha = _sha256(db_path)
    if after_sha != before_sha:
        raise RuntimeError(
            "canonical DB changed during read-only validation: "
            f"{before_sha} -> {after_sha}"
        )

    return {
        "canonical_sha256": before_sha,
        "schema_version": schema_version,
        "item_identities": item_count,
        "materialized_templates": template_count,
        "unknown_templates": item_count - template_count,
        "match_sample_item_id": template_item_id,
        "nonmatch_sample_item_id": nonmatch_item_id,
        "unknown_sample_item_id": unknown_item_id,
        "stat_sample": stat_sample,
        "foreign_key_check": [],
        "integrity_check": integrity,
        "canonical_db_unchanged": True,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/generated/octogamedb.sqlite3"),
    )
    parser.add_argument("--expected-sha256", default=EXPECTED_CANONICAL_SHA256)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    result = validate(args.db, expected_sha256=args.expected_sha256)
    print("P7_T01_LOCAL_VALIDATION_OK")
    for key, value in result.items():
        if isinstance(value, bool):
            rendered = str(value).lower()
        else:
            rendered = value
        print(f"{key}={rendered}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
