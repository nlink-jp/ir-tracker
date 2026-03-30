# Architecture — ir-tracker

## Problem Statement

During an active incident response, the IR team communicates in a Slack channel.
As the conversation grows (hundreds to thousands of messages over hours or days),
it becomes increasingly difficult to answer basic questions:

- What do we know so far?
- Who is doing what right now?
- What happened in the last 30 minutes?
- When did the situation change?

ai-ir solves the post-mortem case (analyze after the incident is closed).
ir-tracker solves the **live** case: continuous analysis of an ongoing incident.

## Core Concept

ir-tracker is **not** a real-time bot. It does not sit in the Slack channel.
Instead, it operates on **exported conversation data** that can be re-ingested
at any time:

```
stail export -c "#incident-2026-0330" --output latest.json
ir-tracker ingest latest.json
ir-tracker analyze
ir-tracker status
```

Each `ingest` adds new messages to a local SQLite database.
Each `analyze` processes only the segments that changed since the last analysis.
Each `status` renders the current timeline.

This can be run manually, on a cron, or triggered by a wrapper script.

## Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│                      ir-tracker                           │
│                                                          │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  Ingest   │  │ Segmentation │  │    Analyzer       │   │
│  │          │  │              │  │                  │   │
│  │ stail/   │→│ Time window  │→│ Gemini 2.5 Pro   │   │
│  │ scat JSON│  │ + entropy   │  │ (1M context)     │   │
│  │ → SQLite │  │ detection   │  │ per segment      │   │
│  └──────────┘  └──────────────┘  └────────┬─────────┘   │
│                                            │             │
│                                            ▼             │
│                                   ┌──────────────────┐   │
│                                   │ Timeline Builder  │   │
│                                   │                  │   │
│                                   │ Segment analyses │   │
│                                   │ → unified view   │   │
│                                   │ → status output  │   │
│                                   │ → Web UI         │   │
│                                   └──────────────────┘   │
│                                                          │
│  Storage: SQLite (messages, segments, analyses, timeline) │
└──────────────────────────────────────────────────────────┘
```

## Components

### 1. Ingest Layer

**Input:** Slack conversation export JSON (stail, scat, or scli format)

Note: stail/scat and scli use different field names for the same data.
The ingest layer normalizes both transparently:
- Timestamp: `ts` (stail/scat) or `timestamp_unix` (scli)
- User ID: `user` (stail/scat) or `user_id` (scli)
- Bot detection: `bot_id`/`subtype` (stail/scat) or `post_type` (scli)
- Thread: `thread_ts` (stail/scat) or `thread_timestamp_unix` (scli)

**Responsibilities:**
- Parse export JSON and extract messages
- Deduplicate by message timestamp (`ts`/`timestamp_unix` — unique per message in Slack)
- Sort chronologically
- Handle repeated ingestion of overlapping data gracefully
- Track ingestion metadata (when each message was first seen)

**Database table: `messages`**

| Column | Type | Description |
|---|---|---|
| `ts` | TEXT PK | Slack message timestamp (unique ID) |
| `user_id` | TEXT | Slack user ID |
| `user_name` | TEXT | Display name |
| `text` | TEXT | Message text (defanged) |
| `thread_ts` | TEXT | Thread parent timestamp |
| `channel` | TEXT | Channel name |
| `is_bot` | BOOL | Whether the message is from a bot |
| `ingested_at` | TEXT | First ingestion timestamp |
| `raw_json` | TEXT | Original message JSON (for reprocessing) |

### 2. Segmentation Engine

**Purpose:** Divide the message stream into analyzable chunks.

**Strategy: Hybrid time-window + entropy-based segmentation**

1. **Base: Fixed time windows** (configurable, default 30 minutes)
   - Simple, predictable, easy to reason about
   - Each window becomes a candidate segment

2. **Entropy detection: merge/split based on activity density**
   - If a window has < N messages (default: 3), merge with adjacent
   - If a window has a sharp activity spike (rate change > 3x), split at the inflection point
   - Gaps > 1 hour create automatic segment boundaries

3. **Segment states:**
   - `pending` — new messages ingested, not yet analyzed
   - `analyzed` — LLM analysis complete
   - `stale` — new messages added to a previously analyzed segment (re-analysis needed)

**Database table: `segments`**

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `start_ts` | TEXT | First message timestamp |
| `end_ts` | TEXT | Last message timestamp |
| `message_count` | INTEGER | Number of messages |
| `state` | TEXT | pending / analyzed / stale |
| `created_at` | TEXT | Segment creation time |
| `analyzed_at` | TEXT | Last analysis time |

### 3. Analyzer

**LLM: Gemini 2.5 Pro via Vertex AI** (1M token context)

Chosen because:
- IR conversations can be very long (thousands of messages)
- Segment analysis needs context from previous segments
- 1M token window allows passing large context without truncation
- Google Search Grounding not needed (internal data only)

**Per-segment analysis produces:**

```json
{
  "segment_id": 1,
  "time_range": "2026-03-30 09:00 - 09:30 JST",
  "summary": "Initial triage: team identified unauthorized access to prod DB...",
  "key_findings": [
    "Unauthorized SSH session from 10.0.1.50 starting at 08:45",
    "Database export of customers table detected in audit log"
  ],
  "active_participants": [
    {
      "user": "alice",
      "role": "Lead Responder",
      "current_activity": "Analyzing SSH session logs"
    }
  ],
  "status_change": "escalated",
  "severity_assessment": "high",
  "open_questions": [
    "How did the attacker obtain SSH credentials?",
    "What other tables were accessed?"
  ]
}
```

**Context chaining:** Each segment analysis receives:
1. The messages in that segment
2. The summary of the previous segment (compressed context)
3. The cumulative key findings list

This allows the LLM to understand continuity without re-reading all prior messages.

**Database table: `analyses`**

| Column | Type | Description |
|---|---|---|
| `segment_id` | INTEGER FK | References segments.id |
| `analysis_json` | TEXT | Full analysis JSON |
| `model` | TEXT | Model used |
| `token_count` | INTEGER | Approximate tokens used |
| `analyzed_at` | TEXT | Analysis timestamp |

### 4. Timeline Builder

**Purpose:** Synthesize segment analyses into a coherent timeline.

**Output formats:**
- **Markdown** — for terminal / piping
- **JSON** — for programmatic use
- **Web UI** — for interactive browsing

**Timeline structure:**

```
[2026-03-30 08:30] INCIDENT OPENED — #incident-2026-0330
  │
  ├─ [08:30-09:00] Initial Detection
  │  Summary: Alert triggered from SIEM...
  │  Participants: @alice (Lead), @bob (SRE)
  │  Findings: Unauthorized SSH session detected
  │
  ├─ [09:00-09:30] Triage & Escalation
  │  Summary: Team identified data exfiltration...
  │  Participants: @alice, @bob, @carol (joined)
  │  Status: ESCALATED to management
  │
  ├─ [09:30-10:00] Containment
  │  Summary: SSH key revoked, DB access locked...
  │  Current: @bob analyzing network logs
  │
  └─ [NOW] Current Status
     Known: 3 key findings
     Active: @alice (log analysis), @bob (network forensics)
     Open questions: 2
