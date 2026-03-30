# ir-tracker

Live incident response tracker — continuous ingestion, segmented analysis, and timeline visualization for ongoing IR conversations.

[日本語版 README はこちら](README.ja.md)

## Concept

While [ai-ir](https://github.com/nlink-jp/ai-ir) analyzes incidents **after** they are resolved (post-mortem), ir-tracker provides **live** situation awareness during an ongoing incident.

```
[During the incident]                    [After the incident]

stail export → ir-tracker ingest         stail export → aiir ingest
             → ir-tracker analyze                     → aiir report
             → ir-tracker status
             ↻ (repeat every 15-30 min)

"What's happening now?"                  "What happened and what did we learn?"
```

## Features

- **Incremental analysis** — only new/changed segments are sent to the LLM
- **Incident summary** — auto-generated executive overview of the entire incident
- **Activity density chart** — visual heatmap of message activity over time
- **Two-column Web UI** — timeline + floating status panel, dark/light themes
- **Message drill-down** — click any segment to view the original conversation
- **Multilingual** — analysis in English, translation overlay for any language (e.g. Japanese)
- **Situation export** — download current situation as Markdown (Web UI + CLI)
- **Context chaining** — compressed prior context for LLM continuity across segments
- **Prompt injection defense** — nonce-tagged XML wrapping for user messages
- **Security headers** — CSP, X-Frame-Options, X-Content-Type-Options

## Quick Start

```bash
# Install
git clone https://github.com/nlink-jp/ir-tracker.git
cd ir-tracker
uv sync

# Configure
export GOOGLE_CLOUD_PROJECT="your-project-id"
gcloud auth application-default login

# Ingest → Analyze → View
ir-tracker ingest export.json
ir-tracker analyze --lang ja
ir-tracker serve
# Open http://127.0.0.1:8080
```

## CLI

```bash
ir-tracker ingest <export.json> [--channel name]  # Import messages (dedup, auto-segment)
ir-tracker analyze [-v] [--lang ja]               # Analyze pending segments + translate
ir-tracker translate --lang ja [-v]               # Translate analyses only
ir-tracker status [--format json|markdown] [--lang ja]  # Output timeline
ir-tracker situation [--lang ja] [-o file.md]     # Current situation as Markdown
ir-tracker export [--lang ja] [-o timeline.html]  # Static HTML report (no server needed)
ir-tracker segments                               # List segments and states
ir-tracker serve [--port 8080] [--host 127.0.0.1] # Start Web UI
ir-tracker reset                                  # Clear analyses (keep messages)
```

All commands accept `--db <path>` to specify the SQLite database (default: `tracker.db`).

## Web UI

| Page | URL | Description |
|------|-----|-------------|
| Timeline | `/` | Incident summary, density chart, segment timeline, status panel |
| Segments | `/segments` | Segment list with states |
| API: Timeline | `/api/timeline` | JSON timeline data |
| API: Situation | `/api/situation.md` | Markdown situation download |
| API: Messages | `/api/segments/{id}/messages` | Segment messages (JSON) |

All pages support `?lang=ja` for translation overlay.

## Static HTML Export

Generate a self-contained HTML file that works without a server — ideal for sharing via email or file share:

```bash
ir-tracker export -o timeline.html                  # English
ir-tracker export --lang ja -o timeline-ja.html     # Japanese
```

Both files include language toggle links. Place them in the same directory for seamless switching.

## Configuration

```bash
export GOOGLE_CLOUD_PROJECT="your-project-id"   # Required
export GOOGLE_CLOUD_LOCATION="us-central1"       # Optional (default: us-central1)
export IR_TRACKER_MODEL="gemini-2.5-pro"         # Optional (default: gemini-2.5-pro)
export IR_TRACKER_TZ="Asia/Tokyo"                # Optional (auto-detected from system)
```

Authentication: `gcloud auth application-default login` or service account key.

## Security

- All data stays local (SQLite file). Only the Vertex AI API endpoint receives data.
- Web UI binds to `127.0.0.1` only. A warning is shown if `--host 0.0.0.0` is used.
- No authentication on the Web UI — deploy only in trusted networks.
- Prompt injection defense via nonce-tagged XML wrapping (`<user_data_{nonce}>`).
- Security headers: `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`.
- All SQL queries use parameterized statements (no string interpolation).
- DOM-based rendering (no `innerHTML`) for user-supplied content in JavaScript.
- Jinja2 auto-escaping enabled for all templates.

## Architecture

```
ir_tracker/
  cli.py           — CLI entry point (argparse subcommands)
  ingest.py        — Parse stail/scat export, dedup by ts
  segmenter.py     — Time-window + gap detection + entropy-based splitting
  analyzer.py      — Gemini 2.5 Pro segment analysis + incident summary
  translator.py    — Gemini Flash parallel translation with caching
  timeline.py      — Markdown/JSON timeline + situation export
  export_html.py   — Self-contained static HTML report generator
  storage.py       — SQLite schema with migration support
  web.py           — FastAPI app (timeline, segments, API endpoints)
  templates/       — Jinja2 HTML (base, timeline, segments)
  static/          — CSS (light/dark themes)
```

## Design Documents

- [Architecture](docs/design/architecture.md) — components, data flow, CLI, security
- [Segmentation](docs/design/segmentation.md) — time window + gap detection algorithm
- [Analysis](docs/design/analysis.md) — LLM pipeline, context chaining, output schema

## Relationship with ai-ir

| Aspect | ai-ir | ir-tracker |
|---|---|---|
| Timing | Post-incident | During incident |
| Input | Single export | Continuous re-ingestion |
| Analysis | Whole conversation | Segmented, incremental |
| Output | Final report | Growing timeline |
| LLM | OpenAI-compatible | Vertex AI Gemini (1M context) |
| Storage | Stateless (files) | Stateful (SQLite) |

Both consume the same stail/scat export format.

## Part of cybersecurity-series

ir-tracker is part of the [cybersecurity-series](https://github.com/nlink-jp/cybersecurity-series) —
AI-augmented tools for threat intelligence, incident response, and security operations.
