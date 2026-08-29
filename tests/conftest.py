from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from octogamedb.db import (
    apply_migrations,
    connect_database,
    record_relation_observation,
    record_scalar_observation,
    select_canonical_observation,
)

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "golden" / "provenance_audit_case.json"
_P6_ITEMCACHE_FIXTURE = Path(__file__).parent / "fixtures" / "p6_t01" / "itemcache.wdb"


def _pack_itemcache_record(
    item_id: int,
    *,
    name: str,
    class_id: int,
    subclass_id: int,
    quality: int,
    inventory_type: int,
    item_level: int,
    required_level: int,
    armor: int = 0,
    max_durability: int = 0,
    stats: tuple[tuple[int, int], ...] = (),
) -> bytes:
    payload = bytearray()

    def u32(value: int) -> None:
        payload.extend(struct.pack("<I", value & 0xFFFFFFFF))

    def i32(value: int) -> None:
        payload.extend(struct.pack("<i", value))

    def f32(value: float) -> None:
        payload.extend(struct.pack("<f", value))

    def cstring(value: str) -> None:
        payload.extend(value.encode("utf-8") + b"\0")

    u32(class_id)
    u32(subclass_id)
    cstring(name)
    cstring("")
    cstring("")
    cstring("")
    u32(0)  # display id
    u32(quality)
    u32(0)  # flags
    u32(0)  # buy price
    u32(0)  # sell price
    u32(inventory_type)
    u32(0xFFFFFFFF)  # allowable class mask == -1
    u32(0xFFFFFFFF)  # allowable race mask == -1
    u32(item_level)
    u32(required_level)
    u32(0)  # required skill id
    u32(0)  # required skill rank
    u32(0)  # required spell id
    u32(0)  # honor rank
    u32(0)  # city rank
    u32(0)  # required reputation faction
    u32(0)  # required reputation rank
    i32(0)  # max count
    i32(1)  # stackable
    u32(0)  # container slots

    padded_stats = list(stats[:10]) + [(0, 0)] * (10 - len(stats[:10]))
    for stat_type, stat_value in padded_stats:
        u32(stat_type)
        i32(stat_value)

    for _ in range(5):
        f32(0.0)
        f32(0.0)
        u32(0)

    u32(armor)
    for _ in range(6):
        u32(0)  # resistances
    u32(2000)  # delay
    u32(0)  # ammo type
    f32(0.0)  # ranged mod range

    for _ in range(5):
        u32(0)  # spell id
        u32(0)  # trigger
        i32(0)  # charges
        i32(0)  # cooldown
        u32(0)  # category
        i32(0)  # category cooldown

    u32(0)  # bonding
    cstring("")  # description
    u32(0)  # page text
    u32(0)  # language
    u32(0)  # page material
    u32(0)  # start quest
    u32(0)  # lock id
    i32(0)  # material
    u32(0)  # sheath
    i32(0)  # random property
    u32(0)  # block
    u32(0)  # item set
    u32(max_durability)
    u32(0)  # area
    u32(0)  # map
    u32(0)  # bag family

    return struct.pack("<II", item_id, len(payload)) + bytes(payload)


def _ensure_p6_itemcache_fixture() -> None:
    """Recreate the small ignored WDB fixture used by P6 tests from tracked Python source."""

    _P6_ITEMCACHE_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    header = b"BDIW" + struct.pack("<I", 5875) + b"SUne" + struct.pack("<II", 0, 1)
    records = (
        _pack_itemcache_record(
            1001,
            name="Fixture Sword",
            class_id=2,
            subclass_id=7,
            quality=2,
            inventory_type=13,
            item_level=25,
            required_level=20,
            max_durability=65,
            stats=((3, 5), (4, 7)),
        ),
        _pack_itemcache_record(
            1002,
            name="Fixture Chest",
            class_id=4,
            subclass_id=4,
            quality=3,
            inventory_type=5,
            item_level=30,
            required_level=25,
            armor=140,
            max_durability=80,
        ),
        _pack_itemcache_record(
            900001,
            name="Fixture Custom",
            class_id=2,
            subclass_id=0,
            quality=4,
            inventory_type=17,
            item_level=60,
            required_level=50,
            max_durability=100,
        ),
    )
    _P6_ITEMCACHE_FIXTURE.write_bytes(header + b"".join(records) + struct.pack("<II", 0, 0))


# tests/fixtures/p6_t01/itemcache.wdb is intentionally ignored by the repository's *.wdb rule.
# Generate it deterministically before test collection instead of relying on a machine-local file.
_ensure_p6_itemcache_fixture()


@pytest.fixture
def golden_audit_case(tmp_path):
    fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    db_path = tmp_path / "golden-audit.sqlite3"

    with connect_database(db_path) as connection:
        apply_migrations(connection)
        source_ids: dict[str, int] = {}
        batch_ids: dict[str, int] = {}
        observation_ids: dict[str, int] = {}

        for source in fixture["sources"]:
            cursor = connection.execute(
                """
                INSERT INTO data_sources(source_key, display_name, source_kind)
                VALUES (?, ?, ?)
                """,
                (source["key"], source["display_name"], source["kind"]),
            )
            source_ids[source["key"]] = int(cursor.lastrowid)

        for batch in fixture["batches"]:
            cursor = connection.execute(
                """
                INSERT INTO import_batches(
                    source_id,
                    source_revision,
                    status,
                    finished_at,
                    rows_read,
                    rows_accepted,
                    rows_inserted,
                    details_json
                )
                VALUES (?, ?, 'succeeded', '2026-08-24T00:00:00Z', ?, ?, ?, ?)
                """,
                (
                    source_ids[batch["source"]],
                    batch["revision"],
                    batch["rows_read"],
                    batch["rows_accepted"],
                    batch["rows_inserted"],
                    json.dumps(batch["details"], sort_keys=True, separators=(",", ":")),
                ),
            )
            batch_ids[batch["key"]] = int(cursor.lastrowid)

        for observation in fixture["observations"]:
            common = {
                "connection": connection,
                "subject_kind": observation["subject_kind"],
                "subject_key": observation["subject_key"],
                "fact_key": observation["fact_key"],
                "import_batch_id": batch_ids[observation["batch"]],
            }
            if observation["kind"] == "scalar":
                observation_id = record_scalar_observation(
                    **common,
                    value=observation["value"],
                    source_record_type=observation.get("source_record_type"),
                    raw_identifier=observation.get("raw_identifier"),
                )
            else:
                observation_id = record_relation_observation(
                    **common,
                    target_kind=observation["target_kind"],
                    target_key=observation["target_key"],
                    relation_instance_key=observation.get("relation_instance_key"),
                    attributes=observation.get("attributes"),
                )
            observation_ids[observation["key"]] = observation_id

        for selection in fixture["canonical"]:
            observation_id = observation_ids[selection["observation"]]
            group_id = int(
                connection.execute(
                    "SELECT observation_group_id FROM source_observations WHERE id = ?",
                    (observation_id,),
                ).fetchone()[0]
            )
            select_canonical_observation(
                connection,
                observation_group_id=group_id,
                observation_id=observation_id,
                selection_policy=selection["selection_policy"],
                selection_reason=selection["selection_reason"],
            )

    return {"db_path": db_path, "fixture": fixture}
