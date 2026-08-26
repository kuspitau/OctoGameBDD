# Data Sources

The project is intentionally multi-source. No single external database is assumed to be perfectly exhaustive or perfectly authoritative for Octo.

## Priority concept

Do **not** hard-code one universal total order for every field.

Use source-aware and field/relation-aware resolution policies. As a default conceptual hierarchy:

1. Octo-specific authoritative/maintained sources;
2. data observed/extracted directly from the Octo client/server interaction;
3. close/current Turtle sources;
4. Vanilla VMaNGOS/CMaNGOS-style baselines;
5. fallback/community data where explicitly approved.

Preserve disagreements even when a canonical winner is selected.

For P3-T05 specifically, D-033 supersedes D-032's original source-priority/acquisition order after a
later audit found a direct Octo quest-query path and a structured Turtle 1.18.1 SQL source. D-032's
semantic distinctions and conservative absence rules remain applicable.

## Primary sources

### OctoDB

- URL: `https://octowow.st/db/`
- Role: primary Octo-specific reference for items/NPCs/quests/objects/spells and their relations where exposed.
- Import strategy:
  - cache raw pages/payloads;
  - parse reproducibly;
  - rate-limit politely;
  - record source URL/ID and retrieval/import metadata;
  - do not repeatedly hit the website when cached source data exists.

#### P3-T05A quest item/reward observation contract

Public investigation on 2026-08-25 found no documented stable structured OctoDB quest endpoint or
immutable database revision. P3-T05 therefore uses the native-ID quest-detail page as the Octo-specific
observation surface, not browse/search result sets:

```text
https://octowow.st/db/?quest=<quest_id>
```

The page is AoWoW-shaped and current pages structurally expose item links under the quest requirement
and reward sections. Representative observations checked during P3-T05A include:

```text
quest 818   A Solvent Spirit       Vanilla
  required: Intact Makrura Eye x4; Crawler Mucus x8
  guaranteed reward: Really Sticky Glue

quest 815   Break a Few Eggs       Vanilla
  required: Taillasher Egg x3
  guaranteed rewards: Tough Hunk of Bread; Tough Jerky

quest 40788 Heavy Earthen Cores    Octo/Turtle custom
  required: Heavy Earthen Core x8
  choice rewards: Roasted Quail; Morning Glory Dew

quest 40675 A Hero's Reward        Octo/Turtle custom
  choice rewards: Band of Durotar; Signet of Durotar; Ring of Durotar
```

The open Vanilla AoWoW implementation `MarkusNemesis/vanillawowdb` at revision
`06e30fae4d448eada30f465c2bef6763f9664596` is a format/lineage reference only, not proof of the
exact OctoDB deployed revision. Its quest templates corroborate the visible family distinction:
ordinary item requirements, a quest-start `Provided Item`, guaranteed item rewards and choice item
rewards are rendered in separate structures, and the item icon calls retain counts even where a
human-visible count of one is omitted.

P3-T05 implementation must inspect the cached raw OctoDB HTML and accept only a source-shaped
structural parse. It must use native item links plus explicit structural count data from the page;
localized quest prose is not a quantity source, and a visually omitted `1` must not be guessed. If
the expected section/item/count representation is absent or changes, the parser fails closed and
reports the page for re-inspection.

OctoDB HTML is deliberately **partial observation evidence** for P3-T05. A successfully parsed page
may supply explicit positive facts, but a missing section/page is not complete negative evidence and
must not drive stale canonical-member cleanup by itself. This conservative rule also avoids treating
current OctoDB browse/filter completeness as authoritative.

Raw/cache convention follows D-014 and `data/README.md`:

```text
data/raw/octodb/quests/<quest_id>.html
```

A future downloader may keep request metadata/manifests beside that local tree or under
`data/cache/octodb/`; these artifacts remain ignored and are not distributed in Git. It must prefer
an already matching cached artifact. For network retrieval, use a descriptive User-Agent, no more
than one request per second by default, bounded retry/backoff for transient failures, and no automatic
parallel scraping unless a later task establishes a service-safe policy.

