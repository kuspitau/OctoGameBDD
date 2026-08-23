"""Cross-domain provenance primitives for source evidence and canonical selection."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

_FACT_KINDS = frozenset({"scalar", "relation"})


def _required_text(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be blank")
    return normalized


def _optional_text(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, name)


def canonical_json(value: Any) -> str:
    """Serialize an observation payload deterministically for comparison/idempotency."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("observation value must be JSON-serializable") from exc


def get_or_create_observation_group(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_key: str | int,
    fact_key: str,
    fact_kind: str,
    fact_instance_key: str = "",
) -> int:
    """Return the stable evidence group for one subject fact/relation."""

    normalized_subject_kind = _required_text(subject_kind, "subject_kind")
    normalized_subject_key = _required_text(str(subject_key), "subject_key")
    normalized_fact_key = _required_text(fact_key, "fact_key")
    normalized_fact_kind = _required_text(fact_kind, "fact_kind")
    if normalized_fact_kind not in _FACT_KINDS:
        raise ValueError(f"fact_kind must be one of {sorted(_FACT_KINDS)!r}")
    normalized_instance_key = fact_instance_key.strip()
    if normalized_fact_kind == "scalar" and normalized_instance_key:
        raise ValueError("scalar facts must not use fact_instance_key")
    if normalized_fact_kind == "relation" and not normalized_instance_key:
        raise ValueError("relation facts require fact_instance_key")

    existing_kind = connection.execute(
        """
        SELECT fact_kind
        FROM observation_groups
        WHERE subject_kind = ? AND subject_key = ? AND fact_key = ?
        LIMIT 1
        """,
        (normalized_subject_kind, normalized_subject_key, normalized_fact_key),
    ).fetchone()
    if existing_kind is not None and existing_kind["fact_kind"] != normalized_fact_kind:
        raise ValueError(
            "existing observation group uses fact_kind "
            f"{existing_kind['fact_kind']!r}, not {normalized_fact_kind!r}"
        )

    connection.execute(
        """
        INSERT OR IGNORE INTO observation_groups(
            subject_kind, subject_key, fact_key, fact_kind, fact_instance_key
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            normalized_subject_kind,
            normalized_subject_key,
            normalized_fact_key,
            normalized_fact_kind,
            normalized_instance_key,
        ),
    )
    row = connection.execute(
        """
        SELECT id, fact_kind
        FROM observation_groups
        WHERE subject_kind = ?
          AND subject_key = ?
          AND fact_key = ?
          AND fact_instance_key = ?
        """,
        (
            normalized_subject_kind,
            normalized_subject_key,
            normalized_fact_key,
            normalized_instance_key,
        ),
    ).fetchone()
    if row is None:
        raise RuntimeError("observation group insert/select failed")
    if row["fact_kind"] != normalized_fact_kind:
        raise ValueError(
            "existing observation group uses fact_kind "
            f"{row['fact_kind']!r}, not {normalized_fact_kind!r}"
        )
    return int(row["id"])


def record_observation(
    connection: sqlite3.Connection,
    *,
    observation_group_id: int,
    import_batch_id: int,
    value: Any,
    source_record_type: str | None = None,
    raw_identifier: str | int | None = None,
    confidence: float | None = None,
    authority_tier: int | None = None,
) -> int:
    """Record stable source evidence and link the import batch that observed it."""

    normalized_record_type = _optional_text(source_record_type, "source_record_type")
    normalized_raw_identifier = (
        None if raw_identifier is None else _required_text(str(raw_identifier), "raw_identifier")
    )
    if confidence is not None and not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    if authority_tier is not None and authority_tier < 0:
        raise ValueError("authority_tier must be non-negative")

    batch = connection.execute(
        "SELECT source_id, source_revision FROM import_batches WHERE id = ?",
        (import_batch_id,),
    ).fetchone()
    if batch is None:
        raise ValueError(f"unknown import_batch_id: {import_batch_id}")

    source_id = int(batch["source_id"])
    source_revision = "" if batch["source_revision"] is None else str(batch["source_revision"])
    value_json = canonical_json(value)
    connection.execute(
        """
        INSERT OR IGNORE INTO source_observations(
            observation_group_id,
            source_id,
            source_revision,
            source_record_type,
            raw_identifier,
            value_json,
            confidence,
            authority_tier
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            observation_group_id,
            source_id,
            source_revision,
            normalized_record_type,
            normalized_raw_identifier,
            value_json,
            confidence,
            authority_tier,
        ),
    )
    row = connection.execute(
        """
        SELECT id
        FROM source_observations
        WHERE observation_group_id = ?
          AND source_id = ?
          AND source_revision = ?
          AND source_record_type IS ?
          AND raw_identifier IS ?
          AND value_json = ?
        """,
        (
            observation_group_id,
            source_id,
            source_revision,
            normalized_record_type,
            normalized_raw_identifier,
            value_json,
        ),
    ).fetchone()
    if row is None:
        raise RuntimeError("source observation insert/select failed")

    observation_id = int(row["id"])
    connection.execute(
        """
        INSERT OR IGNORE INTO observation_import_batches(observation_id, import_batch_id)
        VALUES (?, ?)
        """,
        (observation_id, import_batch_id),
    )
    return observation_id


