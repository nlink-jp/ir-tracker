"""Translate analysis results using Gemini Flash."""

from __future__ import annotations

import json
import os
import sys
import time
import random

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from ir_tracker.storage import Storage

_FLASH_MODEL = "gemini-2.5-flash"
_MAX_RETRIES = 5
_RETRY_BASE_DELAY = 5.0

_LANG_NAMES = {
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Simplified Chinese",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
}


class TranslatedAnalysis(BaseModel):
    """Translated fields of a segment analysis."""
    summary: str = Field(description="Translated summary")
    key_findings: list[str] = Field(description="Translated key findings")
    open_questions: list[str] = Field(description="Translated open questions")
    participants: list[dict] = Field(
        default_factory=list,
        description="Participants with translated current_activity and inferred_role",
    )
    notable_events: list[dict] = Field(
        default_factory=list,
        description="Events with translated description",
    )


def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "resource_exhausted" in msg


def _call_with_retry(fn, label: str = ""):
    for attempt in range(_MAX_RETRIES):
        try:
            return fn()
        except Exception as e:
            if _is_rate_limit(e) and attempt < _MAX_RETRIES - 1:
                delay = min(_RETRY_BASE_DELAY * (2**attempt), 120) + random.uniform(0, 1)
                print(f"  Rate limited [{label}] — retrying in {delay:.1f}s", file=sys.stderr)
                time.sleep(delay)
                continue
            raise
    raise RuntimeError("unreachable")


def _make_client() -> genai.Client:
    return genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
    )


def translate_analysis(
    client: genai.Client, analysis_json: str, lang: str
) -> TranslatedAnalysis:
    """Translate an analysis JSON to the target language using Gemini Flash."""
    lang_name = _LANG_NAMES.get(lang, lang)

    def _run() -> TranslatedAnalysis:
        response = client.models.generate_content(
            model=_FLASH_MODEL,
            contents=(
                f"Translate the following incident response analysis into {lang_name}.\n\n"
                f"Translate these fields: summary, key_findings, open_questions, "
                f"participant activities/roles, and event descriptions.\n\n"
                f"Keep technical terms (IP addresses, hostnames, commands, CVE IDs) as-is.\n"
                f"Keep user_name fields as-is (do not translate names).\n\n"
                f"Analysis:\n{analysis_json}"
            ),
            config=types.GenerateContentConfig(
                system_instruction=(
                    f"You are a professional translator specializing in cybersecurity "
                    f"incident response. Translate accurately into {lang_name}. "
                    f"Preserve all technical terms, IP addresses, and command names. "
                    f"Be concise and natural."
                ),
                response_mime_type="application/json",
                response_schema=TranslatedAnalysis,
            ),
        )
        data = json.loads(response.text)
        return TranslatedAnalysis(**data)

    return _call_with_retry(_run, f"translate-{lang}")


def translate_pending(storage: Storage, lang: str, verbose: bool = False) -> int:
    """Translate all analyzed but untranslated segments. Returns count translated."""
    untranslated = storage.get_untranslated_segments(lang)
    if not untranslated:
        print(f"No segments to translate to {lang}.", file=sys.stderr)
        return 0

    client = _make_client()
    print(f"Translating {len(untranslated)} segment(s) to {lang}...", file=sys.stderr)

    count = 0
    for seg in untranslated:
        analysis = storage.get_analysis(seg["id"])
        if not analysis:
            continue

        result = translate_analysis(client, analysis["analysis_json"], lang)
        storage.save_translation(seg["id"], lang, result.model_dump_json())
        count += 1

        if verbose:
            print(f"  ✓ Segment {seg['id']} translated to {lang}", file=sys.stderr)

    print(f"Done: {count} segment(s) translated to {lang}.", file=sys.stderr)

    # Translate incident summary if present and not yet translated
    incident_summary = storage.get_context("incident_summary")
    existing_trans = storage.get_context(f"incident_summary:{lang}")
    if incident_summary and not existing_trans:
        _translate_incident_summary(client, storage, lang, verbose=verbose)

    return count


def _translate_incident_summary(
    client: genai.Client, storage: Storage, lang: str, verbose: bool = False
) -> None:
    """Translate the incident summary and type."""
    lang_name = _LANG_NAMES.get(lang, lang)
    incident_type = storage.get_context("incident_type") or ""
    incident_summary = storage.get_context("incident_summary") or ""

    text = f"Incident type: {incident_type}\nSummary: {incident_summary}"

    def _run() -> dict:
        response = client.models.generate_content(
            model=os.environ.get("IR_TRACKER_FLASH_MODEL", _FLASH_MODEL),
            contents=(
                f"Translate the following incident summary into {lang_name}.\n"
                f"Keep technical terms (IP addresses, hostnames, CVE IDs) as-is.\n\n"
                f"{text}"
            ),
            config=types.GenerateContentConfig(
                system_instruction=f"Translate accurately into {lang_name}. Be concise.",
                response_mime_type="application/json",
                response_schema={
                    "type": "object",
                    "properties": {
                        "incident_type": {"type": "string"},
                        "summary": {"type": "string"},
                    },
                    "required": ["incident_type", "summary"],
                },
            ),
        )
        return json.loads(response.text)

    result = _call_with_retry(_run, f"incident-summary-{lang}")
    storage.set_context(f"incident_type:{lang}", result["incident_type"])
    storage.set_context(f"incident_summary:{lang}", result["summary"])

    if verbose:
        print(f"  ✓ Incident summary translated to {lang}", file=sys.stderr)
