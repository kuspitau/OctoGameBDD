from __future__ import annotations

import json
import sqlite3

import pytest

from octogamedb.db import (
    apply_migrations,
    canonical_json,
    connect_database,
    get_or_create_observation_group,
    record_relation_observation,
    record_scalar_observation,
    select_canonical_observation,
)


def _batch_for_source(connection, source_id: int, revision: str | None) -> int:
    batch = connection.execute(
        """
        INSERT INTO import_batches(
            source_id, source_revision, status, finished_at, rows_read, rows_accepted
        )
        VALUES (?, ?, 'succeeded', '2026-08-24T00:00:00Z', 1, 1)
        """,
        (source_id, revision),
    )
    return int(batch.lastrowid)


def _source_and_batch(
    connection, source_key: str, revision: str | None
) -> tuple[int, int]:
    source = connection.execute(
        """
        INSERT INTO data_sources(source_key, display_name, source_kind)
        VALUES (?, ?, 'fixture')
        """,
        (source_key, source_key),
    )
    source_id = int(source.lastrowid)
    return source_id, _batch_for_source(connection, source_id, revision)


def test_canonical_json_is_deterministic_and_rejects_nan():
    assert canonical_json({"b": 2, "a": [1, True]}) == '{"a":[1,true],"b":2}'

    with pytest.raises(ValueError):
        canonical_json(float("nan"))


def test_scalar_observations_are_idempotent_and_preserve_conflicts(tmp_path):
    db_path = tmp_path / "provenance.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        source_a, batch_a = _source_and_batch(connection, "source-a", "rev-a")
        repeated_batch_a = _batch_for_source(connection, source_a, "rev-a")
        _, batch_b = _source_and_batch(connection, "source-b", "rev-b")

        first_id = record_scalar_observation(
            connection,
            subject_kind="item",
            subject_key=100,
            fact_key="name",
            import_batch_id=batch_a,
            value="Copper Widget",
            source_record_type="item",
            raw_identifier=100,
            confidence=0.9,
            authority_tier=1,
        )
        repeated_id = record_scalar_observation(
            connection,
            subject_kind="item",
            subject_key="100",
            fact_key="name",
            import_batch_id=repeated_batch_a,
            value="Copper Widget",
            source_record_type="item",
            raw_identifier="100",
            confidence=0.2,
            authority_tier=9,
        )
        conflicting_id = record_scalar_observation(
            connection,
            subject_kind="item",
            subject_key=100,
            fact_key="name",
            import_batch_id=batch_b,
            value="Copper Gizmo",
            source_record_type="item",
            raw_identifier=100,
        )

        assert repeated_id == first_id
        assert conflicting_id != first_id
        assert connection.execute(
            "SELECT COUNT(*) FROM observation_import_batches WHERE observation_id = ?",
            (first_id,),
        ).fetchone()[0] == 2
        rows = connection.execute(
            """
            SELECT value_json
            FROM source_observations
            ORDER BY id
            """
        ).fetchall()
        assert [json.loads(row["value_json"]) for row in rows] == [
            "Copper Widget",
            "Copper Gizmo",
        ]


def test_relation_observation_is_traceable_through_import_batch(tmp_path):
    db_path = tmp_path / "relations.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        source_id, batch_id = _source_and_batch(connection, "loot-source", "loot-rev-7")

        observation_id = record_relation_observation(
            connection,
            subject_kind="creature",
            subject_key=12,
            fact_key="loot.item",
            import_batch_id=batch_id,
            target_kind="item",
            target_key=34,
            attributes={"chance": 0.125, "min_count": 1, "max_count": 2},
            source_record_type="creature_loot",
            raw_identifier="12:34",
        )

        row = connection.execute(
            """
            SELECT
                og.fact_kind,
                so.value_json,
                ib.source_revision,
                ds.id AS source_id,
                ds.source_key
            FROM source_observations AS so
            JOIN observation_groups AS og ON og.id = so.observation_group_id
            JOIN observation_import_batches AS oib ON oib.observation_id = so.id
            JOIN import_batches AS ib ON ib.id = oib.import_batch_id
            JOIN data_sources AS ds ON ds.id = so.source_id
            WHERE so.id = ? AND ib.id = ?
            """,
            (observation_id, batch_id),
        ).fetchone()

        assert row["fact_kind"] == "relation"
        assert json.loads(row["value_json"]) == {
            "attributes": {"chance": 0.125, "max_count": 2, "min_count": 1},
            "target": {"key": "34", "kind": "item"},
        }
        assert row["source_revision"] == "loot-rev-7"
        assert row["source_id"] == source_id
        assert row["source_key"] == "loot-source"