Because the service exposes no immutable public data revision, deterministic source identity is
content-based:

- per page: SHA-256 of the exact response bytes after a successful retrieval;
- batch: SHA-256 of a deterministic UTF-8 manifest containing sorted `(quest_id, page_sha256)` pairs;
- retrieval URL/native quest ID, retrieval time, HTTP status/content type and content hash are retained
  as provenance/import metadata;
- retrieval timestamp never replaces the content hash as source revision.

D-033 keeps this OctoDB contract intact but places direct live Octo quest-query observations ahead of
OctoDB for the specific fields that the live client/server response actually exposes.

### pfQuest

- Repository: `https://github.com/shagu/pfQuest`
- Role: broad Vanilla-style structured Lua dataset; useful skeleton for units, objects, quests, items, zones, coordinates and relations.

P1/P2/P3 public-format inspection is pinned to upstream revision:

```text
104f35678ca39ab1fb78b655f815cc7016f5e0c8
```

The relevant P1 world-slice files at that revision are:

```text
db/zones.lua
db/enUS/zones.lua
db/units.lua
db/enUS/units.lua
db/objects.lua
db/enUS/objects.lua
```

The inspected pfQuest code consumes unit/object `coords` entries as positional `{x, y, zone, respawn}` records. X/Y are zone-percentage coordinates. Zone geometry records are also positional and carry pfQuest-specific coordinate/map context; P1-T01 preserves that context as source provenance instead of assigning canonical map/parent-zone semantics without an authoritative mapping.

The tracked P1-T01 source fixture mirrors those six file paths but is deliberately reduced. The parser is a dependency-free Lua literal-table subset parser, not a general Lua interpreter. Full-source compatibility must be expanded and validated deliberately before P6 full ingestion.

#### P2-T01 item/direct-loot format

P2-T01 reuses the same literal-Lua parser and inspects the item tables at the pinned upstream
revision. Direct item/source identity inputs are:

```text
db/items.lua
db/enUS/items.lua
db/enUS/units.lua
db/enUS/objects.lua
```

Relevant direct source shape:

```text
pfDB["items"]["data"][item_id]["U"][creature_id] = chance_percent
pfDB["items"]["data"][item_id]["O"][gameobject_id] = chance_percent
pfDB["items"]["enUS"][item_id] = item_name
pfDB["units"]["enUS"][creature_id] = creature_name
pfDB["objects"]["enUS"][gameobject_id] = gameobject_name
```

For direct P2 loot:

- `U` is direct creature-loot evidence;
- `O` is direct game-object-loot evidence;
- the numeric value is preserved as the source-listed drop chance percentage;
- item identity/name and direct relations carry pfQuest source/revision/import-batch provenance;
- the unit/object enUS tables supply source identity for legitimate loot targets that have no static
  P1 world record or spawn.

A referenced direct `U`/`O` target may therefore exist as a relation-only canonical template with no
spawn. The importer records the pfQuest-provided name and leaves geography unknown. If a direct
target is absent both from the P1 world and from the corresponding pfQuest enUS name table, the
import fails closed rather than inventing a placeholder identity.

#### P2-T02 reference-loot format

P2-T02 additionally consumes:

```text
db/refloot.lua
```

The deterministic P2 item-source revision hashes the exact five files:

```text
db/items.lua
db/refloot.lua
db/enUS/items.lua
db/enUS/units.lua
db/enUS/objects.lua
```

Primary-source inspection of `database.lua` (`SearchItemID`) and `db/refloot.lua` at the pinned
revision establishes this contract:

```text
pfDB["items"]["data"][item_id]["R"][reference_loot_id] = chance_percent

pfDB["refloot"]["data"][reference_loot_id]["U"][creature_id] = membership_marker
pfDB["refloot"]["data"][reference_loot_id]["O"][gameobject_id] = membership_marker
```

pfQuest itself resolves an item `R` by:

