"""Tests for the translator module (LLM calls mocked)."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from ir_tracker.translator import translate_analysis, translate_pending, TranslatedAnalysis
from ir_tracker.analyzer import SegmentAnalysis
from ir_tracker.storage import Storage


def _make_storage_with_analysis(tmp: str) -> Storage:
    """Create a storage with messages, segments, and analyses."""
    db = str(Path(tmp) / "test.db")
    s = Storage(db)

    for i in range(6):
        s.ingest_message(
            ts=f"1711771{i:03d}.000001", user_id="U001", user_name="alice",
            text=f"msg {i}", thread_ts=None, channel="#inc", is_bot=False, raw_json="{}",
        )

    # Create 2 segments
    s.upsert_segment("1711771000.000001", "1711771002.000001", 3, "analyzed")
    s.upsert_segment("1711771003.000001", "1711771005.000001", 3, "analyzed")
    segs = s.get_segments()

    for seg in segs:
        analysis = SegmentAnalysis(
            summary=f"Summary for segment {seg['id']}",
            key_findings=[f"Finding {seg['id']}"],
            status="investigating",
            severity="high",
            open_questions=[f"Question {seg['id']}"],
        )
        s.save_analysis(seg["id"], analysis.model_dump_json(), "test", 100)
        s.mark_segment_analyzed(seg["id"])

    return s


@patch("ir_tracker.translator._make_client")
def test_translate_pending_parallel(mock_client):
    """Verify parallel translation produces correct results for all segments."""
    def _fake_generate(*args, **kwargs):
        resp = MagicMock()
        trans = TranslatedAnalysis(
            summary="翻訳されたサマリ",
            key_findings=["翻訳された発見"],
            open_questions=["翻訳された質問"],
        )
        resp.text = trans.model_dump_json()
        return resp

    mock_client.return_value.models.generate_content.side_effect = _fake_generate

    with tempfile.TemporaryDirectory() as tmp:
        s = _make_storage_with_analysis(tmp)
        count = translate_pending(s, "ja", verbose=False, max_workers=2)
        assert count == 2

        # Verify translations saved
        segs = s.get_segments()
        for seg in segs:
            trans_json = s.get_translation(seg["id"], "ja")
            assert trans_json is not None
            data = json.loads(trans_json)
            assert "翻訳されたサマリ" in data["summary"]

        s.close()


@patch("ir_tracker.translator._make_client")
def test_translate_pending_sequential(mock_client):
    """Verify sequential fallback works (max_workers=1)."""
    def _fake_generate(*args, **kwargs):
        resp = MagicMock()
        trans = TranslatedAnalysis(
            summary="Translated",
            key_findings=["Translated finding"],
            open_questions=["Translated question"],
        )
        resp.text = trans.model_dump_json()
        return resp

    mock_client.return_value.models.generate_content.side_effect = _fake_generate

    with tempfile.TemporaryDirectory() as tmp:
        s = _make_storage_with_analysis(tmp)
        count = translate_pending(s, "ja", verbose=False, max_workers=1)
        assert count == 2
        s.close()


@patch("ir_tracker.translator._make_client")
def test_translate_skips_already_translated(mock_client):
    """Already translated segments should not be re-translated."""
    mock_client.return_value.models.generate_content.side_effect = RuntimeError("should not be called")

    with tempfile.TemporaryDirectory() as tmp:
        s = _make_storage_with_analysis(tmp)

        # Pre-populate translations
        for seg in s.get_segments():
            s.save_translation(seg["id"], "ja", '{"summary":"existing"}')

        count = translate_pending(s, "ja")
        assert count == 0
        s.close()


def test_translate_analysis_mock():
    """Test translate_analysis with a mocked client."""
    client = MagicMock()
    trans = TranslatedAnalysis(
        summary="要約", key_findings=["発見1"], open_questions=["質問1"],
    )
    client.models.generate_content.return_value.text = trans.model_dump_json()

    result = translate_analysis(client, '{"summary":"test"}', "ja")
    assert result.summary == "要約"
    assert result.key_findings == ["発見1"]
