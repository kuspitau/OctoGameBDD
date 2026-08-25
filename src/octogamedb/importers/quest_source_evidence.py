from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

TORTOISE_REPOSITORY = "https://github.com/Penqle/tortoise-wow"
TORTOISE_PINNED_REVISION = "61a8269151721f6467eddb05e7bed37704d0fc0b"
TORTOISE_BASE_RELATIVE = Path("sql/base/tw_world_quest_template.sql")
TORTOISE_MIGRATIONS_RELATIVE = Path("sql/database_updates/world")
CLASSICAPI_REPOSITORY = "https://github.com/brues-code/ClassicAPI"
CLASSICAPI_PINNED_REVISION = "e793f80f6b45ed49a94dc8abdc9fcac4fe6b03dd"

SOURCE_LIVE = "octo-live-quest-query"
SOURCE_OCTODB = "octodb"
SOURCE_TORTOISE = "tortoise-world-sql"
SOURCE_CMANGOS = "cmangos-vanilla"

_BOUNDED_SINGLE_FIELDS = {"srcitemid": "SrcItemId", "srcitemcount": "SrcItemCount"}
_BOUNDED_SLOT_PATTERNS = (
    (re.compile(r"^reqitemid([1-4])$", re.IGNORECASE), "ReqItemId"),
    (re.compile(r"^reqitemcount([1-4])$", re.IGNORECASE), "ReqItemCount"),
    (re.compile(r"^reqsourceid([1-4])$", re.IGNORECASE), "ReqSourceId"),
    (re.compile(r"^reqsourcecount([1-4])$", re.IGNORECASE), "ReqSourceCount"),
    (re.compile(r"^rewitemid([1-4])$", re.IGNORECASE), "RewItemId"),
    (re.compile(r"^rewitemcount([1-4])$", re.IGNORECASE), "RewItemCount"),
    (re.compile(r"^rewchoiceitemid([1-6])$", re.IGNORECASE), "RewChoiceItemId"),
    (re.compile(r"^rewchoiceitemcount([1-6])$", re.IGNORECASE), "RewChoiceItemCount"),
)
_ENTRY_NAMES = {"entry", "questid", "id"}
_TABLE_RE = r"(?:`?\w+`?\.)?`?quest_template`?"


class QuestSourceError(RuntimeError):
    """Base error for bounded quest-source acquisition."""


class UnsupportedQuestSQL(QuestSourceError):
    """Raised when a quest_template mutation cannot be interpreted safely."""