1. reading the item-side `reference_loot_id -> chance` relation;
2. looking up that ID in `pfDB["refloot"]["data"]`;
3. iterating each `U` and `O` member key;
4. exposing each resulting creature/game-object using the **item-side R chance** as droprate.

The refloot member values are not used by this resolution code; they are membership markers in this
pinned source contract, not probabilities or weights. P2-T02 preserves those numeric markers only as
source provenance.

The pinned resolver performs one-level expansion. It does not recursively resolve `R` fields inside
`refloot`, and the reviewed data/search contract provides no chain/cycle semantics to infer. The P2
adapter therefore treats nested `R` in a refloot definition as unsupported/malformed instead of
inventing recursive behavior.

Direct `U`/`O` and `R` are parallel acquisition paths. The project does not assume independence,
mutual exclusion, or another probability-combination rule when they overlap. Query code deduplicates
the resulting source/spawn while retaining each path/chance separately.

A missing refloot definition is preserved as a native item -> reference relation and reported with an
explicit reason. A reference member that lacks both an existing canonical template and a pfQuest enUS
identity remains provenance evidence and is reported rather than being assigned a fabricated name or
location. Direct target identity continues to use the stricter P2-T01 fail-closed rule.

#### P2-T03 vendor format

At the pinned pfQuest revision, the extractor populates:

```text
pfDB["items"]["data"][item_id]["V"][vendor_creature_id] = maxcount
```

`V` therefore means a vendor creature relation and its source `maxcount`, not drop chance, buy price,
restock duration, or a generalized stock policy. P2-T03 preserves `maxcount` in `vendor_source`
provenance and materializes the explicit `vendor_items` relation.

The P2 fixture under `tests/fixtures/pfquest/items_slice/` is a tiny source-shaped sample, not a
redistribution of the full item/reference database.

#### P3-T01 quest identity/endpoints format

P3-T01 inspects the quest tables and pfQuest runtime lookup behavior at the same pinned revision.
The bounded base inputs are exactly:

```text
db/quests.lua
db/enUS/quests.lua
```

Relevant source shape:

```text
pfDB["quests"]["data"][quest_id]["start"]["U"] = { creature_id, ... }
pfDB["quests"]["data"][quest_id]["start"]["O"] = { gameobject_id, ... }
pfDB["quests"]["data"][quest_id]["end"]["U"]   = { creature_id, ... }
pfDB["quests"]["data"][quest_id]["end"]["O"]   = { gameobject_id, ... }

pfDB["quests"]["enUS"][quest_id]["T"] = quest_title
```

The pfQuest runtime uses its active locale table with enUS fallback and reads quest title field `T`.
The endpoint field families are explicit:

- `start.U` -> creature giver;
- `start.O` -> game-object giver;
- `end.U` -> creature finisher;
- `end.O` -> game-object finisher.

Endpoint lists may contain multiple IDs. Omitted/empty supported lists mean there is no endpoint of
that family. pfQuest also supports other start shapes such as `start.I` for an item-started quest;
P3-T01 deliberately leaves those semantics for later work instead of coercing the item into a
creature/game-object endpoint.

Quest identity scans the union of numeric IDs in the data and enUS tables. A valid locale-only `T`
therefore remains a canonical identity with no inferred endpoints; a row without a usable enUS title
is explicitly reported and skipped rather than receiving a fabricated name.

The deterministic base P3-T01 source revision hashes exactly the two files above. Quest title and each
supported endpoint relation are stored as independent pfQuest provenance observations.

A supported endpoint whose native creature/game-object ID is absent from the canonical P1 world is
retained as source relation evidence and reported under `unresolved_endpoints`. P3-T01 does not invent
a placeholder target or location and does not widen the input set solely to manufacture a relation-only
identity.

The P3 fixture under `tests/fixtures/pfquest/quests_slice/` is a tiny project-selected source-shaped
sample covering multiple giver/finisher endpoints, a missing P1 target, a missing enUS title and an
explicitly deferred item-start relation.

The upstream pfQuest repository uses the MIT license. Tracked fixtures contain only minimal
representative structures/records.

### pfQuest-turtle