def record_scalar_observation(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_key: str | int,
    fact_key: str,
    import_batch_id: int,
    value: Any,
    source_record_type: str | None = None,
    raw_identifier: str | int | None = None,
    confidence: float | None = None,
    authority_tier: int | None = None,
) -> int:
    """Record one scalar source fact against a stable evidence group."""

    group_id = get_or_create_observation_group(
        connection,
        subject_kind=subject_kind,
        subject_key=subject_key,
        fact_key=fact_key,
        fact_kind="scalar",
    )
    return record_observation(
        connection,
        observation_group_id=group_id,
        import_batch_id=import_batch_id,
        value=value,
        source_record_type=source_record_type,
        raw_identifier=raw_identifier,
        confidence=confidence,
        authority_tier=authority_tier,
    )


def record_relation_observation(
    connection: sqlite3.Connection,
    *,
    subject_kind: str,
    subject_key: str | int,
    fact_key: str,
    import_batch_id: int,
    target_kind: str,
    target_key: str | int,
    relation_instance_key: str | None = None,
    attributes: dict[str, Any] | None = None,
    source_record_type: str | None = None,
    raw_identifier: str | int | None = None,
    confidence: float | None = None,
    authority_tier: int | None = None,
) -> int:
    """Record relation-shaped source evidence without making it canonical domain storage."""

    payload: dict[str, Any] = {
        "target": {
            "kind": _required_text(target_kind, "target_kind"),
            "key": _required_text(str(target_key), "target_key"),
        }
    }
    if attributes is not None:
        payload["attributes"] = attributes

    normalized_relation_instance_key = (
        canonical_json(payload["target"])
        if relation_instance_key is None
        else _required_text(relation_instance_key, "relation_instance_key")
    )
    group_id = get_or_create_observation_group(
        connection,
        subject_kind=subject_kind,
        subject_key=subject_key,
        fact_key=fact_key,
        fact_kind="relation",
        fact_instance_key=normalized_relation_instance_key,
    )
    return record_observation(
        connection,
        observation_group_id=group_id,
        import_batch_id=import_batch_id,
        value=payload,
        source_record_type=source_record_type,
        raw_identifier=raw_identifier,
        confidence=confidence,
        authority_tier=authority_tier,
    )


def select_canonical_observation(
    connection: sqlite3.Connection,
    *,
    observation_group_id: int,
    observation_id: int,
    selection_reason: str,
    selection_policy: str | None = None,
) -> None:
    """Select the current canonical evidence winner while preserving all observations."""

    normalized_reason = _required_text(selection_reason, "selection_reason")
    normalized_policy = _optional_text(selection_policy, "selection_policy")
    connection.execute(
        """
        INSERT INTO canonical_selections(
            observation_group_id,
            observation_id,
            selection_policy,
            selection_reason
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(observation_group_id) DO UPDATE SET
            observation_id = excluded.observation_id,
            selection_policy = excluded.selection_policy,
            selection_reason = excluded.selection_reason,
            selected_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """,
        (
            observation_group_id,
            observation_id,
            normalized_policy,
            normalized_reason,
        ),
    )
