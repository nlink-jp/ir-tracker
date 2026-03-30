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
) -> tuple[TranslatedAnalysis, int]:
    """Translate an analysis JSON to the target language using Gemini Flash.

    Returns (translated_analysis, token_count).
    """
    lang_name = _LANG_NAMES.get(lang, lang)
    token_count = 0

    def _run() -> TranslatedAnalysis:
        nonlocal token_count
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
        if response.usage_metadata:
            token_count = (
                (response.usage_metadata.prompt_token_count or 0)
                + (response.usage_metadata.candidates_token_count or 0)
            )
        data = json.loads(response.text)
        return TranslatedAnalysis(**data)

    result = _call_with_retry(_run, f"translate-{lang}")
    return result, token_count


_DEFAULT_WORKERS = 4


def translate_pending(
    storage: Storage, lang: str, verbose: bool = False, max_workers: int = _DEFAULT_WORKERS,
) -> int:
    """Translate all analyzed but untranslated segments. Returns count translated.

    Segment translations run in parallel (up to max_workers) since each is
    independent. DB writes are serialized on the main thread after collection.
    """
    untranslated = storage.get_untranslated_segments(lang)
    if not untranslated:
        print(f"No segments to translate to {lang}.", file=sys.stderr)
        return 0

    client = _make_client()

    # Collect (segment_id, analysis_json) pairs to translate
    tasks: list[tuple[int, str]] = []
    for seg in untranslated:
        analysis = storage.get_analysis(seg["id"])
        if analysis:
            tasks.append((seg["id"], analysis["analysis_json"]))

    if not tasks:
        return 0

    workers = min(max_workers, len(tasks))
    print(f"Translating {len(tasks)} segment(s) to {lang} ({workers} workers)...", file=sys.stderr)

    def _translate_one(item: tuple[int, str]) -> tuple[int, str, int]:
        seg_id, analysis_json = item
        result, tokens = translate_analysis(client, analysis_json, lang)
        return seg_id, result.model_dump_json(), tokens

    if workers <= 1:
        # Sequential fallback
        results = [_translate_one(t) for t in tasks]
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        results = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_translate_one, t): t[0] for t in tasks}
            for future in as_completed(futures):
                results.append(future.result())

    # Write results to DB (main thread, serialized)
    count = 0
    for seg_id, translation_json, tokens in results:
        storage.save_translation(seg_id, lang, translation_json, token_count=tokens)
        count += 1
        if verbose:
            print(f"  ✓ Segment {seg_id} translated to {lang} ({tokens} tokens)", file=sys.stderr)

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
