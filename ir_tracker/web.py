"""Web UI for ir-tracker timeline visualization."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ir_tracker.storage import Storage

_HERE = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=str(_HERE / "templates"))


def _ts_to_display(ts: str) -> str:
    try:
        epoch = float(ts.split(".")[0])
        return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError):
        return ts


def create_app(db_path: str) -> FastAPI:
    app = FastAPI(title="ir-tracker", docs_url=None, redoc_url=None)
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

            # Cumulative summary
            cumulative = _build_cumulative(storage)

            return _TEMPLATES.TemplateResponse(request, "timeline.html", {
                "segments": seg_data,
                "lang": lang,
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

    @app.get("/api/timeline")
    def api_timeline(lang: str = ""):
        from ir_tracker.timeline import build_json_timeline
        storage = _storage()
        try:
            return build_json_timeline(storage, lang=lang)
        finally:
            storage.close()

    return app


def _build_cumulative(storage: Storage) -> dict | None:
    analyses = storage.get_all_analyses()
    if not analyses:
        return None

    findings: list[str] = []
    questions: list[str] = []
    participants: dict[str, str] = {}

    for a in analyses:
        data = json.loads(a["analysis_json"])
        findings.extend(data.get("key_findings", []))
        questions.extend(data.get("open_questions", []))
        for p in data.get("active_participants", []):
            participants[p.get("user_name", "?")] = p.get("current_activity", "")

    return {
        "findings": findings,
        "questions": list(dict.fromkeys(questions)),
        "participants": participants,
    }
