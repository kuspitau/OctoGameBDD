"""SQLite connection helpers owned by OctoGameDB."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB_PATH = Path("data/generated/octogamedb.sqlite3")


def _prepare_parent(path: str | Path) -> None:
    if str(path) == ":memory:":
        return

    db_path = Path(path).expanduser()
    parent = db_path.parent
    if parent != Path("."):
        parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def connect_database(path: str | Path = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    """Open a SQLite connection with project-required safety settings.

    The connection is committed on normal context exit, rolled back on errors,
    and always closed. Parent directories are created for file-backed databases.
    """

    _prepare_parent(path)
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
