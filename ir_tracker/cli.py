"""CLI entry point for ir-tracker."""

import argparse
import json
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Live incident response tracker",
    )
    subparsers = parser.add_subparsers(dest="command")

    # ingest
    ingest_p = subparsers.add_parser("ingest", help="Import messages from stail/scat export")
    ingest_p.add_argument("export_file", help="Path to export JSON file")
    ingest_p.add_argument("--db", default="tracker.db", help="SQLite database path")
    ingest_p.add_argument("--channel", default="", help="Override channel name")

    # analyze
    analyze_p = subparsers.add_parser("analyze", help="Analyze pending/stale segments")
    analyze_p.add_argument("--db", default="tracker.db", help="SQLite database path")
    analyze_p.add_argument("--verbose", "-v", action="store_true")
    analyze_p.add_argument("--lang", "-l", default="", help="Translate after analysis (e.g. ja)")

    # status
    status_p = subparsers.add_parser("status", help="Output current timeline")
    status_p.add_argument("--db", default="tracker.db", help="SQLite database path")
    status_p.add_argument("--format", default="markdown", choices=["markdown", "json"])
    status_p.add_argument("--lang", "-l", default="", help="Display in translated language (e.g. ja)")

    # segments
    segments_p = subparsers.add_parser("segments", help="List segments and states")
    segments_p.add_argument("--db", default="tracker.db", help="SQLite database path")

    # reset
    reset_p = subparsers.add_parser("reset", help="Clear analyses (keep messages)")
    reset_p.add_argument("--db", default="tracker.db", help="SQLite database path")

    # serve
    serve_p = subparsers.add_parser("serve", help="Start Web UI")
    serve_p.add_argument("--db", default="tracker.db", help="SQLite database path")
    serve_p.add_argument("--port", "-p", type=int, default=8080)
    serve_p.add_argument("--host", default="127.0.0.1")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "ingest":
        _run_ingest(args)
    elif args.command == "analyze":
        _run_analyze(args)
    elif args.command == "status":
        _run_status(args)
    elif args.command == "segments":
        _run_segments(args)
    elif args.command == "reset":
        _run_reset(args)
    elif args.command == "serve":
        _run_serve(args)


def _run_ingest(args) -> None:
    from ir_tracker.ingest import ingest_export
    from ir_tracker.segmenter import update_segments
    from ir_tracker.storage import Storage

    new, dup = ingest_export(args.db, args.export_file, args.channel)
    print(f"Ingested: {new} new, {dup} duplicates", file=sys.stderr)

    # Rebuild segments after ingest
    storage = Storage(args.db)
    try:
        pending = update_segments(storage)
        print(f"Segments: {pending} need analysis", file=sys.stderr)
    finally:
        storage.close()


def _run_analyze(args) -> None:
    from ir_tracker.analyzer import analyze_pending
    from ir_tracker.storage import Storage

    storage = Storage(args.db)
    try:
        count = analyze_pending(storage, verbose=args.verbose)
        if args.lang and count > 0:
            from ir_tracker.translator import translate_pending
            translate_pending(storage, args.lang, verbose=args.verbose)
    finally:
        storage.close()


def _run_status(args) -> None:
    from ir_tracker.storage import Storage
    from ir_tracker.timeline import build_markdown_timeline, build_json_timeline

    storage = Storage(args.db)
    try:
        if args.format == "json":
            print(json.dumps(build_json_timeline(storage, lang=args.lang), ensure_ascii=False, indent=2))
        else:
            print(build_markdown_timeline(storage, lang=args.lang))
    finally:
        storage.close()


def _run_segments(args) -> None:
    from ir_tracker.storage import Storage
    from ir_tracker.timeline import _ts_to_datetime

    storage = Storage(args.db)
    try:
        segments = storage.get_segments()
        if not segments:
            print("No segments.", file=sys.stderr)
            return
        print(f"{'ID':>4}  {'State':<10}  {'Messages':>8}  {'Start':<18}  {'End':<18}")
        print(f"{'─'*4}  {'─'*10}  {'─'*8}  {'─'*18}  {'─'*18}")
        for seg in segments:
            print(
                f"{seg['id']:>4}  {seg['state']:<10}  {seg['message_count']:>8}  "
                f"{_ts_to_datetime(seg['start_ts']):<18}  {_ts_to_datetime(seg['end_ts']):<18}"
            )
    finally:
        storage.close()


def _run_reset(args) -> None:
    from ir_tracker.storage import Storage

    storage = Storage(args.db)
    try:
        storage.clear_segments()
        print("Analyses and segments cleared. Messages retained.", file=sys.stderr)
    finally:
        storage.close()


def _run_serve(args) -> None:
    print("Web UI not yet implemented.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
