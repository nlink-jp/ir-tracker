# Changelog

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
