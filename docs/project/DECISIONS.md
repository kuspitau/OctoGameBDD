# Architecture Decision Log

Decisions are durable project memory. Do not silently change them.

A later decision may supersede an earlier one. Record the reason and consequences.

## D-001 — One physical canonical SQLite database

**Status:** accepted

Use one SQLite database for the canonical project model. Organize by logical domains through
tables/modules instead of separate `items.db`, `quests.db`, etc.

## D-002 — Multi-entity model, not item-centric storage

**Status:** accepted

Items, quests, creatures, game objects, recipes, spells, zones, and maps are first-class domains. The
UI may choose any entity as its current point of view.

## D-003 — Native IDs are preserved

**Status:** accepted

Keep game/source IDs alongside any internal surrogate keys. Cross-source reconciliation depends on
them.

## D-004 — Raw → staging → canonical → derived

**Status:** accepted

Separate source artifacts, parsed source-shaped data, canonical normalized truth, and derived/query
data.

## D-005 — Provenance is mandatory

**Status:** accepted

The system must be able to trace canonical facts/relations to source, source revision/import batch,
and derivation when applicable.

## D-006 — Conflicts are preserved

**Status:** accepted

Selecting a canonical value does not delete competing source observations. Resolution policy must be
explicit.

## D-007 — Explicit domain relation tables

**Status:** accepted

Important relations use dedicated tables. A generic graph relation table is not the primary
persistence model.

## D-008 — Derived relations are not primary truth

**Status:** accepted

Examples such as `item -> obtainable zone` and `recipe -> available zone` should normally be derived
from primitive relations. Materialized caches may be added later for measured performance needs.

## D-009 — Template entities and spawn instances are separate

**Status:** accepted

Creature/GameObject identity must not be conflated with geographic spawn records.

## D-010 — Recipe, recipe item, spell, and result item are distinct

**Status:** accepted

Crafting data must preserve the real intermediate entities/relations where sources expose them.

## D-011 — Reuse parsers selectively, own the canonical model

**Status:** accepted

Study/adapt useful parsing/resolution logic from existing projects where licensing permits. Do not
build the project's canonical architecture around another project's final DB schema.

## D-012 — Audit/CLI before polished UI

**Status:** accepted

Build data correctness, traceability, conflict reporting, coverage metrics, and small end-to-end
slices before the graphical explorer.

## D-013 — GitHub read-only agent workflow

**Status:** accepted

GitHub `main` is the validated source of truth for tracked project state. Coding conversations read
GitHub, work in a temporary workspace, and return only a delta package. The human applies, validates,
commits, and pushes.

## D-014 — Large data is local; small fixtures are tracked

**Status:** accepted

Full dumps, client files, scraped caches, and generated DBs stay out of Git. Small representative
samples/fixtures are committed for deterministic tests.

## D-015 — Importers are idempotent

**Status:** accepted

Re-running the same importer against the same source revision must not duplicate rows or change the
result spuriously.

## D-016 — Two validation levels

**Status:** accepted

Level 1 is sample/unit/small integration validation available to a coding conversation. Level 2 is
full-data/local validation executed by the human. A change that requires Level 2 is not fully
validated until those checks pass.

## D-017 — Project docs are the durable memory

**Status:** accepted

`PROJECT`, `ARCHITECTURE`, `DATA_MODEL`, `DATA_SOURCES`, `DECISIONS`, `ROADMAP`, `CURRENT_STATE`,
`AI_GUIDELINES`, and task documents travel with the code and must be updated when relevant.

## D-018 — Serial validated handoffs by default

**Status:** accepted

Avoid multiple stale delta packages against different unmerged bases. Preferred loop:

```text
read current GitHub main
-> implement
-> delta package
-> human apply/test/commit/push
-> next coding conversation
```

## D-019 — Zones are first-class and quest/recipe geography is relational

**Status:** accepted

Quest geography can differ by giver, finisher and objective. Recipe availability should normally be
derived from the geography of its actual acquisition/learning sources.

## D-020 — UI framework choice is deferred

**Status:** accepted

A local browser UI remains the target. NiceGUI is a strong candidate, but no UI framework becomes a
hard dependency before the data/query layer demonstrates its requirements.

## D-021 — Local source paths are runtime configuration

**Status:** accepted

