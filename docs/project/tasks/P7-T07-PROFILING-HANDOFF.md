# P7-T07 profiling handoff

Status: `VALIDATED` (profiling stage consumed by P7-T07)

Base: GitHub `main` commit `50411e9b3abc0d3dd30b60b71208edbd7588ee4b`.

This handoff introduced the deterministic read-only `scripts/profile_p7_t07.py` stage required before
P7-T07 optimization. The human completed both accepted-canonical profiling runs on 2026-09-02; the
canonical schema-14 DB remained byte-identical and the reports were consumed by the P7-T07
optimization work.

The measured dominant cost was not recipe projection or cold database I/O. It was the retained-entity
quest selected-relation N+1 in P7-T05: `_selected_relation_rows()` ran exactly twice per returned
entity and consumed roughly 75-78% of representative no-recipe zone latency.

The current implementation therefore batches only selected quest relations in request-local memory.
No persistent cache, schema migration, canonical mutation, or architecture decision was introduced.
See `docs/project/tasks/P7-T07.md` and `docs/project/CURRENT_STATE.md` for the active post-optimization
validation instructions and routing.

The pre-optimization profile JSON files remain local validation artifacts and should not be committed
by default.
