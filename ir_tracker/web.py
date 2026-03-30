"""Web UI for ir-tracker timeline visualization."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ir_tracker.storage import Storage
from ir_tracker.timeline import build_json_timeline, build_situation_markdown

_HERE = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=str(_HERE / "templates"))


def _ts_to_display(ts: str) -> str:
    try:
        epoch = float(ts.split(".")[0])
        return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError):
        return ts


_MAX_BUCKETS = 200  # Target max buckets for readable chart


def _auto_bucket_seconds(span_sec: float) -> tuple[int, str, str]:
    """Choose bucket size and display formats based on time span.

    Returns (bucket_seconds, time_format, label_format).
    """
    # (threshold_hours, bucket_minutes, time_fmt, label_fmt)
    tiers = [
        (6,    5,    "%H:%M",       "%Y-%m-%d %H:%M"),  # <6h  → 5min
        (24,   15,   "%H:%M",       "%Y-%m-%d %H:%M"),  # <24h → 15min
        (72,   30,   "%H:%M",       "%Y-%m-%d %H:%M"),  # <3d  → 30min
        (168,  60,   "%m/%d %H:00", "%Y-%m-%d %H:00"),  # <7d  → 1h
        (720,  360,  "%m/%d %H:00", "%Y-%m-%d %H:00"),  # <30d → 6h
        (None, 1440, "%m/%d",       "%Y-%m-%d"),         # 30d+ → 1day
    ]
    span_hours = span_sec / 3600
    for threshold, minutes, time_fmt, label_fmt in tiers:
        if threshold is None or span_hours < threshold:
            return minutes * 60, time_fmt, label_fmt
    return 1440 * 60, "%m/%d", "%Y-%m-%d"


def _build_density(storage: Storage) -> list[dict]:
    """Build message density histogram with auto-scaled bucket size.

    Returns list of {"time": str, "count": int, "label": str}
    for chart rendering. Bucket size adapts to the time range.
    """
    messages = storage.get_all_messages()
    if not messages:
        return []

    timestamps = sorted(float(m["ts"].split(".")[0]) for m in messages)
    t_min = timestamps[0]
    t_max = timestamps[-1]
    span = t_max - t_min

    bucket_sec, time_fmt, label_fmt = _auto_bucket_seconds(span)

    # Align to bucket boundaries
    start = math.floor(t_min / bucket_sec) * bucket_sec
    end = math.ceil(t_max / bucket_sec) * bucket_sec + bucket_sec

    # Count messages per bucket using sorted timestamps (O(N) scan)
    buckets: list[dict] = []
    ts_idx = 0
    t = start
    while t < end:
        t_end = t + bucket_sec
        count = 0
        while ts_idx < len(timestamps) and timestamps[ts_idx] < t_end:
            if timestamps[ts_idx] >= t:
                count += 1
            ts_idx += 1
        dt = datetime.fromtimestamp(t)
        buckets.append({
            "time": dt.strftime(time_fmt),
            "label": dt.strftime(label_fmt),
            "count": count,
        })
        t = t_end

    return buckets


def create_app(db_path: str) -> FastAPI:
    app = FastAPI(title="ir-tracker", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
        return response

    app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")

    def _storage() -> Storage:
        return Storage(db_path)

    @app.get("/", response_class=HTMLResponse)
    def timeline_view(request: Request, lang: str = ""):
        storage = _storage()
        try:
            segments = storage.get_segments()
            msg_count = storage.get_message_count()
            time_range = storage.get_time_range()

            # Build segment data for template
            seg_data = []
            for seg in segments:
                item = {
                    "id": seg["id"],
                    "start_display": _ts_to_display(seg["start_ts"]),
                    "end_display": _ts_to_display(seg["end_ts"]),
                    "message_count": seg["message_count"],
                    "state": seg["state"],
                    "analysis": None,
                }

                analysis = storage.get_analysis(seg["id"])
                if analysis:
                    data = json.loads(analysis["analysis_json"])

                    # Overlay translation if available
                    if lang:
                        trans_json = storage.get_translation(seg["id"], lang)
                        if trans_json:
                            trans = json.loads(trans_json)
                            data["summary"] = trans.get("summary", data.get("summary", ""))
                            if trans.get("key_findings"):
                                data["key_findings"] = trans["key_findings"]
                            if trans.get("open_questions"):
                                data["open_questions"] = trans["open_questions"]
                            if trans.get("participants"):
                                data["active_participants"] = trans["participants"]
                            if trans.get("notable_events"):
                                data["notable_events"] = trans["notable_events"]

                    item["analysis"] = data
                seg_data.append(item)

            # Reverse: newest first
            seg_data.reverse()

            # Current status from latest analysis
            current_status = ""
            current_severity = ""
            if seg_data and seg_data[0]["analysis"]:
                latest = seg_data[0]["analysis"]
                current_status = latest.get("status", "")
                current_severity = latest.get("severity", "")

            # Cumulative summary (with translation overlay)
            cumulative = _build_cumulative(storage, lang=lang)

            # Message density for activity chart
            density = _build_density(storage)

            # Incident summary
            incident_type = storage.get_context("incident_type") or ""
            incident_summary = storage.get_context("incident_summary") or ""
            if lang:
                translated = storage.get_context(f"incident_summary:{lang}")
                if translated:
                    incident_summary = translated
                translated_type = storage.get_context(f"incident_type:{lang}")
                if translated_type:
                    incident_type = translated_type

            return _TEMPLATES.TemplateResponse(request, "timeline.html", {
                "segments": seg_data,
                "lang": lang,
                "density": density,
                "incident_type": incident_type,
                "incident_summary": incident_summary,
                "stats": {
                    "messages": msg_count,
                    "segments": len(segments),
                    "analyzed": sum(1 for s in segments if s["state"] == "analyzed"),
                    "current_status": current_status,
                    "current_severity": current_severity,
                    "time_range": (
                        _ts_to_display(time_range[0]),
                        _ts_to_display(time_range[1]),
                    ) if time_range else None,
                },
                "cumulative": cumulative,
            })
        finally:
            storage.close()

    @app.get("/segments", response_class=HTMLResponse)
    def segments_view(request: Request):
        storage = _storage()
        try:
            segments = storage.get_segments()
            seg_data = []
            for seg in segments:
                seg_data.append({
                    **seg,
                    "start_display": _ts_to_display(seg["start_ts"]),
                    "end_display": _ts_to_display(seg["end_ts"]),
                })
            return _TEMPLATES.TemplateResponse(request, "segments.html", {
                "segments": seg_data,
                "lang": "",
            })
        finally:
            storage.close()

    @app.get("/api/segments/{segment_id}/messages")
    def api_segment_messages(segment_id: int):
        storage = _storage()
        try:
            # Find the segment
            segments = storage.get_segments()
            seg = next((s for s in segments if s["id"] == segment_id), None)
            if not seg:
                return {"error": "Segment not found", "messages": []}

            messages = storage.get_messages_in_range(seg["start_ts"], seg["end_ts"])
            return {
                "segment_id": segment_id,
                "start": _ts_to_display(seg["start_ts"]),
                "end": _ts_to_display(seg["end_ts"]),
                "messages": [
                    {
                        "time": _ts_to_display(m["ts"]),
                        "user": m["user_name"] or m["user_id"],
                        "text": m["text"],
                        "is_bot": bool(m["is_bot"]),
                    }
                    for m in messages
                ],
            }
        finally:
            storage.close()

    @app.get("/api/timeline")
    def api_timeline(lang: str = ""):
        storage = _storage()
        try:
            return build_json_timeline(storage, lang=lang)
        finally:
            storage.close()

    @app.get("/api/situation.md")
    def api_situation_md(lang: str = ""):
        storage = _storage()
        try:
            md = build_situation_markdown(storage, lang=lang)
            return Response(
                content=md,
                media_type="text/markdown; charset=utf-8",
                headers={"Content-Disposition": "attachment; filename=situation.md"},
            )
        finally:
            storage.close()

    return app


def _build_cumulative(storage: Storage, lang: str = "") -> dict | None:
    analyses = storage.get_all_analyses()
    if not analyses:
        return None

    findings: list[str] = []
    questions: list[str] = []
    participants: dict[str, str] = {}

    for a in analyses:
        data = json.loads(a["analysis_json"])

        # Overlay translation if available
        if lang:
            trans_json = storage.get_translation(a["segment_id"], lang)
            if trans_json:
                trans = json.loads(trans_json)
                if trans.get("key_findings"):
                    data["key_findings"] = trans["key_findings"]
                if trans.get("open_questions"):
                    data["open_questions"] = trans["open_questions"]
                if trans.get("participants"):
                    data["active_participants"] = trans["participants"]

        findings.extend(data.get("key_findings", []))
        questions.extend(data.get("open_questions", []))
        for p in data.get("active_participants", []):
            participants[p.get("user_name", "?")] = p.get("current_activity", "")

    return {
        "findings": findings,
        "questions": list(dict.fromkeys(questions)),
        "participants": participants,
    }
