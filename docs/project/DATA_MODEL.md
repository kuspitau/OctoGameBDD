# Canonical Data Model

This document defines semantic boundaries. Exact SQL columns are established incrementally through migrations.

## Identity rule

Preserve native game/source identifiers.

A project-local surrogate key may exist, but do not replace useful native IDs with opaque IDs. Source IDs are critical for joining OctoDB, pfQuest, SQL dumps, DBC/WDB, and in-game data.

## Core entities

### Item

Representative attributes:

- native item ID;
- name;
- quality;
- item level / required level;
- class/subclass;
- inventory slot;
- binding/uniqueness flags;
- armor/block/damage/speed/durability;
- prices when authoritative;
- icon/display references;
- descriptions/requirements.

Variable stats belong in normalized structures such as `item_stats(item_id, stat_type, value, ...)`, not a permanently hard-coded narrow schema.

Item effects may relate to spells.

### Creature

A creature template/type, not a geographic instance.

Typical relations:

- creature -> spawn(s);
- creature -> loot entries;
- creature -> quest giver/finisher role;
- creature -> vendor items;
- creature -> trainer spells;
- creature -> abilities/spells when available.

### CreatureSpawn

A particular spawn record.

Representative attributes:

- creature;
- map;
- position X/Y/Z;
- orientation;
- source/native spawn ID when available;
- spawn/group metadata as available.

Zone/subzone can be directly sourced or derived from coordinates/area mappings.

### GameObject

A game-object template/type.

Examples include chests and interactable world objects.

### GameObjectSpawn

Geographic instance of a game object.

Same template-vs-instance rule as creatures.

### Quest

Representative concepts:

- quest ID;
- title;
- quest/minimum level;
- race/class/faction restrictions;
- giver(s);
- finisher(s);
- prerequisite/follow-up relations;
- objectives;
- required items;
- rewards;
- conditions when known.

Do not model a quest with one simplistic `zone_id`.

### Recipe

A crafting recipe/process.

A recipe is **not** the same thing as:

- a recipe-learning item;
- a spell;
- the produced item.

Representative relations:

- recipe -> profession/skill requirement;
- recipe -> result item(s), quantities;
- recipe -> reagent items, quantities;
- recipe -> learning/acquisition source;
- recipe <-> teaching/crafting spell(s), if that is how the source represents it.

### Spell

First-class because many WoW relationships pass through spells:

```text
recipe item -> teaches spell -> creates item
item use/equip effect -> spell
spell -> reagent(s)
trainer -> spell
```

### Zone / Subzone

First-class geographic content entity.

### Map

World/map identity and coordinate context.

## P1-T01 implemented world schema

Migration 3 establishes the first concrete canonical world tables:

```text
maps
zones
creatures
creature_spawns
gameobjects
gameobject_spawns
```

Identity and separation rules:

- `maps.map_id`, `zones.zone_id`, `creatures.creature_id`, and `gameobjects.gameobject_id` preserve native/source-useful numeric identities;
- creature and game-object templates remain separate from spawn rows;
- spawn rows use a project-local integer `spawn_id` plus a stable deterministic `spawn_key` when the input source does not expose a native spawn identifier;
- nullable map/zone hierarchy columns are preferable to inventing relationships from source-specific coordinate metadata.

Spawn coordinate semantics are explicit:

- `coordinate_space = 'zone_percent'` means X/Y are percentages in the referenced zone and are constrained to `0..100`;
- `coordinate_space = 'world'` reserves the schema path for world-coordinate sources with X/Y and optional Z/orientation;
- a zone-percentage source must not be relabeled as world XYZ merely to fit a generic spawn table.

For the P1-T01 pfQuest fixture slice, unit/object coordinates are represented as:

```text
{x, y, zone_id, respawn_seconds}
```

with `coordinate_space = 'zone_percent'`. pfQuest zone geometry/context is preserved in provenance as `pfquest.coordinate_frame`; its first positional value is not treated as an authoritative canonical `map_id` or `parent_zone_id` in this task.

