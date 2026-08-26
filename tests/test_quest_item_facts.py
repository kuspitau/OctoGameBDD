from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from octogamedb.db import apply_migrations, connect_database
from octogamedb.db.provenance import record_relation_observation, select_canonical_observation
from octogamedb.importers.quest_item_facts import reconcile_quest_item_facts
from octogamedb.quest_items import quest_item_facts_by_id


def _slot_rows(count: int, entries: dict[int, tuple[int, int]]) -> list[dict[str, Any]]:
    return [
        {
            "slot": slot,
            "item_id": entries.get(slot, (0, 0))[0],
            "count": entries.get(slot, (0, 0))[1],
        }
        for slot in range(1, count + 1)
    ]


def _tortoise_snapshot(
    revision: str,
    *,
    quest_id: int = 100,
    required: dict[int, tuple[int, int]] | None = None,
    required_sources: dict[int, tuple[int, int]] | None = None,
    source_item: tuple[int, int] | None = None,
    rewards: dict[int, tuple[int, int]] | None = None,
    choices: dict[int, tuple[int, int]] | None = None,
) -> dict[str, Any]:
    required = required or {}
    required_sources = required_sources or {}
    rewards = rewards or {}
    choices = choices or {}
    evidence: list[dict[str, Any]] = []
    for family, entries in (
        ("required_item", required),
        ("required_source", required_sources),
        ("reward_item", rewards),
        ("choice_reward_item", choices),
    ):
        for slot, (item_id, value) in entries.items():
            evidence.append(
                {
                    "fact_family": family,
                    "fact_key": f"{family}:{item_id}",
                    "item_id": item_id,
                    "value": value,
                    "slot": slot,
                }
            )
    source = {"item_id": 0, "count": 0, "id_present": True, "count_present": True}
    if source_item is not None:
        item_id, count = source_item
        source = {"item_id": item_id, "count": count, "id_present": True, "count_present": True}
        evidence.extend(
            [
                {
                    "fact_family": "source_item_id",
                    "fact_key": "source_item_id",
                    "item_id": item_id,
                    "value": item_id,
                    "slot": None,
                },
                {
                    "fact_family": "source_item_count",
                    "fact_key": f"source_item_count:{item_id}",
                    "item_id": item_id,
                    "value": count,
                    "slot": None,
                },
            ]
        )
    return {
        "format": "octogamedb-p3-t05b-tortoise-v1",
        "source_key": "tortoise-world-sql",
        "source_revision": revision,
        "content_hash": f"content-{revision}",
        "projection_hash": f"projection-{revision}",
        "quests": {
            str(quest_id): {
                "quest_id": quest_id,
                "required_items": _slot_rows(4, required),
                "required_sources": _slot_rows(4, required_sources),
                "source_item": source,
                "reward_items": _slot_rows(4, rewards),
                "choice_reward_items": _slot_rows(6, choices),
                "evidence": evidence,
            }
        },
    }


def _live_snapshot(
    capture: str,
    *,
    quest_id: int = 100,
    evidence: list[dict[str, Any]] | None = None,
    source_item_id: int | None = None,
) -> dict[str, Any]:
    evidence = list(evidence or [])
    required_positive = any(row["fact_family"] == "required_item" for row in evidence)
    reward_positive = any(row["fact_family"] == "reward_item" for row in evidence)
    choice_positive = any(row["fact_family"] == "choice_reward_item" for row in evidence)
    if source_item_id is not None:
        evidence.append(
            {
                "fact_family": "source_item_id",
                "fact_key": "source_item_id",
                "item_id": source_item_id,
                "value": source_item_id,
                "slot": None,
            }
        )
    return {
        "format": "octogamedb-p3-t05b-live-v1",
        "source_key": "octo-live-quest-query",
        "semantic_reference_revision": "classicapi-test",
        "capture_hash": capture,
        "quests": {
            str(quest_id): {
                "quest_id": quest_id,
                "status": "success",
                "required_items": {
                    "status": "observed_positive" if required_positive else "unknown",
                    "items": [],
                },
                "required_sources": {"status": "unknown", "items": []},
                "reward_items": {
                    "status": "observed_positive" if reward_positive else "unknown",
                    "items": [],
                },
                "choice_reward_items": {
                    "status": "observed_positive" if choice_positive else "unknown",
                    "items": [],
                },
                "source_item": {
                    "id_status": "observed_positive" if source_item_id else "unknown",
                    "item_id": source_item_id,
                    "count_status": "unknown",
                    "count": None,
                },
                "evidence": evidence,
            }
        },
    }


