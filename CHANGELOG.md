# Changelog

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
