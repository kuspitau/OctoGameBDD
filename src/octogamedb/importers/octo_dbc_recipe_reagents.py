"""Canonical P4-T03 recipe reagent importer from the direct Octo Spell.dbc.

P4-T03 extends the already validated P4-T02 recipe identities.  It therefore
requires the exact same three-file Octo DBC revision as the successful
``octo-dbc-recipes/4`` identity import and refuses cross-revision refreshes.
The raw Spell.dbc reagent arrays are source truth for this bounded slice:
positive Reagent[0..7] item IDs are preserved with the exact corresponding
ReagentCount[0..7] value and native slot index.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from octogamedb.db import record_relation_observation, select_canonical_observation
from octogamedb.importers.summary import ImportSummary

OCTO_DBC_SOURCE_KEY = "octo-client-dbc"
IDENTITY_IMPORTER_VERSION = "octo-dbc-recipes/4"
IMPORTER_VERSION = "octo-dbc-recipe-reagents/1"
SELECTION_POLICY = "octo-client-dbc-recipe-reagents"
_REQUIRED_FILES = ("Spell.dbc", "SkillLine.dbc", "SkillLineAbility.dbc")
_HEADER = struct.Struct("<4sIIII")
_REAGENT_FIRST = 42
_REAGENT_COUNT_FIRST = 50
_REAGENT_SLOTS = 8
_LAYOUTS: dict[str, tuple[tuple[int, int], ...]] = {
    "Spell.dbc": ((176, 704), (173, 692)),
    "SkillLine.dbc": ((22, 88),),
    "SkillLineAbility.dbc": ((15, 60),),
}


class RecipeReagentDbcError(ValueError):
    """Raised when P4-T03 cannot consume the source without guessing."""


@dataclass(frozen=True)
class DbcLayout:
    filename: str
    record_count: int
    field_count: int
    record_size: int
    string_size: int


@dataclass(frozen=True)
class DbcRecipeReagent:
    reagent_index: int
    native_item_id: int
    required_quantity: int


@dataclass(frozen=True)
class DbcSpellReagents:
    spell_id: int
    reagents: tuple[DbcRecipeReagent, ...]
    ignored_negative_reagent_indices: tuple[int, ...]


@dataclass(frozen=True)
class OctoDbcRecipeReagentSlice:
    spells: tuple[DbcSpellReagents, ...]
    layouts: tuple[DbcLayout, ...]


@dataclass(frozen=True)
class _DbcTable:
    path: Path
    record_count: int
    field_count: int
    record_size: int
    string_size: int
    records: bytes

    @classmethod
    def load(cls, path: Path) -> _DbcTable:
        try:
            allowed = _LAYOUTS[path.name]
        except KeyError as exc:  # pragma: no cover - internal guard
            raise RecipeReagentDbcError(f"no reviewed P4-T03 layout for {path.name}") from exc
        try:
            data = path.read_bytes()
        except FileNotFoundError as exc:
            raise RecipeReagentDbcError(f"required DBC file not found: {path}") from exc
        if len(data) < _HEADER.size:
            raise RecipeReagentDbcError(f"{path.name}: file is shorter than the WDBC header")
        magic, record_count, field_count, record_size, string_size = _HEADER.unpack_from(data)
        if magic != b"WDBC":
            raise RecipeReagentDbcError(f"{path.name}: expected WDBC magic, got {magic!r}")
        if (field_count, record_size) not in allowed:
            reviewed = ", ".join(f"{fields}/{size}" for fields, size in allowed)
            raise RecipeReagentDbcError(
                f"{path.name}: unsupported DBC layout {field_count}/{record_size}; "
                f"reviewed layouts are {reviewed}"
            )
        records_size = record_count * record_size
        expected = _HEADER.size + records_size + string_size
        if len(data) != expected:
            raise RecipeReagentDbcError(
                f"{path.name}: header declares {expected} bytes, file has {len(data)}"
            )
        return cls(
            path=path,
            record_count=record_count,
            field_count=field_count,
            record_size=record_size,
            string_size=string_size,
            records=data[_HEADER.size : _HEADER.size + records_size],
        )

    @property
    def layout(self) -> DbcLayout:
        return DbcLayout(
            filename=self.path.name,
            record_count=self.record_count,
            field_count=self.field_count,
            record_size=self.record_size,
            string_size=self.string_size,
        )

    def _offset(self, row: int, field: int) -> int:
        if not 0 <= row < self.record_count or not 0 <= field < self.field_count:
            raise RecipeReagentDbcError(
                f"{self.path.name}: invalid row/field access {row}/{field}"
            )
        return row * self.record_size + field * 4

    def uint32(self, row: int, field: int) -> int:
        return struct.unpack_from("<I", self.records, self._offset(row, field))[0]

    def int32(self, row: int, field: int) -> int:
        return struct.unpack_from("<i", self.records, self._offset(row, field))[0]


def compute_octodbc_recipe_reagent_revision(source_root: str | Path) -> str:
    """Use the exact same deterministic three-file revision algorithm as P4-T02."""

    root = Path(source_root)
    digest = hashlib.sha256()
    for filename in _REQUIRED_FILES:
        path = root / filename
        try:
            content = path.read_bytes()
        except FileNotFoundError as exc:
            raise RecipeReagentDbcError(f"required DBC file not found: {path}") from exc
        digest.update(filename.encode("ascii"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).digest())
    return f"sha256:{digest.hexdigest()}"


def inspect_octodbc_recipe_reagent_layouts(source_root: str | Path) -> tuple[DbcLayout, ...]:
    root = Path(source_root)
    return tuple(_DbcTable.load(root / filename).layout for filename in _REQUIRED_FILES)


def load_octodbc_recipe_reagents(source_root: str | Path) -> OctoDbcRecipeReagentSlice:
    """Parse Spell.dbc reagent slots while validating the complete P4 DBC source envelope."""

    root = Path(source_root)
    spell_table = _DbcTable.load(root / "Spell.dbc")
    other_layouts = tuple(
        _DbcTable.load(root / filename).layout for filename in _REQUIRED_FILES[1:]
    )
    spells: list[DbcSpellReagents] = []
    seen_ids: set[int] = set()
    for row in range(spell_table.record_count):
        spell_id = spell_table.uint32(row, 0)
        if spell_id <= 0:
            raise RecipeReagentDbcError(f"Spell.dbc: invalid native spell ID {spell_id}")
        if spell_id in seen_ids:
            raise RecipeReagentDbcError(f"Spell.dbc: duplicate native spell ID {spell_id}")
        seen_ids.add(spell_id)
        reagents: list[DbcRecipeReagent] = []
        negative_indices: list[int] = []
        for reagent_index in range(_REAGENT_SLOTS):
            native_item_id = spell_table.int32(row, _REAGENT_FIRST + reagent_index)
            required_quantity = spell_table.uint32(
                row, _REAGENT_COUNT_FIRST + reagent_index
            )
            if native_item_id == 0:
                continue
            if native_item_id < 0:
                negative_indices.append(reagent_index)
                continue
            reagents.append(
                DbcRecipeReagent(
                    reagent_index=reagent_index,
                    native_item_id=native_item_id,
                    required_quantity=required_quantity,
                )
            )
        spells.append(
            DbcSpellReagents(
                spell_id=spell_id,
                reagents=tuple(reagents),
                ignored_negative_reagent_indices=tuple(negative_indices),
            )
        )
    spells.sort(key=lambda row: row.spell_id)
    return OctoDbcRecipeReagentSlice(
        spells=tuple(spells),
        layouts=(spell_table.layout, *other_layouts),
    )


def _ensure_source(connection: sqlite3.Connection, source_path: str) -> int:
    connection.execute(
        """
        INSERT INTO data_sources(source_key, display_name, source_kind, source_path)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(source_key) DO UPDATE SET
            display_name = excluded.display_name,
            source_kind = excluded.source_kind,
            source_path = excluded.source_path,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (OCTO_DBC_SOURCE_KEY, "Octo client DBC", "client-dbc", source_path),
    )
    row = connection.execute(
        "SELECT id FROM data_sources WHERE source_key = ?", (OCTO_DBC_SOURCE_KEY,)
    ).fetchone()
    if row is None:  # pragma: no cover
        raise RuntimeError("Octo DBC source registration failed")
    return int(row["id"])


