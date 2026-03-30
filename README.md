# ir-tracker

Live incident response tracker — continuous ingestion, segmented analysis, and timeline visualization for ongoing IR conversations.

**Status: Design phase** — architecture and detailed design complete; implementation pending.

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

## How It Works

1. **Ingest** — Import Slack export (stail/scat format) into SQLite. Deduplicates by message timestamp. Safe to re-run with overlapping data.
2. **Segment** — Divide the message stream into time-based segments (30 min default), with entropy-based splitting for activity bursts and gap detection for quiet periods.
3. **Analyze** — Send each new/changed segment to Gemini 2.5 Pro (1M context). Each segment receives compressed context from prior segments for continuity.
4. **Status** — Render a timeline showing what happened, who is doing what, key findings, and open questions.

## Planned CLI

```bash
ir-tracker ingest <export.json>    # Import messages (dedup, sort)
ir-tracker analyze                  # Analyze pending segments
ir-tracker status                   # Output timeline
ir-tracker serve                    # Web UI
ir-tracker segments                 # List segments and states
ir-tracker reset                    # Clear analyses, keep messages
```

## Design Documents

- [Architecture](docs/design/architecture.md) — components, data flow, CLI interface, security
- [Segmentation](docs/design/segmentation.md) — time window + entropy algorithm, edge cases
- [Analysis](docs/design/analysis.md) — LLM pipeline, context chaining, output schema, cost optimization

## Relationship with ai-ir

| Aspect | ai-ir | ir-tracker |
|---|---|---|
| Timing | Post-incident | During incident |
| Input | Single export | Continuous re-ingestion |
| Analysis | Whole conversation at once | Segmented, incremental |
| Output | Final report | Growing timeline |
| LLM | OpenAI-compatible | Vertex AI Gemini (1M context) |
| Storage | Stateless (files) | Stateful (SQLite) |
