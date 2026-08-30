"""Read-only Level-2 validator for P7-T02 against the accepted canonical DB."""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from pathlib import Path
from typing import Any

from octogamedb.item_acquisition_search import (
    ItemAcquisitionQueryResult,
    query_item_acquisitions,
)
from octogamedb.item_search import MATCH_KNOWN, MATCH_UNKNOWN

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


def _first_direct_sample(connection: sqlite3.Connection) -> tuple[int, str, float]:
    row = connection.execute(
        """
        SELECT item_id, 'creature' AS source_kind, chance_percent
        FROM creature_loot
        UNION ALL
        SELECT item_id, 'gameobject' AS source_kind, chance_percent
        FROM gameobject_loot
        ORDER BY item_id, source_kind
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise RuntimeError("canonical DB has no materialized direct P2 acquisition path")
    return int(row["item_id"]), str(row["source_kind"]), float(row["chance_percent"])


def _first_reference_sample(connection: sqlite3.Connection) -> tuple[int, str, float]:
    row = connection.execute(
        """
        SELECT irl.item_id, 'creature' AS source_kind, irl.chance_percent
        FROM item_reference_loot AS irl
        JOIN reference_loot_creatures AS rlc
          ON rlc.reference_loot_id = irl.reference_loot_id
        UNION ALL
        SELECT irl.item_id, 'gameobject' AS source_kind, irl.chance_percent
        FROM item_reference_loot AS irl
        JOIN reference_loot_gameobjects AS rlg
          ON rlg.reference_loot_id = irl.reference_loot_id
        ORDER BY item_id, source_kind
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise RuntimeError("canonical DB has no resolvable reference P2 acquisition path")
    return int(row["item_id"]), str(row["source_kind"]), float(row["chance_percent"])


def _first_vendor_sample(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT item_id FROM vendor_items ORDER BY item_id, vendor_creature_id LIMIT 1"
    ).fetchone()
    if row is None:
        raise RuntimeError("canonical DB has no materialized vendor P2 acquisition path")
    return int(row["item_id"])


def _assert_known_path(
    connection: sqlite3.Connection,
    *,
    item_id: int,
    path_kind: str,
    source_kind: str | None = None,
    min_drop_chance: float | None = None,
) -> tuple[ItemAcquisitionQueryResult, dict[str, Any]]:
    page = query_item_acquisitions(
        connection,
        item_id=item_id,
        path_kinds=(path_kind,),
        source_kinds=() if source_kind is None else (source_kind,),
        min_drop_chance=min_drop_chance,
        include_states=(MATCH_KNOWN,),
        limit=10,
    )
    if [result.item.item_id for result in page.results] != [item_id]:
        raise RuntimeError(f"representative {path_kind} acquisition query did not round-trip")
    result = page.results[0]
    if result.acquisition_filter.state != MATCH_KNOWN or not result.matching_sources:
        raise RuntimeError(f"representative {path_kind} path was not classified as known_match")
    path = next(
        (
            candidate
            for source in result.matching_sources
            for candidate in source["acquisition_paths"]
            if candidate["path_kind"] == path_kind
        ),
        None,
    )
    if path is None:
        raise RuntimeError(f"representative {path_kind} query lost its matching path")
    if path.get("relation_source") is None:
        raise RuntimeError(f"representative {path_kind} path lacks selected primitive provenance")
    return result, path


def _first_located_sample(connection: sqlite3.Connection) -> tuple[int, int, int]:
    row = connection.execute(
        """
        SELECT cl.item_id, cs.zone_id, COALESCE(cs.map_id, z.map_id) AS map_id
        FROM creature_loot AS cl
        JOIN creature_spawns AS cs ON cs.creature_id = cl.creature_id
        LEFT JOIN zones AS z ON z.zone_id = cs.zone_id
        WHERE cs.zone_id IS NOT NULL AND COALESCE(cs.map_id, z.map_id) IS NOT NULL

        UNION ALL

        SELECT gl.item_id, gs.zone_id, COALESCE(gs.map_id, z.map_id) AS map_id
        FROM gameobject_loot AS gl
        JOIN gameobject_spawns AS gs ON gs.gameobject_id = gl.gameobject_id
        LEFT JOIN zones AS z ON z.zone_id = gs.zone_id
        WHERE gs.zone_id IS NOT NULL AND COALESCE(gs.map_id, z.map_id) IS NOT NULL

        UNION ALL

        SELECT irl.item_id, cs.zone_id, COALESCE(cs.map_id, z.map_id) AS map_id
        FROM item_reference_loot AS irl
        JOIN reference_loot_creatures AS rlc
          ON rlc.reference_loot_id = irl.reference_loot_id
        JOIN creature_spawns AS cs ON cs.creature_id = rlc.creature_id
        LEFT JOIN zones AS z ON z.zone_id = cs.zone_id
        WHERE cs.zone_id IS NOT NULL AND COALESCE(cs.map_id, z.map_id) IS NOT NULL

        UNION ALL

        SELECT irl.item_id, gs.zone_id, COALESCE(gs.map_id, z.map_id) AS map_id
        FROM item_reference_loot AS irl
        JOIN reference_loot_gameobjects AS rlg
          ON rlg.reference_loot_id = irl.reference_loot_id
        JOIN gameobject_spawns AS gs ON gs.gameobject_id = rlg.gameobject_id
        LEFT JOIN zones AS z ON z.zone_id = gs.zone_id
        WHERE gs.zone_id IS NOT NULL AND COALESCE(gs.map_id, z.map_id) IS NOT NULL

        UNION ALL

        SELECT vi.item_id, cs.zone_id, COALESCE(cs.map_id, z.map_id) AS map_id
        FROM vendor_items AS vi
        JOIN creature_spawns AS cs ON cs.creature_id = vi.vendor_creature_id
        LEFT JOIN zones AS z ON z.zone_id = cs.zone_id
        WHERE cs.zone_id IS NOT NULL AND COALESCE(cs.map_id, z.map_id) IS NOT NULL

        ORDER BY 1, 2, 3
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise RuntimeError("canonical DB has no P2 acquisition source with derivable P1 zone/map")
    return int(row["item_id"]), int(row["zone_id"]), int(row["map_id"])


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
        acquisition_item_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT item_id FROM creature_loot
                    UNION
                    SELECT item_id FROM gameobject_loot
                    UNION
                    SELECT item_id FROM item_reference_loot
                    UNION
                    SELECT item_id FROM vendor_items
                )
                """
            ).fetchone()[0]
        )
        if item_count <= 0 or acquisition_item_count <= 0:
            raise RuntimeError("expected non-empty item and P2 acquisition surfaces")

        direct_item_id, direct_source_kind, direct_chance = _first_direct_sample(connection)
        direct_result, direct_path = _assert_known_path(
            connection,
            item_id=direct_item_id,
            path_kind="direct",
            source_kind=direct_source_kind,
            min_drop_chance=direct_chance,
        )
        if direct_result.item.item_id != direct_item_id or direct_path["path_kind"] != "direct":
            raise RuntimeError("representative direct path identity changed unexpectedly")

        reference_item_id, reference_source_kind, reference_chance = _first_reference_sample(
            connection
        )
        _, reference_path = _assert_known_path(
            connection,
            item_id=reference_item_id,
            path_kind="reference",
            source_kind=reference_source_kind,
            min_drop_chance=reference_chance,
        )
        if reference_path.get("reference_membership_source") is None:
            raise RuntimeError("representative reference path lacks membership provenance")

        vendor_item_id = _first_vendor_sample(connection)
        _, vendor_path = _assert_known_path(
            connection,
            item_id=vendor_item_id,
            path_kind="vendor",
            source_kind="creature",
        )
        if vendor_path.get("chance_percent") is not None:
            raise RuntimeError("vendor max_count was exposed as drop chance")
        if vendor_path.get("vendor_max_count") is None:
            raise RuntimeError("representative vendor path lost max_count")

        located_item_id, located_zone_id, located_map_id = _first_located_sample(connection)
        geography_page = query_item_acquisitions(
            connection,
            item_id=located_item_id,
            zone_id=located_zone_id,
            map_id=located_map_id,
            include_states=(MATCH_KNOWN,),
            limit=10,
        )
        if [result.item.item_id for result in geography_page.results] != [located_item_id]:
            raise RuntimeError("known derived zone/map filter did not round-trip")
        if not any(
            source.get("location_source") is not None
            for source in geography_page.results[0].matching_sources
        ):
            raise RuntimeError("known derived geography lacks selected spawn-position provenance")

        unknown_row = connection.execute(
            """
            SELECT i.item_id
            FROM items AS i
            WHERE NOT EXISTS (SELECT 1 FROM creature_loot cl WHERE cl.item_id = i.item_id)
              AND NOT EXISTS (SELECT 1 FROM gameobject_loot gl WHERE gl.item_id = i.item_id)
              AND NOT EXISTS (SELECT 1 FROM item_reference_loot irl WHERE irl.item_id = i.item_id)
              AND NOT EXISTS (SELECT 1 FROM vendor_items vi WHERE vi.item_id = i.item_id)
            ORDER BY i.item_id
            LIMIT 1
            """
        ).fetchone()
        if unknown_row is None:
            raise RuntimeError(
                "expected at least one item without a materialized P2 acquisition row"
            )
        unknown_item_id = int(unknown_row["item_id"])
        unknown_page = query_item_acquisitions(
            connection,
            item_id=unknown_item_id,
            path_kinds=("direct",),
            include_states=(MATCH_UNKNOWN,),
            limit=10,
        )
        if [result.item.item_id for result in unknown_page.results] != [unknown_item_id]:
            raise RuntimeError("missing acquisition evidence was not preserved as unknown")
        if unknown_page.results[0].acquisition_filter.reason != (
            "no_known_matching_path_negative_not_proven"
        ):
            raise RuntimeError("unknown acquisition result lost its conservative reason")

        template_acquisition_row = connection.execute(
            """
            SELECT t.item_id, t.quality
            FROM item_templates AS t
            WHERE EXISTS (SELECT 1 FROM creature_loot cl WHERE cl.item_id = t.item_id)
               OR EXISTS (SELECT 1 FROM gameobject_loot gl WHERE gl.item_id = t.item_id)
               OR EXISTS (SELECT 1 FROM item_reference_loot irl WHERE irl.item_id = t.item_id)
               OR EXISTS (SELECT 1 FROM vendor_items vi WHERE vi.item_id = t.item_id)
            ORDER BY t.item_id
            LIMIT 1
            """
        ).fetchone()
        template_acquisition_sample: int | None = None
        if template_acquisition_row is not None:
            template_acquisition_sample = int(template_acquisition_row["item_id"])
            composed_page = query_item_acquisitions(
                connection,
                item_id=template_acquisition_sample,
                quality=int(template_acquisition_row["quality"]),
                include_states=(MATCH_KNOWN,),
                limit=10,
            )
            if [result.item.item_id for result in composed_page.results] != [
                template_acquisition_sample
            ]:
                raise RuntimeError("materialized P7 template + P2 acquisition composition failed")

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
        "materialized_acquisition_items": acquisition_item_count,
        "direct_sample_item_id": direct_item_id,
        "reference_sample_item_id": reference_item_id,
        "vendor_sample_item_id": vendor_item_id,
        "located_sample_item_id": located_item_id,
        "unknown_acquisition_sample_item_id": unknown_item_id,
        "template_acquisition_sample_item_id": template_acquisition_sample,
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
    print("P7_T02_LOCAL_VALIDATION_OK")
    for key, value in result.items():
        if isinstance(value, bool):
            rendered = str(value).lower()
        else:
            rendered = value
        print(f"{key}={rendered}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