The canonical world rows and generic source observations remain separate layers. A selected source observation may drive a canonical scalar/position, but competing observations remain in the P0 provenance tables.

## P1-T02 map/area hierarchy semantics

P1-T02 does not add a migration. It fills the nullable hierarchy columns that migration 3 already reserved.

From the user's actual Octo client DBC pair:

```text
Map.dbc
  MapID             -> maps.map_id
  localized name    -> maps.name
  map/instance type -> maps.map_kind (normalized)

AreaTable.dbc
  Area ID           -> zones.zone_id
  localized name    -> zones.name
  map/continent ID  -> zones.map_id
  parent area ID    -> zones.parent_zone_id
```

The map/area DBC facts above use the explicit field-specific selection policy recorded by D-025. Lower-authority observations are not deleted when the DBC becomes canonical.

Additional inspected DBC fields such as exploration flag, area flags, exploration level, faction-group mask, liquid override, and Map linked-area context remain source observations for now. They are not promoted into canonical columns without a demonstrated consumer and corresponding data-model decision.

A spawn with a direct canonical `spawn.map_id` uses that value. If the spawn has only a canonical `zone_id`, query code may derive map context as:

```text
Spawn -> Zone -> Map
```

Direct spawn map identity takes precedence over derived zone map identity. This derived query context is not copied into the spawn row merely for convenience.

Most importantly, map hierarchy resolution is independent from coordinate-space conversion:

```text
zone_percent spawn + canonical zone.map_id
    != world-coordinate spawn
```

A pfQuest spawn remains `coordinate_space = 'zone_percent'` even after its zone has an authoritative map relationship.

## P1-T04 effective-view deletion and complete-set semantics

P1-T04 keeps the migration-3 canonical schema unchanged and uses the generic provenance layer to represent source-view replacement semantics explicitly.

For a P1 zone, creature or game object, effective-view membership is a scalar observation:

```text
world_presence = true | false
```

This is source-scoped evidence. `false` means that the entity is absent from that effective source view; it does not by itself assert universal game non-existence.

For creature and game-object spawn membership, the complete effective source set is observed on the template:

```text
spawn_set = [
  {
    spawn_key,
    coordinate_space,
    zone_id,
    x,
    y,
    respawn_seconds
  },
  ...
]
```

The set is deterministic and complete for that effective source view. Individual members still carry their existing scalar provenance:

```text
Creature/GameObject template
  -> selected spawn_set membership
       -> member spawn_key
            -> selected position
            -> selected respawn_seconds
```

Membership and member attributes are distinct facts. Therefore a stale spawn's historical `position` observation may remain preserved/selected after its canonical spawn row is removed; the selected template `spawn_set` determines whether it is currently a member of the active effective view.

Canonical reconciliation rules:

- the installed Turtle effective view may supersede default/base pfQuest selections for this bounded P1 fact family;
- an explicit/non-pfQuest selection remains authoritative unless a separate decision says otherwise;
- stale canonical spawn rows are removed only when their selected position source belongs to the managed pfQuest family and they are absent from the selected complete Turtle set;
- deleting canonical rows never deletes their `source_observations`;
- an absent creature/game-object template is removed only after its managed spawns are gone and no selected non-pfQuest fact supports retaining it;
- an absent zone row is removed only when no selected non-pfQuest fact and no canonical FK dependency requires the identity anchor;
- optional `pfQuest-octo` evidence is recorded without automatic canonical materialization.

This is the durable P1 interpretation recorded by D-026, not a general tombstone schema for every future domain.

## P2-T01 item/direct-loot schema and semantics

Migration 4 establishes the first concrete item/acquisition tables:

```text
items
creature_loot
gameobject_loot
```

Identity rules:

- `items.item_id` preserves the native item ID;
- `creature_loot` is keyed by `(creature_id, item_id)`;
- `gameobject_loot` is keyed by `(gameobject_id, item_id)`;
- direct loot rows reference the canonical P1 template identities with foreign keys;
- `chance_percent` stores the source-listed percentage and is constrained to `0..100`.

The primitive relation is the acquisition fact itself:

```text
Creature C -> drops Item I with chance P
GameObject G -> drops Item I with chance P
```

The location of that acquisition is derived:

```text
Item I
  <- loot relation - Creature/GameObject template
                       -> Spawn
                          -> Zone
                             -> Map
```

P2-T01 therefore does **not** add an `item_zones` table or a zone column to loot relations. A source with no known canonical spawn remains a valid acquisition source with unknown geography.

Provenance representation for direct loot is relation-shaped evidence on the item:

```text
subject_kind      = item
subject_key       = item_id
fact_key          = loot_source
fact_instance_key = creature:<id> | gameobject:<id>
target             = creature/gameobject native ID
attributes          = {chance_percent: P}
```

Canonical loot materialization follows the selected observation for that relation instance. The first observation is selected only if no prior canonical selection exists; later competing observations remain preserved under D-006.

P2-T01 originally deferred `R` reference-loot and still defers `V` vendor relationships. P2-T02 below resolves `R` without changing the direct tables.

P2-T01 requires a canonical target identity before it can materialize a direct loot row. If a
direct-loot target is absent from the P1 static-world materialization but pfQuest provides its enUS
name, the item importer may create that creature/game-object **template identity only** as a
relation-supported canonical anchor. It does not create a spawn, zone, or coordinates. This handles
legitimate non-static sources such as temporary/event gameobjects while preserving D-009. If neither
the P1 world nor the pfQuest enUS identity table can identify the target, the import fails closed.

## P2-T02 reference-loot schema and semantics

Migration 5 adds the explicit reference-loot graph required by the pinned pfQuest source contract:

```text
loot_references(reference_loot_id)
item_reference_loot(item_id, reference_loot_id, chance_percent)
reference_loot_creatures(reference_loot_id, creature_id)
reference_loot_gameobjects(reference_loot_id, gameobject_id)
```

Native pfQuest reference IDs are preserved. Reference expansion is **not** flattened into
`creature_loot` or `gameobject_loot`; those tables continue to mean direct `U`/`O` evidence.

The primitive P2-T02 relations are:

```text
Item I -> LootReference R with chance P
LootReference R -> member Creature C
LootReference R -> member GameObject G
```

For the pinned pfQuest revision, the item-side `R` numeric value is the drop chance percentage used
by pfQuest for every member reached through that reference. The numeric values stored on
`refloot[R].U/O` are membership markers: pfQuest iterates the member keys and does not interpret
those values as probabilities or weights. The project therefore preserves a membership marker in
provenance but does not add a meaningless canonical probability column to the membership tables.

Provenance slots are:

```text
Item -> reference
  subject_kind      = item
  fact_key          = loot_reference
  fact_instance_key = reference:<reference_loot_id>
  target             = loot_reference:<reference_loot_id>
  attributes          = {chance_percent: P}

Reference -> source member
  subject_kind      = loot_reference
  subject_key       = reference_loot_id
  fact_key          = loot_source_member
  fact_instance_key = creature:<id> | gameobject:<id>
  target             = creature/gameobject native ID
  attributes          = {membership_value: source_marker}
```

The pinned pfQuest resolver performs one-level expansion only. A nested `R` in a refloot definition
is therefore unsupported/malformed input for this adapter rather than a recursive graph to infer.
Chains/cycles are not silently invented.

The effective acquisition projection is derived:

```text
Item I
  -> direct Creature/GameObject                      (P2-T01)
  -> LootReference R -> Creature/GameObject member   (P2-T02)
                         -> Spawn -> Zone -> Map      (P1)
```

When direct and reference paths reach the same source/spawn, `find_item_sources()` returns one source
row with multiple `acquisition_paths`. Each path preserves its own chance and provenance. If those
path chances differ, the source-level convenience `chance_percent` is `null`; the project does not
invent an independence/exclusivity rule to combine them.

Missing reference definitions are not silently discarded: the item -> reference relation and native
reference identity remain canonical/provenanced, while the unresolved definition is reported with an
ID/reason and yields no derived member source. A reference-only member lacking both a canonical P1
template and pfQuest enUS identity remains provenance evidence and is likewise reported; no unnamed
canonical template or geography is invented. Direct P2-T01 relations keep their stricter fail-closed
identity behavior.

