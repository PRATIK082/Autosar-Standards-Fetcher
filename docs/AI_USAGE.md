# AI usage — search first, then download

This repo has two layers. The bulk CLI (`download_autosar_standards.py`)
is untouched by AI features. The AI layer (`autosar_mcp_server.py` +
`autosar_web.py`) reuses its crawl/classify/download logic via cache +
filtered download.

## Recommended agent flow

1. `autosar_versions` with `platform` (CP/AP/FO, aliases accepted) to list
   releases actually present in the discovery cache.
2. `autosar_search` with any combination of `query`, `platform`,
   `release` (e.g. `R25-11`), `category` (PDF/Archives/...), `filename`
   substring, and `limit`. Partial names are enough.
3. If one match: `autosar_download` with that exact `url`.
   If many: show candidates, then call `autosar_download` with narrowed
   filters or `download_all=true`. Use `dry_run=true` to preview.
4. `autosar_status` to report manifest counts.

## Design notes

- `discover()` crawls once and caches to
  `<output_dir>/autosar_assets_cache.json`; pass `refresh=true` to recrawl.
- `search_assets()` is pure filtering over the cache (no network).
- `download_assets()` calls the same `AutosarDownloader.download_one()`
  as the CLI, so resume/manifest/SHA-256 behavior is identical.
- Never commit `AUTOSAR_Standards_Library/` (PDF/ZIP copyrighted).
  Commit only code, docs, and `examples/expected_output/` placeholders.

## Web UI

`py -3 autosar_web.py --port 8080` exposes `/api/versions`,
`/api/search`, `/api/download`, `/api/status` with the same semantics.
