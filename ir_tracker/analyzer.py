"""Segment analysis using Gemini 2.5 Pro via Vertex AI."""

from __future__ import annotations

import json
import os
import sys
import time
import random
from datetime import datetime

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from ir_tracker.storage import Storage

_MODEL = "gemini-2.5-pro"
_MAX_RETRIES = 5
_RETRY_BASE_DELAY = 5.0


# ── Output schema ──


class NotableEvent(BaseModel):
    time: str = Field(description="Timestamp or relative time")
    description: str = Field(description="What happened")
    significance: str = Field(description="high, medium, or low")


class ActiveParticipant(BaseModel):
    user_name: str
    inferred_role: str = Field(description="Best guess at their role")
    current_activity: str = Field(description="What they are doing in this segment")


class SegmentAnalysis(BaseModel):
    summary: str = Field(description="2-4 sentence summary of this segment")
    key_findings: list[str] = Field(description="New findings in this segment")
    active_participants: list[ActiveParticipant] = Field(default_factory=list)
    status: str = Field(description="investigating | escalated | contained | monitoring | resolved")
    severity: str = Field(description="critical | high | medium | low | info")
    open_questions: list[str] = Field(default_factory=list)
    notable_events: list[NotableEvent] = Field(default_factory=list)


# ── System prompt ──

_SYSTEM_PROMPT = """\
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
Respond in English regardless of the conversation language.
"""


# ── Retry logic ──


def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "resource_exhausted" in msg


def _call_with_retry(fn, label: str = ""):
    for attempt in range(_MAX_RETRIES):
        try:
            return fn()
        except Exception as e:
            if _is_rate_limit(e) and attempt < _MAX_RETRIES - 1:
                delay = min(_RETRY_BASE_DELAY * (2**attempt), 120) + random.uniform(0, 1)
                print(f"  Rate limited [{label}] — retrying in {delay:.1f}s", file=sys.stderr)
                time.sleep(delay)
                continue
            raise
    raise RuntimeError("unreachable")


# ── Client ──


def _make_client() -> genai.Client:
    return genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
    )


# ── Analysis ──


def _format_messages(messages: list[dict]) -> str:
    """Format messages for the LLM prompt."""
    lines = []
    for m in messages:
        ts = m["ts"]
        user = m["user_name"] or m["user_id"]
        text = m["text"]
        prefix = "[bot] " if m["is_bot"] else ""
        lines.append(f"[{ts}] {prefix}{user}: {text}")
    return "\n".join(lines)


def _build_context(storage: Storage, current_segment_id: int) -> str:
    """Build compressed context from previous segment analyses."""
    analyses = storage.get_all_analyses()
    if not analyses:
        return "No previous segments analyzed yet. This is the first segment."

    context_parts = []
    cumulative_findings: list[str] = []
    participants_seen: set[str] = set()

    for a in analyses:
        if a["segment_id"] >= current_segment_id:
            break
        try:
            data = json.loads(a["analysis_json"])
        except json.JSONDecodeError:
            continue

        context_parts.append(
            f"Segment {a['segment_id']} ({a['start_ts']} - {a['end_ts']}): "
            f"{data.get('summary', 'No summary')}"
        )
        cumulative_findings.extend(data.get("key_findings", []))
        for p in data.get("active_participants", []):
            participants_seen.add(f"{p.get('user_name', '?')} ({p.get('inferred_role', '?')})")

    context = "Previous segment summaries:\n" + "\n".join(context_parts)
    if cumulative_findings:
        context += "\n\nKey findings so far:\n" + "\n".join(f"- {f}" for f in cumulative_findings)
    if participants_seen:
        context += "\n\nKnown participants: " + ", ".join(sorted(participants_seen))

    return context


def analyze_segment(storage: Storage, segment: dict, verbose: bool = False) -> SegmentAnalysis:
    """Analyze a single segment using Gemini."""
    client = _make_client()
    model = os.environ.get("IR_TRACKER_MODEL", _MODEL)

    messages = storage.get_messages_in_range(segment["start_ts"], segment["end_ts"])
    if not messages:
        return SegmentAnalysis(
            summary="No messages in this segment.",
            key_findings=[],
            status="investigating",
            severity="info",
        )

    context = _build_context(storage, segment["id"])
    formatted_messages = _format_messages(messages)

    user_prompt = (
        f"Context from previous segments:\n{context}\n\n"
        f"Current segment ({segment['start_ts']} to {segment['end_ts']}, "
        f"{segment['message_count']} messages):\n\n"
        f"{formatted_messages}"
    )

    if verbose:
        print(f"  Analyzing segment {segment['id']} ({segment['message_count']} messages)...", file=sys.stderr)

    def _run() -> SegmentAnalysis:
        response = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=SegmentAnalysis,
            ),
        )
        data = json.loads(response.text)
        return SegmentAnalysis(**data)

    result = _call_with_retry(_run, f"segment-{segment['id']}")

    # Save to DB
    storage.save_analysis(
        segment_id=segment["id"],
        analysis_json=result.model_dump_json(),
        model=model,
        token_count=0,  # TODO: extract from response metadata if available
    )
    storage.mark_segment_analyzed(segment["id"])

    # Update cumulative context
    storage.set_context("last_summary", result.summary)

    return result


def analyze_pending(storage: Storage, verbose: bool = False) -> int:
    """Analyze all pending and stale segments. Returns count analyzed."""
    segments = storage.get_segments("pending") + storage.get_segments("stale")
    segments.sort(key=lambda s: s["start_ts"])

    if not segments:
        print("No segments to analyze.", file=sys.stderr)
        return 0

    print(f"Analyzing {len(segments)} segment(s)...", file=sys.stderr)
    for seg in segments:
        analyze_segment(storage, seg, verbose=verbose)
        if verbose:
            print(f"  ✓ Segment {seg['id']} analyzed", file=sys.stderr)

    print(f"Done: {len(segments)} segment(s) analyzed.", file=sys.stderr)
    return len(segments)
