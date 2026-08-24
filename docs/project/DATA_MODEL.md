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

The initial pfQuest adapter materializes only direct `U` and `O` relations. `R` reference-loot and `V` vendor relationships are detected/countable but remain deferred until their own relation semantics are implemented.

P2-T01 requires a canonical target identity before it can materialize a direct loot row. If a
direct-loot target is absent from the P1 static-world materialization but pfQuest provides its enUS
name, the item importer may create that creature/game-object **template identity only** as a
relation-supported canonical anchor. It does not create a spawn, zone, or coordinates. This handles
legitimate non-static sources such as temporary/event gameobjects while preserving D-009. If neither
the P1 world nor the pfQuest enUS identity table can identify the target, the import fails closed.

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
reference_loot

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

Examples of derivations:

- Quest Q is given in zone A.
- Item I is obtainable in zone A.
- Recipe R is obtainable in zone B.

Derived values must be reproducible and traceable to their input facts.

## Provenance model requirements

The generic P0 provenance implementation plus P1-T04 complete-view facts must support useful granularity for scalar facts, relations, source-view membership and source-complete relation sets.

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
