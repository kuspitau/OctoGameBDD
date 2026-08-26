"""Canonical P4 spell / skill-line / recipe identity importer from Octo client DBCs.

The parser deliberately supports only explicitly reviewed Vanilla WDBC shapes.  P4-T02 must
fail closed if the configured Octo client exposes any other layout instead of guessing field
positions.  Recipe identity follows D-034: a native spell becomes a recipe only when the same
spell has at least one SkillLineAbility membership and at least one CREATE_ITEM effect.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from octogamedb.db import (
    record_relation_observation,
    record_scalar_observation,
    select_canonical_observation,
)
from octogamedb.importers.summary import ImportSummary

OCTO_DBC_SOURCE_KEY = "octo-client-dbc"
IMPORTER_VERSION = "octo-dbc-recipes/4"
SELECTION_POLICY = "octo-client-dbc-recipe-identity"
SPELL_EFFECT_CREATE_ITEM = 24
_REQUIRED_FILES = ("Spell.dbc", "SkillLine.dbc", "SkillLineAbility.dbc")
_HEADER = struct.Struct("<4sIIII")

# Explicitly reviewed Vanilla layouts.  The 176/704 Spell form is the P4-T01
# pinned Tortoise source shape.  Level-2 validation on the actual Octo client
# proved the standard Vanilla 1.12 173/692 Spell form; its physical field
# positions are independently documented by wow_dbc's Vanilla table reader.
# SkillLine/SkillLineAbility remain the pinned DBCfmt.h forms until local
# validation proves otherwise.
_LAYOUTS: dict[str, tuple[tuple[int, int], ...]] = {
    "Spell.dbc": ((176, 176 * 4), (173, 173 * 4)),
    "SkillLine.dbc": ((22, 22 * 4),),
    "SkillLineAbility.dbc": ((15, 15 * 4),),
}


@dataclass(frozen=True)
class _SpellFieldLayout:
    effect_first: int
    effect_die_sides_first: int
    effect_base_points_first: int
    effect_item_type_first: int
    name_first: int
    rank_first: int


_SPELL_FIELD_LAYOUTS: dict[tuple[int, int], _SpellFieldLayout] = {
    (176, 704): _SpellFieldLayout(
        effect_first=61,
        effect_die_sides_first=64,
        effect_base_points_first=76,
        effect_item_type_first=106,
        name_first=123,
        rank_first=132,
    ),
    (173, 692): _SpellFieldLayout(
        effect_first=60,
        effect_die_sides_first=63,
        effect_base_points_first=75,
        effect_item_type_first=102,
        name_first=120,
        rank_first=129,
    ),
}


class RecipeDbcParseError(ValueError):
    """Raised when the P4 DBC source cannot be interpreted without guessing."""


@dataclass(frozen=True)
class DbcLayout:
    filename: str
    record_count: int
    field_count: int
    record_size: int
    string_size: int


@dataclass(frozen=True)
class DbcSpellEffect:
    effect_index: int
    effect_id: int
    effect_die_sides: int
    effect_base_points: int
    item_type_id: int | None


@dataclass(frozen=True)
class DbcSpell:
    spell_id: int
    name: str | None
    rank_text: str | None
    effects: tuple[DbcSpellEffect, ...]


@dataclass(frozen=True)
class DbcSkillLine:
    skill_line_id: int
    name: str | None


@dataclass(frozen=True)
class DbcSkillLineAbility:
    record_id: int
    skill_line_id: int
    spell_id: int
    required_skill_value: int
    forward_spell_id: int | None
    max_value: int
    min_value: int


@dataclass(frozen=True)
class OctoDbcRecipeSlice:
    spells: tuple[DbcSpell, ...]
    skill_lines: tuple[DbcSkillLine, ...]
    skill_line_abilities: tuple[DbcSkillLineAbility, ...]
    layouts: tuple[DbcLayout, ...]


@dataclass(frozen=True)
class _StrictDbcTable:
    path: Path
    record_count: int
    field_count: int
    record_size: int
    string_size: int
    records: bytes
    strings: bytes

    @classmethod
    def load(cls, path: Path) -> _StrictDbcTable:
        try:
            allowed_layouts = _LAYOUTS[path.name]
        except KeyError as exc:  # pragma: no cover - internal programming guard
            raise RecipeDbcParseError(f"no reviewed P4 layout for {path.name}") from exc
        try:
            data = path.read_bytes()
        except FileNotFoundError as exc:
            raise RecipeDbcParseError(f"required DBC file not found: {path}") from exc
        if len(data) < _HEADER.size:
            raise RecipeDbcParseError(f"{path.name}: file is shorter than the WDBC header")

        magic, record_count, field_count, record_size, string_size = _HEADER.unpack_from(data)
        if magic != b"WDBC":
            raise RecipeDbcParseError(f"{path.name}: expected WDBC magic, got {magic!r}")
        if (field_count, record_size) not in allowed_layouts:
            reviewed = ", ".join(
                f"(field_count={fields}, record_size={size})"
                for fields, size in allowed_layouts
            )
            raise RecipeDbcParseError(
                f"{path.name}: unsupported DBC layout "
                f"(field_count={field_count}, record_size={record_size}); "
                f"reviewed P4-T02 layouts are {reviewed}"
            )

        records_size = record_count * record_size
        expected_file_size = _HEADER.size + records_size + string_size
        if len(data) != expected_file_size:
            raise RecipeDbcParseError(
                f"{path.name}: header declares {expected_file_size} bytes, file has {len(data)}"
            )
        records_start = _HEADER.size
        strings_start = records_start + records_size
        return cls(
            path=path,
            record_count=record_count,
            field_count=field_count,
            record_size=record_size,
            string_size=string_size,
            records=data[records_start:strings_start],
            strings=data[strings_start:],
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

    def _field_offset(self, record_index: int, field_index: int) -> int:
        if not 0 <= record_index < self.record_count:
            raise IndexError(record_index)
        if not 0 <= field_index < self.field_count:
            raise RecipeDbcParseError(
                f"{self.path.name}: field {field_index} outside 0..{self.field_count - 1}"
            )
        return record_index * self.record_size + field_index * 4

    def uint32(self, record_index: int, field_index: int) -> int:
        offset = self._field_offset(record_index, field_index)
        return struct.unpack_from("<I", self.records, offset)[0]

    def int32(self, record_index: int, field_index: int) -> int:
        offset = self._field_offset(record_index, field_index)
        return struct.unpack_from("<i", self.records, offset)[0]

    def string(self, record_index: int, field_index: int) -> str:
        offset = self.uint32(record_index, field_index)
        if offset == 0:
            return ""
        if offset >= self.string_size:
            raise RecipeDbcParseError(
                f"{self.path.name}: string offset {offset} outside string block "
                f"({self.string_size} bytes)"
            )
        end = self.strings.find(b"\0", offset)
        if end < 0:
            raise RecipeDbcParseError(
                f"{self.path.name}: unterminated string at offset {offset}"
            )
        raw = self.strings[offset:end]
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("cp1252")

    def localized_string(self, record_index: int, first_field: int) -> str | None:
        for field_index in range(first_field, first_field + 8):
            value = self.string(record_index, field_index).strip()
            if value:
                return value
        return None


def _optional_positive(value: int) -> int | None:
    return None if value == 0 else value


def load_octodbc_recipe_slice(source_root: str | Path) -> OctoDbcRecipeSlice:
    """Parse the exact P4-T02 Spell/SkillLine/SkillLineAbility WDBC slice."""

    root = Path(source_root)
    spell_table = _StrictDbcTable.load(root / "Spell.dbc")
    skill_line_table = _StrictDbcTable.load(root / "SkillLine.dbc")
    ability_table = _StrictDbcTable.load(root / "SkillLineAbility.dbc")

    spell_fields = _SPELL_FIELD_LAYOUTS.get(
        (spell_table.field_count, spell_table.record_size)
    )
    if spell_fields is None:  # pragma: no cover - guarded by _StrictDbcTable.load
        raise RecipeDbcParseError(
            f"Spell.dbc: no field map for layout "
            f"{spell_table.field_count}/{spell_table.record_size}"
        )

    spells: list[DbcSpell] = []
    seen_spell_ids: set[int] = set()
    for index in range(spell_table.record_count):
        spell_id = spell_table.uint32(index, 0)
        if spell_id <= 0:
            raise RecipeDbcParseError(f"Spell.dbc: invalid native spell ID {spell_id}")
        if spell_id in seen_spell_ids:
            raise RecipeDbcParseError(f"Spell.dbc: duplicate native spell ID {spell_id}")
        seen_spell_ids.add(spell_id)
        effects: list[DbcSpellEffect] = []
        for effect_index in range(3):
            item_type = spell_table.uint32(
                index, spell_fields.effect_item_type_first + effect_index
            )
            effects.append(
                DbcSpellEffect(
                    effect_index=effect_index,
                    effect_id=spell_table.uint32(
                        index, spell_fields.effect_first + effect_index
                    ),
                    effect_die_sides=spell_table.int32(
                        index, spell_fields.effect_die_sides_first + effect_index
                    ),
                    effect_base_points=spell_table.int32(
                        index, spell_fields.effect_base_points_first + effect_index
                    ),
                    item_type_id=_optional_positive(item_type),
                )
            )
        spells.append(
            DbcSpell(
                spell_id=spell_id,
                name=spell_table.localized_string(index, spell_fields.name_first),
                rank_text=spell_table.localized_string(index, spell_fields.rank_first),
                effects=tuple(effects),
            )
        )

    skill_lines: list[DbcSkillLine] = []
    seen_skill_ids: set[int] = set()
    for index in range(skill_line_table.record_count):
        skill_id = skill_line_table.uint32(index, 0)
        if skill_id <= 0:
            raise RecipeDbcParseError(f"SkillLine.dbc: invalid native skill-line ID {skill_id}")
        if skill_id in seen_skill_ids:
            raise RecipeDbcParseError(f"SkillLine.dbc: duplicate native skill-line ID {skill_id}")
        seen_skill_ids.add(skill_id)
        skill_lines.append(
            DbcSkillLine(
                skill_line_id=skill_id,
                name=skill_line_table.localized_string(index, 3),
            )
        )

    abilities: list[DbcSkillLineAbility] = []
    seen_ability_ids: set[int] = set()
    for index in range(ability_table.record_count):
        record_id = ability_table.uint32(index, 0)
        if record_id <= 0:
            raise RecipeDbcParseError(
                f"SkillLineAbility.dbc: invalid native row ID {record_id}"
            )
        if record_id in seen_ability_ids:
            raise RecipeDbcParseError(
                f"SkillLineAbility.dbc: duplicate native row ID {record_id}"
            )
        seen_ability_ids.add(record_id)
        skill_id = ability_table.uint32(index, 1)
        spell_id = ability_table.uint32(index, 2)
        if skill_id <= 0 or spell_id <= 0:
            raise RecipeDbcParseError(
                f"SkillLineAbility.dbc row {record_id}: invalid skill/spell relation "
                f"({skill_id}, {spell_id})"
            )
        abilities.append(
            DbcSkillLineAbility(
                record_id=record_id,
                skill_line_id=skill_id,
                spell_id=spell_id,
                required_skill_value=ability_table.uint32(index, 7),
                forward_spell_id=_optional_positive(ability_table.uint32(index, 8)),
                max_value=ability_table.uint32(index, 10),
                min_value=ability_table.uint32(index, 11),
            )
        )

    # Real Octo Level-2 data can contain SkillLineAbility rows whose spell target is absent
    # from the same Spell.dbc revision. Such rows cannot qualify a P4-T02 recipe because the
    # crafting spell identity itself is unavailable. Preserve/report them as source anomalies
    # instead of fabricating a Spell identity or invalidating unrelated recipe rows.

    # Real Octo Level-2 data can contain SkillLineAbility rows whose skill-line target is
    # absent from the same SkillLine.dbc revision.  That cross-file orphan is not enough to
    # invalidate the entire P4 recipe slice: unrelated class/pet/backport rows are outside this
    # bounded task.  Recipe-qualified orphan memberships are still rejected before any SQLite
    # import because P4-T02 must not fabricate a canonical SkillLine identity.

    spells.sort(key=lambda row: row.spell_id)
    skill_lines.sort(key=lambda row: row.skill_line_id)
    abilities.sort(key=lambda row: row.record_id)
    return OctoDbcRecipeSlice(
        spells=tuple(spells),
        skill_lines=tuple(skill_lines),
        skill_line_abilities=tuple(abilities),
        layouts=(spell_table.layout, skill_line_table.layout, ability_table.layout),
    )


def inspect_octodbc_recipe_layouts(source_root: str | Path) -> tuple[DbcLayout, ...]:
    """Validate and return exact P4 DBC layout metadata without mutating SQLite."""

    return load_octodbc_recipe_slice(source_root).layouts


def compute_octodbc_recipe_revision(source_root: str | Path) -> str:
    """Hash the exact three-file P4 DBC input deterministically."""

    root = Path(source_root)
    digest = hashlib.sha256()
    for filename in _REQUIRED_FILES:
        path = root / filename
        try:
            content = path.read_bytes()
        except FileNotFoundError as exc:
            raise RecipeDbcParseError(f"required DBC file not found: {path}") from exc
        digest.update(filename.encode("ascii"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).digest())
    return f"sha256:{digest.hexdigest()}"


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
    if row is None:  # pragma: no cover - SQLite insert/select invariant
        raise RuntimeError("Octo DBC source registration failed")
    return int(row["id"])


def _selection_for_observation(
    connection: sqlite3.Connection,
    observation_id: int,
    *,
    selection_reason: str,
) -> tuple[Any, bool]:
    row = connection.execute(
        """
        SELECT so.observation_group_id, so.value_json
        FROM source_observations AS so
        WHERE so.id = ?
        """,
        (observation_id,),
    ).fetchone()
    if row is None:  # pragma: no cover - provenance helper invariant
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
                selection_reason=selection_reason,
            )
        return json.loads(str(row["value_json"])), False
    return json.loads(str(current["value_json"])), True


def _scalar_winner(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    subject_kind: str,
    subject_key: int,
    fact_key: str,
    value: Any,
    source_record_type: str,
    raw_identifier: str | int,
) -> tuple[Any, bool]:
    observation_id = record_scalar_observation(
        connection,
        subject_kind=subject_kind,
        subject_key=subject_key,
        fact_key=fact_key,
        import_batch_id=batch_id,
        value=value,
        source_record_type=source_record_type,
        raw_identifier=raw_identifier,
        authority_tier=1,
    )
    return _selection_for_observation(
        connection,
        observation_id,
        selection_reason=(
            "Direct Octo client DBC evidence is the managed P4-T02 canonical selection; "
            "an existing selection using another policy is preserved."
        ),
    )


def _relation_winner(
    connection: sqlite3.Connection,
    *,
    batch_id: int,
    subject_key: int,
    fact_key: str,
    instance_key: str,
    target_kind: str,
    target_key: int,
    attributes: dict[str, Any],
    source_record_type: str,
    raw_identifier: str | int,
) -> tuple[dict[str, Any], bool]:
    observation_id = record_relation_observation(
        connection,
        subject_kind="recipe",
        subject_key=subject_key,
        fact_key=fact_key,
        import_batch_id=batch_id,
        target_kind=target_kind,
        target_key=target_key,
        relation_instance_key=instance_key,
        attributes=attributes,
        source_record_type=source_record_type,
        raw_identifier=raw_identifier,
        authority_tier=1,
    )
    value, protected = _selection_for_observation(
        connection,
        observation_id,
        selection_reason=(
            "Direct Octo client DBC relation evidence is the managed P4-T02 canonical selection; "
            "an existing selection using another policy is preserved."
        ),
    )
    if not isinstance(value, dict):
        raise RecipeDbcParseError(f"selected {fact_key} relation is not an object")
    return value, protected


def _optional_text_winner(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RecipeDbcParseError(f"selected {field} must be a string or null")
    normalized = value.strip()
    return normalized or None


def _positive_relation_target(value: dict[str, Any], kind: str, field: str) -> int:
    target = value.get("target")
    if not isinstance(target, dict) or target.get("kind") != kind:
        raise RecipeDbcParseError(f"selected {field} relation must target {kind}")
    try:
        target_id = int(str(target["key"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise RecipeDbcParseError(f"selected {field} relation has invalid target key") from exc
    if target_id <= 0:
        raise RecipeDbcParseError(f"selected {field} relation target must be positive")
    return target_id


def _relation_attributes(value: dict[str, Any], field: str) -> dict[str, Any]:
    attributes = value.get("attributes", {})
    if not isinstance(attributes, dict):
        raise RecipeDbcParseError(f"selected {field} relation attributes must be an object")
    return attributes


def _changed(row: sqlite3.Row | None, expected: dict[str, Any]) -> bool:
    return row is not None and any(row[key] != value for key, value in expected.items())


def import_octodbc_recipes(
    connection: sqlite3.Connection,
    *,
    source_root: str | Path,
    source_revision: str | None = None,
) -> ImportSummary:
    """Import the bounded P4 canonical identity slice from direct Octo client DBCs."""

    root = Path(source_root)
    source = load_octodbc_recipe_slice(root)
    revision = (
        compute_octodbc_recipe_revision(root)
        if source_revision is None
        else source_revision.strip()
    )
    if not revision:
        raise ValueError("source_revision must not be blank")

    source_spell_ids = {row.spell_id for row in source.spells}
    orphan_spell_abilities = tuple(
        ability
        for ability in source.skill_line_abilities
        if ability.spell_id not in source_spell_ids
    )
    memberships_by_spell: dict[int, list[DbcSkillLineAbility]] = {}
    for ability in source.skill_line_abilities:
        if ability.spell_id not in source_spell_ids:
            continue
        memberships_by_spell.setdefault(ability.spell_id, []).append(ability)

    recipe_spells: list[
        tuple[DbcSpell, tuple[DbcSkillLineAbility, ...], tuple[DbcSpellEffect, ...]]
    ] = []
    for spell in source.spells:
        outputs = tuple(
            effect for effect in spell.effects if effect.effect_id == SPELL_EFFECT_CREATE_ITEM
        )
        memberships = tuple(memberships_by_spell.get(spell.spell_id, ()))
        if not outputs or not memberships:
            continue
        for effect in outputs:
            if effect.item_type_id is None:
                raise RecipeDbcParseError(
                    f"Spell.dbc spell {spell.spell_id} CREATE_ITEM effect {effect.effect_index} "
                    "has no EffectItemType"
                )
        recipe_spells.append((spell, memberships, outputs))

    source_skill_ids = {row.skill_line_id for row in source.skill_lines}
    orphan_skill_line_abilities = tuple(
        ability
        for ability in source.skill_line_abilities
        if ability.skill_line_id not in source_skill_ids
    )
    recipe_spell_ids = {spell.spell_id for spell, _memberships, _outputs in recipe_spells}
    orphan_recipe_memberships = tuple(
        ability
        for ability in orphan_skill_line_abilities
        if ability.spell_id in recipe_spell_ids
    )
    if orphan_recipe_memberships:
        preview = ", ".join(
            f"row {ability.record_id}: spell {ability.spell_id} -> skill {ability.skill_line_id}"
            for ability in orphan_recipe_memberships[:12]
        )
        suffix = "" if len(orphan_recipe_memberships) <= 12 else ", ..."
        raise RecipeDbcParseError(
            "recipe-qualified SkillLineAbility rows reference missing SkillLine identities; "
            "P4-T02 will not fabricate canonical skill lines: " + preview + suffix
        )

    source_id = _ensure_source(connection, str(root))
    rows_read = len(source.spells) + len(source.skill_lines) + len(source.skill_line_abilities)
    batch_cursor = connection.execute(
        """
        INSERT INTO import_batches(source_id, source_revision, status, importer_version, rows_read)
        VALUES (?, ?, 'running', ?, ?)
        """,
        (source_id, revision, IMPORTER_VERSION, rows_read),
    )
    batch_id = int(batch_cursor.lastrowid)
    inserted = 0
    updated = 0
    protected_selections = 0

    resolved_spells: list[tuple[int, str | None, str | None]] = []
    for spell in source.spells:
        name_value, protected = _scalar_winner(
            connection,
            batch_id=batch_id,
            subject_kind="spell",
            subject_key=spell.spell_id,
            fact_key="name",
            value=spell.name,
            source_record_type="Spell.dbc",
            raw_identifier=spell.spell_id,
        )
        protected_selections += int(protected)
        rank_value, protected = _scalar_winner(
            connection,
            batch_id=batch_id,
            subject_kind="spell",
            subject_key=spell.spell_id,
            fact_key="rank_text",
            value=spell.rank_text,
            source_record_type="Spell.dbc",
            raw_identifier=spell.spell_id,
        )
        protected_selections += int(protected)
        resolved_spells.append(
            (
                spell.spell_id,
                _optional_text_winner(name_value, "spell.name"),
                _optional_text_winner(rank_value, "spell.rank_text"),
            )
        )

    resolved_skills: list[tuple[int, str | None]] = []
    for skill in source.skill_lines:
        name_value, protected = _scalar_winner(
            connection,
            batch_id=batch_id,
            subject_kind="skill_line",
            subject_key=skill.skill_line_id,
            fact_key="name",
            value=skill.name,
            source_record_type="SkillLine.dbc",
            raw_identifier=skill.skill_line_id,
        )
        protected_selections += int(protected)
        resolved_skills.append(
            (skill.skill_line_id, _optional_text_winner(name_value, "skill_line.name"))
        )

    for spell_id, name, rank_text in resolved_spells:
        existing = connection.execute(
            "SELECT name, rank_text FROM spells WHERE spell_id = ?", (spell_id,)
        ).fetchone()
        expected = {"name": name, "rank_text": rank_text}
        if existing is None:
            inserted += 1
        elif _changed(existing, expected):
            updated += 1
        connection.execute(
            """
            INSERT INTO spells(spell_id, name, rank_text)
            VALUES (?, ?, ?)
            ON CONFLICT(spell_id) DO UPDATE SET
                name = excluded.name,
                rank_text = excluded.rank_text
            """,
            (spell_id, name, rank_text),
        )

    for skill_line_id, name in resolved_skills:
        existing = connection.execute(
            "SELECT name FROM skill_lines WHERE skill_line_id = ?", (skill_line_id,)
        ).fetchone()
        expected = {"name": name}
        if existing is None:
            inserted += 1
        elif _changed(existing, expected):
            updated += 1
        connection.execute(
            """
            INSERT INTO skill_lines(skill_line_id, name)
            VALUES (?, ?)
            ON CONFLICT(skill_line_id) DO UPDATE SET name = excluded.name
            """,
            (skill_line_id, name),
        )

    canonical_item_ids = {
        int(row[0]) for row in connection.execute("SELECT item_id FROM items").fetchall()
    }
    unresolved_outputs: list[dict[str, int]] = []
    recipe_ids: list[int] = []

    for spell, memberships, outputs in recipe_spells:
        presence_value, protected = _scalar_winner(
            connection,
            batch_id=batch_id,
            subject_kind="recipe",
            subject_key=spell.spell_id,
            fact_key="presence",
            value=True,
            source_record_type="Spell.dbc+SkillLineAbility.dbc",
            raw_identifier=spell.spell_id,
        )
        protected_selections += int(protected)
        if not isinstance(presence_value, bool):
            raise RecipeDbcParseError("selected recipe.presence must be boolean")
        if not presence_value:
            continue

        existing_recipe = connection.execute(
            "SELECT crafting_spell_id FROM recipes WHERE recipe_id = ?", (spell.spell_id,)
        ).fetchone()
        if existing_recipe is None:
            inserted += 1
        elif int(existing_recipe["crafting_spell_id"]) != spell.spell_id:
            updated += 1
        connection.execute(
            """
            INSERT INTO recipes(recipe_id, crafting_spell_id)
            VALUES (?, ?)
            ON CONFLICT(recipe_id) DO UPDATE SET crafting_spell_id = excluded.crafting_spell_id
            """,
            (spell.spell_id, spell.spell_id),
        )
        recipe_ids.append(spell.spell_id)

        for membership in memberships:
            relation, protected = _relation_winner(
                connection,
                batch_id=batch_id,
                subject_key=spell.spell_id,
                fact_key="skill_line_membership",
                instance_key=f"skill-line-ability:{membership.record_id}",
                target_kind="skill_line",
                target_key=membership.skill_line_id,
                attributes={
                    "skill_line_ability_id": membership.record_id,
                    "required_skill_value": membership.required_skill_value,
                    "forward_spell_id": membership.forward_spell_id,
                    "min_value": membership.min_value,
                    "max_value": membership.max_value,
                },
                source_record_type="SkillLineAbility.dbc",
                raw_identifier=membership.record_id,
            )
            protected_selections += int(protected)
            skill_line_id = _positive_relation_target(
                relation, "skill_line", "recipe.skill_line_membership"
            )
            attrs = _relation_attributes(relation, "recipe.skill_line_membership")
            ability_id = int(attrs.get("skill_line_ability_id", membership.record_id))
            required_value = int(attrs.get("required_skill_value", 0))
            if ability_id <= 0 or required_value < 0:
                raise RecipeDbcParseError(
                    "selected recipe.skill_line_membership attributes are invalid"
                )
            if skill_line_id not in {row.skill_line_id for row in source.skill_lines}:
                existing_skill = connection.execute(
                    "SELECT 1 FROM skill_lines WHERE skill_line_id = ?", (skill_line_id,)
                ).fetchone()
                if existing_skill is None:
                    raise RecipeDbcParseError(
                        f"selected recipe skill line {skill_line_id} has no canonical identity"
                    )
            existing = connection.execute(
                """
                SELECT skill_line_id, required_skill_value
                FROM recipe_skill_lines
                WHERE recipe_id = ? AND skill_line_ability_id = ?
                """,
                (spell.spell_id, ability_id),
            ).fetchone()
            expected = {
                "skill_line_id": skill_line_id,
                "required_skill_value": required_value,
            }
            if existing is None:
                inserted += 1
            elif _changed(existing, expected):
                updated += 1
            connection.execute(
                """
                INSERT INTO recipe_skill_lines(
                    recipe_id, skill_line_ability_id, skill_line_id, required_skill_value
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(recipe_id, skill_line_ability_id) DO UPDATE SET
                    skill_line_id = excluded.skill_line_id,
                    required_skill_value = excluded.required_skill_value
                """,
                (spell.spell_id, ability_id, skill_line_id, required_value),
            )

        for effect in outputs:
            assert effect.item_type_id is not None
            relation, protected = _relation_winner(
                connection,
                batch_id=batch_id,
                subject_key=spell.spell_id,
                fact_key="crafted_output",
                instance_key=f"effect:{effect.effect_index}",
                target_kind="item",
                target_key=effect.item_type_id,
                attributes={
                    "effect_index": effect.effect_index,
                    "effect_id": effect.effect_id,
                    "effect_base_points": effect.effect_base_points,
                    "effect_die_sides": effect.effect_die_sides,
                    "quantity_semantics": "calculated_spell_effect",
                },
                source_record_type="Spell.dbc",
                raw_identifier=f"{spell.spell_id}:effect:{effect.effect_index}",
            )
            protected_selections += int(protected)
            native_item_id = _positive_relation_target(relation, "item", "recipe.crafted_output")
            attrs = _relation_attributes(relation, "recipe.crafted_output")
            effect_index = int(attrs.get("effect_index", effect.effect_index))
            if effect_index < 0:
                raise RecipeDbcParseError("selected recipe.crafted_output effect_index is invalid")
            item_id = native_item_id if native_item_id in canonical_item_ids else None
            if item_id is None:
                unresolved_outputs.append(
                    {
                        "recipe_id": spell.spell_id,
                        "effect_index": effect_index,
                        "native_item_id": native_item_id,
                    }
                )
            existing = connection.execute(
                """
                SELECT native_item_id, item_id
                FROM recipe_outputs
                WHERE recipe_id = ? AND effect_index = ?
                """,
                (spell.spell_id, effect_index),
            ).fetchone()
            expected = {"native_item_id": native_item_id, "item_id": item_id}
            if existing is None:
                inserted += 1
            elif _changed(existing, expected):
                updated += 1
            connection.execute(
                """
                INSERT INTO recipe_outputs(recipe_id, effect_index, native_item_id, item_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(recipe_id, effect_index) DO UPDATE SET
                    native_item_id = excluded.native_item_id,
                    item_id = excluded.item_id
                """,
                (spell.spell_id, effect_index, native_item_id, item_id),
            )

    layouts = {
        layout.filename: {
            "record_count": layout.record_count,
            "field_count": layout.field_count,
            "record_size": layout.record_size,
            "string_size": layout.string_size,
        }
        for layout in source.layouts
    }
    details = {
        "dbc_layouts": layouts,
        "source_completeness": {
            "Spell.dbc": "complete_file_for_exact_revision",
            "SkillLine.dbc": "complete_file_for_exact_revision",
            "SkillLineAbility.dbc": "complete_file_for_exact_revision",
            "destructive_absence_reconciliation": False,
        },
        "spell_count": len(source.spells),
        "skill_line_count": len(source.skill_lines),
        "skill_line_ability_count": len(source.skill_line_abilities),
        "orphan_spell_skill_line_ability_count": len(orphan_spell_abilities),
        "orphan_spell_ids": sorted({ability.spell_id for ability in orphan_spell_abilities}),
        "orphan_spell_skill_line_ability_preview": [
            {
                "record_id": ability.record_id,
                "skill_line_id": ability.skill_line_id,
                "spell_id": ability.spell_id,
            }
            for ability in orphan_spell_abilities[:50]
        ],
        "orphan_skill_line_ability_count": len(orphan_skill_line_abilities),
        "orphan_skill_line_ids": sorted(
            {ability.skill_line_id for ability in orphan_skill_line_abilities}
        ),
        "orphan_skill_line_ability_preview": [
            {
                "record_id": ability.record_id,
                "skill_line_id": ability.skill_line_id,
                "spell_id": ability.spell_id,
            }
            for ability in orphan_skill_line_abilities[:50]
        ],
        "orphan_recipe_skill_line_membership_count": 0,
        "recipe_count": len(recipe_ids),
        "recipe_ids": sorted(recipe_ids),
        "unresolved_output_count": len(unresolved_outputs),
        "unresolved_outputs": sorted(
            unresolved_outputs,
            key=lambda row: (row["recipe_id"], row["effect_index"], row["native_item_id"]),
        ),
        "protected_selection_count": protected_selections,
        "fixed_output_quantity_materialized": False,
    }
    connection.execute(
        """
        UPDATE import_batches
        SET
            finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            status = 'succeeded',
            rows_accepted = ?,
            rows_skipped = 0,
            rows_inserted = ?,
            rows_updated = ?,
            warning_count = ?,
            error_count = 0,
            details_json = ?
        WHERE id = ?
        """,
        (
            rows_read,
            inserted,
            updated,
            len(unresolved_outputs),
            json.dumps(details, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            batch_id,
        ),
    )
    return ImportSummary(
        source_key=OCTO_DBC_SOURCE_KEY,
        source_revision=revision,
        status="succeeded",
        rows_read=rows_read,
        rows_accepted=rows_read,
        rows_skipped=0,
        rows_inserted=inserted,
        rows_updated=updated,
        warning_count=len(unresolved_outputs),
        error_count=0,
        details=details,
    )
