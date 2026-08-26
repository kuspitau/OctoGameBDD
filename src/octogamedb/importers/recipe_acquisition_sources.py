"""P4-T04 recipe learning/acquisition importer.

The canonical recipe remains the crafting spell identity established by P4-T02.
This module materializes only acquisition relations that are *proven* by a
cross-source join. Tortoise world SQL identifies a trainer offer, item spell slot,
or quest reward acquisition spell. The wrapper -> learned recipe edge is then
proven preferentially by the exact Octo Spell.dbc revision used by P4-T02
(``LEARN_SPELL``); when that exact-client edge is absent, the pinned Tortoise
``spell_learn_spell`` server dependency may provide lower-authority fallback
evidence under D-035.

Vendor/loot/quest availability of a teaching item is deliberately not copied into
recipe source tables. It remains derivable by joining ``recipe_teaching_items``
with the already canonical item-acquisition relations, preserving D-008/D-019.

The Tortoise repository is a close server-lineage reference rather than exact
Octo production truth. Level-2 replay requires the exact pinned Git revision and a
clean SQL input tree. The importer reports source coverage and refuses unsupported
relevant SQL mutations instead of guessing their effect.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import struct
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from octogamedb.db import record_relation_observation, select_canonical_observation
from octogamedb.importers.octo_dbc_recipe_reagents import (
    compute_octodbc_recipe_reagent_revision,
    inspect_octodbc_recipe_reagent_layouts,
)
from octogamedb.importers.summary import ImportSummary

IDENTITY_IMPORTER_VERSION = "octo-dbc-recipes/4"
IMPORTER_VERSION = "recipe-acquisition-sources/2"
SELECTION_POLICY = "recipe-acquisition-cross-source-v1"
SOURCE_KEY = "tortoise-world+octo-dbc-recipe-acquisition"
TORTOISE_PINNED_SEMANTIC_REVISION = "61a8269151721f6467eddb05e7bed37704d0fc0b"
SPELL_EFFECT_LEARN_SPELL = 36
_REQUIRED_DBC = ("Spell.dbc", "SkillLine.dbc", "SkillLineAbility.dbc")
_WORLD_UPDATES = Path("sql/database_updates/world")
_BASE_FILES = {
    "npc_trainer": Path("sql/base/tw_world_npc_trainer.sql"),
    "npc_trainer_template": Path("sql/base/tw_world_npc_trainer_template.sql"),
    "quest_template": Path("sql/base/tw_world_quest_template.sql"),
    "item_template": Path("sql/base/tw_world_item_template.sql"),
    "creature_template": Path("sql/base/tw_world_creature_template.sql"),
    "spell_learn_spell": Path("sql/base/tw_world_spell_learn_spell.sql"),
}
_HEADER = struct.Struct("<4sIIII")
_SPELL_LAYOUTS = {
    (176, 704): (61, 112),
    (173, 692): (60, 108),
}
_ITEM_SLOTS = 5


class RecipeAcquisitionError(ValueError):
    """Raised when P4-T04 cannot prove acquisition semantics without guessing."""


@dataclass(frozen=True)
class LearnEffect:
    acquisition_spell_id: int
    effect_index: int
    learned_spell_id: int


@dataclass(frozen=True)
class TrainerOffer:
    trainer_kind: str
    native_trainer_entry: int
    trainer_template_id: int | None
    acquisition_spell_id: int
    spell_cost: int
    required_skill_line_id: int | None
    required_skill_value: int
    required_character_level: int
    source_record: str


@dataclass(frozen=True)
class ItemSpellSlot:
    native_item_id: int
    slot: int
    acquisition_spell_id: int
    spell_trigger: int | None
    spell_charges: int | None
    source_record: str


@dataclass(frozen=True)
class QuestRewardSpell:
    native_quest_id: int
    reward_spell_field: str
    acquisition_spell_id: int
    source_record: str


@dataclass(frozen=True)
class ServerLearnLink:
    acquisition_spell_id: int
    learned_spell_id: int
    active: int
    source_record: str


@dataclass(frozen=True)
class ProvenLearning:
    acquisition_spell_id: int
    learned_spell_id: int
    proof_kind: str
    learn_effect_index: int | None
    dbc_effect_indices: tuple[int, ...]
    server_learn_active: int | None
    server_source_records: tuple[str, ...]


@dataclass(frozen=True)
class TortoiseAcquisitionSlice:
    trainer_offers: tuple[TrainerOffer, ...]
    item_spell_slots: tuple[ItemSpellSlot, ...]
    quest_reward_spells: tuple[QuestRewardSpell, ...]
    server_learn_links: tuple[ServerLearnLink, ...]
    unmapped_trainer_template_ids: tuple[int, ...]
    source_revision: str
    git_revision: str | None
    input_count: int


@dataclass(frozen=True)
class _TableSpec:
    table: str
    key_fields: tuple[str, ...]
    selected_fields: tuple[str, ...]
    relevance_fields: tuple[str, ...]


@dataclass(frozen=True)
class _ScalarPredicate:
    field: str
    operator: str
    values: tuple[int, ...] = ()


@dataclass(frozen=True)
class _TupleInPredicate:
    fields: tuple[str, ...]
    values: tuple[tuple[int, ...], ...]


_WherePredicate = _ScalarPredicate | _TupleInPredicate


_TABLE_SPECS = {
    "npc_trainer": _TableSpec(
        "npc_trainer",
        ("entry", "spell"),
        ("entry", "spell", "spellcost", "reqskill", "reqskillvalue", "reqlevel"),
        ("spell",),
    ),
    "npc_trainer_template": _TableSpec(
        "npc_trainer_template",
        ("entry", "spell"),
        ("entry", "spell", "spellcost", "reqskill", "reqskillvalue", "reqlevel"),
        ("spell",),
    ),
    "quest_template": _TableSpec(
        "quest_template",
        ("entry",),
        ("entry", "rewspell", "rewspellcast"),
        ("rewspell", "rewspellcast"),
    ),
    "item_template": _TableSpec(
        "item_template",
        ("entry",),
        (
            "entry",
            *tuple(f"spellid_{slot}" for slot in range(1, _ITEM_SLOTS + 1)),
            *tuple(f"spelltrigger_{slot}" for slot in range(1, _ITEM_SLOTS + 1)),
            *tuple(f"spellcharges_{slot}" for slot in range(1, _ITEM_SLOTS + 1)),
        ),
        tuple(f"spellid_{slot}" for slot in range(1, _ITEM_SLOTS + 1)),
    ),
    "creature_template": _TableSpec(
        "creature_template",
        ("entry",),
        ("entry", "trainer_id"),
        ("trainer_id",),
    ),
    "spell_learn_spell": _TableSpec(
        "spell_learn_spell",
        ("entry", "spellid"),
        ("entry", "spellid", "active"),
        ("spellid",),
    ),
}


def _identifier(value: str) -> str:
    value = value.strip()
    if "." in value:
        value = value.rsplit(".", 1)[-1]
    if value.startswith("`") and value.endswith("`"):
        value = value[1:-1]
    return value.lower()


def _strip_comments_and_split(text: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(text):
        char = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if quote:
            current.append(char)
            if char == "\\" and quote in {"'", '"'} and i + 1 < len(text):
                i += 1
                current.append(text[i])
            elif char == quote:
                if i + 1 < len(text) and text[i + 1] == quote and quote in {"'", '"'}:
                    i += 1
                    current.append(text[i])
                else:
                    quote = None
            i += 1
            continue
        if char in {"'", '"', "`"}:
            quote = char
            current.append(char)
            i += 1
            continue
        if char == "/" and nxt == "*":
            end = text.find("*/", i + 2)
            if end < 0:
                raise RecipeAcquisitionError("unterminated SQL block comment")
            current.append(" ")
            i = end + 2
            continue
        if char == "#":
            end = text.find("\n", i + 1)
            if end < 0:
                break
            current.append("\n")
            i = end + 1
            continue
        if char == "-" and nxt == "-":
            third = text[i + 2] if i + 2 < len(text) else ""
            if not third or third.isspace():
                end = text.find("\n", i + 2)
                if end < 0:
                    break
                current.append("\n")
                i = end + 1
                continue
        if char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            i += 1
            continue
        current.append(char)
        i += 1
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def _split_top_level(text: str, delimiter: str = ",") -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    depth = 0
    i = 0
    while i < len(text):
        char = text[i]
        if quote:
            current.append(char)
            if char == "\\" and quote in {"'", '"'} and i + 1 < len(text):
                i += 1
                current.append(text[i])
            elif char == quote:
                if i + 1 < len(text) and text[i + 1] == quote and quote in {"'", '"'}:
                    i += 1
                    current.append(text[i])
                else:
                    quote = None
            i += 1
            continue
        if char in {"'", '"', "`"}:
            quote = char
            current.append(char)
        elif char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise RecipeAcquisitionError("unbalanced SQL parentheses")
            current.append(char)
        elif char == delimiter and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        i += 1
    if quote or depth != 0:
        raise RecipeAcquisitionError("unterminated quote or unbalanced SQL parentheses")
    parts.append("".join(current).strip())
    return parts


def _extract_tuple_groups(text: str) -> tuple[list[str], str]:
    groups: list[str] = []
    i = 0
    while i < len(text):
        while i < len(text) and (text[i].isspace() or text[i] == ","):
            i += 1
        if i >= len(text):
            return groups, ""
        if text[i] != "(":
            return groups, text[i:].strip()
        start = i + 1
        depth = 1
        quote: str | None = None
        i += 1
        while i < len(text) and depth:
            char = text[i]
            if quote:
                if char == "\\" and quote in {"'", '"'} and i + 1 < len(text):
                    i += 2
                    continue
                if char == quote:
                    if i + 1 < len(text) and text[i + 1] == quote and quote in {"'", '"'}:
                        i += 2
                        continue
                    quote = None
                i += 1
                continue
            if char in {"'", '"'}:
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    groups.append(text[start:i])
                    i += 1
                    break
            i += 1
        if depth:
            raise RecipeAcquisitionError("unterminated SQL VALUES tuple")
    return groups, ""


def _parse_int(token: str, field: str) -> int | None:
    value = token.strip()
    if value.upper() == "NULL":
        return None
    if re.fullmatch(r"[+-]?\d+", value):
        return int(value)
    # MariaDB dumps/updates occasionally serialize integer columns as integral
    # decimal literals (for example RewSpellCast = 0.0). Accept only a zero
    # fractional part; never round a genuinely fractional value.
    decimal = re.fullmatch(r"([+-]?\d+)\.(0+)", value)
    if decimal:
        return int(decimal.group(1))
    raise RecipeAcquisitionError(
        f"{field} requires an integer/NULL literal, got {value[:80]!r}"
    )


def _table_pattern(table: str) -> str:
    return rf"(?:`?\w+`?\.)?`?{re.escape(table)}`?"


def _create_columns(statement: str, table: str) -> list[str] | None:
    match = re.match(
        rf"^CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+{_table_pattern(table)}\s*\((.*)\)\s*.*$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    columns: list[str] = []
    for definition in _split_top_level(match.group(1)):
        stripped = definition.strip()
        if not stripped:
            continue
        first = stripped.split(None, 1)[0]
        normalized = _identifier(first)
        if normalized.upper() in {
            "PRIMARY",
            "UNIQUE",
            "KEY",
            "INDEX",
            "CONSTRAINT",
            "FOREIGN",
            "CHECK",
        }:
            continue
        if normalized not in {
            "primary",
            "unique",
            "key",
            "index",
            "constraint",
            "foreign",
            "check",
        }:
            columns.append(normalized)
    return columns


def _row_selected(
    columns: Sequence[str], values_text: str, selected: set[str]
) -> dict[str, int | None]:
    tokens = _split_top_level(values_text)
    if len(tokens) != len(columns):
        raise RecipeAcquisitionError(
            f"INSERT has {len(tokens)} values for {len(columns)} columns"
        )
    row: dict[str, int | None] = {}
    for column, token in zip(columns, tokens, strict=True):
        name = _identifier(column)
        if name in selected:
            row[name] = _parse_int(token, name)
    return row


def _parse_insert(
    statement: str, spec: _TableSpec, schema_columns: Sequence[str] | None
) -> tuple[str, list[dict[str, int | None]]] | None:
    match = re.match(
        rf"^(INSERT(?:\s+IGNORE)?|REPLACE)\s+INTO\s+{_table_pattern(spec.table)}\s*(.*)$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    operation = re.sub(r"\s+", " ", match.group(1).upper())
    rest = match.group(2).lstrip()
    columns: list[str] | None = None
    if rest.startswith("("):
        groups, _ = _extract_tuple_groups(rest)
        if not groups:
            raise RecipeAcquisitionError(f"{spec.table}: malformed INSERT column list")
        columns = [_identifier(value) for value in _split_top_level(groups[0])]
        depth = 0
        quote: str | None = None
        end_index = None
        for index, char in enumerate(rest):
            if quote:
                if char == quote:
                    quote = None
                continue
            if char in {"'", '"', "`"}:
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    end_index = index + 1
                    break
        if end_index is None:
            raise RecipeAcquisitionError(f"{spec.table}: malformed INSERT column list")
        rest = rest[end_index:].lstrip()
    if not re.match(r"^VALUES\b", rest, flags=re.IGNORECASE):
        raise RecipeAcquisitionError(
            f"{spec.table}: only INSERT/REPLACE ... VALUES is supported"
        )
    rest = re.sub(r"^VALUES\b", "", rest, count=1, flags=re.IGNORECASE).lstrip()
    tuple_groups, trailing = _extract_tuple_groups(rest)
    if not tuple_groups or trailing:
        raise RecipeAcquisitionError(
            f"{spec.table}: unsupported INSERT trailing clause {trailing[:100]!r}"
        )
    effective_columns = columns or (list(schema_columns) if schema_columns else None)
    if not effective_columns:
        raise RecipeAcquisitionError(
            f"{spec.table}: INSERT omits column names before any usable CREATE TABLE"
        )
    selected = set(spec.selected_fields)
    return operation, [_row_selected(effective_columns, group, selected) for group in tuple_groups]


def _assigns_selected_field(text: str, selected: set[str]) -> bool:
    # This is intentionally a permissive *detector*, not an assignment parser. A
    # false positive only makes us parse/fail closed; a false negative would be
    # unsafe. It lets us ignore huge text/vendor/AI updates whose WHERE clauses
    # are outside the bounded P4-T04 projection.
    return any(
        re.search(rf"(?i)(?:^|,)\s*`?{re.escape(field)}`?\s*=", text)
        for field in selected
    )


def _parse_assignments(text: str, selected: set[str]) -> dict[str, int | None]:
    result: dict[str, int | None] = {}
    for assignment in _split_top_level(text):
        match = re.fullmatch(r"\s*(`?\w+`?)\s*=\s*(.+?)\s*", assignment, flags=re.DOTALL)
        if not match:
            raise RecipeAcquisitionError(f"unsupported assignment: {assignment[:120]!r}")
        field = _identifier(match.group(1))
        if field in selected:
            result[field] = _parse_int(match.group(2), field)
    return result


def _split_top_level_and(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    quote: str | None = None
    depth = 0
    i = 0
    while i < len(text):
        char = text[i]
        if quote:
            if char == "\\" and quote in {"'", '"'} and i + 1 < len(text):
                i += 2
                continue
            if char == quote:
                if i + 1 < len(text) and text[i + 1] == quote and quote in {"'", '"'}:
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if char in {"'", '"', "`"}:
            quote = char
            i += 1
            continue
        if char == "(":
            depth += 1
            i += 1
            continue
        if char == ")":
            depth -= 1
            if depth < 0:
                raise RecipeAcquisitionError("unbalanced SQL WHERE parentheses")
            i += 1
            continue
        if depth == 0 and text[i : i + 3].upper() == "AND":
            before = text[i - 1] if i else " "
            after = text[i + 3] if i + 3 < len(text) else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                parts.append(text[start:i].strip())
                start = i + 3
                i += 3
                continue
        i += 1
    if quote or depth != 0:
        raise RecipeAcquisitionError("unterminated quote or unbalanced SQL WHERE parentheses")
    parts.append(text[start:].strip())
    return [part for part in parts if part]


def _where_predicates(where: str, allowed: set[str]) -> tuple[_WherePredicate, ...]:
    predicates: list[_WherePredicate] = []
    for term in _split_top_level_and(where.strip()):
        tuple_in = re.fullmatch(
            r"\s*\((.*?)\)\s+IN\s*\((.*)\)\s*",
            term,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if tuple_in:
            fields = tuple(_identifier(value) for value in _split_top_level(tuple_in.group(1)))
            if not fields or any(field not in allowed for field in fields):
                bad = next((field for field in fields if field not in allowed), "<empty>")
                raise RecipeAcquisitionError(f"unsupported WHERE field {bad}")
            groups, trailing = _extract_tuple_groups(tuple_in.group(2))
            if not groups or trailing:
                raise RecipeAcquisitionError("tuple WHERE IN requires literal tuples")
            values: list[tuple[int, ...]] = []
            for group in groups:
                raw_values = _split_top_level(group)
                if len(raw_values) != len(fields):
                    raise RecipeAcquisitionError("tuple WHERE IN arity mismatch")
                parsed = tuple(_parse_int(value, "WHERE IN") for value in raw_values)
                if any(value is None for value in parsed):
                    raise RecipeAcquisitionError("tuple WHERE IN does not support NULL literals")
                values.append(tuple(int(value) for value in parsed if value is not None))
            predicates.append(_TupleInPredicate(fields, tuple(values)))
            continue

        in_match = re.fullmatch(
            r"\s*(`?\w+`?)\s+IN\s*\((.*)\)\s*",
            term,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if in_match:
            field = _identifier(in_match.group(1))
            if field not in allowed:
                raise RecipeAcquisitionError(f"unsupported WHERE field {field}")
            parsed = tuple(_parse_int(value, field) for value in _split_top_level(in_match.group(2)))
            if any(value is None for value in parsed):
                raise RecipeAcquisitionError("WHERE IN does not support NULL literals")
            predicates.append(
                _ScalarPredicate(field, "IN", tuple(int(value) for value in parsed if value is not None))
            )
            continue

        comparison = re.fullmatch(
            r"\s*(`?\w+`?)\s*(<=|>=|<>|!=|=|<|>)\s*(.+?)\s*",
            term,
            flags=re.DOTALL,
        )
        if comparison:
            field = _identifier(comparison.group(1))
            if field not in allowed:
                raise RecipeAcquisitionError(f"unsupported WHERE field {field}")
            value = _parse_int(comparison.group(3), field)
            if value is None:
                raise RecipeAcquisitionError("WHERE comparison to NULL is unsupported; use IS NULL")
            predicates.append(_ScalarPredicate(field, comparison.group(2), (value,)))
            continue

        null_match = re.fullmatch(
            r"\s*(`?\w+`?)\s+IS\s+(NOT\s+)?NULL\s*", term, flags=re.IGNORECASE
        )
        if null_match:
            field = _identifier(null_match.group(1))
            if field not in allowed:
                raise RecipeAcquisitionError(f"unsupported WHERE field {field}")
            predicates.append(_ScalarPredicate(field, "IS NOT NULL" if null_match.group(2) else "IS NULL"))
            continue
        raise RecipeAcquisitionError(f"unsupported WHERE predicate: {term[:120]!r}")
    return tuple(predicates)


def _matches(row: dict[str, int | None], predicates: Sequence[_WherePredicate]) -> bool:
    for predicate in predicates:
        if isinstance(predicate, _TupleInPredicate):
            current = tuple(row.get(field) for field in predicate.fields)
            if current not in predicate.values:
                return False
            continue
        value = row.get(predicate.field)
        if predicate.operator == "IS NULL":
            if value is not None:
                return False
            continue
        if predicate.operator == "IS NOT NULL":
            if value is None:
                return False
            continue
        if value is None:
            return False
        target = predicate.values[0] if predicate.values else None
        if predicate.operator == "IN":
            if value not in predicate.values:
                return False
        elif predicate.operator == "=" and value != target:
            return False
        elif predicate.operator in {"!=", "<>"} and value == target:
            return False
        elif predicate.operator == "<" and not value < target:
            return False
        elif predicate.operator == "<=" and not value <= target:
            return False
        elif predicate.operator == ">" and not value > target:
            return False
        elif predicate.operator == ">=" and not value >= target:
            return False
    return True


def _simple_positive_key_values(
    predicates: Sequence[_WherePredicate], field: str
) -> tuple[int, ...]:
    values: set[int] = set()
    for predicate in predicates:
        if not isinstance(predicate, _ScalarPredicate) or predicate.field != field:
            continue
        if predicate.operator == "=":
            values.add(predicate.values[0])
        elif predicate.operator == "IN":
            values.update(predicate.values)
    return tuple(sorted(value for value in values if value > 0))


def _row_key(row: dict[str, int | None], spec: _TableSpec) -> tuple[int, ...]:
    values: list[int] = []
    for field in spec.key_fields:
        value = row.get(field)
        if value is None or value <= 0:
            raise RecipeAcquisitionError(f"{spec.table}: missing/invalid key field {field}")
        values.append(int(value))
    return tuple(values)


def _row_has_relevant_payload(row: dict[str, int | None], spec: _TableSpec) -> bool:
    return any(int(row.get(field) or 0) != 0 for field in spec.relevance_fields)


def _apply_statement(
    statement: str,
    spec: _TableSpec,
    schema_columns: list[str] | None,
    rows: dict[tuple[int, ...], dict[str, int | None]],
) -> list[str] | None:
    create = _create_columns(statement, spec.table)
    if create is not None:
        return create

    if re.match(rf"^(?:INSERT|REPLACE)\b.*\b{_table_pattern(spec.table)}\b", statement, flags=re.IGNORECASE | re.DOTALL):
        parsed = _parse_insert(statement, spec, schema_columns)
        assert parsed is not None
        operation, inserted_rows = parsed
        for row in inserted_rows:
            try:
                key = _row_key(row, spec)
            except RecipeAcquisitionError:
                # Rows with no usable native key and no P4-T04 payload are inert
                # placeholders for this bounded projection. A keyless row that
                # *does* carry relevant acquisition data remains fail-closed.
                if not _row_has_relevant_payload(row, spec):
                    continue
                raise
            if operation.startswith("INSERT IGNORE") and key in rows:
                continue
            current = rows.get(key, {}) if operation.startswith("INSERT") else {}
            merged = dict(current)
            merged.update(row)
            rows[key] = merged
        return schema_columns

    update = re.match(
        rf"^UPDATE\s+{_table_pattern(spec.table)}\s+SET\s+(.+)$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if update:
        update_body = update.group(1)
        where_match = re.search(r"\s+WHERE\s+", update_body, flags=re.IGNORECASE)
        if where_match:
            set_text = update_body[: where_match.start()]
            where_text = update_body[where_match.end() :]
        else:
            set_text = update_body
            where_text = None

        selected = set(spec.selected_fields)
        # Crucial bounded-replay rule: if an UPDATE cannot alter any field P4-T04
        # reads, its predicate is irrelevant too. This safely ignores vendor/text/
        # AI maintenance without pretending we can evaluate arbitrary SQL.
        if not _assigns_selected_field(set_text, selected):
            return schema_columns

        assignments = _parse_assignments(set_text, selected)
        if not assignments:
            return schema_columns
        predicates = (
            _where_predicates(where_text, selected) if where_text is not None else ()
        )
        for old_key, row in list(rows.items()):
            if predicates and not _matches(row, predicates):
                continue
            merged = dict(row)
            merged.update(assignments)
            new_key = _row_key(merged, spec)
            if new_key != old_key:
                del rows[old_key]
            rows[new_key] = merged

        # item_template at the pinned source has an empty base dump. Permit only
        # explicit positive entry equality/IN predicates to create a bounded
        # partial item row; range predicates cannot prove which absent rows exist.
        if spec.table == "item_template" and predicates:
            for entry in _simple_positive_key_values(predicates, "entry"):
                key = (entry,)
                if key not in rows:
                    rows[key] = {"entry": entry, **assignments}
        return schema_columns

    delete = re.match(
        rf"^DELETE\s+FROM\s+{_table_pattern(spec.table)}\s+WHERE\s+(.+)$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if delete:
        predicates = _where_predicates(delete.group(1), set(spec.selected_fields))
        for key, row in list(rows.items()):
            if _matches(row, predicates):
                del rows[key]
        return schema_columns

    trunc_or_drop = re.match(
        rf"^(?:TRUNCATE\s+(?:TABLE\s+)?|DROP\s+TABLE(?:\s+IF\s+EXISTS)?\s+){_table_pattern(spec.table)}\b",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if trunc_or_drop:
        rows.clear()
        return schema_columns
    # Dump/session noise is safe to ignore. Schema mutations of a bounded table
    # are not: a changed column/default/key shape can change replay semantics, so
    # fail closed until that exact ALTER form has been reviewed.
    if re.match(r"^(?:LOCK|UNLOCK|SET|USE)\b", statement, flags=re.IGNORECASE):
        return schema_columns
    if re.match(r"^ALTER\b", statement, flags=re.IGNORECASE):
        raise RecipeAcquisitionError(
            f"{spec.table}: unsupported ALTER TABLE shape: {statement[:160]!r}"
        )
    if re.match(r"^(?:INSERT|REPLACE|UPDATE|DELETE|TRUNCATE|DROP)\b", statement, flags=re.IGNORECASE):
        raise RecipeAcquisitionError(
            f"{spec.table}: unsupported mutation shape: {statement[:160]!r}"
        )
    return schema_columns


def _statement_mentions_table(statement: str, table: str) -> bool:
    return bool(re.search(rf"\b`?{re.escape(table)}`?\b", statement, flags=re.IGNORECASE))


def _ordered_world_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for relative in _BASE_FILES.values():
        path = repo_root / relative
        if not path.is_file():
            raise RecipeAcquisitionError(f"required Tortoise SQL file not found: {path}")
        files.append(path)
    update_root = repo_root / _WORLD_UPDATES
    if not update_root.is_dir():
        raise RecipeAcquisitionError(f"Tortoise world update directory not found: {update_root}")
    files.extend(sorted(path for path in update_root.glob("*_world.sql") if path.is_file()))
    return files


def _detect_git_revision(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    value = result.stdout.strip()
    return value or None


def _relevant_git_changes(repo_root: Path) -> tuple[str, ...]:
    paths = [str(path.as_posix()) for path in _BASE_FILES.values()]
    paths.append(_WORLD_UPDATES.as_posix())
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--",
                *paths,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RecipeAcquisitionError(
            "could not verify Tortoise SQL worktree cleanliness"
        ) from exc
    return tuple(line for line in result.stdout.splitlines() if line.strip())


def _verify_pinned_tortoise_checkout(repo_root: Path) -> str | None:
    git_revision = _detect_git_revision(repo_root)
    if git_revision is None:
        # Tiny tracked fixtures used by Level-1 tests are not Git repositories.
        return None
    if git_revision != TORTOISE_PINNED_SEMANTIC_REVISION:
        raise RecipeAcquisitionError(
            "P4-T04 requires pinned Tortoise revision "
            f"{TORTOISE_PINNED_SEMANTIC_REVISION}, got {git_revision}"
        )
    changes = _relevant_git_changes(repo_root)
    if changes:
        preview = "\n".join(changes[:20])
        extra = "" if len(changes) <= 20 else f"\n... {len(changes) - 20} more"
        raise RecipeAcquisitionError(
            "P4-T04 requires a clean Tortoise SQL input tree at the pinned revision; "
            "tracked modifications or untracked world SQL would change the source bytes:\n"
            f"{preview}{extra}"
        )
    return git_revision


def _manifest_revision(repo_root: Path, files: Sequence[Path]) -> tuple[str, str | None]:
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(repo_root).as_posix()
        content = path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).digest())
    git_revision = _detect_git_revision(repo_root)
    payload = {
        "git_revision": git_revision,
        "manifest_sha256": digest.hexdigest(),
        "file_count": len(files),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")), git_revision


def _replay_tables(
    repo_root: Path, files: Sequence[Path]
) -> dict[str, dict[tuple[int, ...], dict[str, int | None]]]:
    states: dict[str, dict[tuple[int, ...], dict[str, int | None]]] = {
        table: {} for table in _TABLE_SPECS
    }
    schemas: dict[str, list[str] | None] = {table: None for table in _TABLE_SPECS}
    unsupported: dict[str, list[str]] = {table: [] for table in _TABLE_SPECS}

    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        statements = _strip_comments_and_split(text)
        for index, statement in enumerate(statements, start=1):
            for table, spec in _TABLE_SPECS.items():
                if not _statement_mentions_table(statement, table):
                    continue
                try:
                    before = schemas[table]
                    schemas[table] = _apply_statement(
                        statement, spec, schemas[table], states[table]
                    )
                    if schemas[table] is None:
                        schemas[table] = before
                except RecipeAcquisitionError as exc:
                    unsupported[table].append(
                        f"{path.relative_to(repo_root)}#{index}: {exc}"
                    )

    failures = {table: values for table, values in unsupported.items() if values}
    if failures:
        chunks: list[str] = []
        for table in sorted(failures):
            values = failures[table]
            preview = "\n".join(values[:12])
            extra = "" if len(values) <= 12 else f"\n... {len(values) - 12} more"
            chunks.append(f"[{table}]\n{preview}{extra}")
        raise RecipeAcquisitionError(
            "unsupported relevant Tortoise SQL mutation(s); refusing to guess:\n"
            + "\n".join(chunks)
        )
    return states


def load_tortoise_acquisition_slice(repo_root: str | Path) -> TortoiseAcquisitionSlice:
    """Replay the bounded acquisition fields from configured Tortoise world SQL."""

    root = Path(repo_root)
    verified_git_revision = _verify_pinned_tortoise_checkout(root)
    files = _ordered_world_files(root)
    source_revision, git_revision = _manifest_revision(root, files)
    if verified_git_revision is not None and git_revision != verified_git_revision:
        raise RecipeAcquisitionError("Tortoise Git revision changed during source manifesting")

    states = _replay_tables(root, files)
    direct_rows = states["npc_trainer"]
    template_rows = states["npc_trainer_template"]
    quest_rows = states["quest_template"]
    item_rows = states["item_template"]
    creature_rows = states["creature_template"]
    server_learn_rows = states["spell_learn_spell"]

    creatures_by_template: dict[int, list[int]] = {}
    for (creature_entry,), row in sorted(creature_rows.items()):
        trainer_id = int(row.get("trainer_id") or 0)
        if trainer_id > 0:
            creatures_by_template.setdefault(trainer_id, []).append(creature_entry)

    trainers: list[TrainerOffer] = []
    for (entry, spell), row in sorted(direct_rows.items()):
        reqskill = int(row.get("reqskill") or 0)
        trainers.append(
            TrainerOffer(
                trainer_kind="direct",
                native_trainer_entry=entry,
                trainer_template_id=None,
                acquisition_spell_id=spell,
                spell_cost=int(row.get("spellcost") or 0),
                required_skill_line_id=reqskill or None,
                required_skill_value=int(row.get("reqskillvalue") or 0),
                required_character_level=int(row.get("reqlevel") or 0),
                source_record=f"direct:{entry}:{spell}",
            )
        )

    unmapped_templates: set[int] = set()
    for (template_id, spell), row in sorted(template_rows.items()):
        creatures = creatures_by_template.get(template_id, ())
        if not creatures:
            unmapped_templates.add(template_id)
            continue
        reqskill = int(row.get("reqskill") or 0)
        for creature_entry in creatures:
            trainers.append(
                TrainerOffer(
                    trainer_kind="template",
                    native_trainer_entry=creature_entry,
                    trainer_template_id=template_id,
                    acquisition_spell_id=spell,
                    spell_cost=int(row.get("spellcost") or 0),
                    required_skill_line_id=reqskill or None,
                    required_skill_value=int(row.get("reqskillvalue") or 0),
                    required_character_level=int(row.get("reqlevel") or 0),
                    source_record=(
                        f"template:{template_id}:{spell}:creature:{creature_entry}"
                    ),
                )
            )

    quests: list[QuestRewardSpell] = []
    for (quest_id,), row in sorted(quest_rows.items()):
        rew_cast = int(row.get("rewspellcast") or 0)
        rew_spell = int(row.get("rewspell") or 0)
        if rew_cast > 0:
            quests.append(
                QuestRewardSpell(
                    native_quest_id=quest_id,
                    reward_spell_field="RewSpellCast",
                    acquisition_spell_id=rew_cast,
                    source_record=f"quest:{quest_id}:RewSpellCast",
                )
            )
        elif rew_spell > 0:
            quests.append(
                QuestRewardSpell(
                    native_quest_id=quest_id,
                    reward_spell_field="RewSpell",
                    acquisition_spell_id=rew_spell,
                    source_record=f"quest:{quest_id}:RewSpell",
                )
            )

    items: list[ItemSpellSlot] = []
    for (item_id,), row in sorted(item_rows.items()):
        for slot in range(1, _ITEM_SLOTS + 1):
            spell_id = int(row.get(f"spellid_{slot}") or 0)
            if spell_id <= 0:
                continue
            trigger = row.get(f"spelltrigger_{slot}")
            charges = row.get(f"spellcharges_{slot}")
            items.append(
                ItemSpellSlot(
                    native_item_id=item_id,
                    slot=slot - 1,
                    acquisition_spell_id=spell_id,
                    spell_trigger=None if trigger is None else int(trigger),
                    spell_charges=None if charges is None else int(charges),
                    source_record=f"item:{item_id}:spell:{slot - 1}",
                )
            )

    server_links = tuple(
        ServerLearnLink(
            acquisition_spell_id=entry,
            learned_spell_id=spell_id,
            active=int(row.get("active") if row.get("active") is not None else 1),
            source_record=f"spell_learn_spell:{entry}:{spell_id}",
        )
        for (entry, spell_id), row in sorted(server_learn_rows.items())
    )

    return TortoiseAcquisitionSlice(
        trainer_offers=tuple(trainers),
        item_spell_slots=tuple(items),
        quest_reward_spells=tuple(quests),
        server_learn_links=server_links,
        unmapped_trainer_template_ids=tuple(sorted(unmapped_templates)),
        source_revision=source_revision,
        git_revision=git_revision,
        input_count=len(files),
    )

def load_octodbc_learn_effects(source_root: str | Path) -> tuple[LearnEffect, ...]:
    """Read only the reviewed Spell Effect/EffectTriggerSpell arrays needed by P4-T04."""

    root = Path(source_root)
    # Validate the exact three-file envelope/layout already accepted by P4-T02/P4-T03.
    inspect_octodbc_recipe_reagent_layouts(root)
    path = root / "Spell.dbc"
    data = path.read_bytes()
    if len(data) < _HEADER.size:
        raise RecipeAcquisitionError("Spell.dbc is shorter than the WDBC header")
    magic, record_count, field_count, record_size, string_size = _HEADER.unpack_from(data)
    if magic != b"WDBC":
        raise RecipeAcquisitionError(f"Spell.dbc expected WDBC magic, got {magic!r}")
    field_map = _SPELL_LAYOUTS.get((field_count, record_size))
    if field_map is None:
        raise RecipeAcquisitionError(
            f"Spell.dbc unsupported P4-T04 layout {field_count}/{record_size}"
        )
    expected = _HEADER.size + record_count * record_size + string_size
    if len(data) != expected:
        raise RecipeAcquisitionError(
            f"Spell.dbc header declares {expected} bytes, file has {len(data)}"
        )
    effect_first, trigger_first = field_map
    records = memoryview(data)[_HEADER.size : _HEADER.size + record_count * record_size]
    effects: list[LearnEffect] = []
    seen_spell_ids: set[int] = set()
    for row in range(record_count):
        base = row * record_size
        spell_id = struct.unpack_from("<I", records, base)[0]
        if spell_id <= 0 or spell_id in seen_spell_ids:
            raise RecipeAcquisitionError(f"Spell.dbc invalid/duplicate spell ID {spell_id}")
        seen_spell_ids.add(spell_id)
        for effect_index in range(3):
            effect_id = struct.unpack_from(
                "<I", records, base + (effect_first + effect_index) * 4
            )[0]
            if effect_id != SPELL_EFFECT_LEARN_SPELL:
                continue
            learned_spell_id = struct.unpack_from(
                "<I", records, base + (trigger_first + effect_index) * 4
            )[0]
            if learned_spell_id <= 0:
                raise RecipeAcquisitionError(
                    f"Spell {spell_id} LEARN_SPELL effect {effect_index} has no trigger spell"
                )
            effects.append(
                LearnEffect(
                    acquisition_spell_id=spell_id,
                    effect_index=effect_index,
                    learned_spell_id=learned_spell_id,
                )
            )
    return tuple(effects)


def _latest_successful_revision(
    connection: sqlite3.Connection, source_key: str, importer_version: str
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
        (source_key, importer_version),
    ).fetchone()
    if row is None or row["source_revision"] is None:
        return None
    value = str(row["source_revision"]).strip()
    return value or None


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
        (
            SOURCE_KEY,
            "Tortoise world SQL + Octo DBC recipe acquisition proof",
            "cross-source-derived",
            source_path,
        ),
    )
    row = connection.execute(
        "SELECT id FROM data_sources WHERE source_key = ?", (SOURCE_KEY,)
    ).fetchone()
    if row is None:  # pragma: no cover
        raise RuntimeError("P4-T04 source registration failed")
    return int(row["id"])


def _selected_relation(
    connection: sqlite3.Connection, observation_id: int
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
                    "P4-T04 materializes only world-source acquisition rows whose wrapper spell "
                    "is proven by the matching Octo Spell.dbc to learn the canonical recipe spell."
                ),
            )
        selected_json = row["value_json"]
    else:
        selected_json = current["value_json"]
    value = json.loads(str(selected_json))
    if not isinstance(value, dict):
        raise RecipeAcquisitionError("selected acquisition relation must be a JSON object")
    return value, protected


def _target(value: dict[str, Any], expected_kind: str) -> int:
    target = value.get("target")
    if not isinstance(target, dict) or target.get("kind") != expected_kind:
        raise RecipeAcquisitionError(
            f"selected acquisition relation must target {expected_kind}"
        )
    try:
        key = int(str(target["key"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise RecipeAcquisitionError("selected acquisition target key is invalid") from exc
    if key <= 0:
        raise RecipeAcquisitionError("selected acquisition target key must be positive")
    return key


def _attrs(value: dict[str, Any]) -> dict[str, Any]:
    attrs = value.get("attributes")
    if not isinstance(attrs, dict):
        raise RecipeAcquisitionError("selected acquisition attributes must be an object")
    return attrs


def _int_attr(attrs: dict[str, Any], key: str, *, minimum: int = 0) -> int:
    try:
        value = int(attrs[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise RecipeAcquisitionError(f"selected acquisition attribute {key} is invalid") from exc
    if value < minimum:
        raise RecipeAcquisitionError(f"selected acquisition attribute {key} < {minimum}")
    return value


def _optional_positive_attr(attrs: dict[str, Any], key: str) -> int | None:
    raw = attrs.get(key)
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise RecipeAcquisitionError(f"selected acquisition attribute {key} is invalid") from exc
    return value if value > 0 else None


def _upsert_and_count(
    connection: sqlite3.Connection,
    table: str,
    key_where: str,
    key_params: tuple[Any, ...],
    select_columns: str,
    expected: tuple[Any, ...],
    insert_sql: str,
    insert_params: tuple[Any, ...],
) -> tuple[int, int]:
    existing = connection.execute(
        f"SELECT {select_columns} FROM {table} WHERE {key_where}", key_params
    ).fetchone()
    inserted = int(existing is None)
    updated = int(existing is not None and tuple(existing) != expected)
    connection.execute(insert_sql, insert_params)
    return inserted, updated


def import_recipe_acquisition_sources(
    connection: sqlite3.Connection,
    *,
    tortoise_repo: str | Path,
    dbc_root: str | Path,
) -> ImportSummary:
    """Materialize proven P4-T04 acquisition relations for canonical recipes."""

    tortoise = load_tortoise_acquisition_slice(tortoise_repo)
    dbc_revision = compute_octodbc_recipe_reagent_revision(dbc_root)
    learning_effects = load_octodbc_learn_effects(dbc_root)

    identity_revision = _latest_successful_revision(
        connection, "octo-client-dbc", IDENTITY_IMPORTER_VERSION
    )
    if identity_revision is None:
        raise RecipeAcquisitionError(
            "P4-T04 requires a successful octo-dbc-recipes/4 identity import first"
        )
    if identity_revision != dbc_revision:
        raise RecipeAcquisitionError(
            "P4-T04 Octo DBC revision differs from the canonical P4-T02 identity revision: "
            f"identity={identity_revision}, acquisition={dbc_revision}"
        )

    composite_revision = json.dumps(
        {
            "octo_dbc_revision": dbc_revision,
            "tortoise_world_revision": json.loads(tortoise.source_revision),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    previous = _latest_successful_revision(connection, SOURCE_KEY, IMPORTER_VERSION)
    if previous is not None and previous != composite_revision:
        raise RecipeAcquisitionError(
            "P4-T04 cross-revision acquisition reconciliation is not implemented; "
            "validate a deliberate refresh task before importing changed world/DBC sources"
        )

    recipe_ids = {
        int(row[0]) for row in connection.execute("SELECT recipe_id FROM recipes").fetchall()
    }
    if not recipe_ids:
        raise RecipeAcquisitionError("P4-T04 requires canonical P4-T02 recipes")
    canonical_item_ids = {
        int(row[0]) for row in connection.execute("SELECT item_id FROM items").fetchall()
    }
    canonical_creature_ids = {
        int(row[0]) for row in connection.execute("SELECT creature_id FROM creatures").fetchall()
    }
    canonical_quest_ids = {
        int(row[0]) for row in connection.execute("SELECT quest_id FROM quests").fetchall()
    }
    canonical_spell_ids = {
        int(row[0]) for row in connection.execute("SELECT spell_id FROM spells").fetchall()
    }

    dbc_by_pair: dict[tuple[int, int], list[int]] = {}
    for effect in learning_effects:
        dbc_by_pair.setdefault(
            (effect.acquisition_spell_id, effect.learned_spell_id), []
        ).append(effect.effect_index)
    for indices in dbc_by_pair.values():
        indices.sort()

    server_by_pair: dict[tuple[int, int], list[ServerLearnLink]] = {}
    for link in tortoise.server_learn_links:
        server_by_pair.setdefault(
            (link.acquisition_spell_id, link.learned_spell_id), []
        ).append(link)

    learned_by_wrapper: dict[int, set[int]] = {}
    for wrapper, learned in dbc_by_pair:
        learned_by_wrapper.setdefault(wrapper, set()).add(learned)
    for wrapper, learned in server_by_pair:
        learned_by_wrapper.setdefault(wrapper, set()).add(learned)

    source_id = _ensure_source(
        connection,
        json.dumps(
            {"tortoise_repo": str(Path(tortoise_repo)), "octo_dbc": str(Path(dbc_root))},
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    rows_read = (
        len(tortoise.trainer_offers)
        + len(tortoise.item_spell_slots)
        + len(tortoise.quest_reward_spells)
    )
    batch_id = int(
        connection.execute(
            """
            INSERT INTO import_batches(
                source_id, source_revision, status, importer_version, rows_read
            ) VALUES (?, ?, 'running', ?, ?)
            """,
            (source_id, composite_revision, IMPORTER_VERSION, rows_read),
        ).lastrowid
    )

    inserted = 0
    updated = 0
    protected_count = 0
    unresolved_items: set[int] = set()
    unresolved_creatures: set[int] = set()
    unresolved_quests: set[int] = set()
    missing_wrapper_spells: set[int] = set()
    non_recipe_learn_targets: set[int] = set()
    materialized = {"teaching_items": 0, "trainer_sources": 0, "quest_learning_sources": 0}
    proof_counts = {"octo_dbc_learn_spell": 0, "tortoise_spell_learn_spell": 0}
    accepted_source_rows = 0

    def proven_links(acquisition_spell_id: int) -> tuple[ProvenLearning, ...]:
        if acquisition_spell_id not in canonical_spell_ids:
            missing_wrapper_spells.add(acquisition_spell_id)
            return ()
        links: list[ProvenLearning] = []
        for learned_spell_id in sorted(learned_by_wrapper.get(acquisition_spell_id, ())):
            if learned_spell_id not in recipe_ids:
                non_recipe_learn_targets.add(learned_spell_id)
                continue
            pair = (acquisition_spell_id, learned_spell_id)
            dbc_indices = tuple(dbc_by_pair.get(pair, ()))
            server_links = tuple(server_by_pair.get(pair, ()))
            if dbc_indices:
                proof_kind = "octo_dbc_learn_spell"
                effect_index: int | None = dbc_indices[0]
            elif server_links:
                proof_kind = "tortoise_spell_learn_spell"
                effect_index = None
            else:  # pragma: no cover - learned_by_wrapper is built from these maps
                continue
            server_active = server_links[0].active if server_links else None
            links.append(
                ProvenLearning(
                    acquisition_spell_id=acquisition_spell_id,
                    learned_spell_id=learned_spell_id,
                    proof_kind=proof_kind,
                    learn_effect_index=effect_index,
                    dbc_effect_indices=dbc_indices,
                    server_learn_active=server_active,
                    server_source_records=tuple(link.source_record for link in server_links),
                )
            )
        return tuple(links)

    def proof_attributes(link: ProvenLearning) -> dict[str, Any]:
        return {
            "learning_proof_kind": link.proof_kind,
            "learn_effect_index": link.learn_effect_index,
            "dbc_learn_effect_indices": list(link.dbc_effect_indices),
            "server_learn_active": link.server_learn_active,
            "server_learn_source_records": list(link.server_source_records),
            "octo_dbc_revision": dbc_revision,
        }

    for item in tortoise.item_spell_slots:
        item_links = proven_links(item.acquisition_spell_id)
        accepted_source_rows += int(bool(item_links))
        for link in item_links:
            attributes = {
                "item_spell_slot": item.slot,
                "spell_trigger": item.spell_trigger,
                "spell_charges": item.spell_charges,
                "acquisition_spell_id": item.acquisition_spell_id,
                "world_source_record": item.source_record,
                **proof_attributes(link),
            }
            observation_id = record_relation_observation(
                connection,
                subject_kind="recipe",
                subject_key=link.learned_spell_id,
                fact_key="teaching_item",
                import_batch_id=batch_id,
                target_kind="item",
                target_key=item.native_item_id,
                relation_instance_key=(
                    f"item:{item.native_item_id}:slot:{item.slot}:spell:{item.acquisition_spell_id}"
                ),
                attributes=attributes,
                source_record_type="item_template+recipe-learning-proof",
                raw_identifier=item.source_record,
                authority_tier=2,
            )
            selected, protected = _selected_relation(connection, observation_id)
            protected_count += int(protected)
            native_item_id = _target(selected, "item")
            attrs = _attrs(selected)
            slot = _int_attr(attrs, "item_spell_slot")
            acquisition_spell_id = _int_attr(attrs, "acquisition_spell_id", minimum=1)
            proof_kind = str(attrs.get("learning_proof_kind", ""))
            if proof_kind not in proof_counts:
                raise RecipeAcquisitionError("selected learning_proof_kind is invalid")
            effect_raw = attrs.get("learn_effect_index")
            learn_effect_index = None if effect_raw is None else int(effect_raw)
            server_raw = attrs.get("server_learn_active")
            server_learn_active = None if server_raw is None else int(server_raw)
            trigger_raw = attrs.get("spell_trigger")
            charges_raw = attrs.get("spell_charges")
            spell_trigger = None if trigger_raw is None else int(trigger_raw)
            spell_charges = None if charges_raw is None else int(charges_raw)
            item_id = native_item_id if native_item_id in canonical_item_ids else None
            if item_id is None:
                unresolved_items.add(native_item_id)
            key = (link.learned_spell_id, native_item_id, slot, acquisition_spell_id)
            expected = (
                item_id,
                spell_trigger,
                spell_charges,
                proof_kind,
                learn_effect_index,
                server_learn_active,
            )
            ins, upd = _upsert_and_count(
                connection,
                "recipe_teaching_items",
                "recipe_id=? AND native_item_id=? AND item_spell_slot=? AND acquisition_spell_id=?",
                key,
                "item_id, spell_trigger, spell_charges, learning_proof_kind, learn_effect_index, server_learn_active",
                expected,
                """
                INSERT INTO recipe_teaching_items(
                    recipe_id, native_item_id, item_id, item_spell_slot, spell_trigger,
                    spell_charges, acquisition_spell_id, learning_proof_kind,
                    learn_effect_index, server_learn_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(recipe_id, native_item_id, item_spell_slot, acquisition_spell_id)
                DO UPDATE SET item_id=excluded.item_id, spell_trigger=excluded.spell_trigger,
                    spell_charges=excluded.spell_charges,
                    learning_proof_kind=excluded.learning_proof_kind,
                    learn_effect_index=excluded.learn_effect_index,
                    server_learn_active=excluded.server_learn_active
                """,
                (
                    link.learned_spell_id,
                    native_item_id,
                    item_id,
                    slot,
                    spell_trigger,
                    spell_charges,
                    acquisition_spell_id,
                    proof_kind,
                    learn_effect_index,
                    server_learn_active,
                ),
            )
            inserted += ins
            updated += upd
            materialized["teaching_items"] += 1
            proof_counts[proof_kind] += 1

    for trainer in tortoise.trainer_offers:
        trainer_links = proven_links(trainer.acquisition_spell_id)
        accepted_source_rows += int(bool(trainer_links))
        for link in trainer_links:
            attributes = {
                "trainer_kind": trainer.trainer_kind,
                "trainer_template_id": trainer.trainer_template_id,
                "acquisition_spell_id": trainer.acquisition_spell_id,
                "spell_cost": trainer.spell_cost,
                "required_skill_line_id": trainer.required_skill_line_id,
                "required_skill_value": trainer.required_skill_value,
                "required_character_level": trainer.required_character_level,
                "world_source_record": trainer.source_record,
                **proof_attributes(link),
            }
            observation_id = record_relation_observation(
                connection,
                subject_kind="recipe",
                subject_key=link.learned_spell_id,
                fact_key="trainer_source",
                import_batch_id=batch_id,
                target_kind="creature",
                target_key=trainer.native_trainer_entry,
                relation_instance_key=(
                    f"{trainer.trainer_kind}:creature:{trainer.native_trainer_entry}:"
                    f"template:{trainer.trainer_template_id or 0}:spell:{trainer.acquisition_spell_id}"
                ),
                attributes=attributes,
                source_record_type="trainer-world+recipe-learning-proof",
                raw_identifier=trainer.source_record,
                authority_tier=2,
            )
            selected, protected = _selected_relation(connection, observation_id)
            protected_count += int(protected)
            native_entry = _target(selected, "creature")
            attrs = _attrs(selected)
            trainer_kind = str(attrs.get("trainer_kind", ""))
            if trainer_kind not in {"direct", "template"}:
                raise RecipeAcquisitionError("selected trainer_kind is invalid")
            template_raw = attrs.get("trainer_template_id")
            trainer_template_id = None if template_raw is None else int(template_raw)
            acquisition_spell_id = _int_attr(attrs, "acquisition_spell_id", minimum=1)
            proof_kind = str(attrs.get("learning_proof_kind", ""))
            if proof_kind not in proof_counts:
                raise RecipeAcquisitionError("selected learning_proof_kind is invalid")
            effect_raw = attrs.get("learn_effect_index")
            learn_effect_index = None if effect_raw is None else int(effect_raw)
            server_raw = attrs.get("server_learn_active")
            server_learn_active = None if server_raw is None else int(server_raw)
            spell_cost = _int_attr(attrs, "spell_cost")
            required_skill_line_id = _optional_positive_attr(attrs, "required_skill_line_id")
            required_skill_value = _int_attr(attrs, "required_skill_value")
            required_character_level = _int_attr(attrs, "required_character_level")
            creature_id = native_entry if native_entry in canonical_creature_ids else None
            if creature_id is None:
                unresolved_creatures.add(native_entry)
            key = (
                link.learned_spell_id,
                trainer_kind,
                native_entry,
                acquisition_spell_id,
            )
            expected = (
                creature_id,
                trainer_template_id,
                proof_kind,
                learn_effect_index,
                server_learn_active,
                spell_cost,
                required_skill_line_id,
                required_skill_value,
                required_character_level,
            )
            ins, upd = _upsert_and_count(
                connection,
                "recipe_trainer_sources",
                "recipe_id=? AND trainer_kind=? AND native_trainer_entry=? AND acquisition_spell_id=?",
                key,
                "creature_id, trainer_template_id, learning_proof_kind, learn_effect_index, server_learn_active, spell_cost, required_skill_line_id, required_skill_value, required_character_level",
                expected,
                """
                INSERT INTO recipe_trainer_sources(
                    recipe_id, trainer_kind, native_trainer_entry, creature_id,
                    trainer_template_id, acquisition_spell_id, learning_proof_kind,
                    learn_effect_index, server_learn_active, spell_cost,
                    required_skill_line_id, required_skill_value, required_character_level
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(recipe_id, trainer_kind, native_trainer_entry, acquisition_spell_id)
                DO UPDATE SET creature_id=excluded.creature_id,
                    trainer_template_id=excluded.trainer_template_id,
                    learning_proof_kind=excluded.learning_proof_kind,
                    learn_effect_index=excluded.learn_effect_index,
                    server_learn_active=excluded.server_learn_active,
                    spell_cost=excluded.spell_cost,
                    required_skill_line_id=excluded.required_skill_line_id,
                    required_skill_value=excluded.required_skill_value,
                    required_character_level=excluded.required_character_level
                """,
                (
                    link.learned_spell_id,
                    trainer_kind,
                    native_entry,
                    creature_id,
                    trainer_template_id,
                    acquisition_spell_id,
                    proof_kind,
                    learn_effect_index,
                    server_learn_active,
                    spell_cost,
                    required_skill_line_id,
                    required_skill_value,
                    required_character_level,
                ),
            )
            inserted += ins
            updated += upd
            materialized["trainer_sources"] += 1
            proof_counts[proof_kind] += 1

    for quest in tortoise.quest_reward_spells:
        quest_links = proven_links(quest.acquisition_spell_id)
        accepted_source_rows += int(bool(quest_links))
        for link in quest_links:
            attributes = {
                "reward_spell_field": quest.reward_spell_field,
                "acquisition_spell_id": quest.acquisition_spell_id,
                "world_source_record": quest.source_record,
                **proof_attributes(link),
            }
            observation_id = record_relation_observation(
                connection,
                subject_kind="recipe",
                subject_key=link.learned_spell_id,
                fact_key="quest_learning_source",
                import_batch_id=batch_id,
                target_kind="quest",
                target_key=quest.native_quest_id,
                relation_instance_key=(
                    f"quest:{quest.native_quest_id}:{quest.reward_spell_field}:"
                    f"spell:{quest.acquisition_spell_id}"
                ),
                attributes=attributes,
                source_record_type="quest_template+recipe-learning-proof",
                raw_identifier=quest.source_record,
                authority_tier=2,
            )
            selected, protected = _selected_relation(connection, observation_id)
            protected_count += int(protected)
            native_quest_id = _target(selected, "quest")
            attrs = _attrs(selected)
            reward_spell_field = str(attrs.get("reward_spell_field", ""))
            if reward_spell_field not in {"RewSpellCast", "RewSpell"}:
                raise RecipeAcquisitionError("selected quest reward spell field is invalid")
            acquisition_spell_id = _int_attr(attrs, "acquisition_spell_id", minimum=1)
            proof_kind = str(attrs.get("learning_proof_kind", ""))
            if proof_kind not in proof_counts:
                raise RecipeAcquisitionError("selected learning_proof_kind is invalid")
            effect_raw = attrs.get("learn_effect_index")
            learn_effect_index = None if effect_raw is None else int(effect_raw)
            server_raw = attrs.get("server_learn_active")
            server_learn_active = None if server_raw is None else int(server_raw)
            quest_id = native_quest_id if native_quest_id in canonical_quest_ids else None
            if quest_id is None:
                unresolved_quests.add(native_quest_id)
            key = (
                link.learned_spell_id,
                native_quest_id,
                reward_spell_field,
                acquisition_spell_id,
            )
            expected = (quest_id, proof_kind, learn_effect_index, server_learn_active)
            ins, upd = _upsert_and_count(
                connection,
                "recipe_quest_learning_sources",
                "recipe_id=? AND native_quest_id=? AND reward_spell_field=? AND acquisition_spell_id=?",
                key,
                "quest_id, learning_proof_kind, learn_effect_index, server_learn_active",
                expected,
                """
                INSERT INTO recipe_quest_learning_sources(
                    recipe_id, native_quest_id, quest_id, reward_spell_field,
                    acquisition_spell_id, learning_proof_kind, learn_effect_index,
                    server_learn_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(recipe_id, native_quest_id, reward_spell_field, acquisition_spell_id)
                DO UPDATE SET quest_id=excluded.quest_id,
                    learning_proof_kind=excluded.learning_proof_kind,
                    learn_effect_index=excluded.learn_effect_index,
                    server_learn_active=excluded.server_learn_active
                """,
                (
                    link.learned_spell_id,
                    native_quest_id,
                    quest_id,
                    reward_spell_field,
                    acquisition_spell_id,
                    proof_kind,
                    learn_effect_index,
                    server_learn_active,
                ),
            )
            inserted += ins
            updated += upd
            materialized["quest_learning_sources"] += 1
            proof_counts[proof_kind] += 1

    warning_count = (
        len(unresolved_items)
        + len(unresolved_creatures)
        + len(unresolved_quests)
        + len(missing_wrapper_spells)
        + len(tortoise.unmapped_trainer_template_ids)
    )
    details = {
        "source_contract": {
            "identity_separation": "recipe remains crafting spell anchored entity",
            "learning_proof_priority": [
                "Octo Spell.dbc LEARN_SPELL",
                "Tortoise spell_learn_spell fallback",
            ],
            "trainer_world_evidence": [
                "npc_trainer",
                "npc_trainer_template",
                "creature_template.trainer_id",
            ],
            "quest_reward_precedence": "RewSpellCast when nonzero, else RewSpell",
            "quest_learning_scans_all_effect_slots": True,
            "item_availability_is_derived": True,
            "trainer_templates_expand_to_creature_entries": True,
        },
        "source_completeness": {
            "tortoise_world_sql": "close-lineage reference, not Octo production truth",
            "item_template": "only rows/effective writes present in configured Tortoise SQL",
            "absence_is_universal_negative_evidence": False,
            "cross_revision_reconciliation": False,
            "spell_learn_spell": (
                "server learning-edge fallback under D-035; Octo DBC proof wins on matching pairs"
            ),
        },
        "tortoise_semantic_reference_revision": TORTOISE_PINNED_SEMANTIC_REVISION,
        "tortoise_git_revision": tortoise.git_revision,
        "tortoise_input_file_count": tortoise.input_count,
        "octo_dbc_revision": dbc_revision,
        "learn_effect_count": len(learning_effects),
        "world_trainer_offer_count": len(tortoise.trainer_offers),
        "world_item_spell_slot_count": len(tortoise.item_spell_slots),
        "world_quest_reward_spell_count": len(tortoise.quest_reward_spells),
        "server_spell_learn_link_count": len(tortoise.server_learn_links),
        "unmapped_trainer_template_ids": list(tortoise.unmapped_trainer_template_ids),
        **{f"materialized_{key}": value for key, value in materialized.items()},
        "materialized_learning_proof_counts": proof_counts,
        "unresolved_item_ids": sorted(unresolved_items),
        "unresolved_trainer_creature_entries": sorted(unresolved_creatures),
        "unresolved_quest_ids": sorted(unresolved_quests),
        "missing_canonical_wrapper_spell_ids": sorted(missing_wrapper_spells),
        "non_recipe_learn_target_ids": sorted(non_recipe_learn_targets),
        "protected_selection_count": protected_count,
    }
    connection.execute(
        """
        UPDATE import_batches
        SET finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            status = 'succeeded', rows_accepted = ?, rows_skipped = ?,
            rows_inserted = ?, rows_updated = ?, warning_count = ?, error_count = 0,
            details_json = ?
        WHERE id = ?
        """,
        (
            accepted_source_rows,
            rows_read - accepted_source_rows,
            inserted,
            updated,
            warning_count,
            json.dumps(details, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            batch_id,
        ),
    )
    return ImportSummary(
        source_key=SOURCE_KEY,
        source_revision=composite_revision,
        status="succeeded",
        rows_read=rows_read,
        rows_accepted=accepted_source_rows,
        rows_skipped=rows_read - accepted_source_rows,
        rows_inserted=inserted,
        rows_updated=updated,
        warning_count=warning_count,
        error_count=0,
        details=details,
    )