def _latest_successful_revision(
    connection: sqlite3.Connection, importer_version: str
) -> str | None:
    row = connection.execute(
        """
        SELECT ib.source_revision
        FROM import_batches AS ib
        JOIN data_sources AS ds ON ds.id = ib.source_id
        WHERE ds.source_key = ?
          AND ib.importer_version = ?
          AND ib.status = 'succeeded'
        ORDER BY ib.id DESC
        LIMIT 1
        """,
        (OCTO_DBC_SOURCE_KEY, importer_version),
    ).fetchone()
    if row is None or row["source_revision"] is None:
        return None
    value = str(row["source_revision"]).strip()
    return value or None


def _selected_relation(
    connection: sqlite3.Connection,
    observation_id: int,
) -> tuple[dict[str, Any], bool]:
    row = connection.execute(
        "SELECT observation_group_id, value_json FROM source_observations WHERE id = ?",
        (observation_id,),
    ).fetchone()
    if row is None:  # pragma: no cover
        raise RuntimeError(f"observation {observation_id} disappeared")
    group_id = int(row["observation_group_id"])
    current = connection.execute(
        """
        SELECT cs.observation_id, cs.selection_policy, so.value_json
        FROM canonical_selections AS cs
        JOIN source_observations AS so ON so.id = cs.observation_id
        WHERE cs.observation_group_id = ?
        """,
        (group_id,),
    ).fetchone()
    protected = current is not None and current["selection_policy"] != SELECTION_POLICY
    if current is None or not protected:
        if (
            current is None
            or int(current["observation_id"]) != observation_id
            or current["selection_policy"] != SELECTION_POLICY
        ):
            select_canonical_observation(
                connection,
                observation_group_id=group_id,
                observation_id=observation_id,
                selection_policy=SELECTION_POLICY,
                selection_reason=(
                    "Direct Octo Spell.dbc reagent-slot evidence is the managed P4-T03 "
                    "selection; selections using another policy are preserved."
                ),
            )
        value = json.loads(str(row["value_json"]))
        if not isinstance(value, dict):
            raise RecipeReagentDbcError("selected recipe reagent relation is not an object")
        return value, False
    value = json.loads(str(current["value_json"]))
    if not isinstance(value, dict):
        raise RecipeReagentDbcError("protected recipe reagent relation is not an object")
    return value, True


