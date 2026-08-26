from __future__ import annotations

import json

from octogamedb.__main__ import main
from octogamedb.db import connect_database


def test_status_command_smoke(tmp_path, capsys):
    db_path = tmp_path / "status.sqlite3"

    assert main(["status", "--db", str(db_path)]) == 0

    output = capsys.readouterr().out
    assert f"Database: {db_path}" in output
    assert "Schema version: 10" in output
    assert "Applied migrations: 10" in output
    assert "Registered sources: 0" in output
    assert "Import batches: 0" in output

    with connect_database(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone()[0] == 10


def test_audit_cli_json_commands(golden_audit_case, capsys):
    db_path = str(golden_audit_case["db_path"])

    assert main(["coverage", "--db", db_path, "--json"]) == 0
    coverage = json.loads(capsys.readouterr().out)
    assert coverage == golden_audit_case["fixture"]["expected_coverage"]

    assert main(["conflict", "--db", db_path, "--json"]) == 0
    conflicts = json.loads(capsys.readouterr().out)
    assert conflicts["conflict_count"] == 2
    assert conflicts["unresolved_conflict_count"] == 1

    assert main(["trace", "item", "100", "--fact", "name", "--db", db_path, "--json"]) == 0
    trace = json.loads(capsys.readouterr().out)
    assert trace["group_count"] == 1
    assert trace["groups"][0]["fact_key"] == "name"

    assert main(["source", "source-a", "--db", db_path, "--json"]) == 0
    source = json.loads(capsys.readouterr().out)
    assert source["source_count"] == 1
    assert source["sources"][0]["source_key"] == "source-a"


def test_audit_cli_human_output(golden_audit_case, capsys):
    db_path = str(golden_audit_case["db_path"])

    assert main(["coverage", "--db", db_path]) == 0
    output = capsys.readouterr().out
    assert "Coverage scope: generic-provenance" in output
    assert "Unresolved conflicts: 1" in output

    assert main(["conflict", "--db", db_path]) == 0
    output = capsys.readouterr().out
    assert "Conflicts: 2" in output
    assert "quest:99 giver [giver-slot-1]: 2 values (unresolved)" in output