- Reviewed public repository: `https://github.com/KameleonUK/pfQuest-turtle`
- P1-T03/P2-T04/P3-T02 reviewed revision: `5b8eeeeb4119be9d075087f0f0e08c187b35ad61`
- Role: current Turtle-style pfQuest overlay present in the user's launcher-managed Octo installation; important source for custom/current world, item/acquisition and bounded quest data.

Relevant P1 composition evidence includes:

```text
pfQuest-turtle.toc
patchtable.lua
overwrites.lua
db/zones-turtle.lua
db/enUS/zones-turtle.lua
db/units-turtle.lua
db/enUS/units-turtle.lua
db/objects-turtle.lua
db/enUS/objects-turtle.lua
```

The addon declares a dependency on pfQuest, loads Turtle data/localization tables, then runs
`overwrites.lua` before `patchtable.lua`.

The reviewed `patchtable.lua` applies the patch at **top-entry level**:

- if a patch value is the string `"_"`, the base entry is removed;
- otherwise the patch value replaces the corresponding base entry wholesale;
- this is not a recursive merge.

The reviewed Kameleon `overwrites.lua` also removes a documented set of phantom zone IDs from
localized Turtle zone tables through a small loop. P1-T03 reproduces this known safe pattern without
executing Lua **when the loaded source contains it**.

The launcher-installed copy used for Level-2 validation can differ from the reviewed public revision.
In the previously observed local copy, the phantom-zone cleanup loop is absent, so the effective local
view correctly retains entries that the newer reviewed public `overwrites.lua` would remove.
Public-revision behavior is never injected into a different installed source.

Local validation key:

```toml
[source_paths]
pfquest_turtle = "..."
```

#### P2-T04 effective item/acquisition view

P2-T04 extends the bounded composition to the exact P2 fact family already implemented. The reviewed
Turtle load lists contain:

```text
db/items-turtle.lua
db/refloot-turtle.lua
db/enUS/items-turtle.lua
db/enUS/units-turtle.lua
db/enUS/objects-turtle.lua
overwrites.lua
patchtable.lua
```

The public reviewed `items-turtle.lua` contains all three relevant top-entry shapes: ordinary whole
replacements, empty tables that wipe base acquisition fields, and `"_"` removals. The reviewed
`refloot-turtle.lua` also contains `"_"` removals and whole reference-definition replacements.
`overwrites.lua` contains at least one direct nested assignment into
`pfDB["items"]["data-turtle"]`; P2-T04 therefore applies supported direct literal mutations before
top-entry composition instead of treating the patch files as immutable.

The effective P2 view is intentionally limited to:

```text
item enUS identity/name
item U direct creature loot
item O direct game-object loot
item R one-level reference loot
item V vendor relation/maxcount
refloot U/O membership
unit/object enUS identity for relation-only targets
```

The project does **not** import Turtle item stats, quest/recipe implications, prices/economics, or a
general arbitrary-Lua overlay in P2-T04.

Item data membership and item localization membership are distinct. This matches pfQuest itself:
`SearchItemID` aborts when `items[id]` is absent, while name lookup iterates the localized item table.
Accordingly an `items-turtle.lua` `"_"` removal clears the managed acquisition set but does not by
itself erase a still-present item name.

P2-T04 stores the Turtle evidence under the distinct `pfquest-turtle` source identity. For patched
entries it records complete source-view facts (`item_presence`, `item_acquisition_set`,
`loot_reference_presence`, `loot_reference_member_set`) in addition to the existing individual
relation observations. D-027 defines when those sets may supersede base pfQuest materialization and
when stale managed relations may be removed. Explicit/custom selections are protected by policy,
even when their selected observation uses the `pfquest` source key; a protected complete set never
causes Turtle primitive relation provenance to be fabricated for relations absent from Turtle.

Installed Turtle data may also contain a U/O/V target ID that has no matching canonical P1 identity
and no usable effective enUS unit/object identity. Level-2 validation exposed such a case. P2-T04
preserves that acquisition relation in provenance and reports it under
`unresolved_acquisition_targets`; it does not invent a named creature/gameobject and therefore does
not materialize the relation into an FK-backed domain table until an identity source exists.

