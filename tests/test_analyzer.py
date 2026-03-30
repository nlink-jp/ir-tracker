"""Tests for the analyzer module (LLM calls mocked)."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from ir_tracker.analyzer import (
    SegmentAnalysis,
    analyze_segment,
    analyze_pending,
    generate_incident_summary,
    IncidentSummary,
    _format_messages,
    _ts_to_local,
    _build_context,
)
from ir_tracker.storage import Storage
from datetime import timezone


def _make_storage(tmp: str, messages: list[dict] | None = None) -> Storage:
    db = str(Path(tmp) / "test.db")
    s = Storage(db)
    if messages:
        for m in messages:
            s.ingest_message(
                ts=m["ts"], user_id=m.get("user_id", "U001"),
                user_name=m.get("user_name", "alice"), text=m.get("text", "test"),
                thread_ts=None, channel="#inc", is_bot=False, raw_json=json.dumps(m),
            )
    return s


def test_format_messages():
    msgs = [
        {"ts": "1711771200.000100", "user_name": "alice", "user_id": "U001",
         "text": "hello", "is_bot": 0},
        {"ts": "1711771260.000200", "user_name": "", "user_id": "U002",
         "text": "world", "is_bot": 1},
    ]
    result = _format_messages(msgs, timezone.utc)
    lines = result.split("\n")
    assert len(lines) == 2
    assert "alice: hello" in lines[0]
    assert "[bot] U002: world" in lines[1]


def test_ts_to_local():
    from datetime import timedelta
    jst = timezone(timedelta(hours=9))
    result = _ts_to_local("1711771200.000100", jst)
    assert "2024-03-30" in result


def test_build_context_empty():
    with tempfile.TemporaryDirectory() as tmp:
        s = _make_storage(tmp)
        ctx = _build_context(s, 1)
        assert "first segment" in ctx.lower()
        s.close()


def test_build_context_with_prior():
    with tempfile.TemporaryDirectory() as tmp:
        s = _make_storage(tmp)
        # Insert a fake segment and analysis
        s.upsert_segment("100.0", "200.0", 5, "analyzed")
        seg = s.get_segments()[0]
        analysis = SegmentAnalysis(
            summary="Initial triage complete",
            key_findings=["SSH breach detected"],
            status="investigating",
            severity="high",
        )
        s.save_analysis(seg["id"], analysis.model_dump_json(), "test-model", 100)
        s.mark_segment_analyzed(seg["id"])

        ctx = _build_context(s, seg["id"] + 1)
        assert "Initial triage" in ctx
        assert "SSH breach" in ctx
        s.close()


def _mock_gemini_response(analysis: SegmentAnalysis, token_count: int = 500):
    """Create a mock Gemini response with usage_metadata."""
    response = MagicMock()
    response.text = analysis.model_dump_json()
    response.usage_metadata = MagicMock()
    response.usage_metadata.prompt_token_count = token_count - 100
    response.usage_metadata.candidates_token_count = 100
    return response


@patch("ir_tracker.analyzer._make_client")
def test_analyze_segment_records_tokens(mock_client):
    analysis = SegmentAnalysis(
        summary="Test analysis",
        key_findings=["finding1"],
        status="investigating",
        severity="high",
    )
    mock_client.return_value.models.generate_content.return_value = (
        _mock_gemini_response(analysis, 750)
    )

    with tempfile.TemporaryDirectory() as tmp:
        msgs = [{"ts": f"1711771200.{i:06d}", "text": f"msg {i}"} for i in range(5)]
        s = _make_storage(tmp, msgs)
        from ir_tracker.segmenter import update_segments
        update_segments(s)

        seg = s.get_segments()[0]
        analyze_segment(s, seg, verbose=False)

        saved = s.get_analysis(seg["id"])
        assert saved is not None
        assert saved["token_count"] == 750
        s.close()


@patch("ir_tracker.analyzer._make_client")
def test_analyze_pending_generates_summary(mock_client):
    analysis = SegmentAnalysis(
        summary="Test", key_findings=[], status="investigating", severity="info",
    )
    summary = IncidentSummary(
        incident_type="Test Incident", summary="An incident occurred.",
    )

    call_count = {"n": 0}

    def side_effect(*args, **kwargs):
        call_count["n"] += 1
        resp = MagicMock()
        resp.usage_metadata = MagicMock()
        resp.usage_metadata.prompt_token_count = 100
        resp.usage_metadata.candidates_token_count = 50
        # Last call is the incident summary
        if call_count["n"] <= 1:
            resp.text = analysis.model_dump_json()
        else:
            resp.text = summary.model_dump_json()
        return resp

    mock_client.return_value.models.generate_content.side_effect = side_effect

    with tempfile.TemporaryDirectory() as tmp:
        msgs = [{"ts": f"1711771200.{i:06d}", "text": f"msg {i}"} for i in range(5)]
        s = _make_storage(tmp, msgs)
        from ir_tracker.segmenter import update_segments
        update_segments(s)

        count = analyze_pending(s, verbose=False)
        assert count == 1

        assert s.get_context("incident_type") == "Test Incident"
        assert s.get_context("incident_summary") == "An incident occurred."
        s.close()
