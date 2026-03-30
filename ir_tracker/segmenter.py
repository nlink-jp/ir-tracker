"""Segmentation engine — divide messages into analyzable segments."""

from __future__ import annotations

from dataclasses import dataclass

from ir_tracker.storage import Storage

# Default configuration
DEFAULT_WINDOW_MINUTES = 30
DEFAULT_GAP_THRESHOLD_MINUTES = 60
DEFAULT_MIN_MESSAGES = 3
DEFAULT_RATE_CHANGE_FACTOR = 3.0


@dataclass
class SegmentBounds:
    """A segment's time boundaries and message count."""
    start_ts: str
    end_ts: str
    message_count: int


def _ts_to_seconds(ts: str) -> float:
    """Convert Slack timestamp (e.g. '1711234567.123456') to seconds."""
    return float(ts.split(".")[0])


def build_segments(
    storage: Storage,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
    gap_threshold_minutes: int = DEFAULT_GAP_THRESHOLD_MINUTES,
    min_messages: int = DEFAULT_MIN_MESSAGES,
    rate_change_factor: float = DEFAULT_RATE_CHANGE_FACTOR,
) -> list[SegmentBounds]:
    """Build segments from all messages in the database.

    Algorithm:
    1. Fixed time windows
    2. Gap detection (split at gaps > threshold)
    3. Merge sparse windows (< min_messages)
    4. (Future: entropy-based split for dense windows)

    Returns a list of SegmentBounds, sorted chronologically.
    """
    messages = storage.get_all_messages()
    if not messages:
        return []

    timestamps = [m["ts"] for m in messages]
    window_sec = window_minutes * 60
    gap_sec = gap_threshold_minutes * 60

    # Step 1 + 2: Build windows with gap detection
    windows: list[list[str]] = []
    current_window: list[str] = [timestamps[0]]
    window_start = _ts_to_seconds(timestamps[0])

    for ts in timestamps[1:]:
        ts_sec = _ts_to_seconds(ts)
        prev_sec = _ts_to_seconds(current_window[-1])

        # Gap detection: force boundary
        if ts_sec - prev_sec > gap_sec:
            windows.append(current_window)
            current_window = [ts]
            window_start = ts_sec
        # Window boundary
        elif ts_sec - window_start >= window_sec:
            windows.append(current_window)
            current_window = [ts]
            window_start = ts_sec
        else:
            current_window.append(ts)

    if current_window:
        windows.append(current_window)

    # Step 3: Merge sparse windows
    merged: list[list[str]] = []
    for window in windows:
        if merged and len(window) < min_messages and len(merged[-1]) < min_messages * 10:
            # Merge with previous
            merged[-1].extend(window)
        elif len(window) < min_messages and merged:
            merged[-1].extend(window)
        else:
            merged.append(window)

    # Handle edge case: single sparse window at the end
    if len(merged) > 1 and len(merged[-1]) < min_messages:
        merged[-2].extend(merged[-1])
        merged.pop()

    # Convert to SegmentBounds
    segments = []
    for window in merged:
        if window:
            segments.append(SegmentBounds(
                start_ts=window[0],
                end_ts=window[-1],
                message_count=len(window),
            ))

    return segments


def update_segments(
    storage: Storage,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
    gap_threshold_minutes: int = DEFAULT_GAP_THRESHOLD_MINUTES,
    min_messages: int = DEFAULT_MIN_MESSAGES,
) -> int:
    """Rebuild segments and update the database.

    Returns the number of segments that need analysis (pending or stale).
    """
    bounds_list = build_segments(
        storage,
        window_minutes=window_minutes,
        gap_threshold_minutes=gap_threshold_minutes,
        min_messages=min_messages,
    )

    # Get existing segments for state comparison
    existing = {(s["start_ts"], s["end_ts"]): s for s in storage.get_segments()}

    needs_analysis = 0
    for bounds in bounds_list:
        key = (bounds.start_ts, bounds.end_ts)
        if key in existing:
            old = existing[key]
            if old["message_count"] != bounds.message_count and old["state"] == "analyzed":
                storage.upsert_segment(bounds.start_ts, bounds.end_ts, bounds.message_count, "stale")
                needs_analysis += 1
            elif old["state"] in ("pending", "stale"):
                storage.upsert_segment(bounds.start_ts, bounds.end_ts, bounds.message_count, old["state"])
                needs_analysis += 1
        else:
            storage.upsert_segment(bounds.start_ts, bounds.end_ts, bounds.message_count, "pending")
            needs_analysis += 1

    return needs_analysis