The deterministic P2 Turtle revision hashes the exact validated composition inputs above plus the
toc/XML load-list files. A materially different local layout or unsupported indirect mutation of a bounded P2
input table fails explicitly rather than being guessed.

#### P3-T02 effective quest identity/endpoint view

The reviewed Turtle addon contains the bounded P3 inputs:

```text
pfQuest-turtle.toc
init/data-turtle.xml
init/enUS-turtle.xml
db/quests-turtle.lua
db/enUS/quests-turtle.lua
overwrites.lua
patchtable.lua
```

The TOC loads Turtle data/localization before `overwrites.lua` and `patchtable.lua`. The reviewed
`patchtable.lua` includes `quests` in the same top-entry patch mechanism used by other Turtle tables:
`"_"` removes a quest top-level entry and any other value replaces the base entry wholesale.

At reviewed revision `5b8eeeeb4119be9d075087f0f0e08c187b35ad61`, `overwrites.lua` includes a
direct nested mutation of `pfDB["quests"]["data-turtle"]`. P3-T02 therefore applies direct literal
mutations of the bounded quest patch tables before composition and fails closed on unsupported
indirect/runtime mutations instead of executing arbitrary Lua.

P3-T02 is limited to the P3-T01 fact family:

```text
quest enUS identity/name (T)
start.U creature giver
start.O game-object giver
end.U creature finisher
end.O game-object finisher
```

It does not import objectives, prerequisites/follow-ups, required items, rewards, richer restrictions
or item-start semantics.

D-028 records complete effective-view facts under the distinct `pfquest-turtle` source:

```text
quest_presence
quest_endpoint_set
```

These are complete-view membership facts, not a reason to relabel inherited primitive facts. A quest
name or endpoint inherited unchanged from base pfQuest keeps pfQuest primitive `name`/`endpoint`
provenance even though it participates in the active Turtle effective view. Explicit/custom selected
facts remain protected; stale managed canonical identities/endpoints may be removed only under the
bounded D-028 policy, while historical source observations are retained.

A Turtle-selected endpoint whose target is missing from canonical P1 identity remains unresolved
provenance and is not materialized through a fabricated target/spawn/geography. P3-T02 deliberately
does not widen to Turtle unit/object identity solely to hide that diagnostic.

The deterministic P3 Turtle revision hashes exactly the seven files listed above. The installed local
copy remains the authoritative Level-2/version-specific input; a source layout that materially differs
from the reviewed contract must fail explicitly and be re-inspected rather than guessed.

### pfQuest-octo

- Repository: `https://github.com/paokkerkir/pfQuest-octo`
- Role: Octo-specific additions/overwrites for pfQuest; especially useful as comparison/enrichment for custom content, coordinates and unit/object corrections.

P1-T03 review is pinned to:

```text
dd3dc1fb80afe7a71e5c8ca8c31ca2a3ef57af67
```

The reviewed latest commit is dated 2026-05-12 and is titled:

```text
db: revert to 1.17.2 data
```

Therefore P1-T03 does **not** assume `pfQuest-octo` is globally newer or automatically preferable to
the currently maintained Turtle fork. It remains relevant because `overwrites.lua` contains explicit
Octo-specific manual corrections, including unit name/faction/coordinate changes.

When pfQuest base, current Turtle and pfQuest-octo differ, preserve source identities and compare them
before defining canonical policy.

Optional local key:

```toml
[source_paths]
pfquest_octo = "..."
```

#### P1-T03 effective-view contract

P1-T03 constructs independent effective views:

```text
pfQuest + pfQuest-turtle
pfQuest + pfQuest-octo   (when available)
```

It compares zone/creature/gameobject IDs that are added, removed or changed. It does **not** choose a
canonical winner and does not write either overlay into SQLite. Canonical/provenance reconciliation
is handled by P1-T04 because deletion and replaced spawn sets require explicit durable semantics.