@dataclass(frozen=True)
class SourceInput:
    path: str
    sha256: str


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def stable_hash(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_git_revision(repository: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    revision = result.stdout.strip()
    return revision or None


def _identifier(value: str) -> str:
    value = value.strip()
    if value.startswith("`") and value.endswith("`"):
        value = value[1:-1]
    return value


def bounded_field_name(value: str) -> str | None:
    name = _identifier(value)
    lower = name.lower()
    if lower in _BOUNDED_SINGLE_FIELDS:
        return _BOUNDED_SINGLE_FIELDS[lower]
    for pattern, prefix in _BOUNDED_SLOT_PATTERNS:
        match = pattern.fullmatch(name)
        if match:
            return f"{prefix}{int(match.group(1))}"
    return None


def _entry_field(columns: Sequence[str]) -> str:
    for column in columns:
        if _identifier(column).lower() in _ENTRY_NAMES:
            return _identifier(column)
    raise UnsupportedQuestSQL("quest_template schema has no recognized entry/quest ID column")


def _strip_comments_and_split(text: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    i = 0
    quote: str | None = None
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
                raise UnsupportedQuestSQL("unterminated SQL block comment")
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
                raise UnsupportedQuestSQL("unbalanced SQL parentheses")
            current.append(char)
        elif char == delimiter and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        i += 1
    if quote or depth != 0:
        raise UnsupportedQuestSQL("unterminated quote or unbalanced SQL parentheses")
    parts.append("".join(current).strip())
    return parts


def _parse_int(token: str, *, field: str) -> int | None:
    value = token.strip()
    if value.upper() == "NULL":
        return None
    if not re.fullmatch(r"[+-]?\d+", value):
        raise UnsupportedQuestSQL(f"{field} requires an integer/NULL literal, got: {value[:80]}")
    return int(value)


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
            raise UnsupportedQuestSQL("unterminated VALUES tuple")
    return groups, ""


def _parse_create_columns(statement: str) -> list[str] | None:
    match = re.match(
        rf"^CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+{_TABLE_RE}\s*\((.*)\)\s*.*$",
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
        columns.append(normalized)
    if not columns:
        raise UnsupportedQuestSQL("quest_template CREATE TABLE yielded no columns")
    _entry_field(columns)
    return columns


def _row_from_values(columns: Sequence[str], values_text: str) -> dict[str, int | None]:
    tokens = _split_top_level(values_text)
    if len(tokens) != len(columns):
        raise UnsupportedQuestSQL(
            f"quest_template INSERT has {len(tokens)} values for {len(columns)} columns"
        )
    row: dict[str, int | None] = {}
    for column, token in zip(columns, tokens, strict=True):
        canonical = bounded_field_name(column)
        normalized = _identifier(column)
        if canonical or normalized.lower() in _ENTRY_NAMES:
            row[canonical or normalized] = _parse_int(token, field=normalized)
    return row


def _parse_insert(
    statement: str,
    schema_columns: Sequence[str] | None,
) -> tuple[str, list[dict[str, int | None]], list[str] | None] | None:
    match = re.match(
        rf"^(INSERT(?:\s+IGNORE)?|REPLACE)\s+INTO\s+{_TABLE_RE}\s*(.*)$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    operation = re.sub(r"\s+", " ", match.group(1).upper())
    rest = match.group(2).lstrip()
    columns: list[str] | None = None
    if rest.startswith("("):
        groups, trailing = _extract_tuple_groups(rest)
        if not groups:
            raise UnsupportedQuestSQL("quest_template INSERT has malformed column list")
        columns = [_identifier(item) for item in _split_top_level(groups[0])]
        consumed = rest.find(")") + 1
        rest = rest[consumed:].lstrip()
    if not re.match(r"^VALUES\b", rest, flags=re.IGNORECASE):
        raise UnsupportedQuestSQL("only quest_template INSERT/REPLACE ... VALUES is supported")
    rest = re.sub(r"^VALUES\b", "", rest, count=1, flags=re.IGNORECASE).lstrip()
    tuple_groups, trailing = _extract_tuple_groups(rest)
    if not tuple_groups:
        raise UnsupportedQuestSQL("quest_template INSERT/REPLACE contains no VALUES tuples")
    if trailing:
        raise UnsupportedQuestSQL(
            "unsupported trailing clause on quest_template INSERT/REPLACE: " + trailing[:100]
        )
    effective_columns = columns or (list(schema_columns) if schema_columns else None)
    if not effective_columns:
        raise UnsupportedQuestSQL(
            "quest_template INSERT omits column names and no CREATE TABLE/schema was available"
        )
    rows = [_row_from_values(effective_columns, group) for group in tuple_groups]
    return operation, rows, effective_columns


def _parse_where_clause(where_text: str) -> tuple[list[int], list[tuple[str, int | None]]]:
    parts = re.split(r"\s+AND\s+", where_text.strip(), flags=re.IGNORECASE)
    entries: list[int] | None = None
    predicates: list[tuple[str, int | None]] = []
    for part in parts:
        text = part.strip()
        match = re.fullmatch(r"`?(?:entry|questid|id)`?\s*=\s*([+-]?\d+)", text, flags=re.IGNORECASE)
        if match:
            if entries is not None:
                raise UnsupportedQuestSQL("quest_template WHERE declares entry more than once")
            entries = [int(match.group(1))]
            continue
        match = re.fullmatch(
            r"`?(?:entry|questid|id)`?\s+IN\s*\(([^)]*)\)", text, flags=re.IGNORECASE | re.DOTALL
        )
        if match:
            if entries is not None:
                raise UnsupportedQuestSQL("quest_template WHERE declares entry more than once")
            values = [
                _parse_int(token, field="entry") for token in _split_top_level(match.group(1))
            ]
            if any(value is None for value in values):
                raise UnsupportedQuestSQL("quest_template WHERE entry IN cannot contain NULL")
            entries = [int(value) for value in values if value is not None]
            continue
        match = re.fullmatch(r"(`?\w+`?)\s*=\s*(NULL|[+-]?\d+)", text, flags=re.IGNORECASE)
        if match:
            canonical = bounded_field_name(match.group(1))
            if canonical is None:
                raise UnsupportedQuestSQL(
                    "bounded quest_template WHERE guard references unsupported field: "
                    + _identifier(match.group(1))
                )
            predicates.append((canonical, _parse_int(match.group(2), field=canonical)))
            continue
        raise UnsupportedQuestSQL(
            "bounded quest_template UPDATE/DELETE supports WHERE entry =/IN plus "
            "AND bounded_field = integer/NULL guards only"
        )
    if entries is None:
        raise UnsupportedQuestSQL("bounded quest_template UPDATE/DELETE requires entry =/IN")
    return entries, predicates


def _where_matches(row: Mapping[str, int | None], predicates: Sequence[tuple[str, int | None]]) -> bool:
    for field, expected in predicates:
        if field not in row:
            raise UnsupportedQuestSQL(
                f"cannot evaluate quest_template WHERE guard {field}: field absent from replay row"
            )
        if row.get(field) != expected:
            return False
    return True

def _bounded_assignment_present(statement: str) -> bool:
    lowered = statement.lower()
    candidates = ["srcitemid", "srcitemcount", "reqitem", "reqsource", "rewitem", "rewchoiceitem"]
    return any(candidate in lowered for candidate in candidates)


def _apply_update(statement: str, rows: dict[int, dict[str, int | None]]) -> bool:
    match = re.match(
        rf"^UPDATE\s+{_TABLE_RE}\s+SET\s+(.*?)\s+WHERE\s+(.+)$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return False
    if not _bounded_assignment_present(match.group(1)):
        return True
    assignments: dict[str, int | None] = {}
    for assignment in _split_top_level(match.group(1)):
        pair = assignment.split("=", 1)
        if len(pair) != 2:
            raise UnsupportedQuestSQL("malformed bounded quest_template UPDATE assignment")
        canonical = bounded_field_name(pair[0].strip())
        if canonical:
            assignments[canonical] = _parse_int(pair[1], field=canonical)
    if not assignments:
        return True
    entries, predicates = _parse_where_clause(match.group(2))
    for entry in entries:
        if entry not in rows:
            raise UnsupportedQuestSQL(
                f"bounded quest_template UPDATE targets missing entry {entry}; "
                "base/migration replay may be incomplete"
            )
        if _where_matches(rows[entry], predicates):
            rows[entry].update(assignments)
    return True


def _apply_delete(statement: str, rows: dict[int, dict[str, int | None]]) -> bool:
    match = re.match(
        rf"^DELETE\s+FROM\s+{_TABLE_RE}\s+WHERE\s+(.+)$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return False
    entries, predicates = _parse_where_clause(match.group(1))
    for entry in entries:
        row = rows.get(entry)
        if row is not None and _where_matches(row, predicates):
            rows.pop(entry, None)
    return True


def _statement_targets_quest_template(statement: str) -> bool:
    return bool(
        re.match(
            rf"^(?:(?:INSERT(?:\s+IGNORE)?|REPLACE)\s+INTO|UPDATE|DELETE\s+FROM|"
            rf"ALTER\s+TABLE|CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?|"
            rf"DROP\s+TABLE(?:\s+IF\s+EXISTS)?|TRUNCATE\s+TABLE|LOCK\s+TABLES?)"
            rf"\s+{_TABLE_RE}\b",
            statement.strip(),
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _safe_non_row_statement(statement: str) -> bool:
    stripped = statement.strip()
    if re.match(r"^(LOCK|UNLOCK|SET)\b", stripped, flags=re.IGNORECASE):
        return True
    return bool(
        re.match(
            rf"^ALTER\s+TABLE\s+{_TABLE_RE}\s+(?:DISABLE|ENABLE)\s+KEYS\s*$",
            stripped,
            flags=re.IGNORECASE,
        )
    )


def _is_truncate(statement: str) -> bool:
    return bool(
        re.match(rf"^TRUNCATE\s+TABLE\s+{_TABLE_RE}\s*$", statement.strip(), flags=re.IGNORECASE)
    )


def _canonicalize_row(entry: int, row: Mapping[str, int | None]) -> dict[str, Any]:
    def slots(id_prefix: str, count_prefix: str, count_max: int) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for slot in range(1, count_max + 1):
            id_key = f"{id_prefix}{slot}"
            count_key = f"{count_prefix}{slot}"
            if id_key not in row and count_key not in row:
                continue
            result.append(
                {
                    "slot": slot,
                    "item_id": row.get(id_key),
                    "count": row.get(count_key),
                    "id_field": id_key,
                    "count_field": count_key,
                }
            )
        return result

    required_items = slots("ReqItemId", "ReqItemCount", 4)
    required_sources = slots("ReqSourceId", "ReqSourceCount", 4)
    reward_items = slots("RewItemId", "RewItemCount", 4)
    choice_items = slots("RewChoiceItemId", "RewChoiceItemCount", 6)
    source_item = {
        "item_id": row.get("SrcItemId") if "SrcItemId" in row else None,
        "count": row.get("SrcItemCount") if "SrcItemCount" in row else None,
        "id_present": "SrcItemId" in row,
        "count_present": "SrcItemCount" in row,
    }
    evidence: list[dict[str, Any]] = []
    for family, values in (
        ("required_item", required_items),
        ("required_source", required_sources),
        ("reward_item", reward_items),
        ("choice_reward_item", choice_items),
    ):
        for value in values:
            item_id = value["item_id"]
            if isinstance(item_id, int) and item_id > 0:
                evidence.append(
                    {
                        "fact_family": family,
                        "fact_key": f"{family}:{item_id}",
                        "item_id": item_id,
                        "value": value["count"],
                        "slot": value["slot"],
                    }
                )
    source_item_id = source_item["item_id"]
    if isinstance(source_item_id, int) and source_item_id > 0:
        evidence.append(
            {
                "fact_family": "source_item_id",
                "fact_key": "source_item_id",
                "item_id": source_item_id,
                "value": source_item_id,
                "slot": None,
            }
        )
        if source_item["count_present"]:
            evidence.append(
                {
                    "fact_family": "source_item_count",
                    "fact_key": f"source_item_count:{source_item_id}",
                    "item_id": source_item_id,
                    "value": source_item["count"],
                    "slot": None,
                }
            )
    return {
        "quest_id": entry,
        "required_items": required_items,
        "required_sources": required_sources,
        "source_item": source_item,
        "reward_items": reward_items,
        "choice_reward_items": choice_items,
        "evidence": evidence,
    }


def _content_set_hash(inputs: Sequence[SourceInput]) -> str:
    payload = [{"path": item.path, "sha256": item.sha256} for item in inputs]
    return stable_hash(payload)


def _apply_insert_rows(
    *,
    operation: str,
    insert_rows: Sequence[Mapping[str, int | None]],
    insert_columns: Sequence[str],
    rows: dict[int, dict[str, int | None]],
    context: str,
) -> None:
    entry_name = _entry_field(insert_columns)
    for row in insert_rows:
        entry_value = row.get(entry_name)
        if entry_value is None:
            for key, value in row.items():
                if key.lower() in _ENTRY_NAMES:
                    entry_value = value
                    break
        if not isinstance(entry_value, int):
            raise UnsupportedQuestSQL(f"{context} INSERT row has no integer quest entry")
        bounded = {key: value for key, value in row.items() if bounded_field_name(key)}
        if operation == "INSERT IGNORE" and entry_value in rows:
            continue
        if operation == "INSERT" and entry_value in rows:
            raise UnsupportedQuestSQL(
                f"{context} plain INSERT duplicates quest_template entry {entry_value}; "
                "cannot replay MySQL duplicate-key behavior safely"
            )
        rows[entry_value] = bounded


def load_tortoise_quest_projection(
    repository: Path,
    *,
    quest_ids: Iterable[int] | None = None,
    source_revision: str | None = None,
    schema_sql: Path | None = None,
) -> dict[str, Any]:
    repository = repository.resolve()
    base_path = repository / TORTOISE_BASE_RELATIVE
    migrations_root = repository / TORTOISE_MIGRATIONS_RELATIVE
    if not base_path.is_file():
        raise QuestSourceError(f"missing Tortoise base file: {base_path}")
    if not migrations_root.is_dir():
        raise QuestSourceError(f"missing Tortoise world migration directory: {migrations_root}")

    selected = {int(value) for value in quest_ids} if quest_ids is not None else None
    rows: dict[int, dict[str, int | None]] = {}
    inputs: list[SourceInput] = []

    base_text = base_path.read_text(encoding="utf-8", errors="strict")
    base_statements = _strip_comments_and_split(base_text)
    embedded_schema: list[str] | None = None
    for statement in base_statements:
        parsed = _parse_create_columns(statement)
        if parsed:
            embedded_schema = parsed
            break

    schema_columns = embedded_schema
    # The external schema is metadata only for positional dumps that do not
    # carry their own CREATE TABLE. Do not content-address an unused schema.
    if schema_columns is None:
        candidate_schema = schema_sql.resolve() if schema_sql is not None else repository / "sql/create_databases.sql"
        if candidate_schema.is_file():
            schema_text = candidate_schema.read_text(encoding="utf-8", errors="strict")
            for statement in _strip_comments_and_split(schema_text):
                parsed = _parse_create_columns(statement)
                if parsed:
                    schema_columns = parsed
                    break
            if schema_columns is None:
                raise UnsupportedQuestSQL(
                    f"no quest_template CREATE TABLE in schema SQL: {candidate_schema}"
                )
            try:
                schema_label = candidate_schema.relative_to(repository).as_posix()
            except ValueError:
                schema_label = candidate_schema.name
            inputs.append(SourceInput(schema_label, sha256_file(candidate_schema)))
        elif schema_sql is not None:
            raise QuestSourceError(f"missing explicit schema SQL: {candidate_schema}")

    inputs.append(SourceInput(TORTOISE_BASE_RELATIVE.as_posix(), sha256_file(base_path)))
    for statement in base_statements:
        parsed_schema = _parse_create_columns(statement)
        if parsed_schema:
            schema_columns = parsed_schema
            continue
        parsed_insert = _parse_insert(statement, schema_columns)
        if parsed_insert is not None:
            operation, insert_rows, insert_columns = parsed_insert
            if schema_columns is None and insert_columns:
                schema_columns = list(insert_columns)
            _apply_insert_rows(
                operation=operation,
                insert_rows=insert_rows,
                insert_columns=insert_columns or schema_columns or [],
                rows=rows,
                context="base SQL",
            )
            continue
        if _statement_targets_quest_template(statement):
            if _is_truncate(statement):
                rows.clear()
                continue
            # mysqldump commonly drops the table before recreating it. This is
            # safe only in the base bootstrap; a migration DROP fails closed.
            if re.match(
                rf"^DROP\s+TABLE(?:\s+IF\s+EXISTS)?\s+{_TABLE_RE}\s*$",
                statement.strip(),
                flags=re.IGNORECASE,
            ):
                rows.clear()
                continue
            if _safe_non_row_statement(statement):
                continue
            raise UnsupportedQuestSQL(
                "unsupported quest_template statement in base SQL: "
                + statement[:160].replace("\n", " ")
            )

    relevant_migrations: list[Path] = []
    for path in sorted(migrations_root.rglob("*.sql"), key=lambda p: p.as_posix().lower()):
        text = path.read_text(encoding="utf-8", errors="strict")
        if "quest_template" not in text.lower():
            continue
        statements = _strip_comments_and_split(text)
        relevant_statements = [
            statement for statement in statements if _statement_targets_quest_template(statement)
        ]
        if not relevant_statements:
            continue
        relevant_migrations.append(path)
        relative = path.relative_to(repository).as_posix()
        inputs.append(SourceInput(relative, sha256_file(path)))
        for statement in relevant_statements:
            parsed_schema = _parse_create_columns(statement)
            if parsed_schema:
                raise UnsupportedQuestSQL(
                    f"migration {relative} attempts quest_template CREATE TABLE; unsupported"
                )
            parsed_insert = _parse_insert(statement, schema_columns)
            if parsed_insert is not None:
                operation, insert_rows, insert_columns = parsed_insert
                _apply_insert_rows(
                    operation=operation,
                    insert_rows=insert_rows,
                    insert_columns=insert_columns or schema_columns or [],
                    rows=rows,
                    context=f"migration {relative}",
                )
                continue
            if _apply_update(statement, rows):
                continue
            if _apply_delete(statement, rows):
                continue
            if _is_truncate(statement):
                rows.clear()
                continue
            if _safe_non_row_statement(statement):
                continue
            raise UnsupportedQuestSQL(
                f"unsupported quest_template mutation in {relative}: "
                + statement[:160].replace("\n", " ")
            )

    missing = sorted(selected.difference(rows)) if selected is not None else []
    revision = source_revision or detect_git_revision(repository) or "unknown"
    output_entries = sorted(rows) if selected is None else sorted(selected.intersection(rows))
    quests = {str(entry): _canonicalize_row(entry, rows[entry]) for entry in output_entries}
    result: dict[str, Any] = {
        "format": "octogamedb-p3-t05b-tortoise-v1",
        "source_key": SOURCE_TORTOISE,
        "source_repository": TORTOISE_REPOSITORY,
        "source_revision": revision,
        "base_path": TORTOISE_BASE_RELATIVE.as_posix(),
        "migration_root": TORTOISE_MIGRATIONS_RELATIVE.as_posix(),
        "relevant_migration_count": len(relevant_migrations),
        "inputs": [{"path": item.path, "sha256": item.sha256} for item in inputs],
        "content_hash": _content_set_hash(inputs),
        "missing_requested_quest_ids": missing,
        "quests": quests,
    }
    result["projection_hash"] = stable_hash(
        {key: value for key, value in result.items() if key != "projection_hash"}
    )
    return result

def _percent_decode(value: str) -> str:
    try:
        return unquote(value, encoding="utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise QuestSourceError("live probe metadata contains invalid UTF-8 percent escapes") from exc

def _parse_item_pairs(value: str) -> list[tuple[int, int]]:
    if not value:
        return []
    pairs: list[tuple[int, int]] = []
    for raw_pair in value.split(","):
        if not raw_pair:
            continue
        match = re.fullmatch(r"(\d+):(\d+)", raw_pair)
        if not match:
            raise QuestSourceError(f"malformed live item/count pair: {raw_pair}")
        item_id = int(match.group(1))
        count = int(match.group(2))
        if item_id > 0 and count > 0:
            pairs.append((item_id, count))
    return pairs


def _extract_probe_records(text: str) -> list[str]:
    # Addon records deliberately percent-escape metadata so a record never contains a quote.
    return re.findall(r'"(OQPB1\|[^"\r\n]*)"', text)


def _record_fields(record: str) -> dict[str, str]:
    if not record.startswith("OQPB1|"):
        raise QuestSourceError("unsupported live probe record version")
    fields: dict[str, str] = {}
    for part in record.split("|")[1:]:
        if "=" not in part:
            raise QuestSourceError(f"malformed live probe field: {part}")
        key, value = part.split("=", 1)
        if key in fields:
            raise QuestSourceError(f"duplicate live probe field: {key}")
        fields[key] = value
    return fields


def normalize_live_saved_variables(path: Path) -> dict[str, Any]:
    path = path.resolve()
    raw_bytes = path.read_bytes()
    text = raw_bytes.decode("utf-8", errors="strict")
    records = _extract_probe_records(text)
    if not records:
        raise QuestSourceError(f"no OQPB1 records found in SavedVariables: {path}")
    quests: dict[str, Any] = {}
    for raw_record in records:
        fields = _record_fields(raw_record)
        try:
            quest_id = int(fields["quest_id"])
        except (KeyError, ValueError) as exc:
            raise QuestSourceError("live probe record has invalid/missing quest_id") from exc
        status = fields.get("status", "unknown")
        required = _parse_item_pairs(fields.get("requirements", "")) if status == "success" else []
        rewards = _parse_item_pairs(fields.get("reward_items", "")) if status == "success" else []
        choices = _parse_item_pairs(fields.get("reward_choices", "")) if status == "success" else []
        src_item_id = 0
        if status == "success" and fields.get("src_item_id", ""):
            try:
                src_item_id = int(fields["src_item_id"])
            except ValueError as exc:
                raise QuestSourceError("live probe src_item_id is not an integer") from exc
        evidence: list[dict[str, Any]] = []
        for family, pairs in (
            ("required_item", required),
            ("reward_item", rewards),
            ("choice_reward_item", choices),
        ):
            for slot, (item_id, count) in enumerate(pairs, start=1):
                evidence.append(
                    {
                        "fact_family": family,
                        "fact_key": f"{family}:{item_id}",
                        "item_id": item_id,
                        "value": count,
                        "slot": slot,
                    }
                )
        if src_item_id > 0:
            evidence.append(
                {
                    "fact_family": "source_item_id",
                    "fact_key": "source_item_id",
                    "item_id": src_item_id,
                    "value": src_item_id,
                    "slot": None,
                }
            )
        quests[str(quest_id)] = {
            "quest_id": quest_id,
            "status": status,
            "error": _percent_decode(fields.get("error", "")) or None,
            "capture_metadata": {
                "captured_at": _percent_decode(fields.get("captured_at", "")) or None,
                "realm": _percent_decode(fields.get("realm", "")) or None,
                "client_build": _percent_decode(fields.get("client_build", "")) or None,
                "classicapi_revision": _percent_decode(fields.get("classicapi_revision", ""))
                or CLASSICAPI_PINNED_REVISION,
            },
            "required_items": {
                "status": "observed_positive" if required else "unknown",
                "items": [{"item_id": item, "count": count} for item, count in required],
            },
            "reward_items": {
                "status": "observed_positive" if rewards else "unknown",
                "items": [{"item_id": item, "count": count} for item, count in rewards],
            },
            "choice_reward_items": {
                "status": "observed_positive" if choices else "unknown",
                "items": [{"item_id": item, "count": count} for item, count in choices],
            },
            "source_item": {
                "id_status": "observed_positive" if src_item_id > 0 else "unknown",
                "item_id": src_item_id if src_item_id > 0 else None,
                "count_status": "unknown",
                "count": None,
            },
            "required_sources": {"status": "unknown", "items": []},
            "evidence": evidence,
            "record_hash": hashlib.sha256(raw_record.encode("utf-8")).hexdigest(),
        }
    ordered_quests = {key: quests[key] for key in sorted(quests, key=int)}
    result: dict[str, Any] = {
        "format": "octogamedb-p3-t05b-live-v1",
        "source_key": SOURCE_LIVE,
        "source_repository": CLASSICAPI_REPOSITORY,
        "semantic_reference_revision": CLASSICAPI_PINNED_REVISION,
        "raw_saved_variables_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "record_count": len(records),
        "quests": ordered_quests,
    }
    result["capture_hash"] = stable_hash({key: value for key, value in result.items() if key != "capture_hash"})
    return result


def load_evidence_csv(path: Path, *, source_key: str, source_revision: str) -> dict[str, Any]:
    if source_key not in {SOURCE_OCTODB, SOURCE_CMANGOS}:
        raise QuestSourceError(
            "CSV evidence snapshots are restricted to octodb or cmangos-vanilla in P3-T05B"
        )
    path = path.resolve()
    quests: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = ["quest_id", "fact_family", "item_id", "value", "slot"]
        if (reader.fieldnames or []) != required:
            raise QuestSourceError(
                "evidence CSV header must be exactly: quest_id,fact_family,item_id,value,slot"
            )
        for line_number, row in enumerate(reader, start=2):
            try:
                quest_id = int(row["quest_id"] or "")
                family = row["fact_family"] or ""
                item_id = int(row["item_id"] or "0")
                value = int(row["value"] or "")
                slot = int(row["slot"]) if row["slot"] else None
            except ValueError as exc:
                raise QuestSourceError(f"invalid integer in evidence CSV line {line_number}") from exc
            if family not in _PRIORITY or source_key not in _PRIORITY[family]:
                raise QuestSourceError(
                    f"source {source_key} is not eligible for {family!r} on CSV line {line_number}"
                )
            if quest_id <= 0:
                raise QuestSourceError(f"invalid quest_id on CSV line {line_number}")
            if family == "source_item_id":
                if item_id <= 0 or value != item_id:
                    raise QuestSourceError(
                        f"source_item_id line {line_number} requires positive item_id == value"
                    )
                fact_key = "source_item_id"
            else:
                if item_id <= 0:
                    raise QuestSourceError(f"positive item_id required on CSV line {line_number}")
                if value < 0:
                    raise QuestSourceError(f"non-negative value required on CSV line {line_number}")
                fact_key = f"{family}:{item_id}"
            quest = quests.setdefault(str(quest_id), {"quest_id": quest_id, "evidence": []})
            quest["evidence"].append(
                {
                    "fact_family": family,
                    "fact_key": fact_key,
                    "item_id": item_id,
                    "value": value,
                    "slot": slot,
                }
            )
    ordered_quests = {key: quests[key] for key in sorted(quests, key=int)}
    result: dict[str, Any] = {
        "format": "octogamedb-p3-t05b-evidence-csv-v1",
        "source_key": source_key,
        "source_revision": source_revision,
        "input_sha256": sha256_file(path),
        "quests": ordered_quests,
    }
    result["projection_hash"] = stable_hash(
        {key: value for key, value in result.items() if key != "projection_hash"}
    )
    return result


_PRIORITY: dict[str, dict[str, int]] = {
    "required_item": {SOURCE_LIVE: 40, SOURCE_OCTODB: 30, SOURCE_TORTOISE: 20, SOURCE_CMANGOS: 10},
    "reward_item": {SOURCE_LIVE: 40, SOURCE_OCTODB: 30, SOURCE_TORTOISE: 20, SOURCE_CMANGOS: 10},
    "choice_reward_item": {
        SOURCE_LIVE: 40,
        SOURCE_OCTODB: 30,
        SOURCE_TORTOISE: 20,
        SOURCE_CMANGOS: 10,
    },
    "source_item_id": {SOURCE_LIVE: 40, SOURCE_OCTODB: 30, SOURCE_TORTOISE: 20, SOURCE_CMANGOS: 10},
    "source_item_count": {SOURCE_OCTODB: 30, SOURCE_TORTOISE: 20, SOURCE_CMANGOS: 10},
    "required_source": {SOURCE_TORTOISE: 20, SOURCE_CMANGOS: 10},
}


def compare_source_snapshots(snapshots: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: dict[int, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    quest_observations: dict[int, list[dict[str, Any]]] = defaultdict(list)
    seen_quest_ids: set[int] = set()
    input_sources: list[dict[str, Any]] = []
    for snapshot in snapshots:
        source_key = str(snapshot.get("source_key", ""))
        if source_key not in {SOURCE_LIVE, SOURCE_OCTODB, SOURCE_TORTOISE, SOURCE_CMANGOS}:
            raise QuestSourceError(f"unsupported comparison source_key: {source_key!r}")
        input_sources.append(
            {
                "source_key": source_key,
                "source_revision": snapshot.get("source_revision")
                or snapshot.get("semantic_reference_revision"),
                "content_hash": snapshot.get("content_hash")
                or snapshot.get("capture_hash")
                or snapshot.get("projection_hash"),
            }
        )
        quests = snapshot.get("quests", {})
        if not isinstance(quests, Mapping):
            raise QuestSourceError(f"{source_key} snapshot quests must be an object")
        for raw_quest_id, quest in quests.items():
            quest_id = int(raw_quest_id)
            seen_quest_ids.add(quest_id)
            if not isinstance(quest, Mapping):
                raise QuestSourceError(f"quest {quest_id} in {source_key} must be an object")
            observation: dict[str, Any] = {"source_key": source_key}
            if "status" in quest:
                observation["status"] = quest.get("status")
            for field in ("required_items", "reward_items", "choice_reward_items", "required_sources"):
                family_value = quest.get(field)
                if isinstance(family_value, Mapping) and "status" in family_value:
                    observation[f"{field}_status"] = family_value.get("status")
            source_item = quest.get("source_item")
            if isinstance(source_item, Mapping):
                if "id_status" in source_item:
                    observation["source_item_id_status"] = source_item.get("id_status")
                if "count_status" in source_item:
                    observation["source_item_count_status"] = source_item.get("count_status")
            quest_observations[quest_id].append(observation)
            evidence = quest.get("evidence", [])
            if not isinstance(evidence, list):
                raise QuestSourceError(f"quest {quest_id} evidence in {source_key} must be a list")
            for item in evidence:
                if not isinstance(item, Mapping):
                    raise QuestSourceError("comparison evidence must be objects")
                family = str(item.get("fact_family", ""))
                fact_key = str(item.get("fact_key", ""))
                if family not in _PRIORITY:
                    raise QuestSourceError(f"unsupported fact family: {family!r}")
                if source_key not in _PRIORITY[family]:
                    raise QuestSourceError(
                        f"source {source_key} is not eligible evidence for fact family {family}"
                    )
                if not fact_key:
                    raise QuestSourceError("comparison evidence requires fact_key")
                observed = dict(item)
                observed["source_key"] = source_key
                observed["priority"] = _PRIORITY[family][source_key]
                grouped[quest_id][fact_key].append(observed)

    compared_quests: dict[str, Any] = {}
    for quest_id in sorted(seen_quest_ids):
        facts: dict[str, Any] = {}
        for fact_key in sorted(grouped[quest_id]):
            evidence = sorted(
                grouped[quest_id][fact_key],
                key=lambda item: (
                    -int(item["priority"]),
                    str(item["source_key"]),
                    -1 if item.get("slot") is None else int(item["slot"]),
                    json.dumps(item.get("value"), sort_keys=True),
                ),
            )
            highest = max(int(item["priority"]) for item in evidence)
            top = [item for item in evidence if int(item["priority"]) == highest]
            top_values = {_json_bytes(item.get("value")) for item in top}
            selected = None
            selection_status = "selected"
            if len(top_values) == 1:
                selected = {
                    "source_key": top[0]["source_key"],
                    "value": top[0].get("value"),
                    "priority": highest,
                }
            else:
                selection_status = "ambiguous_same_priority"
            all_values = {_json_bytes(item.get("value")) for item in evidence}
            facts[fact_key] = {
                "fact_family": evidence[0]["fact_family"],
                "selection_status": selection_status,
                "selected": selected,
                "conflict": len(all_values) > 1,
                "evidence": evidence,
            }
        compared_quests[str(quest_id)] = {
            "quest_id": quest_id,
            "facts": facts,
            "source_observations": sorted(
                quest_observations[quest_id], key=lambda item: str(item["source_key"])
            ),
        }
    result: dict[str, Any] = {
        "format": "octogamedb-p3-t05b-comparison-v1",
        "priority_contract": {
            family: [
                source
                for source, _ in sorted(priorities.items(), key=lambda item: -item[1])
            ]
            for family, priorities in _PRIORITY.items()
        },
        "sources": input_sources,
        "quests": compared_quests,
    }
    result["comparison_hash"] = stable_hash(
        {key: value for key, value in result.items() if key != "comparison_hash"}
    )
    return result


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
