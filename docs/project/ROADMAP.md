# Roadmap

The roadmap is staged to keep source semantics, provenance and canonical selection auditable before
large-scale ingestion or UI work.

## P0 — foundation and provenance

Status: `VALIDATED`.

Delivered project/package skeleton, migration/versioning, provenance primitives, source observations,
canonical selections and audit/query primitives.

## P1 — world foundation

Status: `VALIDATED` through P1-T04.

Delivered maps/zones, creature/gameobject identities and separate spawns, direct Octo DBC geography,
pfQuest base world import, Turtle/Octo overlay composition, complete-set spawn evidence and managed
effective-view reconciliation.

## P2 — items and acquisition sources

Status: `VALIDATED` through P2-T04.

Delivered item identity plus direct/reference loot and vendor relations with bounded Turtle effective-
view reconciliation. Item template/stat facts are handled in P6.

## P3 — quests

Status: `VALIDATED` through P3-T05B.

Delivered quest identity/endpoints, restrictions/progression, structured objectives, item
requirements/rewards and conservative Octo/Turtle source-specific evidence.

## P4 — spells, recipes, reagents and acquisition

Status: `VALIDATED` through P4-T04.

Delivered recipe/spell identity, outputs, reagents and trainer/recipe-item acquisition sources.

## P5 — coverage, provenance and conflict auditing

Status: `VALIDATED` through P5-T08.

The bounded world-source conflict audit established that pfQuest/Turtle/Octo spawn disagreement is
predominantly source-specific complete spawn-membership divergence. No global merge/source-promotion
rule was justified; D-025/D-026 remained unchanged.

## P6 — broader source ingestion and remaining domains

Status: `VALIDATED` through P6-T03; P6-T04 is `READY_FOR_IMPLEMENTATION`.

Canonical DB remains migration 13 until P6-T04 completes an explicit D-029 promotion cycle:

```text
623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

### P6-T01 — item template/stat source contract and bounded ingestion slice

Status: `VALIDATED`.

Accepted D-036's bounded direct-Octo `itemcache.wdb` evidence contract for the supported item-template
and ten-slot stat family. Migration 14 provides validated projection capability but was intentionally
validated only on a disposable DB copy.

### P6-T02 — direct Octo item-cache freshness, coverage and bounded refresh probe

Status: `VALIDATED`.

Measured partial cache coverage and established D-037's freshness-aware direct query path. A five-ID
real-client probe produced three `refresh_proven_direct_observation` results and two unknowns while
leaving the canonical DB byte-identical.

### P6-T03 — resumable direct-Octo acquisition campaign for known canonical cache misses

Status: `VALIDATED`.

Scaled the P6-T02 probe into a durable, deterministic, interruption-safe bounded campaign with
conservative retry/unknown semantics and duplicate/no-op replay handling.

Final cumulative real-client campaign evidence on 2026-08-29:

```text
canonical item population                = 23336
initial matching cache coverage          =  7554
current matching cache coverage          =  7654
campaign candidate count                 = 15782
attempted unique IDs                     =    19
sessions                                 =     2
retries                                  =     1
historical_cache_only                    =    85
refresh_proven_direct_observation        =     8
unknown_retryable                        =     5
remaining queued                         = 15684
refresh-proven rate over attempted IDs   = 42.105263%
canonical DB unchanged                   = true
```

The first DDoS-affected session validated the conservative/interruption path; the later stable session
validated positive acquisition. Completed-session replay was an evidence-preserving duplicate no-op.
The full repository suite reached 258 passing tests, with Ruff and compileall also passing.

The dedicated post-hotfix automatic restart-wrapper branch was not deliberately replayed end-to-end,
but focused tests cover it and the underlying real interruption/recovery mechanism was already
exercised. This is accepted as non-blocking.

### P6-T04 — bounded migration-14 canonical promotion of validated item-template/stat evidence

Status: `READY_FOR_IMPLEMENTATION`.

Perform the first explicit D-029 canonical promotion cycle for migration 14. Reuse the validated P6
schema/import path, define exactly which D-036/D-037 evidence classes are eligible for managed
canonical selection, preserve provenance/conflicts/custom selections, back up the migration-13
canonical DB before any write, validate idempotence/integrity/representative queries, and record the
new canonical SHA only after every Level-2 gate passes.

P6-T04 does not require acquisition of all 15k+ remaining candidates before promotion. Whole-
population coverage remains explicitly partial.

Potential later P6 work remains consumer-driven and field-specific, including weapon damage/speed/
block, item effects/spells/tooltips, continued/background bounded direct acquisition, and explicit
fallback adapters where direct Octo coverage is insufficient. No universal source priority is
introduced.

## P7 — query/exploration layer

Status: `PLANNED`.

Build richer provenance-aware cross-domain exploration after sufficient P6 canonical coverage:

- item acquisition/source exploration;
- arbitrary item stat filtering/sorting and weighted scores;
- quest chains/objectives/rewards;
- creature/gameobject geography;
- recipe/reagent/acquisition traversal;
- configurable columns, saved searches and comparisons.

## P8 — UI/application workflow

Status: `PLANNED`.

Add the user-facing local browser UI only after the data/query semantics are reliable.
