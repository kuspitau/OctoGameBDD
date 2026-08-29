# P6 item-template/stat source contract

Status: `VALIDATED`

This document is the validated source/model contract for P6-T01. It is intentionally narrower than
a full item-template model. The real Octo cache validator passed on 2026-08-29. The contract is now
accepted under D-036, while the canonical DB baseline deliberately remains migration 13 because no
D-029 promotion cycle was performed.

## 1. Scope proved by P6-T01

P6-T01 establishes provenance-backed, filterable canonical facts for this bounded family:

- item class and subclass IDs;
- quality;
- inventory/equipment type ID;
- item level and required level;
- allowable class/race masks;
- required skill ID/rank;
- required spell ID;
- required reputation faction/rank;
- armor;
- six resistance values;
- maximum durability;
- the complete ordered set of ten raw item-stat slots.

The first query proof filters canonical items by `required_level`, raw `inventory_type`, and one or
more raw stat type/value minima. It also returns the selected-observation trace for every P6 template
fact on each result.

The following candidate fields are deliberately deferred rather than flattened prematurely:

- weapon damage rows and attack delay/speed;
- shield block;
- item effects/use/equip/proc spells;
- tooltip/description text;
- display/icon semantics;
- random-property/enchantment semantics.

The 1.12 cache parser traverses the packet positions needed to reach the adopted fields, but skipped
families are not promoted to canonical P6 facts.

## 2. Primary source: Octo client `itemcache.wdb`

### Source identity

Source key:

```text
octo-itemcache
```

Source kind:

```text
client-cache
```

The physical file is the locale-specific `itemcache.wdb` below the user's Octo client. The Level-2
validator discovers it from the already-established `[source_paths].wow_root` configuration, normally
under one of:

```text
<WOW_ROOT>\WDB\<locale>\itemcache.wdb
<WOW_ROOT>\Cache\WDB\<locale>\itemcache.wdb
```

No user-machine path is committed.

### Why this is direct Octo evidence

The WoW client writes item-query responses received from the connected server into `itemcache.wdb`.
For Vanilla 1.12, the relevant server response is `SMSG_ITEM_QUERY_SINGLE_RESPONSE`. Therefore a
successfully parsed cache record is direct client-observed evidence of what the Octo server supplied
for that item query, not an inferred Vanilla/Turtle baseline.

The parser contract was checked against:

- the generic WDB header/record contract documented by wowdev;
- the Vanilla item-query response layout in VMaNGOS `ItemHandler.cpp`, inspected at commit
  `e3722f19171c45d97e6741b4f2e43686c761b8b0`;
- the client-cache behavior documented by AzerothCore's WDB documentation.

Those public references define file/protocol shape only. They are **not** the item data source. The
actual observations come from the user's Octo cache file.

### Cache revision identity

A mutable client cache must not be identified only by path or mtime. The importer therefore computes a
deterministic bounded revision:

```text
sha256:<digest>
```

The digest contains:

1. the supported WDB header semantics (`signature`, client build/version, locale, record size/version);
2. the sorted explicit requested item IDs;
3. the SHA-256 of each requested raw WDB record when present;
4. an explicit `MISSING` marker for each requested ID absent from that snapshot.

Unrelated cache growth does not change the revision of an already-selected bounded slice.

### Completeness semantics

`itemcache.wdb` is a **partial-positive source**:

- a present, successfully parsed item record is authoritative positive evidence for the adopted fields
  in that response;
- a requested item ID absent from the cache means `unknown/not observed in this cache`, not
  `item/field absent on Octo`;
- cache absence never authorizes deletion or deselection of an existing canonical fact;
- the complete ten stat slots of a present supported record are treated as one complete-set fact
  (`template.stat_slots`), including zero/empty slots;
- only non-empty stat modifiers are projected into the query table; the complete ten-slot payload
  remains preserved in provenance.

The parser fails closed on unsupported/truncated/trailing record shapes. Real-client Level-2 validation
is required before this format contract is accepted for Octo N'Zoth.

A cache record is direct evidence but does not by itself prove **freshness**: Vanilla caches can retain
an older server response until the entry/cache is refreshed. The deterministic record hash makes the
exact observed snapshot auditable, but P6-T01 does not claim that an arbitrary pre-existing cache is a
live-current server snapshot. Consequently migration 14 is validated on a disposable DB copy only;
future unbounded/canonical promotion must define a refresh/freshness procedure or add corroborating
direct evidence before treating cache coverage as current-world truth.

## 3. Other considered source families

P6-T01 does **not** introduce a universal source priority.

| Source family | P6-T01 role | Authority for adopted fields | Completeness/limitation |
| --- | --- | --- | --- |
| Octo client `itemcache.wdb` | implemented ingestion source | tier `0` for fields actually present in a supported record | partial-positive across item IDs; complete adopted payload within a parsed record |
| OctoDB item-detail evidence | reviewed candidate/corroboration | not assigned in this task | no stable structured revision/completeness contract accepted yet |
| pfQuest base | existing identity/acquisition source | none for P6 template/stat facts | its P2 item database is not a canonical item-template/stat feed |
| `pfquest-turtle` overlay | existing active item/world evidence | none for P6 template/stat facts in this task | P2 deliberately did not generalize overlay stats into truth |
| Tortoise/managed server SQL | future fallback candidate | lower than direct Octo if/when an exact revision/parser is accepted | production adapter intentionally deferred |
| CMaNGOS/VMaNGOS-style baseline | protocol/reference or last-resort fallback candidate | lower than direct Octo; no data adapter in this task | must not be mistaken for Octo truth |

