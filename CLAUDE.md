# CLAUDE.md — ir-tracker

**Organization rules (mandatory): https://github.com/nlink-jp/.github/blob/main/CONVENTIONS.md**

## Purpose

Live incident response tracker. Ingests Slack conversation exports (stail/scat format),
segments by time window, analyzes each segment with Gemini 2.5 Pro, and presents a
growing timeline with Web UI.

## Architecture

### Module Structure

```
ir_tracker/
  cli.py           — CLI entry point (argparse subcommands)
  ingest.py        — Parse stail/scat export, dedup by ts
  segmenter.py     — Time-window + gap detection segmentation
  analyzer.py      — Gemini 2.5 Pro segment analysis + incident summary
  translator.py    — Gemini Flash translation with DB caching
  timeline.py      — Markdown/JSON timeline + situation Markdown export
  storage.py       — SQLite schema (messages, segments, analyses, translations, context)
  web.py           — FastAPI app (timeline, segments, API endpoints, security headers)
  templates/       — Jinja2 HTML (base, timeline, segments)
  static/          — CSS (light/dark themes, density chart, modal)
```

### Data Flow

```
stail export JSON → ingest (dedup) → SQLite messages
                                   → segmenter (time windows + gap detection)
                                   → analyzer (Gemini Pro, context chaining, nonce-tagged prompts)
                                   → incident summary (Gemini Pro, post-analysis)
                                   → translator (Gemini Flash, cached)
                                   → Web UI / CLI output
```

### Database Tables

- `messages` — Slack messages, PK by `ts`
- `segments` — Time segments with state (pending/analyzed/stale)
- `analyses` — Per-segment LLM analysis JSON
- `analysis_translations` — Cached translations per segment+lang
- `timeline_context` — KV store (incident_summary, incident_type, etc.)

## Security Rules

1. **Prompt injection defense**: User messages are wrapped in nonce-tagged XML
   (`<user_data_{nonce}>...</user_data_{nonce}>`) before LLM submission.
   System prompt explicitly instructs the LLM to treat tagged content as data only.
2. **No innerHTML**: All JavaScript rendering of user-supplied data uses DOM API
   (`createElement` + `textContent`), never `innerHTML`.
3. **Jinja2 auto-escaping**: All template variables auto-escaped. No `|safe` usage.
4. **Parameterized SQL**: All queries use `?` placeholders. No string interpolation.
5. **Security headers**: CSP, X-Frame-Options: DENY, X-Content-Type-Options: nosniff.
6. **Localhost-only binding**: Web UI defaults to 127.0.0.1. Warning on non-localhost.
7. **No secret logging**: API keys and credentials never appear in logs or output.

## Development Rules

- Python with uv virtual environment (`uv sync` to install)
- Run tests: `uv run pytest tests/ -v`
- Type hints on all function signatures
- Small, typed commits: `feat:`, `fix:`, `test:`, `chore:`, `docs:`, `security:`
- README.md and README.ja.md updated in the same commit as behaviour changes
- CHANGELOG.md updated on each feature addition

## LLM Configuration

```bash
export GOOGLE_CLOUD_PROJECT="your-project-id"   # Required
export GOOGLE_CLOUD_LOCATION="us-central1"       # Optional
export IR_TRACKER_MODEL="gemini-2.5-pro"         # Optional (analysis model)
export IR_TRACKER_TZ="Asia/Tokyo"                # Optional (auto-detected)
```

Authentication: `gcloud auth application-default login` or service account.

## CLI Commands

All commands accept `--db <path>` (default: `tracker.db`).

| Command | Description |
|---------|-------------|
| `ingest <file> [--channel name]` | Import messages, dedup, auto-segment |
| `analyze [-v] [--lang ja]` | Analyze pending segments + translate |
| `translate --lang ja [-v]` | Translate analyses only |
| `status [--format json\|markdown] [--lang ja]` | Output timeline |
| `situation [--lang ja] [-o file]` | Current situation as Markdown |
| `segments` | List segments and states |
| `serve [--port 8080] [--host 127.0.0.1]` | Start Web UI |
| `reset` | Clear analyses (keep messages) |

## Web UI Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Timeline view (supports `?lang=ja`) |
| GET | `/segments` | Segment list |
| GET | `/api/timeline` | JSON timeline |
| GET | `/api/situation.md` | Markdown situation download |
| GET | `/api/segments/{id}/messages` | Segment messages JSON |

## Design Decisions

### Analysis Language
Analysis runs in English for maximum LLM accuracy. Translation is applied at
output time via Gemini Flash. Translation results are cached in DB to avoid
re-translation. This two-phase approach (English analysis + on-demand translation)
preserves analytical quality while supporting multilingual display.

### Timezone Handling
Slack timestamps are UTC epoch. The analyzer converts to local time before
sending to the LLM, and explicitly tells the LLM the timezone context. This
ensures the LLM correctly interprets time references in user messages (which
are in local time). `IR_TRACKER_TZ` env var overrides auto-detection.

### Density Chart Scaling
The activity density chart auto-scales bucket size based on time range:
<6h=5min, <24h=15min, <3d=30min, <7d=1h, <30d=6h, 30d+=1day.
This prevents chart degradation for long-running incidents.
