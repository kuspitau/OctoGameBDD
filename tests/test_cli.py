from __future__ import annotations

import hashlib
import json
from pathlib import Path

from octogamedb.__main__ import main
from octogamedb.db import connect_database
from octogamedb.db.migrations import discover_migrations


def test_status_command_smoke(tmp_path, capsys):
    db_path = tmp_path / "status.sqlite3"
    migrations = discover_migrations()
    expected_version = migrations[-1].version
    expected_count = len(migrations)

    assert main(["status", "--db", str(db_path)]) == 0
    output = capsys.readouterr().out
    assert f"Database: {db_path}" in output
    assert f"Schema version: {expected_version}" in output
    assert f"Applied migrations: {expected_count}" in output
    assert "Registered sources: 0" in output
    assert "Import batches: 0" in output

    with connect_database(db_path) as connection:
        migration_count = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone()[0]
        assert migration_count == expected_count


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

    assert main(["resolution", "--db", db_path, "--json"]) == 0
    resolution = json.loads(capsys.readouterr().out)
    assert resolution["scope"] == "provenance-resolution"
    assert resolution["selected_group_count"] == 1
    assert resolution["unresolved_conflict_group_count"] == 1

    assert main(
        ["resolution", "--subject-kind", "item", "--fact", "name", "--db", db_path, "--json"]
    ) == 0
    resolution = json.loads(capsys.readouterr().out)
    assert resolution["observation_group_count"] == 1
    assert resolution["resolved_conflict_group_count"] == 1

    assert main(["unselected", "--limit", "0", "--db", db_path, "--json"]) == 0
    unselected = json.loads(capsys.readouterr().out)
    assert unselected["scope"] == "unselected-single-value"
    assert unselected["group_count"] == 3
    assert unselected["returned_group_count"] == 0
    assert unselected["groups"] == []

    assert main(
        ["unselected", "--subject-kind", "item", "--source", "source-a", "--db", db_path, "--json"]
    ) == 0
    unselected = json.loads(capsys.readouterr().out)
    assert unselected["group_count"] == 1
    assert unselected["groups"][0]["fact_key"] == "quality"


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

    assert main(["resolution", "--db", db_path]) == 0
    output = capsys.readouterr().out
    assert "Resolution scope: provenance-resolution" in output
    assert "Selected groups: 1" in output
    assert "Unselected single-value groups: 3" in output
    assert "Resolved conflicts: 1" in output
    assert "Unresolved conflicts: 1" in output
    assert "fixture-source-priority/v1: selected=1, conflicts=1" in output
    assert "source-b: selected=1, conflicts=1" in output

    assert main(["unselected", "--limit", "1", "--db", db_path]) == 0
    output = capsys.readouterr().out
    assert "Unselected scope: unselected-single-value" in output
    assert "Matched single-value unselected groups: 3" in output
    assert "Detailed groups returned: 1" in output
    assert "Unresolved classification: 3" in output
    assert "creature.loot.item (relation): groups=2" in output
    assert "source-a: groups=3, observations=3" in output


def test_resolution_cli_does_not_change_existing_database(golden_audit_case, capsys):
    db_path = Path(golden_audit_case["db_path"])
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert main(["resolution", "--db", str(db_path), "--json"]) == 0
    capsys.readouterr()
    after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert after == before


def test_unselected_cli_does_not_change_existing_database(golden_audit_case, capsys):
    db_path = Path(golden_audit_case["db_path"])
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert main(["unselected", "--limit", "0", "--db", str(db_path), "--json"]) == 0
    capsys.readouterr()
    after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert after == before