def _reviewed_snapshot(
    source_key: str, revision: str, evidence: list[dict[str, Any]], *, quest_id: int = 100
) -> dict[str, Any]:
    return {
        "format": "octogamedb-p3-t05b-evidence-csv-v1",
        "source_key": source_key,
        "source_revision": revision,
        "projection_hash": f"projection-{source_key}-{revision}",
        "quests": {str(quest_id): {"quest_id": quest_id, "evidence": evidence}},
    }


@contextmanager
def _open_db(tmp_path, *, item_ids: range | tuple[int, ...] = range(1, 20)):
    db_path = tmp_path / "p3-t05.sqlite3"
    with connect_database(db_path) as connection:
        apply_migrations(connection)
        connection.execute("INSERT INTO quests(quest_id, name) VALUES (100, 'Quest 100')")
        connection.executemany(
            "INSERT INTO items(item_id, name) VALUES (?, ?)",
            [(item_id, f"Item {item_id}") for item_id in item_ids],
        )
        yield connection


def test_migration_materializes_distinct_families_and_reqsource_zero(tmp_path):
    with _open_db(tmp_path) as connection:
        connection.execute("INSERT INTO quest_item_objectives(quest_id, item_id) VALUES (100, 1)")
        connection.execute("INSERT INTO quest_item_objectives(quest_id, item_id) VALUES (100, 9)")
        snapshot = _tortoise_snapshot(
            "r1",
            required={1: (1, 3)},
            required_sources={1: (2, 0)},
            source_item=(3, 2),
            rewards={1: (1, 1), 2: (4, 1)},
            choices={1: (1, 5), 2: (5, 2), 3: (6, 1)},
        )
        summary = reconcile_quest_item_facts(connection, snapshots=[snapshot])
        view = quest_item_facts_by_id(connection, 100)

        assert summary.status == "succeeded"
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 10
        assert view["required_items"][0]["quantity"] == 3
        assert view["required_items"][0]["objective_membership"] is True
        assert view["required_sources"][0]["raw_source_count"] == 0
        assert view["provided_item"]["item_id"] == 3
        assert view["provided_item"]["quantity"] == 2
        assert {row["item_id"] for row in view["guaranteed_rewards"]} == {1, 4}
        assert {row["item_id"] for row in view["choice_rewards"]["items"]} == {1, 5, 6}
        assert view["objective_membership"]["objective_only_item_ids"] == [9]
        assert view["objective_membership"]["equivalence_assumed"] is False
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_partial_live_positive_overrides_without_absence_deletion_or_downgrade(tmp_path):
    with _open_db(tmp_path) as connection:
        tortoise = _tortoise_snapshot("r1", required={1: (1, 3), 2: (2, 4)})
        live = _live_snapshot(
            "cap1",
            evidence=[
                {
                    "fact_family": "required_item",
                    "fact_key": "required_item:1",
                    "item_id": 1,
                    "value": 7,
                    "slot": 1,
                }
            ],
        )
        reconcile_quest_item_facts(connection, snapshots=[tortoise, live])
        assert dict(
            connection.execute(
                "SELECT item_id, quantity FROM quest_required_items WHERE quest_id = 100"
            ).fetchall()
        ) == {1: 7, 2: 4}

        live_unknown = _live_snapshot("cap2")
        second = reconcile_quest_item_facts(connection, snapshots=[tortoise, live_unknown])
        assert dict(
            connection.execute(
                "SELECT item_id, quantity FROM quest_required_items WHERE quest_id = 100"
            ).fetchall()
        ) == {1: 7, 2: 4}
        assert second.rows_updated == 0


def test_complete_tortoise_set_removes_stale_managed_fallback(tmp_path):
    with _open_db(tmp_path) as connection:
        reconcile_quest_item_facts(
            connection, snapshots=[_tortoise_snapshot("r1", required={1: (1, 2)})]
        )
        assert connection.execute("SELECT COUNT(*) FROM quest_required_items").fetchone()[0] == 1

        summary = reconcile_quest_item_facts(
            connection, snapshots=[_tortoise_snapshot("r2", required={})]
        )
        assert connection.execute("SELECT COUNT(*) FROM quest_required_items").fetchone()[0] == 0
        assert summary.details["canonical_rows_deleted"] >= 1


