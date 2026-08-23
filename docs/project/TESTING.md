# Testing Strategy

## Objectives

Tests must protect semantics, not only row counts.

Important invariants include:

- import idempotency;
- native-ID preservation;
- template vs spawn separation;
- relation direction/cardinality;
- provenance survival;
- conflict preservation;
- deterministic derivation;
- migration safety.

## Test layers

### Unit

Pure parsers, converters, normalizers, resolvers.

### Fixture integration

Small source-format inputs -> staging/canonical outputs.

### Golden cases

A curated set of known representative entities/relations.

Golden cases should eventually cover:

- simple item;
- creature-drop item;
- game-object/container item;
- quest reward;
- crafted item;
- recipe learned from different source types;
- quest with giver/objective/finisher in different zones;
- custom Octo entity;
- source conflict;
- reference-loot edge case.

### Full-data local tests

Run by the human against real/large data.

Examples:

- full import completes without unexpected errors;
- repeated import is idempotent;
- counts/coverage are plausible;
- known Octo custom entities resolve;
- conflict and provenance reports remain inspectable;
- DB integrity checks pass.

### Performance

Add only after representative volumes exist.

Measure:

- import time;
- generated DB size;
- query latency for target explorer queries;
- derived-view build time.

Do not prematurely optimize before measuring.
