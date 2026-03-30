# Changelog

## [0.2.3] - 2026-03-31

### Added
- Token usage display in Web UI stats bar (Pro/Flash breakdown)
- Migration failure safety: error logging with recovery guidance

## [0.2.2] - 2026-03-31

### Added
- Record translation token usage from `usage_metadata` in `analysis_translations` table
- Schema migration support: `_migrate()` adds columns to existing databases non-destructively
- Recursive dense window splitting: multiple rate spikes within a single window produce multiple segments
- Test for recursive splitting (31 tests total)

### Changed
- `translate_analysis()` now returns `(TranslatedAnalysis, token_count)` tuple

## [0.2.1] - 2026-03-31

### Added
- Record token usage from Vertex AI `usage_metadata` (prompt + candidates)
- Mock tests for analyzer (6 tests) and translator (4 tests) — 30 tests total
- Storage docstring documenting thread safety design

### Changed
- Move function-scoped imports to module level in `web.py`

## [0.2.0] - 2026-03-31

### Added
- Entropy-based dense window splitting (Step 4 of segmentation algorithm)
- Split windows at activity rate inflection points when rate change exceeds `rate_change_factor` (default 3x)
- Tests for dense window split and uniform rate no-split cases (20 tests total)

## [0.1.3] - 2026-03-31

### Changed
- Parallelize segment translations using ThreadPoolExecutor (default 4 workers)
- DB writes serialized on main thread for SQLite safety

## [0.1.2] - 2026-03-31

### Fixed
- Correct docs: stail/scat/scli all share the same export schema (`timestamp_unix`, `user_id`, `post_type`)
- Sample fixture updated from raw Slack API format to actual stail/scli format
- Document `--db`, `--channel`, `--host` flags in CLI reference (README, README.ja, CLAUDE.md)

## [0.1.1] - 2026-03-31

### Fixed
- Support scli `channel export` format (`timestamp_unix`, `post_type`, `thread_timestamp_unix`)
- Ingest now transparently handles both stail/scat and scli export formats

## [0.1.0] - 2026-03-31

### Added
- Core pipeline: ingest, segment, analyze, translate, timeline
- `ingest` — parse stail/scat export JSON, deduplicate by message ts
- `analyze` — Gemini 2.5 Pro segment analysis with context chaining
- `translate` — Gemini Flash translation with DB caching
- `situation` — export current situation as Markdown (CLI + API)
- `status` — Markdown and JSON timeline output
- `segments` — list segments and states
- `serve` — Web UI with FastAPI
- `reset` — clear analyses while keeping messages
- Incident summary — auto-generated executive overview after analysis
- Activity density chart — auto-scaled time buckets with Canvas rendering
- Message drill-down modal — click segment to view original conversation
- Two-column Web UI — timeline + floating status panel
- Dark/light theme with system preference detection and manual toggle
- Language toggle — EN/JA translation overlay on all views
- Situation Markdown download from Web UI
- Timezone-aware analysis — local time in all outputs, TZ info passed to LLM
- Prompt injection defense — nonce-tagged XML wrapping for user messages
- Security headers — CSP, X-Frame-Options, X-Content-Type-Options
- DOM-based rendering (no innerHTML) for user-supplied content
- Non-localhost bind warning for `--host` flag
- 17 tests (storage: 7, ingest: 4, segmenter: 6)
