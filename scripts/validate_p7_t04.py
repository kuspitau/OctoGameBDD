"""Read-only Level-2 validator for P7-T04 against the accepted canonical DB."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from octogamedb.item_search import MATCH_KNOWN
from octogamedb.recipe_search import query_recipes, recipe_query_page_to_dict

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


def _one(connection: sqlite3.Connection, sql: str) -> sqlite3.Row:
    row = connection.execute(sql).fetchone()
    if row is None:
        raise RuntimeError(
            "accepted canonical DB has no representative row for required P7-T04 gate"
        )
    return row


def _recipe_detail(connection: sqlite3.Connection, recipe_id: int) -> dict[str, Any]:
    page = query_recipes(connection, recipe_id=recipe_id, limit=10)
    matches = [result for result in page.results if result.recipe["recipe_id"] == recipe_id]
    if len(matches) != 1 or matches[0].match_state != MATCH_KNOWN:
        raise RuntimeError(f"recipe {recipe_id} did not round-trip as one known_match")
    return matches[0].recipe


def _located_teaching_item_sample(connection: sqlite3.Connection) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT recipe_id, item_id, zone_id, map_id
        FROM (
            SELECT ti.recipe_id, ti.item_id, s.zone_id,
                   COALESCE(s.map_id, z.map_id) AS map_id, 1 AS path_order
            FROM recipe_teaching_items AS ti
            JOIN creature_loot AS l ON l.item_id = ti.item_id
            JOIN creature_spawns AS s ON s.creature_id = l.creature_id
            LEFT JOIN zones AS z ON z.zone_id = s.zone_id
            WHERE ti.item_id IS NOT NULL AND s.zone_id IS NOT NULL
              AND COALESCE(s.map_id, z.map_id) IS NOT NULL

            UNION ALL

            SELECT ti.recipe_id, ti.item_id, s.zone_id,
                   COALESCE(s.map_id, z.map_id) AS map_id, 2 AS path_order
            FROM recipe_teaching_items AS ti
            JOIN gameobject_loot AS l ON l.item_id = ti.item_id
            JOIN gameobject_spawns AS s ON s.gameobject_id = l.gameobject_id
            LEFT JOIN zones AS z ON z.zone_id = s.zone_id
            WHERE ti.item_id IS NOT NULL AND s.zone_id IS NOT NULL
              AND COALESCE(s.map_id, z.map_id) IS NOT NULL

            UNION ALL

            SELECT ti.recipe_id, ti.item_id, s.zone_id,
                   COALESCE(s.map_id, z.map_id) AS map_id, 3 AS path_order
            FROM recipe_teaching_items AS ti
            JOIN vendor_items AS v ON v.item_id = ti.item_id
            JOIN creature_spawns AS s ON s.creature_id = v.vendor_creature_id
            LEFT JOIN zones AS z ON z.zone_id = s.zone_id
            WHERE ti.item_id IS NOT NULL AND s.zone_id IS NOT NULL
              AND COALESCE(s.map_id, z.map_id) IS NOT NULL
        )
        ORDER BY recipe_id, item_id, path_order, zone_id, map_id
        LIMIT 1
        """
    ).fetchone()


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
        recipe_count = int(connection.execute("SELECT COUNT(*) FROM recipes").fetchone()[0])
        if recipe_count <= 0:
            raise RuntimeError("expected non-empty canonical recipe identity surface")

        identity_sample = _one(
            connection,
            """
            SELECT rsl.recipe_id, rsl.skill_line_id, rsl.required_skill_value,
                   ro.native_item_id AS output_item_id
            FROM recipe_skill_lines AS rsl
            JOIN recipe_outputs AS ro ON ro.recipe_id = rsl.recipe_id
            WHERE ro.item_id IS NOT NULL
            ORDER BY rsl.recipe_id, rsl.skill_line_ability_id, ro.effect_index
            LIMIT 1
            """,
        )
        identity_recipe_id = int(identity_sample["recipe_id"])
        identity_page = query_recipes(
            connection,
            recipe_id=identity_recipe_id,
            skill_line_id=int(identity_sample["skill_line_id"]),
            min_required_skill=int(identity_sample["required_skill_value"]),
            max_required_skill=int(identity_sample["required_skill_value"]),
            output_item_id=int(identity_sample["output_item_id"]),
            limit=10,
        )
        if [result.recipe["recipe_id"] for result in identity_page.results] != [identity_recipe_id]:
            raise RuntimeError("recipe identity/skill/output sample did not round-trip")
        if identity_page.results[0].match_state != MATCH_KNOWN:
            raise RuntimeError("known recipe identity/skill/output sample was not known_match")

        multi_reagent_sample = _one(
            connection,
            """
            SELECT recipe_id, COUNT(*) AS reagent_count
            FROM recipe_reagents
            GROUP BY recipe_id
            HAVING COUNT(*) >= 2
            ORDER BY recipe_id
            LIMIT 1
            """,
        )
        multi_reagent_recipe_id = int(multi_reagent_sample["recipe_id"])
        expected_reagents = [
            (int(row["reagent_index"]), int(row["native_item_id"]), int(row["required_quantity"]))
            for row in connection.execute(
                """
                SELECT reagent_index, native_item_id, required_quantity
                FROM recipe_reagents
                WHERE recipe_id = ?
                ORDER BY reagent_index
                """,
                (multi_reagent_recipe_id,),
            ).fetchall()
        ]
        multi_detail = _recipe_detail(connection, multi_reagent_recipe_id)
        observed_reagents = [
            (row["reagent_index"], row["native_item_id"], row["required_quantity"])
            for row in multi_detail["reagents"]
        ]
        if observed_reagents != expected_reagents:
            raise RuntimeError("multi-reagent recipe lost slot identity or exact quantity")

        teaching_sample = _one(
            connection,
            """
            SELECT recipe_id, native_item_id, item_id
            FROM recipe_teaching_items
            ORDER BY recipe_id, native_item_id, item_spell_slot, acquisition_spell_id
            LIMIT 1
            """,
        )
        teaching_recipe_id = int(teaching_sample["recipe_id"])
        teaching_native_item_id = int(teaching_sample["native_item_id"])
        teaching_detail = _recipe_detail(connection, teaching_recipe_id)
        teaching_rows = [
            row
            for row in teaching_detail["learning"]["teaching_items"]
            if row["native_item_id"] == teaching_native_item_id
        ]
        if not teaching_rows:
            raise RuntimeError("representative teaching item disappeared from recipe detail")
        if teaching_rows[0]["provenance"] is None:
            raise RuntimeError("representative teaching item lost selected proof provenance")

        located_teaching = _located_teaching_item_sample(connection)
        located_teaching_recipe_id: int | None = None
        located_teaching_item_id: int | None = None
        if located_teaching is not None:
            located_teaching_recipe_id = int(located_teaching["recipe_id"])
            located_teaching_item_id = int(located_teaching["item_id"])
            geo_page = query_recipes(
                connection,
                recipe_id=located_teaching_recipe_id,
                teaching_zone_id=int(located_teaching["zone_id"]),
                teaching_map_id=int(located_teaching["map_id"]),
                limit=10,
            )
            if [result.recipe["recipe_id"] for result in geo_page.results] != [
                located_teaching_recipe_id
            ]:
                raise RuntimeError("known teaching-item acquisition geography did not round-trip")
            matching_teaching = [
                row
                for row in geo_page.results[0].recipe["learning"]["teaching_items"]
                if row["item_id"] == located_teaching_item_id
            ]
            if (
                not matching_teaching
                or not matching_teaching[0]["acquisition_composition"]["sources"]
            ):
                raise RuntimeError("known teaching-item P7 acquisition paths were not composed")

        direct_trainer_sample = _one(
            connection,
            """
            SELECT ts.recipe_id, ts.native_trainer_entry, ts.creature_id, s.zone_id,
                   COALESCE(s.map_id, z.map_id) AS map_id
            FROM recipe_trainer_sources AS ts
            JOIN creature_spawns AS s ON s.creature_id = ts.creature_id
            LEFT JOIN zones AS z ON z.zone_id = s.zone_id
            WHERE ts.trainer_kind = 'direct' AND ts.creature_id IS NOT NULL
              AND s.zone_id IS NOT NULL AND COALESCE(s.map_id, z.map_id) IS NOT NULL
            ORDER BY ts.recipe_id, ts.native_trainer_entry, s.spawn_key
            LIMIT 1
            """,
        )
        direct_trainer_recipe_id = int(direct_trainer_sample["recipe_id"])
        direct_trainer_entry = int(direct_trainer_sample["native_trainer_entry"])
        trainer_geo_page = query_recipes(
            connection,
            recipe_id=direct_trainer_recipe_id,
            trainer_zone_id=int(direct_trainer_sample["zone_id"]),
            trainer_map_id=int(direct_trainer_sample["map_id"]),
            limit=10,
        )
        if [result.recipe["recipe_id"] for result in trainer_geo_page.results] != [
            direct_trainer_recipe_id
        ]:
            raise RuntimeError("known direct-trainer geography did not round-trip")
        direct_rows = [
            row
            for row in trainer_geo_page.results[0].recipe["learning"]["trainers"]
            if row["native_trainer_entry"] == direct_trainer_entry
            and row["trainer_kind"] == "direct"
        ]
        if not direct_rows or not direct_rows[0]["locations"]:
            raise RuntimeError("direct trainer lost known P1 geography")
        for field in (
            "spell_cost",
            "required_skill_value",
            "required_character_level",
            "acquisition_spell_id",
            "learning_proof_kind",
        ):
            if field not in direct_rows[0]:
                raise RuntimeError(f"direct trainer lost P4-T04 field: {field}")

        template_trainer_sample = _one(
            connection,
            """
            SELECT recipe_id, native_trainer_entry, trainer_template_id
            FROM recipe_trainer_sources
            WHERE trainer_kind = 'template'
            ORDER BY recipe_id, native_trainer_entry, acquisition_spell_id
            LIMIT 1
            """,
        )
        template_trainer_recipe_id = int(template_trainer_sample["recipe_id"])
        template_entry = int(template_trainer_sample["native_trainer_entry"])
        template_detail = _recipe_detail(connection, template_trainer_recipe_id)
        template_rows = [
            row
            for row in template_detail["learning"]["trainers"]
            if row["native_trainer_entry"] == template_entry and row["trainer_kind"] == "template"
        ]
        if not template_rows or template_rows[0]["trainer_template_id"] is None:
            raise RuntimeError("template-expanded trainer semantics were not retained")

        quest_sample = _one(
            connection,
            """
            SELECT recipe_id, native_quest_id, quest_id
            FROM recipe_quest_learning_sources
            WHERE quest_id IS NOT NULL
            ORDER BY recipe_id, native_quest_id, acquisition_spell_id
            LIMIT 1
            """,
        )
        quest_recipe_id = int(quest_sample["recipe_id"])
        quest_id = int(quest_sample["quest_id"])
        quest_detail = _recipe_detail(connection, quest_recipe_id)
        quest_rows = [
            row
            for row in quest_detail["learning"]["quest_reward_spells"]
            if row["native_quest_id"] == quest_id
        ]
        if not quest_rows or quest_rows[0]["quest_context"] is None:
            raise RuntimeError("resolved quest learning source did not compose P7-T03 context")
        if quest_rows[0]["provenance"] is None:
            raise RuntimeError("quest learning source lost selected proof provenance")

        unresolved = connection.execute(
            """
            SELECT 'teaching_item' AS source_kind, recipe_id, native_item_id AS native_id
            FROM recipe_teaching_items
            WHERE item_id IS NULL
            UNION ALL
            SELECT 'trainer', recipe_id, native_trainer_entry
            FROM recipe_trainer_sources
            WHERE creature_id IS NULL
            ORDER BY recipe_id, source_kind, native_id
            LIMIT 1
            """
        ).fetchone()
        if unresolved is None:
            raise RuntimeError("expected validated P4-T04 baseline to retain an unresolved source")
        unresolved_recipe_id = int(unresolved["recipe_id"])
        unresolved_native_id = int(unresolved["native_id"])
        unresolved_kind = str(unresolved["source_kind"])
        unresolved_detail = _recipe_detail(connection, unresolved_recipe_id)
        if unresolved_kind == "teaching_item":
            unresolved_rows = [
                row
                for row in unresolved_detail["learning"]["teaching_items"]
                if row["native_item_id"] == unresolved_native_id
            ]
        else:
            unresolved_rows = [
                row
                for row in unresolved_detail["learning"]["trainers"]
                if row["native_trainer_entry"] == unresolved_native_id
            ]
        if not unresolved_rows or unresolved_rows[0]["resolved"] is not False:
            raise RuntimeError(
                "unresolved P4 learning target disappeared or was fabricated as resolved"
            )

        deterministic_a = recipe_query_page_to_dict(
            query_recipes(connection, recipe_id=identity_recipe_id, limit=10)
        )
        deterministic_b = recipe_query_page_to_dict(
            query_recipes(connection, recipe_id=identity_recipe_id, limit=10)
        )
        if json.dumps(deterministic_a, sort_keys=True) != json.dumps(
            deterministic_b, sort_keys=True
        ):
            raise RuntimeError("repeated representative recipe query is not deterministic")

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
        "recipe_identities": recipe_count,
        "identity_skill_output_sample_recipe_id": identity_recipe_id,
        "multi_reagent_sample_recipe_id": multi_reagent_recipe_id,
        "teaching_item_sample_recipe_id": teaching_recipe_id,
        "teaching_item_sample_native_item_id": teaching_native_item_id,
        "located_teaching_item_sample_recipe_id": located_teaching_recipe_id,
        "located_teaching_item_sample_item_id": located_teaching_item_id,
        "located_direct_trainer_sample_recipe_id": direct_trainer_recipe_id,
        "located_direct_trainer_sample_entry": direct_trainer_entry,
        "template_trainer_sample_recipe_id": template_trainer_recipe_id,
        "template_trainer_sample_entry": template_entry,
        "quest_learning_sample_recipe_id": quest_recipe_id,
        "quest_learning_sample_quest_id": quest_id,
        "unresolved_learning_sample_recipe_id": unresolved_recipe_id,
        "unresolved_learning_sample_kind": unresolved_kind,
        "unresolved_learning_sample_native_id": unresolved_native_id,
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
    print("P7_T04_LOCAL_VALIDATION_OK")
    for key, value in result.items():
        if isinstance(value, bool):
            rendered = str(value).lower()
        else:
            rendered = value
        print(f"{key}={rendered}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
