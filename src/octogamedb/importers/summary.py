"""Machine-readable import summary primitives shared by future source importers."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ImportSummary:
    """Stable importer result payload suitable for CLI, tests, and saved artifacts."""

    source_key: str
    source_revision: str | None
    status: str
    rows_read: int
    rows_accepted: int
    rows_skipped: int
    rows_inserted: int
    rows_updated: int
    warning_count: int
    error_count: int
    details: Any = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary with a stable field contract."""

        return asdict(self)

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize deterministically for machine-readable handoff/audit output."""

        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            indent=indent,
            sort_keys=True,
        )

    def write_json(self, path: str | Path) -> None:
        """Write the summary as UTF-8 JSON, creating parent directories when needed."""

        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(self.to_json() + "\n", encoding="utf-8")


def _decode_details(details_json: str | None) -> Any:
    if details_json is None:
        return None
    try:
        return json.loads(details_json)
    except json.JSONDecodeError:
        return {"invalid_details_json": details_json}


def import_summary_for_batch(connection: sqlite3.Connection, batch_id: int) -> ImportSummary:
    """Build a stable summary payload for one persisted import batch."""

    row = connection.execute(
        """
        SELECT
            ds.source_key,
            ib.source_revision,
            ib.status,
            ib.rows_read,
            ib.rows_accepted,
            ib.rows_skipped,
            ib.rows_inserted,
            ib.rows_updated,
            ib.warning_count,
            ib.error_count,
            ib.details_json
        FROM import_batches AS ib
        JOIN data_sources AS ds ON ds.id = ib.source_id
        WHERE ib.id = ?
        """,
        (batch_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown import batch: {batch_id}")

    return ImportSummary(
        source_key=str(row["source_key"]),
        source_revision=None if row["source_revision"] is None else str(row["source_revision"]),
        status=str(row["status"]),
        rows_read=int(row["rows_read"]),
        rows_accepted=int(row["rows_accepted"]),
        rows_skipped=int(row["rows_skipped"]),
        rows_inserted=int(row["rows_inserted"]),
        rows_updated=int(row["rows_updated"]),
        warning_count=int(row["warning_count"]),
        error_count=int(row["error_count"]),
        details=_decode_details(row["details_json"]),
    )
