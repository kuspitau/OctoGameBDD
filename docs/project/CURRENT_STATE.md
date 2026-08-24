# Current State

## Repository state

GitHub `main` is the source-of-truth base for this delta:

- branch: `main`
- base commit: `3302785ba6ece92df6c45df379420484d4eacb23`

That commit is `Implement P1-T02 Octo DBC map hierarchy`. P1-T02 is therefore present on the validated source-of-truth branch and closed for normal routing.

**Status:** `IMPLEMENTED_AWAITING_LOCAL_VALIDATION`

## Current milestone

**P1 — World foundation**

## Current task

**P1-T03 — pfQuest Turtle/Octo effective world views and comparison**

Detailed task specification:

- `docs/project/tasks/P1-T03.md`

## Why the task scope changed

Initial investigation considered `pfQuest-octo` as the required Octo overlay. Local validation showed that the user's launcher installation already contains `pfQuest-turtle`.

Primary-source verification then established:

- the launcher-provided Turtle addon belongs to the `pfQuest-turtle` line; `KameleonUK/pfQuest-turtle` is the current public maintained reference inspected for format/behavior;
- reviewed revision `5b8eeeeb4119be9d075087f0f0e08c187b35ad61` is dated 2026-08-02;
- it contains current Turtle 1.18.x world data and provides public format/behavior evidence, but the user's installed addon must be treated as version-specific local input;
- reviewed `pfQuest-octo` revision `dd3dc1fb80afe7a71e5c8ca8c31ca2a3ef57af67` is dated 2026-05-12 and its commit explicitly reverts its database to 1.17.2 data;
- `pfQuest-octo` still contains useful Octo-specific manual corrections, so it is retained as an optional comparison source rather than discarded.

This does not establish a universal source priority. P1-T03 only constructs and compares effective source views.

## Implementation in this delta

- adds `pfquest_overlay_world.py`;
- composes the existing P1 pfQuest world subset with Turtle-style patch tables;
- reproduces `patchtable.lua` semantics: `"_"` deletes, otherwise replace the top-level entry wholesale;
- applies direct literal world-table assignments from `overwrites.lua` without executing Lua;
- reproduces the reviewed Kameleon phantom-zone cleanup loop when that supported pattern is actually present in the loaded overlay;
- fails closed on unsupported indirect world-table mutation;
- loads both:
  - `pfQuest + pfQuest-turtle`;
  - `pfQuest + pfQuest-octo`;
- compares the two resulting views by added/removed/changed zone, creature and gameobject IDs without selecting a winner;
- retains the existing P1 dataclasses and zone-percent coordinate validation;
- introduces no schema migration and performs no SQLite writes.

## Local path/config state

Required:

```toml
[source_paths]
pfquest = "<installed pfQuest directory>"
pfquest_turtle = "<installed pfQuest-turtle directory>"
```

Optional but supported:

```toml
pfquest_octo = "<installed pfQuest-octo directory>"
```

The task helper resolves the two required sources. A valid existing or auto-detected `pfquest_octo` is retained/recorded but is never required.

## Agent/sample validation

A focused workspace was assembled from the P1-T01 parser/dataclass subset exposed on GitHub `main` plus the new P1-T03 module/tests.

Performed:

```bash
PYTHONPATH=src python -m pytest -q tests/test_pfquest_overlay_world.py
```

Result:

```text
5 passed
```

Coverage includes:

- Turtle top-entry replacement/deletion;
- Turtle phantom-zone cleanup when present, plus non-invention when absent;
- direct literal Octo overwrites;
- cross-view comparison;
- fail-closed behavior for unsupported indirect Lua mutation.

Also performed:

```bash
python -m py_compile src/octogamedb/importers/pfquest_overlay_world.py tests/test_pfquest_overlay_world.py
```

Result: success.

The full existing repository suite and Ruff remain required locally because the execution environment does not expose a complete mounted checkout and does not provide the user's addon files.

## Required local validation

After extracting `changes.zip`, run:

```bat
get_path.bat
```

Then:

```bash
git diff
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check src tests
python -m compileall -q src tests
```

Then, from PowerShell at the project root:

