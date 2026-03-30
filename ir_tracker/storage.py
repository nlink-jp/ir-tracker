"""SQLite storage for messages, segments, and analyses."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS messages (
    ts          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    user_name   TEXT NOT NULL DEFAULT '',
    text        TEXT NOT NULL DEFAULT '',
    thread_ts   TEXT,
    channel     TEXT NOT NULL DEFAULT '',
    is_bot      INTEGER NOT NULL DEFAULT 0,
    ingested_at TEXT NOT NULL,
    raw_json    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS segments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    start_ts      TEXT NOT NULL,
    end_ts        TEXT NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    state         TEXT NOT NULL DEFAULT 'pending',
    created_at    TEXT NOT NULL,
    analyzed_at   TEXT
);

CREATE TABLE IF NOT EXISTS analyses (
    segment_id   INTEGER PRIMARY KEY,
    analysis_json TEXT NOT NULL,
    model        TEXT NOT NULL DEFAULT '',
    token_count  INTEGER NOT NULL DEFAULT 0,
    analyzed_at  TEXT NOT NULL,
    FOREIGN KEY (segment_id) REFERENCES segments(id)
);

CREATE TABLE IF NOT EXISTS timeline_context (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_translations (
    segment_id  INTEGER NOT NULL,
    lang        TEXT NOT NULL,
    translation_json TEXT NOT NULL,
    translated_at TEXT NOT NULL,
    token_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (segment_id, lang),
    FOREIGN KEY (segment_id) REFERENCES segments(id)
);
"""


