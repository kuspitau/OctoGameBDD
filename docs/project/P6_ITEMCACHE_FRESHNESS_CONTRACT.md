# P6 item-cache freshness and bounded direct-query contract

Status: `VALIDATED`

This document is the validated P6-T02 acquisition/freshness contract. It refines D-036 without
changing the adopted item-template field family. The accepted freshness rules are recorded by D-037.

The canonical local DB remains migration 13. P6-T02 performed no canonical mutation or migration-14
promotion.

## 1. Problem separated by P6-T02

P6-T01 proved that a supported `itemcache.wdb` record can be parsed and ingested as direct Octo
positive evidence. It did not prove that:

- an arbitrary existing cache record is current;
- the cache contains every canonical item;
- an absent item is absent on the server;
- opening/resolving an already-cached item forces a server refresh.

P6-T02 therefore treats three questions independently:

1. parser correctness;
2. cache coverage;
3. evidence of current-session acquisition/freshness.

## 2. Public protocol/runtime evidence

The bounded probe was designed from primary implementation references rather than from a timing-only
assumption.

### pfQuest client behavior reference

Reviewed repository/revision:

```text
shagu/pfQuest
master @ 104f35678ca39ab1fb78b655f815cc7016f5e0c8
file: database.lua
```

The reviewed runtime contains a clean-WDB locale/item-information path using an item hyperlink query
of the form:

```text
ItemRefTooltip:SetHyperlink("item:<id>:0:0:0")
```

and waits for item information to become available instead of assuming synchronous completion.

### VMaNGOS protocol reference

Reviewed repository/revision:

```text
vmangos/core
development @ 810fef8f23938427df89c7528d5276bbb8015008
files:
  src/game/Handlers/ItemHandler.cpp
  src/game/Server/Protocol/Opcodes.cpp
```

The reviewed path confirms the Vanilla item-query request/response family:

```text
CMSG_ITEM_QUERY_SINGLE
SMSG_ITEM_QUERY_SINGLE_RESPONSE
```

These public repositories are semantic/protocol references only. The actual P6-T02 observations come
from the user's live Octo client/session and local WDB/SavedVariables artifacts.

## 3. Clean-cache state is valid

An initially absent `itemcache.wdb` is a first-class preflight state. The validator must not create a
synthetic WDB file merely to satisfy the parser.

For a clean cache:

- cache record count is zero;
- every canonical item ID is cache-missing/unknown;
- the coverage revision includes an explicit absent-cache marker plus the canonical population;
- no item identity or negative evidence is invented.

If a post-session WDB is later created, its actual raw records may supply freshness proof. If no WDB is
written but the client reports a successful current-session load, the result remains session-observed
and freshness-limited.

## 4. Deterministic coverage report

The read-only coverage report compares the complete parsed cache membership with the existing
canonical `items.item_id` population.

It measures at minimum:

- total cache records;
- canonical item identities;
- cache records matching canonical identity;
- cache-only native IDs;
- canonical IDs missing from cache, always labelled unknown;
- class/subclass distribution;
- quality distribution;
- inventory-type distribution;
- item-level and required-level distributions;
- records with non-empty stats, armor, durability or resistances;
- supported restriction-field presence;
- representative low/high IDs;
- malformed/unsupported/duplicate diagnostics.

The report does not materialize migration-14 rows and does not create canonical item identities.

A present-cache coverage revision hashes:

- supported WDB header semantics;
- the sorted canonical item-ID population;
- sorted cache membership and exact raw-record hashes.

A clean-cache coverage revision uses an explicit `ABSENT` marker instead of synthetic WDB bytes.

## 5. Candidate selection

The bounded freshness probe selects only **known canonical item IDs absent from the preflight cache**.
Candidate selection is deterministic and spread across the ordered missing population rather than
scanning an arbitrary integer range.

P6-T02 validates a default five-ID real-client probe. The implementation remains hard-bounded to no
more than 20 explicit IDs per addon invocation.

No cache-only ID or guessed numeric ID is queried merely to discover whether it exists.

## 6. Bounded client probe

The validated addon processes one outstanding item ID at a time.

