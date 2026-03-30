"""Tests for the segmentation engine."""

import tempfile
from pathlib import Path

from ir_tracker.storage import Storage
from ir_tracker.segmenter import build_segments, update_segments


def _make_storage_with_messages(timestamps: list[str]) -> tuple[Storage, str]:
    """Create a storage with messages at the given timestamps."""
    tmp = tempfile.mkdtemp()
    db = str(Path(tmp) / "test.db")
    s = Storage(db)
    for i, ts in enumerate(timestamps):
        s.ingest_message(ts, f"U{i:03d}", f"user{i}", f"msg {i}", None, "#inc", False, "{}")
    return s, db


def test_single_segment():
    # 5 messages within 10 minutes → 1 segment
    base = 1711234567
    timestamps = [f"{base + i * 60}.000001" for i in range(5)]
    s, _ = _make_storage_with_messages(timestamps)
    segs = build_segments(s, window_minutes=30)
    assert len(segs) == 1
    assert segs[0].message_count == 5
    s.close()


def test_two_segments_by_window():
    # 10 messages, 5 in first 10 min, 5 in next 40 min → split by 30 min window
    base = 1711234567
    timestamps = [f"{base + i * 120}.000001" for i in range(5)]  # 0, 2, 4, 6, 8 min
    timestamps += [f"{base + 2400 + i * 120}.000001" for i in range(5)]  # 40, 42, 44, 46, 48 min
    s, _ = _make_storage_with_messages(timestamps)
    segs = build_segments(s, window_minutes=30)
    assert len(segs) == 2
    s.close()


def test_gap_detection():
    # Messages with a 2-hour gap → 2 segments
    base = 1711234567
    timestamps = [f"{base + i * 60}.000001" for i in range(5)]
    timestamps += [f"{base + 7200 + i * 60}.000001" for i in range(5)]  # 2h later
    s, _ = _make_storage_with_messages(timestamps)
    segs = build_segments(s, window_minutes=30, gap_threshold_minutes=60)
    assert len(segs) == 2
    s.close()


def test_merge_sparse():
    # 2 messages in window 1, 1 message in window 2 → merged (< min_messages)
    base = 1711234567
    timestamps = [
        f"{base}.000001",
        f"{base + 60}.000001",
        f"{base + 1900}.000001",  # 31 min later, new window but only 1 msg
    ]
    s, _ = _make_storage_with_messages(timestamps)
    segs = build_segments(s, window_minutes=30, min_messages=3)
    assert len(segs) == 1  # merged due to sparse
    assert segs[0].message_count == 3
    s.close()


def test_update_segments_counts_pending():
    base = 1711234567
    timestamps = [f"{base + i * 60}.000001" for i in range(5)]
    s, _ = _make_storage_with_messages(timestamps)
    pending = update_segments(s)
    assert pending > 0
    segs = s.get_segments("pending")
    assert len(segs) > 0
    s.close()


def test_empty_database():
    tmp = tempfile.mkdtemp()
    db = str(Path(tmp) / "test.db")
    s = Storage(db)
    segs = build_segments(s)
    assert len(segs) == 0
    s.close()


def test_split_dense_window():
    """A window with a 4x rate change should be split at the inflection point."""
    base = 1711234567
    # Slow phase: 4 messages over 10 minutes (0.4 msg/min)
    slow = [f"{base + i * 150}.000001" for i in range(4)]
    # Fast phase: 8 messages over 2 minutes (4 msg/min) — 10x rate change
    fast_start = base + 600  # 10 min in
    fast = [f"{fast_start + i * 15}.000001" for i in range(8)]
    timestamps = slow + fast

    s, _ = _make_storage_with_messages(timestamps)
    segs = build_segments(s, window_minutes=30, rate_change_factor=3.0)
    assert len(segs) == 2
    assert segs[0].message_count + segs[1].message_count == 12
    s.close()


def test_no_split_when_rate_uniform():
    """Uniform rate should not trigger a split."""
    base = 1711234567
    # 10 messages evenly spaced over 10 minutes
    timestamps = [f"{base + i * 60}.000001" for i in range(10)]
    s, _ = _make_storage_with_messages(timestamps)
    segs = build_segments(s, window_minutes=30, rate_change_factor=3.0)
    assert len(segs) == 1
    assert segs[0].message_count == 10
    s.close()