def test_unresolved_item_stays_explicit_in_provenance_and_read_model(tmp_path):
    with _open_db(tmp_path, item_ids=(1, 2, 3)) as connection:
        summary = reconcile_quest_item_facts(
            connection,
            snapshots=[
                _tortoise_snapshot(
                    "r1", required={1: (99, 2)}, choices={1: (98, 1)}
                )
            ],
        )
        view = quest_item_facts_by_id(connection, 100)
        assert connection.execute("SELECT COUNT(*) FROM quest_required_items").fetchone()[0] == 0
        assert view["required_items"][0]["item_id"] == 99
        assert view["required_items"][0]["resolved"] is False
        assert view["choice_rewards"]["selected_member_count"] == 1
        assert view["choice_rewards"]["materialized_member_count"] == 0
        assert view["choice_rewards"]["items"][0]["item_id"] == 98
        assert view["choice_rewards"]["items"][0]["resolved"] is False
        assert any(
            row.get("item_id") == 99
            for row in summary.details["unresolved_item_or_quest_targets"]
        )


def test_custom_selection_is_protected_and_remains_materialized(tmp_path):
    with _open_db(tmp_path) as connection:
        reconcile_quest_item_facts(
            connection, snapshots=[_tortoise_snapshot("r1", required={1: (1, 3)})]
        )
        source_id = connection.execute(
            "INSERT INTO data_sources(source_key, display_name, source_kind) VALUES "
            "('manual-test', 'Manual test', 'manual')"
        ).lastrowid
        batch_id = connection.execute(
            """
            INSERT INTO import_batches(source_id, source_revision, status, finished_at,
                                       importer_version, rows_read, rows_accepted)
            VALUES (?, 'manual-r1', 'succeeded', '2026-08-26T00:00:00Z', 'test', 1, 1)
            """,
            (source_id,),
        ).lastrowid
        observation_id = record_relation_observation(
            connection,
            subject_kind="quest",
            subject_key=100,
            fact_key="quest_required_item",
            import_batch_id=int(batch_id),
            target_kind="item",
            target_key=1,
            relation_instance_key="1",
            attributes={"quantity": 9, "source_slots": [1]},
        )
        group_id = connection.execute(
            "SELECT observation_group_id FROM source_observations WHERE id = ?", (observation_id,)
        ).fetchone()[0]
        select_canonical_observation(
            connection,
            observation_group_id=int(group_id),
            observation_id=observation_id,
            selection_policy="manual-explicit",
            selection_reason="test protected selection",
        )

        summary = reconcile_quest_item_facts(
            connection, snapshots=[_tortoise_snapshot("r2", required={1: (1, 4)})]
        )
        assert connection.execute(
            "SELECT quantity FROM quest_required_items WHERE quest_id = 100 AND item_id = 1"
        ).fetchone()[0] == 9
        assert summary.details["protected_selection_events"]


def test_same_item_across_slots_and_families_preserves_evidence_without_silent_merge(tmp_path):
    with _open_db(tmp_path) as connection:
        octodb = _reviewed_snapshot(
            "octodb",
            "octodb-r1",
            [
                {
                    "fact_family": "required_item",
                    "fact_key": "required_item:1",
                    "item_id": 1,
                    "value": 2,
                    "slot": 1,
                },
                {
                    "fact_family": "required_item",
                    "fact_key": "required_item:1",
                    "item_id": 1,
                    "value": 5,
                    "slot": 2,
                },
                {
                    "fact_family": "reward_item",
                    "fact_key": "reward_item:1",
                    "item_id": 1,
                    "value": 1,
                    "slot": 1,
                },
            ],
        )
        summary = reconcile_quest_item_facts(
            connection,
            snapshots=[_tortoise_snapshot("r1", required={1: (1, 1)}), octodb],
        )
        view = quest_item_facts_by_id(connection, 100)
        assert summary.details["ambiguous_same_priority"]
        set_value = connection.execute(
            """
            SELECT so.value_json
            FROM observation_groups AS og
            JOIN source_observations AS so ON so.observation_group_id = og.id
            JOIN data_sources AS ds ON ds.id = so.source_id
            WHERE og.subject_kind='quest' AND og.subject_key='100'
              AND og.fact_key='quest_required_item_set' AND ds.source_key='octodb'
            """
        ).fetchone()[0]
        assert '"slot":1' in set_value and '"slot":2' in set_value
        assert {row["item_id"] for row in view["guaranteed_rewards"]} == {1}
        assert view["required_items"] == []
        assert connection.execute(
            "SELECT COUNT(*) FROM quest_required_items WHERE quest_id = 100"
        ).fetchone()[0] == 0
        assert view["conflicts"]


