from __future__ import annotations

from octogamedb.__main__ import main
from octogamedb.db import connect_database


def test_status_command_smoke(tmp_path, capsys):
    db_path = tmp_path / "status.sqlite3"

    assert main(["status", "--db", str(db_path)]) == 0

    output = capsys.readouterr().out
    assert f"Database: {db_path}" in output
    assert "Schema version: 1" in output
    assert "Applied migrations: 1" in output
    assert "Registered sources: 0" in output
    assert "Import batches: 0" in output

    with connect_database(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone()[0] == 1
