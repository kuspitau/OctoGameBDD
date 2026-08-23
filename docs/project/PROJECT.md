# Project Definition

## Purpose

Build an external local application for creating, auditing, querying, and exploring a rich interconnected database of OctoWoW game content.

The underlying model is multi-entity rather than item-centric. The same database must support different perspectives:

- item-centric;
- quest-centric;
- creature-centric;
- game-object-centric;
- recipe/crafting-centric;
- spell-centric;
- zone/world-centric.

## Primary first-class domains

- Items
- Quests
- Creatures
- Creature spawns
- Game objects
- Game object spawns
- Recipes
- Spells
- Zones / subzones
- Maps

Secondary/reference domains may include:

- professions / skills;
- factions;
- item classes/subclasses;
- creature families/types;
- vendors and trainers as creature roles/domain relations.

## Key user capabilities

### Item exploration

For an item, show/filter:

- identity, quality, levels, type/subtype, slot;
- armor/block/damage/speed/durability where applicable;
- stats and effects;
- requirements and restrictions;
- icon and WoW-like tooltip;
- all known acquisition paths:
  - creature loot and drop rates;
  - game-object/container loot;
  - item/container loot;
  - fishing and other specialized loot;
  - quest rewards;
  - vendors;
  - crafting;
  - other sources as discovered;
- source locations/spawns and zones.

### Quest exploration

Represent independently:

- giver(s);
- finisher(s);
- prerequisites and follow-ups;
- objectives;
- required items;
- creatures/game objects involved;
- guaranteed and choice rewards;
- zones derived from giver/finisher/objective geography.

A quest may be given, performed, and finished in different zones.

### Creature / game-object exploration

Show:

- template identity and attributes;
- spawn instances and geography;
- loot;
- vendor/trainer roles where relevant;
- quest relations.

Template entities and spawn instances are distinct.

### Craft / recipe exploration

A recipe is a first-class entity and is not equivalent to:

- the recipe item;
- the teaching spell;
- the crafted item.

Represent:

- profession / required skill;
- output item(s) and quantities;
- reagents and quantities;
- cooldown/conditions when available;
- learning/acquisition source:
  - trainer;
  - vendor;
  - item;
  - quest;
  - creature/game-object loot;
  - other source.

Recipe availability in a zone should normally be **derived from its actual source geography**, not duplicated as arbitrary primary truth.

### Zone exploration

Zones are first-class entities, not just a field on other records.

A zone view should eventually answer questions such as:

- creatures and game objects present;
- quests given here;
- quests finished here;
- quests with objectives here;
- recipes obtainable here;
- vendors/trainers;
- items obtainable here through loot, quests, vendors, crafting sources, etc.

## Search goals

The eventual query/UI layer should allow:

- filtering and sorting by arbitrary item stats;
- source-type and drop-chance filters;
- zone/location filters;
- cross-domain queries;
- configurable displayed columns;
- saved searches;
- custom weighted stat scores;
- item comparisons;
- graphical maps/spawn overlays.

Example future query:

> Leather chest items, required level <= 40, Agility >= 10, Stamina >= 8,
> obtainable from a Horde-accessible source with drop chance >= 5%.

## Non-goals for early milestones

Do not start by building a polished UI or attempting a full-world import.

First build:

1. reliable schema and import infrastructure;
2. provenance and conflict handling;
3. audit/trace/coverage tooling;
4. small vertical slices with representative fixtures;
5. only then scale to the full dataset and graphical explorer.
