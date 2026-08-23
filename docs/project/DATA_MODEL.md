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

Exact implementation is deferred, but the model must support provenance at useful granularity for both scalar facts and relations.

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

A canonical winner must not delete competing source observations.

## Roles, not premature entities

Vendors and trainers should initially be represented as roles/relations of creatures (or game objects if evidence requires it), rather than creating duplicate identity records for the same NPC.

Promote to separate first-class entities only if a demonstrated requirement justifies it.
