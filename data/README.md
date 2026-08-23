# Local data layout

Only this README and intentionally small samples are committed.

Recommended local layout:

```text
data/
  samples/       # tiny tracked or hand-curated samples
  raw/           # downloaded/extracted source data (ignored)
  staging/       # parsed source-shaped outputs (ignored)
  derived/       # generated derived datasets/caches (ignored)
  generated/     # canonical SQLite DB and other generated artifacts (ignored)
  downloads/     # temporary downloads (ignored)
  cache/         # HTTP/source caches (ignored)
```

Do not commit full SQL dumps, MPQ files, WDB caches, generated SQLite databases, or scraped page archives.