User-machine absolute paths must not be hard-coded into tracked code or tracked configuration.
Stable local source locations belong in ignored `config.local.toml`, normally under `[source_paths]`.
When required locations are missing, coding handoffs provide task-specific discovery/configuration
through `get_path.bat`.

## D-022 — Handoff BAT helpers travel inside the delta ZIP

**Status:** accepted

Transient `delete_files.bat` and `get_path.bat` helpers are included at the project root inside
`changes.zip` when needed. They are ignored by Git and are not separate delivery artifacts.
`MANIFEST.txt` remains outside the ZIP and documents whether each helper is present and how to use it.

## D-023 — Public external formats are researched from primary sources

**Status:** accepted

When a parser/importer depends on a public addon/project/database, coding conversations inspect
current primary source code/docs and relevant issues/discussions/history when necessary instead of
guessing formats from memory. The user's local copy is reserved for version-specific extraction and
Level 2 validation rather than being the only source of format knowledge.

## D-024 — Geographic coordinate spaces are explicit

**Status:** accepted

Spawn/location coordinates must carry their coordinate-space semantics instead of being forced into a
single generic X/Y/Z interpretation.

In particular:

- source coordinates expressed as percentages within a zone are stored as `zone_percent` and retain
  their zone identity;
- world-coordinate sources may use `world` with X/Y and optional Z/orientation;
- conversion between coordinate spaces is derived behavior and must be traceable to the
  coordinate-frame/map inputs used;
- source-specific zone/map frame fields are preserved as provenance until their canonical meaning is
  established from authoritative evidence.

## D-025 — Direct Octo DBC is authoritative for canonical map/area hierarchy facts

**Status:** accepted

For the bounded map/area fact family established in P1-T02, observations from the user's actual Octo
client `Map.dbc` and `AreaTable.dbc` may supersede lower-authority canonical selections.

This applies to map name/kind and zone/area name, map identity and parent-area identity. Competing
observations remain preserved. Selection records the explicit `octo-client-dbc-geography` policy.
This is field-specific authority, not a universal DBC priority. Spawn map context may be derived from
its canonical zone without rewriting coordinate space or the spawn row.

## D-026 — Effective-source deletion and complete-set replacement are provenance facts

**Status:** accepted

P1-T04 reconciles Turtle-style overlay replacement without confusing source-view absence with
universal game non-existence.

For bounded P1 world facts:

- `world_presence` records entity membership in an effective source view;
- `world_presence = false` is negative source evidence, not a global tombstone;
- creature/game-object full spawn membership is stored as deterministic `spawn_set` evidence;
- per-spawn `position` and `respawn_seconds` remain primitive attribute evidence.

The installed Turtle effective view may supersede only default/base pfQuest selections for this
bounded family. Explicit/non-pfQuest selections remain protected. Stale managed pfQuest-family spawn
rows may be removed when absent from the selected complete set, while historical source observations
remain. Optional `pfQuest-octo` remains comparison evidence unless explicitly selected. D-025 keeps
its map/area authority.

## D-027 — Turtle item overlay uses bounded P2 complete-set reconciliation

**Status:** accepted

P2-T04 defines item-specific effective-view facts instead of silently generalizing D-026:

```text
item_presence
item_acquisition_set
loot_reference_presence
loot_reference_member_set
```

Existing primitive `name`, `loot_source`, `loot_reference`, `vendor_source`, and
`loot_source_member` observations remain the detailed evidence.

The active Turtle item view may replace only managed/default base selections. Explicit/custom
selections remain protected even when their observation source key is `pfquest`. Stale canonical P2
relations are removed only when their selected primitive relation is managed and the selected
complete set excludes them. Missing target identity stays unresolved evidence without fabricated
canonical templates/spawns. Turtle top-entry `"_"` deletion and replace-whole semantics are reproduced
from the source, including supported direct literal overwrites before patching.

This decision remains limited to the P2 identity + U/O/R/V + one-level refloot family.

## D-028 — Turtle quest identity/endpoints use bounded complete-view reconciliation

**Status:** accepted

P3-T02 defines a quest-specific effective-view policy for the P3-T01 fact family instead of silently
generalizing D-026 or D-027.

Complete effective-view facts are:

```text
quest_presence
quest_endpoint_set
```