```powershell
@'
import re
import tomllib
from pathlib import Path

from octogamedb.importers.pfquest_overlay_world import (
    compare_pfquest_world_slices,
    load_pfquest_octo_world_slice,
    load_pfquest_turtle_world_slice,
)
from octogamedb.importers.pfquest_world import parse_pfquest_assignment

config = tomllib.loads(Path("config.local.toml").read_text(encoding="utf-8"))
paths = config["source_paths"]
turtle_root = Path(paths["pfquest_turtle"])

turtle = load_pfquest_turtle_world_slice(paths["pfquest"], turtle_root)
print("TURTLE")
print("zones", len(turtle.zones))
print("creatures", len(turtle.creatures))
print("gameobjects", len(turtle.gameobjects))
print("creature_spawns", sum(len(row.spawns) for row in turtle.creatures))
print("gameobject_spawns", sum(len(row.spawns) for row in turtle.gameobjects))

turtle_zone_ids = {row.zone_id for row in turtle.zones}
zone_patch_path = turtle_root / "db" / "enUS" / "zones-turtle.lua"
zone_patch = parse_pfquest_assignment(
    zone_patch_path.read_text(encoding="utf-8"),
    domain="zones",
    table_name="enUS-turtle",
)
explicit_zone_deletes = sorted(
    key for key, value in zone_patch.items()
    if isinstance(key, int) and value == "_"
)
assert not (set(explicit_zone_deletes) & turtle_zone_ids)
print("explicit '_' zone deletions applied", len(explicit_zone_deletes))

overwrite_text = (turtle_root / "overwrites.lua").read_text(encoding="utf-8")
match = re.search(r"local\s+phantom_zones\s*=\s*\{(.*?)\}", overwrite_text, re.S)
if match and "tbl[zid] = nil" in overwrite_text:
    phantom_ids = [int(value) for value in re.findall(r"\d+", match.group(1))]
    assert not (set(phantom_ids) & turtle_zone_ids)
    print("installed phantom cleanup applied", phantom_ids)
else:
    print("installed phantom cleanup: not present")

assert all(
    0.0 <= spawn.x <= 100.0 and 0.0 <= spawn.y <= 100.0
    for row in (*turtle.creatures, *turtle.gameobjects)
    for spawn in row.spawns
)
print("Turtle installed-source invariants: OK")

if paths.get("pfquest_octo"):
    octo = load_pfquest_octo_world_slice(paths["pfquest"], paths["pfquest_octo"])
    diff = compare_pfquest_world_slices(turtle, octo)
    print("OCTO")
    print("zones", len(octo.zones))
    print("creatures", len(octo.creatures))
    print("gameobjects", len(octo.gameobjects))
    print("DIFF")
    for label, result in (
        ("zones", diff.zones),
        ("creatures", diff.creatures),
        ("gameobjects", diff.gameobjects),
    ):
        print(
            label,
            "added", len(result.added),
            "removed", len(result.removed),
            "changed", len(result.changed),
        )
        print("  added sample", result.added[:20])
        print("  removed sample", result.removed[:20])
        print("  changed sample", result.changed[:20])
'@ | python -
```
Expected invariants:

- full tests pass;
- Ruff reports no errors;
- Python compilation succeeds;
- the Turtle effective view loads successfully;
- every top-level zone deletion (`"_"`) declared by the installed Turtle patch is absent from the effective view;
- if the installed `overwrites.lua` contains the supported phantom-zone cleanup loop, those locally declared IDs are absent; if the loop is absent, no such deletion is invented;
- all emitted spawn percentages remain within `[0, 100]`;
- when `pfquest_octo` is configured, both views load and the comparison prints deterministic added/removed/changed ID sets;
- no database or tracked data file is created.

## Level-2 source-version observation

The user's installed `pfQuest-turtle` loaded successfully with:

```text
zones 773
creatures 13802
gameobjects 20965
creature_spawns 110071
gameobject_spawns 74994
```

Its local `overwrites.lua` does **not** contain the reviewed public `phantom_zones` / `tbl[zid] = nil` cleanup pattern. Zone `5138` therefore remains present as `The Deadmines`. This is accepted as local-source behavior rather than overwritten with semantics from another revision.

## Known limitations

P1-T03 handles only the static enUS P1 world subset. It is not a general Lua interpreter. A new upstream indirect mutation pattern touching zones/units/objects deliberately fails validation and must be reviewed before support is added.

No source is declared canonical by this task.

## Next handoff rule

After local validation, commit and push P1-T03 to `main`. The next conversation must confirm the resulting main commit before advancing.

Next bounded task: **P1-T04 — overlay provenance/canonical reconciliation**, explicitly modeling deletion/existence evidence and stale replaced spawn sets before writing the overlay views into SQLite.