```

### 5. Web UI

Extends the timeline view with:
- Auto-refresh (poll for new analyses)
- Segment detail drill-down
- Participant activity tracker
- Finding accumulator
- Dark/light mode (reuse news-collector pattern)

## CLI Interface

```
ir-tracker ingest <export.json> [--db tracker.db] [--channel #name]
    Import messages from stail/scat export. Deduplicates automatically.

ir-tracker analyze [--db tracker.db] [--model gemini-2.5-pro]
    Analyze pending/stale segments. Only processes what changed.

ir-tracker status [--db tracker.db] [--format markdown|json]
    Output current timeline and status.

ir-tracker serve [--db tracker.db] [--port 8080]
    Start Web UI.

ir-tracker segments [--db tracker.db]
    List segments with their states (for debugging).

ir-tracker reset [--db tracker.db]
    Clear all analyses (keep messages). Forces re-analysis.
```

## Data Flow: Typical Usage

```bash
# 1. Export current conversation from Slack
stail export -c "#incident-2026-0330" --output latest.json

# 2. Ingest (safe to re-run — deduplicates)
ir-tracker ingest latest.json

# 3. Analyze new segments
ir-tracker analyze

# 4. View status
ir-tracker status

# 5. Or open Web UI
ir-tracker serve
```

Repeat steps 1-4 periodically (every 15-30 min) during the incident.

## Configuration

```bash
export GOOGLE_CLOUD_PROJECT="your-project-id"
gcloud auth application-default login
```

| Environment variable | Description |
|---|---|
| `GOOGLE_CLOUD_PROJECT` | GCP project ID (required) |
| `GOOGLE_CLOUD_LOCATION` | Vertex AI region (default: us-central1) |
| `IR_TRACKER_MODEL` | Model name (default: gemini-2.5-pro) |
| `IR_TRACKER_SEGMENT_WINDOW` | Segment window in minutes (default: 30) |
| `IR_TRACKER_MIN_MESSAGES` | Minimum messages per segment (default: 3) |

## Security Considerations

- All data stays local (SQLite file)
- Only the Vertex AI API endpoint receives data
- Message text should be defanged before ingestion (use ai-ir's `aiir ingest`
  for preprocessing, or integrate defanging inline)
- No credentials stored in the database
- Web UI binds to 127.0.0.1 only (no external access)

## Relationship with ai-ir

| Aspect | ai-ir | ir-tracker |
|---|---|---|
| Timing | Post-incident | During incident |
| Input | Single export | Continuous re-ingestion |
| Analysis | Whole conversation | Segmented, incremental |
| Output | Final report | Growing timeline |
| LLM | OpenAI-compatible | Vertex AI Gemini (1M context) |
| Storage | Stateless (files) | Stateful (SQLite) |

They complement each other:
- Use ir-tracker during the incident for live visibility
- Use ai-ir after the incident for the post-mortem report
- Both consume the same stail/scat export format

## Development Plan

| Phase | Content | Priority |
|---|---|---|
| **Phase 1** | DB schema + ingest (dedup, sort) + CLI | Must |
| **Phase 2** | Segmentation engine (time window + entropy) | Must |
| **Phase 3** | Segment analysis (Gemini Pro, context chaining) | Must |
| **Phase 4** | Status output (Markdown timeline) | Must |
| **Phase 5** | Web UI (timeline visualization) | Should |
| **Phase 6** | Defanging integration, ai-ir interop | Nice |
