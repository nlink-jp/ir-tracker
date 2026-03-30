"""Tests for the ingest module."""

import json
import tempfile
from pathlib import Path

from ir_tracker.ingest import ingest_export
from ir_tracker.storage import Storage


def _write_export(tmp: str, data: dict | list) -> str:
    path = str(Path(tmp) / "export.json")
    Path(path).write_text(json.dumps(data), encoding="utf-8")
    return path


def test_ingest_scat_format():
    with tempfile.TemporaryDirectory() as tmp:
        export_path = _write_export(tmp, {
            "channel_name": "#incident",
            "messages": [
                {"ts": "1711234567.000001", "user": "U001", "text": "hello"},
                {"ts": "1711234568.000001", "user": "U002", "text": "world"},
            ],
        })
        db = str(Path(tmp) / "test.db")
        new, dup = ingest_export(db, export_path)
        assert new == 2
        assert dup == 0


def test_ingest_bare_array():
    with tempfile.TemporaryDirectory() as tmp:
        export_path = _write_export(tmp, [
            {"ts": "1711234567.000001", "user": "U001", "text": "hello"},
        ])
        db = str(Path(tmp) / "test.db")
        new, dup = ingest_export(db, export_path)
        assert new == 1


def test_ingest_dedup():
    with tempfile.TemporaryDirectory() as tmp:
        export_path = _write_export(tmp, {
            "channel_name": "#inc",
            "messages": [
                {"ts": "1711234567.000001", "user": "U001", "text": "hello"},
            ],
        })
        db = str(Path(tmp) / "test.db")
        new1, dup1 = ingest_export(db, export_path)
        new2, dup2 = ingest_export(db, export_path)
        assert new1 == 1
        assert dup1 == 0
        assert new2 == 0
        assert dup2 == 1


def test_ingest_incremental():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "test.db")

        # First export: 2 messages
        p1 = _write_export(tmp, {"channel_name": "#inc", "messages": [
            {"ts": "1711234567.000001", "user": "U001", "text": "first"},
            {"ts": "1711234568.000001", "user": "U002", "text": "second"},
        ]})
        ingest_export(db, p1)

        # Second export: overlaps + 1 new
        p2 = str(Path(tmp) / "export2.json")
        Path(p2).write_text(json.dumps({"channel_name": "#inc", "messages": [
            {"ts": "1711234568.000001", "user": "U002", "text": "second"},
            {"ts": "1711234569.000001", "user": "U003", "text": "third"},
        ]}))
        new, dup = ingest_export(db, p2)
        assert new == 1
        assert dup == 1

        s = Storage(db)
        assert s.get_message_count() == 3
        s.close()