class Storage:
    """SQLite storage for ir-tracker.

    Each Storage instance owns its own SQLite connection and must not be
    shared across threads. The translator's parallel workers create their
    own results in-thread and write to the DB on the main thread only.
    """

    def __init__(self, db_path: str) -> None:
        self._db = sqlite3.connect(db_path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self._migrate()
        self._db.commit()

    def _migrate(self) -> None:
        """Apply incremental schema migrations for existing databases.

        Each migration is idempotent (checks before applying). Wrapped in
        a transaction so partial failures don't leave the DB in a broken state.
        """
        import sys
        try:
            # v0.2.2: add token_count to analysis_translations
            cols = {row[1] for row in self._db.execute("PRAGMA table_info(analysis_translations)")}
            if "token_count" not in cols:
                self._db.execute("ALTER TABLE analysis_translations ADD COLUMN token_count INTEGER NOT NULL DEFAULT 0")
        except Exception as e:
            print(f"WARNING: Schema migration failed: {e}", file=sys.stderr)
            print("The database may need manual repair. Back up tracker.db before retrying.", file=sys.stderr)
            raise

    def close(self) -> None:
        self._db.close()

    # ── Messages ──

    def ingest_message(
        self,
        ts: str,
        user_id: str,
        user_name: str,
        text: str,
        thread_ts: str | None,
        channel: str,
        is_bot: bool,
        raw_json: str,
    ) -> bool:
        """Insert a message. Returns False if ts already exists (dedup)."""
        try:
            self._db.execute(
                "INSERT INTO messages (ts, user_id, user_name, text, thread_ts, channel, is_bot, ingested_at, raw_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ts, user_id, user_name, text, thread_ts, channel, int(is_bot), datetime.now().isoformat(), raw_json),
            )
            self._db.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_all_messages(self) -> list[dict]:
        """Return all messages sorted by timestamp."""
        rows = self._db.execute(
            "SELECT * FROM messages ORDER BY ts ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_message_count(self) -> int:
        row = self._db.execute("SELECT COUNT(*) FROM messages").fetchone()
        return row[0]

    def get_time_range(self) -> tuple[str, str] | None:
        """Return (earliest_ts, latest_ts) or None if empty."""
        row = self._db.execute(
            "SELECT MIN(ts), MAX(ts) FROM messages"
        ).fetchone()
        if row[0] is None:
            return None
        return (row[0], row[1])

    def get_messages_in_range(self, start_ts: str, end_ts: str) -> list[dict]:
        """Return messages within a timestamp range (inclusive)."""
        rows = self._db.execute(
            "SELECT * FROM messages WHERE ts >= ? AND ts <= ? ORDER BY ts ASC",
            (start_ts, end_ts),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Segments ──

    def upsert_segment(
        self, start_ts: str, end_ts: str, message_count: int, state: str = "pending"
    ) -> int:
        """Insert or update a segment. Returns the segment ID."""
        # Check if a segment with overlapping range exists
        existing = self._db.execute(
            "SELECT id, state FROM segments WHERE start_ts = ? AND end_ts = ?",
            (start_ts, end_ts),
        ).fetchone()

        if existing:
            seg_id = existing["id"]
            old_state = existing["state"]
            # If analyzed and message count changed, mark stale
            new_state = state
            if old_state == "analyzed" and state == "pending":
                new_state = "stale"
            self._db.execute(
                "UPDATE segments SET message_count = ?, state = ? WHERE id = ?",
                (message_count, new_state, seg_id),
            )
            self._db.commit()
            return seg_id

        cursor = self._db.execute(
            "INSERT INTO segments (start_ts, end_ts, message_count, state, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (start_ts, end_ts, message_count, state, datetime.now().isoformat()),
        )
        self._db.commit()
        return cursor.lastrowid

    def get_segments(self, state: str | None = None) -> list[dict]:
        """Return segments, optionally filtered by state."""
        if state:
            rows = self._db.execute(
                "SELECT * FROM segments WHERE state = ? ORDER BY start_ts ASC",
                (state,),
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM segments ORDER BY start_ts ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_segment_analyzed(self, segment_id: int) -> None:
        self._db.execute(
            "UPDATE segments SET state = 'analyzed', analyzed_at = ? WHERE id = ?",
            (datetime.now().isoformat(), segment_id),
        )
        self._db.commit()

    def clear_segments(self) -> None:
        """Delete all segments, analyses, translations, and context (keep messages)."""
        self._db.execute("DELETE FROM analysis_translations")
        self._db.execute("DELETE FROM analyses")
        self._db.execute("DELETE FROM segments")
        self._db.execute("DELETE FROM timeline_context")
        self._db.commit()

    # ── Analyses ──

    def save_analysis(
        self, segment_id: int, analysis_json: str, model: str, token_count: int
    ) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO analyses (segment_id, analysis_json, model, token_count, analyzed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (segment_id, analysis_json, model, token_count, datetime.now().isoformat()),
        )
        self._db.commit()

    def get_analysis(self, segment_id: int) -> dict | None:
        row = self._db.execute(
            "SELECT * FROM analyses WHERE segment_id = ?", (segment_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_all_analyses(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT a.*, s.start_ts, s.end_ts, s.message_count "
            "FROM analyses a JOIN segments s ON a.segment_id = s.id "
            "ORDER BY s.start_ts ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Translations ──

    def save_translation(
        self, segment_id: int, lang: str, translation_json: str, token_count: int = 0,
    ) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO analysis_translations "
            "(segment_id, lang, translation_json, translated_at, token_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (segment_id, lang, translation_json, datetime.now().isoformat(), token_count),
        )
        self._db.commit()

    def get_translation(self, segment_id: int, lang: str) -> str | None:
        row = self._db.execute(
            "SELECT translation_json FROM analysis_translations WHERE segment_id = ? AND lang = ?",
            (segment_id, lang),
        ).fetchone()
        return row["translation_json"] if row else None

    def get_untranslated_segments(self, lang: str) -> list[dict]:
        """Return analyzed segments that have no translation for the given language."""
        rows = self._db.execute(
            "SELECT s.* FROM segments s "
            "WHERE s.state = 'analyzed' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM analysis_translations t WHERE t.segment_id = s.id AND t.lang = ?"
            ") ORDER BY s.start_ts ASC",
            (lang,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_token_usage(self) -> dict[str, int]:
        """Return cumulative token usage by category.

        Returns {"analysis": N, "translation": N, "total": N}.
        """
        row_a = self._db.execute("SELECT COALESCE(SUM(token_count), 0) FROM analyses").fetchone()
        row_t = self._db.execute("SELECT COALESCE(SUM(token_count), 0) FROM analysis_translations").fetchone()
        analysis = row_a[0]
        translation = row_t[0]
        return {"analysis": analysis, "translation": translation, "total": analysis + translation}

    # ── Context ──

    def set_context(self, key: str, value: str) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO timeline_context (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._db.commit()

    def get_context(self, key: str) -> str | None:
        row = self._db.execute(
            "SELECT value FROM timeline_context WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None