`quest_presence` is true when the composed effective source view has a usable enUS title for the
quest. `quest_endpoint_set` is the complete supported giver/finisher set over the P3-T01 endpoint
families:

```text
(giver|finisher) × (creature|gameobject) × native target ID
```

Primitive `name` and `endpoint` observations remain source-specific:

- inherited base facts remain `pfquest` evidence;
- facts actually introduced/replaced by the Turtle quest patch are `pfquest-turtle` evidence.

The managed Turtle selection policy is:

```text
pfquest-turtle-effective-quests
```

It may supersede only the corresponding managed/default base quest view. Explicit/custom canonical
selections remain protected, including custom policies selecting an observation whose source key is
still `pfquest`.

A stale canonical endpoint may be removed only when the selected primitive endpoint relation is
managed and the selected complete endpoint set excludes it. Quest identity may be removed for an
absent effective title only when no protected selected support requires retaining it. Historical
observations are never deleted.

A Turtle-added usable title can activate a quest whose base data row existed but P3-T01 skipped for
missing base enUS title; inherited base endpoint facts keep base provenance. Missing P1 endpoint
identity remains explicit unresolved evidence and does not create a fake creature/game-object,
spawn, or geography.

The Turtle quest revision hashes the exact bounded load/composition inputs and validates the relevant
TOC/XML/patchtable markers. D-028 is limited to quest identity and giver/finisher endpoints; later
quest restrictions, dependencies, objectives and rewards require their own source/model review.

## D-029 — The generated canonical DB is a local validated baseline with one-step backup

**Status:** accepted

GitHub `main` remains the source of truth for tracked code, migrations, importers, tests and project
memory. The large generated data state is intentionally local.

When `CURRENT_STATE.md` records that a cumulative local DB has been successfully built and validated,
this path is the canonical local data baseline:

```text
data/generated/octogamedb.sqlite3
```

It represents all validated import/reconciliation stages through the level named in
`CURRENT_STATE.md`. It is the preferred cumulative real-data starting point for later tests and
project evolution instead of guessing among historical validation DBs or rebuilding from zero for
every task.

Before **any mutation** of the canonical local DB, create or replace:

```text
data/generated/octogamedb_bak.sqlite3
```

with an exact copy of the canonical DB. The `_bak` file is a one-step rollback state, not historical
version storage; replace an existing `_bak` on the next canonical mutation cycle.

Exploratory, destructive or first-run Level-2 validation should use a dedicated copy when practical.
If canonical evolution fails after writes, restore from `_bak` before considering the canonical state
valid. A task is not allowed to claim that the canonical DB advanced until its required Level-2
checks pass.

Both the canonical DB and `_bak` are ignored generated artifacts and must never be committed or
included in `changes.zip`. The project must remain capable of rebuilding the canonical DB from a
fresh SQLite file using tracked code plus configured local sources. The canonical local DB is a
validated working baseline, not an irreplaceable source artifact.

The operational details live in `docs/project/CANONICAL_DB.md`.

## D-030 — P3 quest restrictions/dependencies preserve pfQuest set semantics

**Status:** accepted

P3-T03 is a separate bounded fact family from D-028. It covers only pfQuest quest fields:

```text
lvl
min
race
class
pre
close
```

Primary-source inspection establishes the following contract at the pinned revisions:

- `lvl` is quest level and `min` is minimum player level;
- `race` and `class` are source bitmasks; extractor value `0` is omitted, so an absent field is
  distinct from an explicitly supplied numeric `0`;
- `pre` is the source's single alternative prerequisite set: pfQuest runtime accepts the quest when
  **at least one** listed predecessor is complete;
- `pre` combines source predecessors discovered from `PrevQuestId`, negative-exclusive `NextQuestId`
  backlinks, and `NextQuestInChain` backlinks; no separate exported `next` fact survives;
- follow-ups are therefore derived as the reverse of the selected prerequisite relation under D-008;
- `close` is the complete per-quest member list generated for a positive `ExclusiveGroup` and may
  include the quest itself; no stable source group ID survives in the exported table, so P3-T03 does
  not invent one;
- the pinned Turtle runtime extends race-bit names but the canonical P3-T03 schema keeps race/class
  masks raw rather than baking server-specific labels into identity-independent truth.

Migration 8 materializes the query-oriented projection with nullable scalar columns on `quests` plus
explicit grouped-set tables:

```text
quest_prerequisite_sets
quest_prerequisite_set_members
quest_close_sets
quest_close_set_members
```

The parent rows preserve set declaration/presence and selected member count. This intentionally keeps
an explicit empty `pre = {}` distinguishable from an absent `pre` field. Member tables contain only
referenced quests that already have canonical identities; missing IDs remain provenance and explicit
`unresolved_progression_relations` diagnostics. No placeholder quest identity is fabricated.

Source-shaped raw lists remain provenance facts alongside normalized complete-set facts and primitive
member relations. Duplicate source members are reported deterministically before the canonical set is
deduplicated. Self prerequisites, prerequisite cycles, unexpected missing-self `close` sets, and
inconsistent materialized `close` peer sets are audit diagnostics; `close` self-membership itself is
expected source behavior rather than an error.

P3-T03 deliberately reuses the already validated P3-T02 quest compositor and therefore uses the same
exact base/Turtle source revision inputs. Turtle top-entry replacement/deletion replaces the entire
bounded progression view for a touched quest; omitted P3-T03 fields become absent rather than merging
with base values. The pinned Turtle `overwrites.lua` does not currently mutate these six fields, but
its contents remain revisioned/composed before patchtable replacement through the shared adapter.

Managed selection policies are task-specific:

```text
pfquest-base-effective-quest-progression
pfquest-turtle-effective-quest-progression
```

They may replace only managed/default selections. Explicit/custom scalar, complete-set, or primitive
relation selections remain protected. Historical source observations are never deleted.

D-030 is limited to restrictions/dependencies. Objectives, required items, rewards, item-started
quests, skill/profession requirements and localized body text remain deferred.

## D-031 — P3 quest item quantities/rewards are source-gated

**Status:** accepted

P3-T05 must not infer quantity-bearing quest requirements or item rewards from the distributed
pfQuest objective membership export.

Primary-source inspection of `shagu/pfQuest` at revision
`104f35678ca39ab1fb78b655f815cc7016f5e0c8` establishes that `toolbox/extractor.lua` reads raw
`ReqItemId1..4` and `ReqSourceId1..4` fields only to build the item objective membership set later
serialized as `obj.I`. The exported quest record does not preserve the corresponding raw counts and
does not serialize guaranteed or choice item reward fields. `db/quests-itemreq.lua` is item-use target
evidence, not quantity evidence. The current public extractor was also checked on 2026-08-25 and
still does not export `ReqItemCount`.

The reviewed `KameleonUK/pfQuest-turtle` revision
`5b8eeeeb4119be9d075087f0f0e08c187b35ad61` does not repair that loss: its public
`db/quests-turtle.lua` is empty, as is the currently published file checked on 2026-08-25.

Consequences:

- P3-T04 `obj.I` remains source-backed objective membership only; no quantity may be attached to a
  member by positional matching, ID coincidence, or a default count;
- required item, required source/provided item, guaranteed reward and choice reward facts remain
  blocked until a reviewed source contract carries their exact semantics;
- no P3-T05 schema/import/reconciliation migration may be added merely to make the planned model
  writable before such a source contract exists;
- the next task is P3-T05A, which must establish a reproducible source and revision strategy before
  P3-T05 implementation resumes;
- source investigation follows the existing `DATA_SOURCES.md` priority. Octo-specific authoritative
  data such as OctoDB should be evaluated first; a pinned Vanilla VMaNGOS/CMaNGOS-style source may be
  used only under an explicit field/relation policy and must not be silently promoted to Octo truth.

This decision does not reject the P3-T05 canonical direction. Once a valid source is established,
requirements and guaranteed/choice rewards should still use explicit domain relations, exact
source-backed quantities, mandatory provenance and bounded effective-view reconciliation where the
selected source semantics justify it.

## D-032 — P3 quest item/reward authority is field-specific: OctoDB observations over a pinned CMaNGOS baseline

**Status:** accepted

P3-T05A establishes a source contract without promoting either OctoDB or CMaNGOS to universal quest
truth.

For P3-T05 item/reward families, the preferred Octo-specific evidence is a cached OctoDB quest-detail
page addressed by native quest ID:

```text
https://octowow.st/db/?quest=<quest_id>
```

