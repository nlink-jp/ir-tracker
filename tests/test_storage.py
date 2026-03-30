"""Tests for the storage module."""

import tempfile
from pathlib import Path

from ir_tracker.storage import Storage


def test_ingest_and_retrieve():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "test.db")
        s = Storage(db)
        ok = s.ingest_message("1711234567.000001", "U001", "alice", "hello", None, "#inc", False, "{}")
        assert ok is True
        assert s.get_message_count() == 1
        msgs = s.get_all_messages()
        assert len(msgs) == 1
        assert msgs[0]["user_name"] == "alice"
        s.close()


def test_dedup():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "test.db")
        s = Storage(db)
        assert s.ingest_message("1711234567.000001", "U001", "alice", "hello", None, "#inc", False, "{}") is True
        assert s.ingest_message("1711234567.000001", "U001", "alice", "hello", None, "#inc", False, "{}") is False
        assert s.get_message_count() == 1
        s.close()


def test_time_range():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "test.db")
        s = Storage(db)
        s.ingest_message("1711234567.000001", "U001", "alice", "first", None, "#inc", False, "{}")
        s.ingest_message("1711234999.000001", "U002", "bob", "last", None, "#inc", False, "{}")
        r = s.get_time_range()
        assert r is not None
        assert r[0] == "1711234567.000001"
        assert r[1] == "1711234999.000001"
        s.close()


def test_segments():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "test.db")
        s = Storage(db)
        sid = s.upsert_segment("1711234567.000001", "1711236367.000001", 10, "pending")
        assert sid > 0
        segs = s.get_segments("pending")
        assert len(segs) == 1
        assert segs[0]["message_count"] == 10

        s.mark_segment_analyzed(sid)
        assert len(s.get_segments("pending")) == 0
        assert len(s.get_segments("analyzed")) == 1
        s.close()


def test_segment_stale_on_update():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "test.db")
        s = Storage(db)
        sid = s.upsert_segment("1711234567.000001", "1711236367.000001", 10, "pending")
        s.mark_segment_analyzed(sid)

        # Re-upsert with more messages → should become stale
        s.upsert_segment("1711234567.000001", "1711236367.000001", 15, "pending")
        segs = s.get_segments("stale")
        assert len(segs) == 1
        assert segs[0]["message_count"] == 15
        s.close()


def test_analysis():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "test.db")
        s = Storage(db)
        sid = s.upsert_segment("1711234567.000001", "1711236367.000001", 10, "pending")
        s.save_analysis(sid, '{"summary": "test"}', "gemini-2.5-pro", 1000)
        a = s.get_analysis(sid)
        assert a is not None
        assert '"test"' in a["analysis_json"]
        s.close()


def test_clear_segments():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "test.db")
        s = Storage(db)
        s.ingest_message("1711234567.000001", "U001", "alice", "hello", None, "#inc", False, "{}")
        s.upsert_segment("1711234567.000001", "1711234567.000001", 1, "analyzed")
        s.save_analysis(1, '{}', "test", 0)

        s.clear_segments()
        assert len(s.get_segments()) == 0
        assert s.get_message_count() == 1  # messages preserved
        s.close()