#### P1-T04 provenance/reconciliation contract

P1-T04 preserves three distinct source identities in SQLite:

```text
pfquest
pfquest-turtle
pfquest-octo
```

For reproducible local validation it can derive content revisions from the exact six P1 pfQuest world
files and the exact Turtle-style overlay input set (`*-turtle` files plus `overwrites.lua`). The
content revision identifies the installed inputs; it does not claim equivalence with a reviewed
public commit.

Effective-source deletion is recorded as:

```text
world_presence = false
```

This means absent from that effective source view, not globally nonexistent.

Creature/game-object top-entry replacement is also represented by a complete deterministic:

```text
spawn_set
```

The installed `pfquest-turtle` view is the active pfQuest-family P1 view and may supersede only
base/default pfQuest selections for this bounded fact family. It does not override explicit or
non-pfQuest selections. Stale canonical spawn rows selected from the managed pfQuest family are
removed when absent from the selected Turtle set, while all old source observations remain.

`pfquest-octo` remains comparison evidence in P1-T04: differences are recorded under its own source
revision but do not automatically mutate canonical world rows. A future decision may introduce
field/relation-specific Octo selection where justified; P1-T04 deliberately does not invent one.

### Octo client DBC

Extract from the user's actual Octo client where available.

Useful areas include:

- maps/zones/area hierarchy;
- spells and icons;
- skill/profession data;
- item display/set/random-property metadata;
- creature types/families/display data;
- locks/factions/talents and other client-side reference tables.

These files are local/large and normally remain outside Git.

#### P1-T02 Map/Area vertical slice

P1-T02 consumes only:

```text
Map.dbc
AreaTable.dbc
```

from a local extracted DBC directory configured as:

```toml
[source_paths]
octo_dbc = "..."
```

The user's actual local files are registered as source key:

```text
octo-client-dbc
```

When an explicit client build/revision is unavailable, the importer computes a deterministic SHA-256
composite revision from the exact `Map.dbc` / `AreaTable.dbc` bytes. Re-importing unchanged files
therefore reuses stable source observations while still recording a new import-batch trace.

The classic WDBC container and field semantics were checked against CMaNGOS Classic source revision:

```text
9b682be617ac61c127c23aa60d7b4ffbc0ce37e6
```

Relevant format-reference files:

```text
src/shared/Database/DBCFileLoader.cpp
src/game/Server/DBCStructure.h
src/game/Server/DBCEnums.h
src/game/Server/DBCStores.cpp
```

This CMaNGOS source is a parser/semantic reference only. CMaNGOS rows are not imported as Octo truth
by P1-T02.

For the bounded facts defined by D-025, the direct Octo client DBC is authoritative for canonical
map/area identity and hierarchy:

- map name/type;
- zone/area name;
- area -> map relation;
- subzone -> parent-area relation.

This does not establish a universal DBC-over-everything rule. Other fields/relations continue to use
explicit source-aware policies, and all competing observations remain preserved.

The P1-T02 binary tests use small synthetic WDBC files. Real client DBC files are never committed.

#### P4-T01 spell/recipe semantic contract

P4-T01 inspects public source behavior before any broad crafting migration. The primary pinned
semantic reference is:

```text
repository: https://github.com/Penqle/tortoise-wow
revision:   61a8269151721f6467eddb05e7bed37704d0fc0b
branch:     main
```

Relevant files:

```text
src/game/Database/DBCStructure.h
src/game/Spells/SpellEntry.h
src/game/Spells/SpellDefines.h
src/game/Spells/SpellEffects.cpp
src/game/Objects/ItemPrototype.h
src/game/Objects/Creature.h
src/game/Handlers/NPCHandler.cpp
sql/base/tw_world_npc_trainer.sql
sql/base/tw_world_npc_trainer_template.sql
```

Established source semantics:

