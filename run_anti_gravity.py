#!/usr/bin/env python3
"""
PROJECT ANTI-GRAVITY
Advanced Financial Research Orchestrator & Market Intelligence Analyst

Monitors 53 financial YouTube channels across 9 segments, maintains a
differential state ledger, extracts transcripts, and synthesises "The Juice"
– a unified market intelligence dossier – on every run.

Quick start
-----------
  export YOUTUBE_API_KEY="AIza..."
  python run_anti_gravity.py

With Google Drive sync:
  python run_anti_gravity.py --gdrive --gdrive-credentials ~/.anti_gravity/gdrive_credentials.json

Force processing of all channels (including weekly ones):
  python run_anti_gravity.py --force-weekly

Verbose mode:
  python run_anti_gravity.py -v
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import textwrap


BANNER = r"""
  ___        _   _        ___               _ _
 / _ \      | | (_)      / _ \             (_) |
/ /_\ \ _ __| |_ _ _____/ /_\ \_ __  _ __  _| |_  _   _
|  _  || '_ \ __| |______  _  | '_ \| '_ \| | __|| | | |
| | | || | | | |_| |      | | | | | | | | | | |_ | |_| |
\_| |_/|_| |_|\__|_|      \_| |_/_| |_|_| |_|\__| \__, |
                                                     __/ |
              PROJECT ANTI-GRAVITY                  |___/
     Financial Market Intelligence Orchestrator v1.0
"""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_anti_gravity.py",
        description="Project Anti-Gravity: Financial Market Intelligence Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Environment variables:
              YOUTUBE_API_KEY   YouTube Data API v3 key (alternative to --yt-api-key)

            Examples:
              python run_anti_gravity.py --yt-api-key AIza...
              python run_anti_gravity.py --gdrive
              python run_anti_gravity.py --force-weekly -v
        """),
    )

    parser.add_argument(
        "--yt-api-key",
        metavar="KEY",
        default=os.environ.get("YOUTUBE_API_KEY", ""),
        help="YouTube Data API v3 key (or set $YOUTUBE_API_KEY)",
    )
    parser.add_argument(
        "--gdrive",
        action="store_true",
        help="Enable Google Drive sync for the state ledger",
    )
    parser.add_argument(
        "--gdrive-credentials",
        metavar="PATH",
        default=os.path.expanduser("~/.anti_gravity/gdrive_credentials.json"),
        help="Path to Google Drive OAuth 2.0 credentials JSON (default: ~/.anti_gravity/gdrive_credentials.json)",
    )
    parser.add_argument(
        "--force-weekly",
        action="store_true",
        help="Process weekly/weekend channels even if they ran less than 7 days ago",
    )
    parser.add_argument(
        "--data-dir",
        metavar="DIR",
        default=os.path.expanduser("~/.anti_gravity"),
        help="Directory for the local state ledger (default: ~/.anti_gravity)",
    )
    parser.add_argument(
        "--reports-dir",
        metavar="DIR",
        default=os.path.expanduser("~/.anti_gravity/reports"),
        help="Directory where reports are written (default: ~/.anti_gravity/reports)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging",
    )

    return parser.parse_args()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    # Quieten noisy third-party loggers unless verbose
    if not verbose:
        for noisy in ("googleapiclient", "google", "urllib3", "httplib2"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> int:
    args = _parse_args()
    _setup_logging(args.verbose)

    print(BANNER)

    # ── Validate YouTube API key ──────────────────────────────────────────────
    if not args.yt_api_key:
        print(
            "ERROR: YouTube Data API v3 key is required.\n"
            "  Pass --yt-api-key YOUR_KEY  or  export YOUTUBE_API_KEY=YOUR_KEY\n\n"
            "  Get a key at: https://console.cloud.google.com/apis/library/youtube.googleapis.com",
            file=sys.stderr,
        )
        return 1

    # ── Optional Google Drive client ──────────────────────────────────────────
    drive_client = None
    if args.gdrive:
        try:
            from anti_gravity.gdrive import GoogleDriveClient
            drive_client = GoogleDriveClient(credentials_path=args.gdrive_credentials)
            print(f"[+] Google Drive sync enabled (credentials: {args.gdrive_credentials})\n")
        except ImportError as exc:
            print(f"[!] Google Drive libraries not installed: {exc}", file=sys.stderr)
            print("    Run: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib\n")
        except Exception as exc:
            print(f"[!] Google Drive init failed: {exc}", file=sys.stderr)
            print("    Continuing with local-only storage.\n")

    # ── Build and run orchestrator ────────────────────────────────────────────
    from anti_gravity.orchestrator import AntiGravityOrchestrator

    orchestrator = AntiGravityOrchestrator(
        youtube_api_key=args.yt_api_key,
        drive_client=drive_client,
        data_dir=args.data_dir,
        reports_dir=args.reports_dir,
        force_weekly=args.force_weekly,
    )

    print("Initiating market intelligence sweep across 53 channels...\n")

    try:
        result = orchestrator.run()
    except Exception as exc:
        logging.exception("Fatal error during Anti-Gravity sweep: %s", exc)
        return 2

    # ── Print summary ─────────────────────────────────────────────────────────
    s = result["stats"]
    print()
    print("=" * 65)
    print("  ANTI-GRAVITY SWEEP COMPLETE")
    print("=" * 65)
    print(f"  Run timestamp:            {result['run_timestamp'][:19]} UTC")
    print(f"  Channels checked:         {s['channels_checked']}")
    print(f"  Channels skipped (cadence): {s['channels_skipped']}")
    print(f"  Videos scanned:           {s['videos_scanned']}")
    print(f"  Already processed:        {s['skipped_already_processed']}")
    print(f"  Filtered (< 10 min):      {s['skipped_too_short']}")
    print(f"  Newly processed:          {s['processed']}")
    print(f"  Without transcript:       {s['no_transcript']}")
    print(f"  Errors:                   {s['errors']}")
    print(f"  Numeric metrics retained: {result['total_numbers_extracted']}")
    print()

    if result["report_files"]:
        print(f"  Reports → {args.reports_dir}/")
        for f in result["report_files"]:
            print(f"    {os.path.basename(f)}")
    else:
        print("  No new videos processed — nothing to report.")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