def _relation_target(value: dict[str, Any]) -> int:
    target = value.get("target")
    if not isinstance(target, dict) or target.get("kind") != "item":
        raise RecipeReagentDbcError("selected recipe reagent relation must target item")
    try:
        native_item_id = int(str(target["key"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise RecipeReagentDbcError("selected recipe reagent has invalid item target") from exc
    if native_item_id <= 0:
        raise RecipeReagentDbcError("selected recipe reagent item target must be positive")
    return native_item_id


def _relation_attributes(value: dict[str, Any]) -> tuple[int, int]:
    attrs = value.get("attributes")
    if not isinstance(attrs, dict):
        raise RecipeReagentDbcError("selected recipe reagent attributes must be an object")
    try:
        reagent_index = int(attrs["reagent_index"])
        required_quantity = int(attrs["required_quantity"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RecipeReagentDbcError("selected recipe reagent attributes are invalid") from exc
    if not 0 <= reagent_index < _REAGENT_SLOTS or required_quantity < 0:
        raise RecipeReagentDbcError("selected recipe reagent slot/quantity is invalid")
    return reagent_index, required_quantity


def import_octodbc_recipe_reagents(
    connection: sqlite3.Connection,
    *,
    source_root: str | Path,
    source_revision: str | None = None,
) -> ImportSummary:
    """Materialize the bounded P4-T03 reagent slice for existing P4-T02 recipes."""

    root = Path(source_root)
    source = load_octodbc_recipe_reagents(root)
    computed_revision = compute_octodbc_recipe_reagent_revision(root)
    if source_revision is not None:
        requested_revision = source_revision.strip()
        if not requested_revision:
            raise ValueError("source_revision must not be blank")
        if requested_revision != computed_revision:
            raise RecipeReagentDbcError(
                "provided P4-T03 source_revision does not match the configured DBC bytes: "
                f"provided={requested_revision}, computed={computed_revision}"
            )
    revision = computed_revision

    identity_revision = _latest_successful_revision(connection, IDENTITY_IMPORTER_VERSION)
    if identity_revision is None:
        raise RecipeReagentDbcError(
            "P4-T03 requires a successful octo-dbc-recipes/4 identity import first"
        )
    if identity_revision != revision:
        raise RecipeReagentDbcError(
            "P4-T03 DBC revision differs from the P4-T02 recipe-identity revision: "
            f"identity={identity_revision}, reagent={revision}"
        )
    previous_reagent_revision = _latest_successful_revision(connection, IMPORTER_VERSION)
    if previous_reagent_revision is not None and previous_reagent_revision != revision:
        raise RecipeReagentDbcError(
            "P4-T03 cross-revision reagent reconciliation is not implemented; "
            "validate a deliberate refresh task before importing a new DBC revision"
        )

    recipe_rows = connection.execute(
        "SELECT recipe_id, crafting_spell_id FROM recipes ORDER BY recipe_id"
    ).fetchall()
    if not recipe_rows:
        raise RecipeReagentDbcError("P4-T03 requires canonical P4-T02 recipes")
    recipe_ids: set[int] = set()
    for row in recipe_rows:
        recipe_id = int(row["recipe_id"])
        crafting_spell_id = int(row["crafting_spell_id"])
        if recipe_id != crafting_spell_id:
            raise RecipeReagentDbcError(
                f"recipe {recipe_id} is not anchored to its crafting spell ID"
            )
        recipe_ids.add(recipe_id)

    by_spell = {row.spell_id: row for row in source.spells}
    missing_recipe_spells = sorted(recipe_ids - set(by_spell))
    if missing_recipe_spells:
        preview = ", ".join(str(value) for value in missing_recipe_spells[:20])
        raise RecipeReagentDbcError(
            "canonical recipes are missing from the matching Spell.dbc revision: " + preview
        )

    source_id = _ensure_source(connection, str(root))
    rows_read = len(source.spells)
    batch_id = int(
        connection.execute(
            """
            INSERT INTO import_batches(
                source_id, source_revision, status, importer_version, rows_read
            )
            VALUES (?, ?, 'running', ?, ?)
            """,
            (source_id, revision, IMPORTER_VERSION, rows_read),
        ).lastrowid
    )
    canonical_item_ids = {
        int(row[0]) for row in connection.execute("SELECT item_id FROM items").fetchall()
    }
    inserted = 0
    updated = 0
    protected_count = 0
    unresolved: list[dict[str, int]] = []
    zero_quantity: list[dict[str, int]] = []
    ignored_negative: list[dict[str, int]] = []
    materialized_count = 0

    for recipe_id in sorted(recipe_ids):
        spell = by_spell[recipe_id]
        ignored_negative.extend(
            {"recipe_id": recipe_id, "reagent_index": index}
            for index in spell.ignored_negative_reagent_indices
        )
        for reagent in spell.reagents:
            observation_id = record_relation_observation(
                connection,
                subject_kind="recipe",
                subject_key=recipe_id,
                fact_key="reagent",
                import_batch_id=batch_id,
                target_kind="item",
                target_key=reagent.native_item_id,
                relation_instance_key=f"slot:{reagent.reagent_index}",
                attributes={
                    "reagent_index": reagent.reagent_index,
                    "required_quantity": reagent.required_quantity,
                    "quantity_semantics": "spell_reagent_count",
                },
                source_record_type="Spell.dbc",
                raw_identifier=f"{recipe_id}:reagent:{reagent.reagent_index}",
                authority_tier=1,
            )
            selected, protected = _selected_relation(connection, observation_id)
            protected_count += int(protected)
            native_item_id = _relation_target(selected)
            reagent_index, required_quantity = _relation_attributes(selected)
            if reagent_index != reagent.reagent_index:
                raise RecipeReagentDbcError(
                    "selected recipe reagent changed the source slot identity for "
                    f"recipe {recipe_id}: {reagent.reagent_index} -> {reagent_index}"
                )
            item_id = native_item_id if native_item_id in canonical_item_ids else None
            if item_id is None:
                unresolved.append(
                    {
                        "recipe_id": recipe_id,
                        "reagent_index": reagent_index,
                        "native_item_id": native_item_id,
                        "required_quantity": required_quantity,
                    }
                )
            if required_quantity == 0:
                zero_quantity.append(
                    {
                        "recipe_id": recipe_id,
                        "reagent_index": reagent_index,
                        "native_item_id": native_item_id,
                    }
                )

            existing = connection.execute(
                """
                SELECT native_item_id, item_id, required_quantity
                FROM recipe_reagents
                WHERE recipe_id = ? AND reagent_index = ?
                """,
                (recipe_id, reagent_index),
            ).fetchone()
            expected = (native_item_id, item_id, required_quantity)
            if existing is None:
                inserted += 1
            elif tuple(existing) != expected:
                updated += 1
            connection.execute(
                """
                INSERT INTO recipe_reagents(
                    recipe_id, reagent_index, native_item_id, item_id, required_quantity
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(recipe_id, reagent_index) DO UPDATE SET
                    native_item_id = excluded.native_item_id,
                    item_id = excluded.item_id,
                    required_quantity = excluded.required_quantity
                """,
                (recipe_id, reagent_index, native_item_id, item_id, required_quantity),
            )
            materialized_count += 1

    warning_count = len(unresolved) + len(zero_quantity) + len(ignored_negative)
    details = {
        "dbc_layouts": {
            layout.filename: {
                "record_count": layout.record_count,
                "field_count": layout.field_count,
                "record_size": layout.record_size,
                "string_size": layout.string_size,
            }
            for layout in source.layouts
        },
        "source_completeness": {
            "Spell.dbc": "complete_file_for_exact_revision",
            "identity_revision_match_required": True,
            "destructive_cross_revision_absence_reconciliation": False,
        },
        "identity_importer_version": IDENTITY_IMPORTER_VERSION,
        "identity_source_revision": identity_revision,
        "spell_count": len(source.spells),
        "canonical_recipe_count": len(recipe_ids),
        "recipe_reagent_count": materialized_count,
        "unresolved_reagent_count": len(unresolved),
        "unresolved_reagents": sorted(
            unresolved,
            key=lambda row: (row["recipe_id"], row["reagent_index"]),
        ),
        "zero_quantity_reagent_count": len(zero_quantity),
        "zero_quantity_reagents": sorted(
            zero_quantity,
            key=lambda row: (row["recipe_id"], row["reagent_index"]),
        ),
        "ignored_negative_reagent_slot_count": len(ignored_negative),
        "ignored_negative_reagent_slots": sorted(
            ignored_negative,
            key=lambda row: (row["recipe_id"], row["reagent_index"]),
        ),
        "protected_selection_count": protected_count,
        "reagent_slot_count": _REAGENT_SLOTS,
        "reagent_slots_scanned_independently": True,
    }
    connection.execute(
        """
        UPDATE import_batches
        SET finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            status = 'succeeded',
            rows_accepted = ?,
            rows_skipped = ?,
            rows_inserted = ?,
            rows_updated = ?,
            warning_count = ?,
            error_count = 0,
            details_json = ?
        WHERE id = ?
        """,
        (
            len(recipe_ids),
            rows_read - len(recipe_ids),
            inserted,
            updated,
            warning_count,
            json.dumps(details, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            batch_id,
        ),
    )
    return ImportSummary(
        source_key=OCTO_DBC_SOURCE_KEY,
        source_revision=revision,
        status="succeeded",
        rows_read=rows_read,
        rows_accepted=len(recipe_ids),
        rows_skipped=rows_read - len(recipe_ids),
        rows_inserted=inserted,
        rows_updated=updated,
        warning_count=warning_count,
        error_count=0,
        details=details,
    )