- `Spell.Id` is native spell identity; `SpellName` and `Rank` are metadata and do not collapse IDs;
- `SkillLineAbility.skillId` relates a profession/skill line to `spellId`;
- `SkillLineAbility.req_skill_value` is the trade-skill requirement for the reviewed source shape;
- `SPELL_EFFECT_CREATE_ITEM = 24` uses `EffectItemType[slot]` as the created item target;
- created count comes from the calculated spell-effect value, so `EffectBasePoints` alone is not a
  universally safe final recipe-output quantity;
- `SPELL_EFFECT_LEARN_SPELL = 36` uses `EffectTriggerSpell[slot]` as the learned spell target;
- item spell data is an array of slots carrying `SpellId`, trigger and charge/cooldown semantics;
- trainer rows preserve an acquisition spell plus independent `reqskill`, `reqskillvalue`, `reqlevel`
  and cost fields.

This establishes D-034. The reviewed Tortoise source is a semantic/structured Turtle-lineage
reference, not proof of exact Octo production presence. For P4-T02 actual Octo spell and skill-line
identity should prefer the configured direct Octo DBC when its layout is verified. The existing
`[source_paths].octo_dbc` key is sufficient; P4-T01 adds no new local path.

For the exact source revision, preserve effect and item-spell slot/order as provenance. An item or
trainer acquisition spell is not automatically the recipe spell; a `LEARN_SPELL` effect must prove
the target. A craft spell becomes a recipe candidate only when source evidence also proves
profession/skill-line membership and at least one `CREATE_ITEM` effect.

The tracked P4-T01 fixture is intentionally reduced and source-shaped rather than copied from the
full external source:

```text
tests/fixtures/p4_t01/source_contract.json
```

Its deterministic content revision is:

```text
sha256:cf4661faa4e9f8f7ba7d4f38f2dea1175a02eb4f8236638b7b3704da9b59cf14
```

CMaNGOS Classic revision `9b682be617ac61c127c23aa60d7b4ffbc0ce37e6`, already pinned for P1-T02,
remains compatible Vanilla DBC/parser corroboration. No new universal source-priority order is created
by P4-T01.

### Octo client WDB cache

Potential files include item/creature/gameobject/quest caches.

Role:

- highly valuable direct observations from Octo;
- useful for custom entries and conflict checking.

Limitation:

- cache coverage depends on what the client has actually queried, so it is not inherently exhaustive.

### Octo live quest-query observations via ClassicAPI

Pinned public semantic reference for P3-T05B/D-033:

```text
repository: https://github.com/brues-code/ClassicAPI
revision:   e793f80f6b45ed49a94dc8abdc9fcac4fe6b03dd
branch:     master
```

Relevant implementation files:

```text
src/quest/Data.cpp
src/quest/Details.cpp
src/quest/Cache.h
```

At that revision:

- `C_QuestLog.RequestLoadQuestByID(questID)` requests/loads quest static data and settles through
  `QUEST_DATA_LOAD_RESULT`;
- `C_QuestLog.GetQuestDetails(questID)` emits ordinary item requirements with native item ID and
  exact count;
- `rewardItems` emits guaranteed item IDs/counts;
- `choiceItems` emits choice reward IDs/counts;
- `srcItemID` exposes the quest-start source/provided item ID.

A capture performed in the user's actual Octo client is registered separately as, for example:

```text
octo-live-quest-query
```

This is direct Octo client/server **positive field evidence**, not a complete database export. The
reviewed API does not expose `ReqSourceId/ReqSourceCount` or a count paired with `srcItemID`, and it
explicitly documents other server-enforced quest fields that the 1.12 query cache does not contain.
A failed query, missing result or missing field is therefore unknown, never complete negative
evidence.

The acquisition path must be conservative. ClassicAPI documents that materializing full quest detail
tables for hundreds of quests in a tight loop can exhaust Vanilla's fixed Lua memory pool. A P3-T05B
probe should therefore be user-triggered, resumable and sequential, with one outstanding request at a
time: request an ID, wait for `QUEST_DATA_LOAD_RESULT`, copy only the bounded source-shaped fields,
then continue. Candidate IDs should come from the union of known canonical/pfQuest/Tortoise/cached
OctoDB quest IDs rather than brute-forcing an arbitrary numeric range.