A successfully parsed page may contribute only facts that are explicitly represented by the page's
quest-item/reward structure: ordinary required items, quest-start provided items when present,
guaranteed item rewards and choice item rewards. The page and its exact bytes are provenance. Because
OctoDB exposes no immutable public data revision and no stable structured quest API was identified in
P3-T05A, each cached page revision is its SHA-256; a batch revision hashes the sorted native-ID/page
hash manifest. Retrieval time is metadata, not source identity.

OctoDB HTML is treated as **partial observation evidence**, not a complete negative source view. A
missing section or missing quest page therefore cannot by itself delete stale managed canonical
members. This remains true even though current pages clearly expose Vanilla and Octo/custom quest
requirements/reward families. Page parsing must fail closed if section/item/count structure is not
recognized; prose descriptions are not a quantity source.

The pinned Vanilla fallback/baseline is:

```text
cmangos/classic-db
250a705a462c1acb457d3002359c7e0052c4dafe
Full_DB/ClassicDB_1_12_1_z2815.sql.gz
blob 0a77f5230a3d5d6db968678203dfe3b30c34b8a9

cmangos/mangos-classic semantic reference
9b682be617ac61c127c23aa60d7b4ffbc0ce37e6
```

Its fixed `quest_template` slot families are complete baseline evidence for each present Vanilla quest
row:

```text
ReqItemId[4] / ReqItemCount[4]
ReqSourceId[4] / ReqSourceCount[4]
SrcItemId / SrcItemCount
RewChoiceItemId[6] / RewChoiceItemCount[6]
RewItemId[4] / RewItemCount[4]
```

CMaNGOS may fill/select a P3-T05 fact only under an explicit Vanilla fallback policy when no
higher-priority Octo-specific selected observation exists for that fact family. An OctoDB/Octo-specific
observation never gets overwritten merely because the Vanilla baseline has a convenient row. Source
disagreements are retained under D-006.

The families are not semantically interchangeable:

- `ReqItemId/ReqItemCount` is an item and amount required to complete the quest;
- `SrcItemId/SrcItemCount` is an item and amount supplied to the player for the quest;
- `ReqSourceId/ReqSourceCount` is auxiliary source-item/drop-control data used by the quest/loot
  runtime, not a turn-in quantity. In current CMaNGOS ClassicDB, a nonzero `ReqSourceId` with
  `ReqSourceCount = 0` is valid and means the normal core/stack drop behavior rather than “requires
  zero”;
- `RewItem*` is guaranteed item reward evidence;
- `RewChoiceItem*` is the alternative choice-reward set.

Source slot/order is preserved in provenance for every fixed-slot family. Repeated item IDs across
slots or semantic families are not collapsed before provenance. Choice slot order is presentation
order only; it does not imply gameplay preference/ranking.

For ordinary requirements and reward families, `item_id = 0` means the CMaNGOS slot is absent. A
nonzero item ID with an unexpected zero quantity is retained as source-shaped anomaly evidence rather
than silently defaulted. `ReqSourceCount = 0` is the documented exception above. OctoDB counts must be
extracted from structural page data; a visually omitted “1” must not be guessed from prose.

Missing canonical item identity stays an unresolved native item ID with source/slot/quantity evidence;
P3-T05 must not fabricate an item row solely to satisfy a foreign key. Non-item rewards remain outside
P3-T05 unless later implementation proves they are structurally inseparable.

## D-033 — P3-T05 authority adds direct Octo quest-query observations and pinned Turtle 1.18.1 SQL

**Status:** accepted

A post-P3-T05A audit found two materially stronger P3-T05 inputs that were not part of D-032's
original investigation: direct quest-query observations from the live Octo client/server interaction
through ClassicAPI, and a current structured Turtle 1.18.1 world-SQL restoration. D-033 supersedes
D-032 **only for the current P3-T05 source-priority/acquisition strategy**. D-032 remains the durable
record of P3-T05A and its semantic distinctions, source-slot preservation, `ReqSourceCount = 0`
handling, OctoDB fail-closed parsing and partial-positive absence rules remain applicable.

Pinned public semantic/reference revisions for this decision are:

```text
brues-code/ClassicAPI
master @ e793f80f6b45ed49a94dc8abdc9fcac4fe6b03dd

Penqle/tortoise-wow
main @ 61a8269151721f6467eddb05e7bed37704d0fc0b

SandreaSub/Questie-Octo
main @ 389af5f003f1a0f05132a7d39410c7d184700800

Xian55/tortoise-db-viewer
main @ f274ac2b00aa7e3b25def609bd354ca4feb298e9
```

ClassicAPI establishes a direct Octo observation path. At the pinned revision,
`C_QuestLog.RequestLoadQuestByID(questID)` loads/requests quest static data and settles through
`QUEST_DATA_LOAD_RESULT`; `C_QuestLog.GetQuestDetails(questID)` exposes ordinary item requirements as
native item ID + count, guaranteed reward items + counts, choice reward items + counts, and
`srcItemID`. Observations obtained by running this path in the user's actual Octo client are stored
under a distinct source identity such as:

```text
octo-live-quest-query
```

This source is high-authority **positive field evidence**, not a complete server quest-template view.
The reviewed API does not expose `ReqSourceId/ReqSourceCount` or a count corresponding to
`srcItemID`; several other server-enforced quest restrictions are also absent from the Vanilla query
cache. Query failure, a missing field, or an unqueryable candidate therefore means unknown for that
fact and may not authorize negative complete-set cleanup. Live captures must record client/realm and
capture metadata where available and preserve the raw capture alongside any normalized projection.

`Penqle/tortoise-wow` at the pinned revision is an unofficial community restoration of Turtle-WoW
1.18.1 build 7272. For P3-T05, the relevant source-shaped data is the effective `quest_template`
formed from:

```text
sql/base/tw_world_quest_template.sql
sql/database_updates/world/*
```

with only applicable ordered world migrations affecting the bounded quest-template facts included in
the deterministic input revision. This source is registered separately, for example as:

```text
tortoise-world-sql
```

It is a broad, structured, close Turtle-lineage source that can cover custom content and the fixed
slot families absent from pfQuest. It is **not** relabeled as Octo production truth. Any disagreement
with direct Octo observations or OctoDB remains an explicit source conflict under D-006. Questie-Octo
is corroborating audit evidence that current Turtle/Tortoise server source is practically useful for
Octo quest/spawn/script verification; it is not promoted to a canonical source by this decision.

The current field-family priority target becomes:

| P3-T05 family | Current selection priority |
| --- | --- |
| ordinary required item + count | Octo live quest query -> OctoDB -> Tortoise SQL -> CMaNGOS Vanilla |
| guaranteed reward item + count | Octo live quest query -> OctoDB -> Tortoise SQL -> CMaNGOS Vanilla |
| choice reward item + count | Octo live quest query -> OctoDB -> Tortoise SQL -> CMaNGOS Vanilla |
| quest-start/source item ID | Octo live quest query -> OctoDB -> Tortoise SQL -> CMaNGOS Vanilla |
| quest-start/source item count | OctoDB only when structurally explicit -> Tortoise SQL -> CMaNGOS Vanilla |
| `ReqSource` ID/raw count semantics | Tortoise SQL -> CMaNGOS Vanilla; Octo-specific live coverage remains unresolved |

Priority is field-family-specific and does not imply that a lower row is erased when a higher source
exists. Competing observations remain provenance. A lower-priority complete source may fill missing
facts when the explicit family policy allows it, but it cannot manufacture a field the higher source
does not expose or reinterpret absence as contradiction.

`tortoise-db-viewer` is retained as a technical implementation/reference source, not as P3-T05 raw
evidence. Its builder correctly stages Tortoise base SQL plus migrations, but its derived
`quest_item(quest,item,role,count)` projection intentionally normalizes source semantics, including
suppressing a `ReqSource` row when the same item is already an ordinary `ReqItem`. That is useful for
its UI but would destroy source-family/slot/duplicate evidence required by D-005/D-006/D-032.
OctoGameBDD must therefore consume source-shaped Tortoise SQL rather than importing the viewer's
final quest projection as canonical P3-T05 evidence.

Because the new hierarchy changes acquisition and reconciliation assumptions immediately before
schema implementation, P3-T05 is gated by P3-T05B. P3-T05B must validate a source-shaped Tortoise
adapter and a conservative direct-Octo live capture path, establish deterministic revisions and
cross-source golden comparisons, and leave the canonical DB unchanged. Only after P3-T05B is
validated may P3-T05 resume implementation against D-033.
