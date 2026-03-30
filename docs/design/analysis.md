# Segment Analysis — Detailed Design

## LLM Choice

**Gemini 2.5 Pro** via Vertex AI (`google.golang.org/genai` / `google-genai`).

Rationale:
- 1M token context window — handles large segments without truncation
- Structured output via `response_schema` — reliable JSON extraction
- Same Vertex AI infrastructure as news-collector and gem-cli
- No OpenAI compatibility layer needed

## Analysis Pipeline

For each segment in `pending` or `stale` state:

```
┌─────────────────────────────────────┐
│ Input:                              │
│   - Messages in this segment        │
│   - Previous segment summary        │
│   - Cumulative key findings         │
│   - Cumulative participant roster   │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│ Gemini 2.5 Pro                      │
│ System: "You are an IR analyst..."  │
│ User: segment data + context        │
│ response_schema: SegmentAnalysis    │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│ Output: SegmentAnalysis JSON        │
│   - summary                         │
│   - key_findings (new in this seg)  │
│   - active_participants             │
│   - status_change                   │
│   - severity_assessment             │
│   - open_questions                  │
└─────────────────────────────────────┘
```

## Context Chaining

To avoid re-reading the entire conversation for each segment, we pass
**compressed context** from prior segments:

```
Segment 3 analysis input:
  - [Context] Previous summary: "In segments 1-2, the team identified..."
  - [Context] Key findings so far: [finding1, finding2, finding3]
  - [Context] Known participants: [alice: Lead, bob: SRE, carol: Comms]
  - [Current] Messages in segment 3: [m45, m46, ..., m72]
```

This gives the LLM enough context to understand continuity without
consuming the full token budget on old messages.

## System Prompt

```
You are an incident response analyst providing real-time situation awareness.

Analyze the current segment of an ongoing IR conversation. You will receive:
1. Context from previous segments (summary, findings, participants)
2. The messages in the current time segment

For this segment, determine:
- What happened in this time period
- What new information was discovered
- Who is actively participating and what they are doing
- Whether the incident status changed (escalated, contained, resolved, etc.)
- What questions remain unanswered

Be concise and factual. Focus on actionable information.
Do not speculate beyond what the messages state.

IMPORTANT: Respond in English regardless of the conversation language.
```

## Output Schema

```json
{
  "segment_id": 3,
  "time_range": {
    "start": "2026-03-30T09:00:00+09:00",
    "end": "2026-03-30T09:30:00+09:00"
  },
  "summary": "string — 2-4 sentence summary of this segment",
  "key_findings": [
    "New finding discovered in this segment"
  ],
  "active_participants": [
    {
      "user_name": "alice",
      "inferred_role": "Lead Responder",
      "current_activity": "Analyzing SSH session logs from bastion host"
    }
  ],
  "status": "investigating | escalated | contained | monitoring | resolved",
  "severity": "critical | high | medium | low | info",
  "open_questions": [
    "How did the attacker obtain SSH credentials?"
  ],
  "notable_events": [
    {
      "time": "09:15",
      "description": "Database export detected in audit log",
      "significance": "high"
    }
  ]
}
```

## Incremental Analysis

| Scenario | Action |
|---|---|
| New segment (no prior analysis) | Full analysis |
| Segment marked `stale` (new messages added) | Re-analyze with updated messages |
| Segment already `analyzed`, no changes | Skip |

Re-analysis of a stale segment replaces the previous analysis entirely.
The old analysis is not preserved (the new one has all the messages).

## Cost Optimization

- Only `pending` and `stale` segments are sent to the LLM
- Context chaining avoids re-reading full history
- Gemini Flash could be used for "quick status" queries (cheaper, lower
  quality) while Pro is reserved for segment analysis
- Token count is tracked per analysis for cost monitoring

## Error Handling

- LLM timeout (> 120s): retry once, then mark segment as `error`
- Invalid JSON response: retry once with explicit format reminder
- Rate limiting (429): exponential backoff (same retry.py pattern as news-collector)
- Segment too large (> 500K tokens): split into sub-segments before analysis