Raw capture and normalized projection must stay distinguishable. A recommended ignored local layout
is:

```text
data/raw/octo-live/quest-query/<capture-id>/
```

Retain the original SavedVariables/raw capture and a manifest carrying the capture ID, client/build or
realm metadata when knowable, ClassicAPI semantic revision, timestamps and deterministic content
hashes. A later normalized projection must never replace the raw observation as provenance.

## Secondary / enrichment sources

### Tortoise-WoW 1.18.1 restoration data

Pinned P3-T05B/D-033 reference:

```text
repository: https://github.com/Penqle/tortoise-wow
revision:   61a8269151721f6467eddb05e7bed37704d0fc0b
branch:     main
```

The repository describes itself as an unofficial community-driven restoration of Turtle-WoW 1.18.1,
targeting build 7272 with the 2026-04-12 hotfixes. Its documented database setup imports `sql/base`
and then applies tracked server database updates. This makes it a close, structured Turtle-lineage
source for custom/current world content, but **not proof of the exact Octo production database**.

For P3-T05B the source-shaped effective quest input is:

```text
sql/base/tw_world_quest_template.sql
sql/database_updates/world/*
```

Only applicable ordered world migrations that actually alter the bounded quest-template facts need
to participate in the deterministic P3-T05B revision. The adapter must preserve the source families,
slot numbers, duplicate/repeated IDs, explicit zeros and source anomalies rather than first collapsing
them into a UI-oriented model.

Register this evidence distinctly, for example:

```text
tortoise-world-sql
```

Tortoise can provide broad structured evidence for ordinary required items, auxiliary `ReqSource`,
quest-start/source item fields, guaranteed rewards and choice rewards, including custom 1.18.1
content. Under D-033 it sits below direct Octo live observations and OctoDB where those sources expose
the bounded family, and above the Vanilla CMaNGOS fallback. Conflicts are preserved rather than being
relabelled or silently overwritten.

For P4-T01 the same pinned revision is also a primary **semantic reference** for spell effects,
SkillLineAbility, item spell slots and trainer acquisition rows. That use does not change the P3-T05
source-priority policy and does not relabel Tortoise rows as exact Octo production data.

### Tortoise-WoW Database Viewer

Pinned technical reference:

```text
repository: https://github.com/Xian55/tortoise-db-viewer
revision:   f274ac2b00aa7e3b25def609bd354ca4feb298e9
branch:     main
```

Role: technical reference for parsing, ordered migration application, normalization, loot-reference
resolution, DBC+SQL joins, spell/item/recipe reconstruction and local SQLite exploration.

Its builder is useful corroboration because it stages `Penqle/tortoise-wow` base SQL and
`sql/database_updates/world` before deriving the browser database. However, its final quest model is
already transformed: it projects quest items to `quest_item(quest,item,role,count)` and intentionally
suppresses a `ReqSource` member when the same native item is already present as a normal requirement.
That behavior is reasonable for the viewer UI but loses exactly the source-family/slot/duplicate
evidence OctoGameBDD requires.

Strategy: study/selectively adapt parser/migration ideas where licensing allows; do **not** ingest the
viewer SQLite/`quest_item` projection as raw P3-T05 truth and do not adopt its final schema as
OctoGameBDD's canonical architecture.

### Questie-Octo audit corroboration

Pinned audit reference:

```text
repository: https://github.com/SandreaSub/Questie-Octo
revision:   389af5f003f1a0f05132a7d39410c7d184700800
branch:     main
```

`Docs/SOURCE_PROVENANCE.md` records a maintenance practice that treats direct current Octo client
extractions as client-side authority and current Turtle/Tortoise server source as server-side
quest/spawn/script evidence, while keeping addons as comparison/reference implementations. This is
useful corroboration that Tortoise data is practically relevant when auditing Octo behavior.

Questie-Octo is **not** promoted to a primary canonical source for OctoGameBDD by D-033. Its generated
or presentation-oriented tables remain secondary corroboration unless a future bounded task reviews a
specific field contract.