## P2-T03 vendor acquisition semantics

Migration 6 adds the explicit canonical vendor relation:

```text
vendor_items(vendor_creature_id, item_id)
```

The primitive relation is that a creature vendor sells an item. The pfQuest source value from
`items[item_id]["V"][vendor_creature_id]` is preserved separately as `max_count` provenance on the
`vendor_source` relation; it is not reinterpreted as price, restock time, drop chance, or a generalized
stock policy.

A named vendor absent from the static P1 world may be materialized as a relation-only creature
template without a spawn. Vendor geography remains derived from P1 creature spawns when available.

## P2-T04 Turtle effective item/acquisition semantics

P2-T04 adds no schema migration. It uses generic scalar provenance to represent complete source-view
membership for only the P2 facts already modeled by migrations 4–6:

```text
item_presence
item_acquisition_set
loot_reference_presence
loot_reference_member_set
```

`item_acquisition_set` is the complete effective U/O/R/V membership for a patched item data entry.
`loot_reference_member_set` is the complete effective U/O membership for a patched refloot entry.
These complete-set facts govern membership; the existing individual `loot_source`, `loot_reference`,
`vendor_source`, and `loot_source_member` observations remain the primitive attribute/relation
evidence used by audit and item-source queries.

The active Turtle view may replace only default/base managed selections. A selection is managed by
its selection policy as well as its source key: an explicit/custom selection is protected even if its
observation source key is `pfquest`. A protected complete-set selection does not cause Turtle
primitive relation observations to be synthesized for relations Turtle did not provide.

Materialized stale relations may be deleted only when the selected complete set excludes them and the
individual selected relation is still under the replaceable managed policy. Source observations are
never deleted. Item localization presence is tracked separately from item data/acquisition presence;
removing acquisition data does not by itself erase a still-present item identity.

A complete `item_acquisition_set` may name a creature/gameobject/vendor ID for which no canonical P1
identity and no effective enUS identity exists. The complete-set fact and primitive source relation
remain valid provenance in that case, but the relation is not materialized into `creature_loot`,
`gameobject_loot`, or `vendor_items` because doing so would require inventing a target identity or
violating a foreign key. Such members are reported in `unresolved_acquisition_targets`.

## P3-T01 quest identity/endpoints schema and semantics

Migration 7 establishes the first concrete quest tables:

```text
quests(quest_id, name)
quest_creature_endpoints(quest_id, endpoint_kind, creature_id)
quest_gameobject_endpoints(quest_id, endpoint_kind, gameobject_id)
```

Identity and relation rules:

- `quests.quest_id` preserves the native quest ID;
- `endpoint_kind` is constrained to `giver | finisher`;
- creature and game-object endpoint relations remain distinct FK-backed domain relations rather than
  a generic polymorphic graph;
- endpoint targets reuse canonical P1 creature/game-object **template** identities, never spawn IDs;
- endpoint rows do not duplicate zone/map/location columns.

For the bounded base-pfQuest adapter, primitive relation evidence is:

```text
Quest Q -> giver Creature C
Quest Q -> giver GameObject G
Quest Q -> finisher Creature C
Quest Q -> finisher GameObject G
```

Provenance is represented as:

```text
quest name
  subject_kind      = quest
  subject_key       = quest_id
  fact_key          = name

quest endpoint
  subject_kind      = quest
  subject_key       = quest_id
  fact_key          = endpoint
  fact_instance_key = <giver|finisher>:<creature|gameobject>:<native_id>
  target             = creature/gameobject native ID
  attributes          = {endpoint_kind: giver|finisher}
```

As in earlier domains, the first observation is selected only when no prior canonical selection
exists. Later competing name/relation evidence remains available in the generic provenance layer.

The base adapter considers numeric quest IDs from both the data and enUS localization tables. A
locale-only quest with a valid title may therefore exist canonically with no endpoints; a quest with
no usable title is reported/skipped rather than given a placeholder name.