Validated safety/state parameters:

```text
poll interval       = 0.20 s
retry interval      = 3.0 s
timeout per ID      = 15.0 s
maximum attempts    = 5
maximum IDs/run     = 20
```

Per-ID probe states include:

```text
already_cached
loaded_after_query
timeout_unknown
pending
```

`already_cached` is deliberately not a freshness success. The client may satisfy the request from the
local WDB without a server round trip.

The addon exports machine-readable SavedVariables containing the exact requested IDs, per-ID result,
locale/client/session metadata where available, and completion state. The external validator, not the
addon, computes raw WDB record hashes.

## 7. Freshness classes

### `refresh_proven_direct_observation`

Requires all three:

1. the item ID was absent from the pre-probe cache snapshot;
2. the current-session probe reported `loaded_after_query`;
3. after logout/client exit, a raw WDB record exists for the same ID and its exact bytes are hashed.

This is the strongest current direct-Octo evidence class established by P6-T02.

### `session_observed_freshness_limited`

The ID was absent before the probe and the current session reports a successful load, but no
post-session WDB raw record is available.

This proves current-session acquisition behavior, but the current implementation has no persisted
source-shaped template payload to materialize automatically from this class alone.

### `historical_cache_only`

The ID already existed in the pre-probe cache. That record remains direct Octo positive evidence under
D-036, but P6-T02 does not claim that resolving it in the current session forced a refresh.

### `unknown`

Timeout, missing response or insufficient evidence remains unknown. It is never item non-existence,
field absence or authorization to delete/deselect another observation.

## 8. Validated real-client result — 2026-08-29

Classical local gates requested before the remaining Level-2 run all passed. The clean-WDB correction
then passed 10 focused pytest tests, Ruff and compileall.

Final real-client coverage/preflight:

```text
canonical item identities                 = 23336
itemcache records                         =  7119
cache records matching canonical identity =  6667
cache-only native IDs                     =   452
canonical IDs missing from cache          = 16669
probe item IDs                            = 1,7646,15984,41360,93116
```

Final post-session freshness result:

```text
refresh_proven_direct_observation = 3
unknown                           = 2
itemcache_post_exists             = true
canonical_db_unchanged            = true
```

Successful validation markers:

```text
P6_T02_PREFLIGHT_OK
P6_T02_LOCAL_VALIDATION_OK
P6_T02_REMAINING_LOCAL_VALIDATION_COMPLETE
```

Canonical SHA before and after:

```text
623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

## 9. Selection and ingestion consequences

For the D-036 item-template field family:

- a `refresh_proven_direct_observation` raw record is eligible to be treated as current direct-Octo
  positive evidence by a later explicitly bounded ingestion step;
- a historical cache record remains positive `octo-itemcache` evidence but must not be labelled fresh
  merely because it is present;
- a session-only success proves acquisition behavior but cannot stand in for absent raw field bytes;
- unknown/timeouts never become negative evidence;
- competing observations and protected manual/custom selections remain preserved.

P6-T02 does **not** authorize a default whole-cache canonical import. The observed cache contains only
6,667 of 23,336 canonical identities, and the five-ID proof intentionally demonstrates mechanism, not
throughput or exhaustive availability.

## 10. Canonical lifecycle

P6-T02 is read-only with respect to the canonical DB.

Current baseline remains:

```text
migration 13 / 0013_recipe_acquisition_sources.sql
SHA-256 623e29d83abd20335506d2a23dcbd525331de4f1bc10d38fccd7aa550a7613d7
```

Migration 14 is still validated schema capability only. A later promotion requires an explicit D-029
backup/mutation/validation cycle and a defined cumulative data state.

## 11. Routed next step

The evidence routes P6-T03:

```text
P6-T03 — Resumable direct-Octo acquisition campaign for known canonical cache misses
```

P6-T03 should scale the proven mechanism conservatively, not broaden its semantics. It must retain
canonical-ID-only candidate selection, one outstanding request, bounded batches, resumable state,
per-ID freshness evidence, and unknown-on-timeout behavior while keeping the canonical DB read-only.