def test_duplicate_same_value_slots_are_independent_provenance_before_normalization(tmp_path):
    with _open_db(tmp_path) as connection:
        octodb = _reviewed_snapshot(
            "octodb",
            "octodb-r1",
            [
                {
                    "fact_family": "required_item",
                    "fact_key": "required_item:1",
                    "item_id": 1,
                    "value": 2,
                    "slot": 1,
                },
                {
                    "fact_family": "required_item",
                    "fact_key": "required_item:1",
                    "item_id": 1,
                    "value": 2,
                    "slot": 2,
                },
            ],
        )
        reconcile_quest_item_facts(
            connection,
            snapshots=[_tortoise_snapshot("r1", required={1: (1, 2)}), octodb],
        )
        view = quest_item_facts_by_id(connection, 100)

        required = view["required_items"]
        assert len(required) == 1
        assert required[0]["item_id"] == 1
        assert required[0]["quantity"] == 2
        assert required[0]["source_slots"] == [1, 2]
        assert [row["source_slot"] for row in required[0]["source_evidence"]] == [1, 2]
        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM source_observations AS so
            JOIN observation_groups AS og ON og.id = so.observation_group_id
            JOIN data_sources AS ds ON ds.id = so.source_id
            WHERE og.subject_kind='quest' AND og.subject_key='100'
              AND og.fact_key='quest_required_item' AND og.fact_instance_key='1'
              AND ds.source_key='octodb'
            """
        ).fetchone()[0] == 2
        assert view["conflicts"] == []


def test_new_same_priority_ambiguity_clears_stale_managed_materialization(tmp_path):
    with _open_db(tmp_path) as connection:
        reconcile_quest_item_facts(
            connection, snapshots=[_tortoise_snapshot("r1", required={1: (1, 1)})]
        )
        assert connection.execute(
            "SELECT quantity FROM quest_required_items WHERE quest_id = 100 AND item_id = 1"
        ).fetchone()[0] == 1

        ambiguous_octodb = _reviewed_snapshot(
            "octodb",
            "octodb-r1",
            [
                {
                    "fact_family": "required_item",
                    "fact_key": "required_item:1",
                    "item_id": 1,
                    "value": 2,
                    "slot": 1,
                },
                {
                    "fact_family": "required_item",
                    "fact_key": "required_item:1",
                    "item_id": 1,
                    "value": 5,
                    "slot": 2,
                },
            ],
        )
        summary = reconcile_quest_item_facts(
            connection,
            snapshots=[_tortoise_snapshot("r2", required={1: (1, 1)}), ambiguous_octodb],
        )
        view = quest_item_facts_by_id(connection, 100)

        assert summary.details["ambiguous_same_priority"]
        assert summary.details["canonical_rows_deleted"] >= 1
        assert connection.execute(
            "SELECT COUNT(*) FROM quest_required_items WHERE quest_id = 100 AND item_id = 1"
        ).fetchone()[0] == 0
        assert view["required_items"] == []
        assert view["conflicts"]


def test_live_source_item_without_count_stays_unknown(tmp_path):
    with _open_db(tmp_path) as connection:
        summary = reconcile_quest_item_facts(
            connection, snapshots=[_live_snapshot("cap1", source_item_id=3)]
        )
        view = quest_item_facts_by_id(connection, 100)
        assert summary.status == "succeeded"
        assert view["provided_item"]["item_id"] == 3
        assert view["provided_item"]["quantity"] is None
        assert view["provided_item"]["quantity_status"] == "unknown"


def test_same_revision_reconciliation_is_canonically_idempotent(tmp_path):
    with _open_db(tmp_path) as connection:
        snapshots = [
            _tortoise_snapshot(
                "r1",
                required={1: (1, 2)},
                required_sources={1: (2, 0)},
                source_item=(3, 1),
                rewards={1: (4, 1)},
                choices={1: (5, 1)},
            )
        ]
        first = reconcile_quest_item_facts(connection, snapshots=snapshots)
        second = reconcile_quest_item_facts(connection, snapshots=snapshots)
        assert first.rows_inserted > 0
        assert second.rows_inserted == 0
        assert second.rows_updated == 0
        assert second.details["canonical_rows_deleted"] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