A source endpoint whose P1 target identity is absent is not silently discarded and is not materialized
against a fabricated template. Its relation observation is retained and the importer reports an
`unresolved_endpoints` diagnostic with native IDs. P3-T01 deliberately does not create relation-only
endpoint templates from additional name sources; a later task may widen identity resolution when a
concrete source contract justifies it.

Quest endpoint geography is derived:

```text
Quest
  -> creature/gameobject endpoint template
       -> P1 spawn
          -> zone
             -> map
```

`quest_by_id()` uses direct `spawn.map_id` when present and otherwise derives map context from
`zones.map_id`, preserving the P1 coordinate space. No `quest_zones` table or quest-level zone column
is introduced.

Item-started quest paths (`start.I`), prerequisites/follow-ups, objectives, required items, rewards and
restrictions remain outside this first slice. Turtle quest overlays are also known to affect the
bounded source view, but D-027 is explicitly P2-only; P3-T01 does not generalize its complete-set
reconciliation policy without a quest-specific follow-up decision/task.

## P3-T02 Turtle effective quest identity/endpoint semantics

P3-T02 adds no schema migration. It uses the generic provenance layer to represent the active
Turtle-composed view of only the facts already modeled by P3-T01:

```text
quest_presence
quest_endpoint_set
```

`quest_presence` is a scalar boolean indicating whether the composed source view has a usable enUS
quest title. `quest_endpoint_set` is the complete set of supported giver/finisher endpoints for the
composed quest record, with each member carrying:

```text
endpoint_kind = giver | finisher
target_kind   = creature | gameobject
target_id     = native template ID
```

These complete-view facts are separate from primitive `name` and `endpoint` observations. A value can
be part of the effective Turtle view while still being inherited from base pfQuest. In that case the
complete-view observation is Turtle-view evidence but the primitive name/endpoint remains pfQuest
source evidence. P3-T02 does not manufacture Turtle primitive provenance for inherited base facts.

The active Turtle view may supersede only default/base managed selections for this bounded P3 fact
family. Explicit/custom selections remain protected. A stale materialized endpoint is deleted only
when the selected complete endpoint set excludes it and the selected primitive endpoint relation is
managed. An absent effective quest identity is deleted only when no protected selected fact supports
retaining it. Source observations remain even when canonical rows are removed.

Quest data and localization are independent composition dimensions. A Turtle localization addition
can activate a quest whose base data had previously been skipped for lack of a usable title. In that
case inherited base endpoints may become materializable, but they are recorded as base pfQuest
primitive evidence. A selected endpoint whose P1 target identity is absent remains unresolved
provenance and is not materialized through a fabricated template/spawn/geography.

D-028 deliberately limits these semantics to quest name plus `start/end × U/O`. Objectives,
prerequisites/follow-ups, required items, rewards, restrictions and item-started quest semantics need
separate bounded P3 contracts before they can participate in effective-view reconciliation.

## Important relation families

Use dedicated domain tables (exact names may evolve):

```text
item_stats

creature_spawns
gameobject_spawns

creature_loot
gameobject_loot
item_loot
fishing_loot
skinning_loot
pickpocket_loot
disenchant_loot
loot_references
item_reference_loot
reference_loot_creatures
reference_loot_gameobjects

quest_givers
quest_finishers
quest_prerequisites
quest_objectives
quest_required_items
quest_rewards

recipe_results
recipe_reagents
recipe_sources
recipe_spells

vendor_items
trainer_spells

item_spells
spell_creates
spell_reagents
```

Specialized loot types should remain distinguishable when their semantics matter.

## Quest <-> zone semantics

Possible derived or explicit relation types include:

- `GIVER`;
- `FINISHER`;
- `OBJECTIVE`;
- finer objective classes when supported:
  - kill;
  - loot;
  - interact;
  - explore/travel.

Prefer deriving giver/finisher geography from NPC/game-object source + spawn geography when the primitive relations are available.

## Recipe <-> zone semantics

Do not create `recipe_zones` as primary truth merely because a recipe can be obtained in a zone.

Prefer:

```text
Recipe -> source -> Creature/Vendor/Trainer/Quest/Item/Loot
                     |
                     v
                   Spawn/Zone
```

Then derive recipe availability.

## Facts vs derivations

Examples of primitives:

- NPC X has spawn Y at coordinate Z.
- Quest Q is given by NPC X.
- Creature C drops item I with source-listed chance P.
- Item I refers to loot-reference R with source-listed chance P.
- Loot-reference R contains creature/game-object source S.

Examples of derivations:

- Quest Q is given in zone A.
- Item I is obtainable from reference member S.
- Item I is obtainable in zone A.
- Recipe R is obtainable in zone B.

Derived values must be reproducible and traceable to their input facts.

## Provenance model requirements

The generic P0 provenance implementation plus P1-T04/P2-T04/P3-T02 complete-view facts must support useful granularity for scalar facts, relations, source-view membership and source-complete relation sets.

Conceptual metadata:

```text
source
source_revision
import_batch
raw_identifier
confidence / authority tier
is_derived
derivation_rule
```

A canonical winner must not delete competing source observations. Materialized-row deletion caused by a selected complete source set is likewise not provenance deletion.

## Roles, not premature entities

Vendors and trainers should initially be represented as roles/relations of creatures (or game objects if evidence requires it), rather than creating duplicate identity records for the same NPC.

Promote to separate first-class entities only if a demonstrated requirement justifies it.

## P4-T01 spell/recipe identity contract

D-034 establishes the source-backed boundary that P4 schema work must implement.

The durable identity chain is:

```text
SkillLineAbility.skillId
        |
        v
crafting Spell.Id -- CREATE_ITEM(effect slot) --> result Item ID
        ^
        |
LEARN_SPELL(effect slot)
        |
acquisition Spell.Id
    ^              ^
    |              |
item spell slot   trainer row
```

The entities are not collapsed:

- `Spell` is a native spell row identified by `Spell.Id`;
- `Recipe` is a separate process entity whose durable native recipe key is anchored to a proven
  crafting spell ID;
- a teaching `Item` is an acquisition source, not the recipe;
- an acquisition/learning spell is still a `Spell`, and may be distinct from the crafting spell;
- a result `Item` is reached through a `CREATE_ITEM` effect slot, not by recipe/item-name matching.

A spell qualifies as a recipe in the bounded P4 contract only when source evidence proves both:

```text
SkillLineAbility.spellId == Spell.Id
and
Spell.Effect[slot] == CREATE_ITEM
```

Profession/skill requirement semantics are separate:

```text
SkillLineAbility.skillId          -> profession/skill-line native identity
SkillLineAbility.req_skill_value  -> required profession/trade-skill value
trainer.reqskill                  -> trainer acquisition prerequisite skill line
trainer.reqskillvalue             -> trainer acquisition prerequisite value
trainer.reqlevel                  -> trainer acquisition character-level requirement
Spell.Rank                        -> display/rank metadata
```

These values must not be copied into one generic `required_level` field.

Output relations are effect-slot shaped. A future canonical relation should preserve at minimum:

```text
recipe/craft_spell_id
result_item_id
effect_slot
source/revision/provenance
```

and may later add source-backed quantity semantics. P4-T01 deliberately does not define a fixed final
output quantity column from `EffectBasePoints` alone because the reviewed core computes create count
from the calculated spell-effect value. Multiple `CREATE_ITEM` slots remain representable.

Learning/acquisition relations are also slot shaped. Item spell slot and `LEARN_SPELL` effect slot are
both provenance-bearing evidence. A later acquisition graph may model:

```text
teaching item -> item spell slot -> acquisition spell
acquisition spell -> LEARN_SPELL effect slot -> craft spell/recipe
trainer creature -> trainer spell row -> acquisition spell
```

A missing teaching item is not missing recipe identity. Quest, trainer, automatic/known-by-default or
other learning sources may attach later to the same recipe independently.

P4-T01 adds no canonical tables. P4-T02 is responsible for the first minimal migration implementing
spell, skill-line, recipe identity/membership and crafted-output relations under this contract.