Existing source revisions remain those already pinned in `DATA_SOURCES.md`; P6-T01 does not repin
pfQuest/Turtle. The VMaNGOS commit above is a **format-reference revision**, not a selected data
revision.

## 4. Field-specific canonical selection

Every adopted scalar is observed separately with a fact key of the form:

```text
template.<field>
```

The complete ordered stat payload uses:

```text
template.stat_slots
```

Direct Octo cache observations use:

```text
authority_tier = 0
selection_policy = p6-item-template/octo-itemcache
```

The P6 selector may replace only selections created by a known P6 managed policy, and only when the
new observation has a strictly better authority tier or refreshes the same managed source family at
the same tier. Unknown/manual/custom selection policies are protected and are never silently replaced.
All competing observations remain stored.

Managed policy names reserved by the implementation are:

```text
p6-item-template/octo-itemcache
p6-item-template/octodb
p6-item-template/tortoise-fallback
p6-item-template/cmangos-fallback
```

Only the first is a production ingestion policy in P6-T01. The remaining names exist so conflict and
selection behavior can be tested without asserting that those fallback adapters are already accepted.

## 5. Canonical projection introduced by migration 14

Migration:

```text
0014_item_template_facts.sql
```

Tables:

```text
item_templates
item_stat_modifiers
```

`item_templates` is a one-row-per-canonical-item projection of the selected scalar facts.
`item_stat_modifiers` stores the non-empty selected stat slots with their original slot index and raw
numeric stat type/value.

The projection is rebuildable from canonical selections; provenance remains in the existing generic
`observation_groups`, `source_observations`, and `canonical_selections` tables.

An Octo cache record whose native item ID is not yet present in canonical `items` is retained in
provenance but does not cause a placeholder identity row to be invented.

## 6. Bounded ingestion contract

The production importer accepts an explicit non-empty set of positive native item IDs. There is no
unbounded default. This makes the first P6 slice auditable and prevents accidental whole-cache
promotion.

The Level-1 fixture covers:

- an equippable weapon-shaped item with multiple non-empty stat slots;
- an armor-shaped item with armor, restrictions and multiple stats;
- a custom/high native ID absent from canonical `items`;
- a requested ID absent from the cache;
- a managed lower-authority conflicting observation;
- a manual/custom conflicting selection that must remain protected;
- malformed/unknown trailing record shape.

## 7. Query proof

`octogamedb.item_search.query_item_templates()` proves the first consumer path. It can combine:

```text
required_level <= N
inventory_type = raw_slot_id
stat_type A >= X
stat_type B >= Y
```

The function intentionally accepts raw stat type IDs and does not invent semantic labels before an
explicit enum/DBC contract exists. Every result carries the current provenance/selection trace.

## 8. Validation and canonical lifecycle

Focused implementation validation established the parser/import/query behavior. The integrated human
checkout then passed all classical checks:

```text
python -m pip install -e ".[dev]"      passed
pytest --basetemp=...                  228 passed
python -m ruff check src tests         passed
python -m compileall -q src tests      passed
```

The final Level-2 validator ran against the user's real Octo cache and an untouched migration-13
canonical baseline. It copied that DB to `data/generated/p6_t01_validation.sqlite3`, applied migration
14 only to the copy, imported the same bounded real slice twice, and verified idempotence, canonical
selections, foreign keys, SQLite integrity and canonical immutability.

Validated result on 2026-08-29:

```text
P6_T01_LOCAL_VALIDATION_OK
canonical_sha256=623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
selected_item_count=25
selected_item_ids=4,8,10,25,16,24,26,27,28,31,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49
first_rows_inserted=28
first_rows_updated=0
item_templates=25
item_stat_modifiers=3
source_observations=2208906
canonical_db_unchanged=true
```

The real cache shape therefore satisfies the P6-T01 parser/import contract. This validation proves
compatibility with the observed cache bytes; it still does not prove that arbitrary pre-existing
records are fresh/current or that cache coverage is exhaustive.

Migration 14 is accepted as validated schema capability, but the generated canonical DB is not
promoted by P6-T01. The current canonical DB remains migration 13 with SHA-256:

```text
623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

## 9. Accepted closeout and next bounded question

The validated contract is folded into durable project memory through D-036 plus `DATA_SOURCES.md` and
`DATA_MODEL.md`. No existing world/quest/recipe decision is superseded.

P6-T01 closes with these durable boundaries:

- present supported cache records are direct Octo positive field evidence;
- cache absence is unknown;
- cache freshness is not implied by mere presence;
- the ten stat slots are complete for a present supported record;
- managed P6 field selection is explicit and preserves competing/manual evidence;
- the importer remains bounded and no whole-cache default exists;
- migration 14 is validated but not the current canonical DB baseline.

The final real probe produced 25 template projections and 3 non-empty stat modifiers. That sample is
not interpreted as whole-cache coverage. Instead it routes:

```text
P6-T02 — Direct Octo item-cache freshness, coverage and bounded refresh probe
```

P6-T02 must measure actual cache coverage and establish a reproducible currentness/refresh acquisition
contract before full template/stat ingestion or D-029 migration-14 promotion.
