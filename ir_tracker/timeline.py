"""Timeline builder — synthesize segment analyses into a status view."""

from __future__ import annotations

import json
from datetime import datetime

from ir_tracker.storage import Storage


def _ts_to_datetime(ts: str) -> str:
    """Convert Slack timestamp to human-readable datetime."""
    try:
        epoch = float(ts.split(".")[0])
        return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError):
        return ts


def build_markdown_timeline(storage: Storage, lang: str = "") -> str:
    """Build a Markdown timeline from all analyses."""
    analyses = storage.get_all_analyses()
    segments = storage.get_segments()
    msg_count = storage.get_message_count()
    time_range = storage.get_time_range()

    lines = ["# Incident Timeline", ""]

    if not time_range:
        lines.append("No messages ingested yet.")
        return "\n".join(lines)

    lines.append(f"**Messages**: {msg_count}  |  "
                 f"**Segments**: {len(segments)}  |  "
                 f"**Analyzed**: {sum(1 for s in segments if s['state'] == 'analyzed')}")
    lines.append(f"**Time range**: {_ts_to_datetime(time_range[0])} — {_ts_to_datetime(time_range[1])}")
    lines.append("")

    # Current status from latest analysis
    if analyses:
        latest = json.loads(analyses[-1]["analysis_json"])
        status = latest.get("status", "unknown").upper()
        severity = latest.get("severity", "unknown").upper()
        lines.append(f"**Current status**: {status}  |  **Severity**: {severity}")
        lines.append("")

    lines.append("---")
    lines.append("")

    # Segment timeline
    for seg in segments:
        start = _ts_to_datetime(seg["start_ts"])
        end = _ts_to_datetime(seg["end_ts"])
        state_icon = {"analyzed": "✅", "pending": "⏳", "stale": "🔄"}.get(seg["state"], "❓")

        lines.append(f"## [{start} — {end}] {state_icon}")
        lines.append(f"*{seg['message_count']} messages*")
        lines.append("")

        # Get analysis if available
        analysis = storage.get_analysis(seg["id"])
        if analysis:
            data = json.loads(analysis["analysis_json"])

            # Overlay translation if requested and available
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

            # Summary
            lines.append(data.get("summary", ""))
            lines.append("")

            # Key findings
            findings = data.get("key_findings", [])
            if findings:
                lines.append("**Key findings:**")
                for f in findings:
                    lines.append(f"- {f}")
                lines.append("")

            # Active participants
            participants = data.get("active_participants", [])
            if participants:
                lines.append("**Participants:**")
                for p in participants:
                    role = p.get("inferred_role", "")
                    activity = p.get("current_activity", "")
                    lines.append(f"- **@{p.get('user_name', '?')}** ({role}): {activity}")
                lines.append("")

            # Notable events
            events = data.get("notable_events", [])
            if events:
                lines.append("**Events:**")
                for e in events:
                    sig = e.get("significance", "")
                    sig_icon = {"high": "🔴", "medium": "🟡", "low": "⚪"}.get(sig, "")
                    lines.append(f"- {sig_icon} [{e.get('time', '')}] {e.get('description', '')}")
                lines.append("")

            # Open questions
            questions = data.get("open_questions", [])
            if questions:
                lines.append("**Open questions:**")
                for q in questions:
                    lines.append(f"- ❓ {q}")
                lines.append("")
        else:
            lines.append("*Analysis pending*")
            lines.append("")

        lines.append("---")
        lines.append("")

    # Cumulative summary
    if analyses:
        all_findings: list[str] = []
        all_questions: list[str] = []
        all_participants: dict[str, str] = {}

        for a in analyses:
            data = json.loads(a["analysis_json"])
            all_findings.extend(data.get("key_findings", []))
            all_questions.extend(data.get("open_questions", []))
            for p in data.get("active_participants", []):
                all_participants[p.get("user_name", "?")] = p.get("current_activity", "")

        lines.append("## Summary")
        lines.append("")
        if all_findings:
            lines.append(f"**{len(all_findings)} key finding(s):**")
            for i, f in enumerate(all_findings, 1):
                lines.append(f"{i}. {f}")
            lines.append("")
        if all_participants:
            lines.append(f"**{len(all_participants)} participant(s) tracked:**")
            for user, activity in sorted(all_participants.items()):
                lines.append(f"- @{user}: {activity}")
            lines.append("")
        if all_questions:
            unique_q = list(dict.fromkeys(all_questions))
            lines.append(f"**{len(unique_q)} open question(s):**")
            for q in unique_q:
                lines.append(f"- {q}")
            lines.append("")

    return "\n".join(lines)


def build_json_timeline(storage: Storage, lang: str = "") -> dict:
    """Build a JSON timeline from all analyses."""
    analyses = storage.get_all_analyses()
    segments = storage.get_segments()
    msg_count = storage.get_message_count()
    time_range = storage.get_time_range()

    timeline_segments = []
    for seg in segments:
        analysis = storage.get_analysis(seg["id"])
        seg_data = {
            "id": seg["id"],
            "start": _ts_to_datetime(seg["start_ts"]),
            "end": _ts_to_datetime(seg["end_ts"]),
            "message_count": seg["message_count"],
            "state": seg["state"],
        }
        if analysis:
            seg_data["analysis"] = json.loads(analysis["analysis_json"])
            if lang:
                trans_json = storage.get_translation(seg["id"], lang)
                if trans_json:
                    seg_data["translation"] = json.loads(trans_json)
        timeline_segments.append(seg_data)

    return {
        "message_count": msg_count,
        "segment_count": len(segments),
        "time_range": {
            "start": _ts_to_datetime(time_range[0]) if time_range else None,
            "end": _ts_to_datetime(time_range[1]) if time_range else None,
        },
        "segments": timeline_segments,
        "generated_at": datetime.now().isoformat(),
    }