def test_fact_kind_cannot_change_for_an_existing_group(tmp_path):
    db_path = tmp_path / "kind.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        group_id = get_or_create_observation_group(
            connection,
            subject_kind="item",
            subject_key=1,
            fact_key="name",
            fact_kind="scalar",
        )
        assert group_id > 0

        with pytest.raises(ValueError, match="existing observation group uses fact_kind"):
            get_or_create_observation_group(
                connection,
                subject_kind="item",
                subject_key=1,
                fact_key="name",
                fact_kind="relation",
                fact_instance_key='{"key":"2","kind":"item"}',
            )


def test_canonical_selection_must_reference_same_group_and_preserves_losers(tmp_path):
    db_path = tmp_path / "selection.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        _, batch_a = _source_and_batch(connection, "source-a", "rev-a")
        _, batch_b = _source_and_batch(connection, "source-b", "rev-b")

        winner_a = record_scalar_observation(
            connection,
            subject_kind="item",
            subject_key=7,
            fact_key="name",
            import_batch_id=batch_a,
            value="Name A",
        )
        winner_b = record_scalar_observation(
            connection,
            subject_kind="item",
            subject_key=7,
            fact_key="name",
            import_batch_id=batch_b,
            value="Name B",
        )
        other_group_observation = record_scalar_observation(
            connection,
            subject_kind="item",
            subject_key=7,
            fact_key="quality",
            import_batch_id=batch_a,
            value=3,
        )
        group_id = int(
            connection.execute(
                "SELECT observation_group_id FROM source_observations WHERE id = ?",
                (winner_a,),
            ).fetchone()[0]
        )

        select_canonical_observation(
            connection,
            observation_group_id=group_id,
            observation_id=winner_a,
            selection_policy="source-priority/v1",
            selection_reason="Source A is authoritative for item names.",
        )
        select_canonical_observation(
            connection,
            observation_group_id=group_id,
            observation_id=winner_b,
            selection_policy="manual-review",
            selection_reason="Reviewed conflict and selected source B.",
        )

        selection = connection.execute(
            """
            SELECT observation_id, selection_policy, selection_reason
            FROM canonical_selections
            WHERE observation_group_id = ?
            """,
            (group_id,),
        ).fetchone()
        assert selection["observation_id"] == winner_b
        assert selection["selection_policy"] == "manual-review"
        assert selection["selection_reason"] == "Reviewed conflict and selected source B."
        assert connection.execute(
            "SELECT COUNT(*) FROM source_observations WHERE observation_group_id = ?",
            (group_id,),
        ).fetchone()[0] == 2

        with pytest.raises(sqlite3.IntegrityError):
            select_canonical_observation(
                connection,
                observation_group_id=group_id,
                observation_id=other_group_observation,
                selection_reason="Invalid cross-group selection.",
            )

        assert connection.execute(
            "SELECT observation_id FROM canonical_selections WHERE observation_group_id = ?",
            (group_id,),
        ).fetchone()[0] == winner_b


def test_observation_quality_constraints_are_enforced(tmp_path):
    db_path = tmp_path / "constraints.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        _, batch_id = _source_and_batch(connection, "source-a", "rev-a")

        with pytest.raises(ValueError, match="confidence"):
            record_scalar_observation(
                connection,
                subject_kind="item",
                subject_key=1,
                fact_key="name",
                import_batch_id=batch_id,
                value="A",
                confidence=1.1,
            )

        with pytest.raises(ValueError, match="authority_tier"):
            record_scalar_observation(
                connection,
                subject_kind="item",
                subject_key=1,
                fact_key="name",
                import_batch_id=batch_id,
                value="A",
                authority_tier=-1,
            )


