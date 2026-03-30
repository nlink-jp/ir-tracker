"""Ingest stail/scat export JSON into the tracker database."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ir_tracker.storage import Storage


def ingest_export(db_path: str, export_path: str, channel_override: str = "") -> tuple[int, int]:
    """Ingest a stail/scat export JSON file.

    Supports two formats:
    1. scat/stail export: {"channel_name": "...", "messages": [...]}
    2. Bare message array: [{"ts": "...", ...}, ...]

    Returns (new_count, duplicate_count).
    """
    data = json.loads(Path(export_path).read_text(encoding="utf-8"))

    # Detect format
    if isinstance(data, dict):
        messages = data.get("messages", [])
        channel = channel_override or data.get("channel_name", "unknown")
    elif isinstance(data, list):
        messages = data
        channel = channel_override or "unknown"
    else:
        raise ValueError(f"Unsupported export format in {export_path}")

    storage = Storage(db_path)
    try:
        new_count = 0
        dup_count = 0

        for msg in messages:
            # Support both stail format (ts) and scli format (timestamp_unix)
            ts = msg.get("ts") or msg.get("timestamp_unix", "")
            if not ts:
                continue

            user_id = msg.get("user") or msg.get("user_id", "")
            user_name = msg.get("user_name") or msg.get("username", "")
            text = msg.get("text", "")
            thread_ts = msg.get("thread_ts") or msg.get("thread_timestamp_unix")
            is_bot = bool(
                msg.get("bot_id")
                or msg.get("subtype") == "bot_message"
                or msg.get("post_type") == "bot"
            )

            if storage.ingest_message(
                ts=ts,
                user_id=user_id,
                user_name=user_name,
                text=text,
                thread_ts=thread_ts,
                channel=channel,
                is_bot=is_bot,
                raw_json=json.dumps(msg, ensure_ascii=False),
            ):
                new_count += 1
            else:
                dup_count += 1

        return new_count, dup_count
    finally:
        storage.close()