def test_distinct_relation_targets_are_distinct_fact_instances(tmp_path):
    db_path = tmp_path / "relation-instances.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        _, batch_id = _source_and_batch(connection, "source-a", "rev-a")

        first = record_relation_observation(
            connection,
            subject_kind="creature",
            subject_key=12,
            fact_key="loot.item",
            import_batch_id=batch_id,
            target_kind="item",
            target_key=34,
            attributes={"chance": 0.1},
        )
        second = record_relation_observation(
            connection,
            subject_kind="creature",
            subject_key=12,
            fact_key="loot.item",
            import_batch_id=batch_id,
            target_kind="item",
            target_key=35,
            attributes={"chance": 0.2},
        )

        assert first != second
        groups = connection.execute(
            """
            SELECT fact_instance_key
            FROM observation_groups
            WHERE subject_kind = 'creature' AND subject_key = '12' AND fact_key = 'loot.item'
            ORDER BY fact_instance_key
            """
        ).fetchall()
        assert len(groups) == 2
        assert {json.loads(row["fact_instance_key"])["key"] for row in groups} == {"34", "35"}


def test_explicit_relation_instance_key_can_preserve_competing_targets(tmp_path):
    db_path = tmp_path / "relation-target-conflict.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        _, batch_a = _source_and_batch(connection, "source-a", "rev-a")
        _, batch_b = _source_and_batch(connection, "source-b", "rev-b")

        first = record_relation_observation(
            connection,
            subject_kind="quest",
            subject_key=99,
            fact_key="giver",
            import_batch_id=batch_a,
            target_kind="creature",
            target_key=10,
            relation_instance_key="giver-slot-1",
        )
        second = record_relation_observation(
            connection,
            subject_kind="quest",
            subject_key=99,
            fact_key="giver",
            import_batch_id=batch_b,
            target_kind="creature",
            target_key=11,
            relation_instance_key="giver-slot-1",
        )

        assert first != second
        group_ids = {
            row[0]
            for row in connection.execute(
                "SELECT observation_group_id FROM source_observations WHERE id IN (?, ?)",
                (first, second),
            ).fetchall()
        }
        assert len(group_ids) == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM source_observations WHERE observation_group_id = ?",
            (group_ids.pop(),),
        ).fetchone()[0] == 2


def test_same_source_different_revisions_remain_distinct_observations(tmp_path):
    db_path = tmp_path / "source-revisions.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        source_id, batch_v1 = _source_and_batch(connection, "source-a", "rev-1")
        batch_v2 = _batch_for_source(connection, source_id, "rev-2")

        observation_v1 = record_scalar_observation(
            connection,
            subject_kind="item",
            subject_key=1,
            fact_key="name",
            import_batch_id=batch_v1,
            value="Same Name",
            raw_identifier=1,
        )
        observation_v2 = record_scalar_observation(
            connection,
            subject_kind="item",
            subject_key=1,
            fact_key="name",
            import_batch_id=batch_v2,
            value="Same Name",
            raw_identifier=1,
        )

        assert observation_v1 != observation_v2
        revisions = {
            row["source_revision"]
            for row in connection.execute(
                "SELECT source_revision FROM source_observations WHERE id IN (?, ?)",
                (observation_v1, observation_v2),
            ).fetchall()
        }
        assert revisions == {"rev-1", "rev-2"}


def test_import_batch_link_must_match_observation_source_and_revision(tmp_path):
    db_path = tmp_path / "provenance-link.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        _, batch_a = _source_and_batch(connection, "source-a", "rev-a")
        _, batch_b = _source_and_batch(connection, "source-b", "rev-b")

        observation_id = record_scalar_observation(
            connection,
            subject_kind="item",
            subject_key=1,
            fact_key="name",
            import_batch_id=batch_a,
            value="A",
        )

        with pytest.raises(sqlite3.IntegrityError, match="provenance mismatch"):
            connection.execute(
                """
                INSERT INTO observation_import_batches(observation_id, import_batch_id)
                VALUES (?, ?)
                """,
                (observation_id, batch_b),
            )
