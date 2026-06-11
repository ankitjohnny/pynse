"""
Main workflow engine for Project Anti-Gravity.

Executes the 4-step pipeline:
  Step 1 — Database reconciliation (load state ledger)
  Step 2 — Delta scanning (fetch only new, unprocessed videos per cadence)
  Step 3 — Transcript extraction + analysis
  Step 4 — Report generation (segment records + The Juice dossier)
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .analyzer import AnalyzedVideo, analyze_video
from .config import (
    CHANNELS,
    DAILY_CADENCES,
    DB_FILENAME,
    DATA_DIR,
    MAX_VIDEOS_PER_CHANNEL,
    MIN_VIDEO_DURATION_SECONDS,
    REPORTS_DIR,
    TRANSCRIPT_LANGUAGES,
    Cadence,
    Channel,
    SegmentID,
)
from .database import StateDatabase
from .reporter import build_segment_reports, build_the_juice
from .transcript import fetch_transcript
from .youtube_client import YouTubeClient

logger = logging.getLogger(__name__)


class AntiGravityOrchestrator:
    """
    Stateful, differential YouTube channel monitor and market intelligence
    synthesiser.

    Parameters
    ----------
    youtube_api_key : str
        YouTube Data API v3 key.
    drive_client : optional GoogleDriveClient
        When provided, the state ledger is mirrored to Google Drive.
    data_dir : str
        Local directory for the JSON state ledger and cache.
    reports_dir : str
        Directory where markdown report files are written.
    force_weekly : bool
        Process weekly channels even if they ran less than 7 days ago.
    channels : list[Channel]
        Override the default 53-channel roster for testing.
    """

    def __init__(
        self,
        youtube_api_key: str,
        drive_client=None,
        data_dir: str = DATA_DIR,
        reports_dir: str = REPORTS_DIR,
        force_weekly: bool = False,
        channels: Optional[List[Channel]] = None,
    ) -> None:
        self.db = StateDatabase(
            local_path=os.path.join(data_dir, DB_FILENAME),
            drive_client=drive_client,
            drive_filename=DB_FILENAME,
        )
        self.yt = YouTubeClient(api_key=youtube_api_key)
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.force_weekly = force_weekly
        self.channels = channels or CHANNELS

    # ── Cadence gate ──────────────────────────────────────────────────────────

    def _should_process_channel(self, channel: Channel) -> bool:
        """
        Daily / dynamic / high-volume channels → always check.
        Weekly channels    → skip if last run was < 7 days ago
                              (unless --force-weekly is set).
        """
        if channel.cadence in DAILY_CADENCES or self.force_weekly:
            return True
        last = self.db.get_channel_last_run(channel.handle)
        if last is None:
            return True
        return (datetime.now(timezone.utc) - last) >= timedelta(days=7)

    # ── Channel ID resolution (cached) ────────────────────────────────────────

    def _resolve_channel_id(self, channel: Channel) -> Optional[str]:
        cached = self.db.get_cached_channel_id(channel.handle)
        if cached:
            return cached
        channel_id = self.yt.resolve_channel_id(channel.handle)
        if channel_id:
            self.db.cache_channel_id(channel.handle, channel_id)
            logger.info("Resolved %s → %s", channel.handle, channel_id)
        else:
            logger.warning("Could not resolve channel ID for %s", channel.handle)
        return channel_id

    # ── Main entry point ──────────────────────────────────────────────────────

    def run(self) -> Dict[str, Any]:
        """
        Execute a full Anti-Gravity intelligence sweep.

        Returns a summary dict with stats and paths of written report files.
        """
        run_start = datetime.now(timezone.utc)
        logger.info("=== ANTI-GRAVITY SWEEP STARTED: %s ===", run_start.isoformat())
        logger.info(
            "Ledger state: %d previously processed videos",
            self.db.get_processed_count(),
        )

        videos_by_segment: Dict[SegmentID, List[AnalyzedVideo]] = defaultdict(list)
        stats: Dict[str, int] = {
            "channels_checked": 0,
            "channels_skipped": 0,
            "videos_scanned": 0,
            "skipped_already_processed": 0,
            "skipped_too_short": 0,
            "processed": 0,
            "no_transcript": 0,
            "errors": 0,
        }

        # ── STEP 1: Database reconciliation ──────────────────────────────────
        logger.info("STEP 1 — Database reconciliation complete")

        # ── STEP 2: Delta scanning ────────────────────────────────────────────
        logger.info("STEP 2 — Delta scanning across %d channels", len(self.channels))

        for channel in self.channels:
            if not self._should_process_channel(channel):
                logger.debug("Cadence gate: skipping %s", channel.handle)
                stats["channels_skipped"] += 1
                continue

            stats["channels_checked"] += 1
            channel_id = self._resolve_channel_id(channel)
            if not channel_id:
                stats["errors"] += 1
                continue

            last_run = self.db.get_channel_last_run(channel.handle)
            logger.info(
                "Scanning %-35s (last run: %s)",
                channel.handle,
                last_run.strftime("%Y-%m-%d") if last_run else "never",
            )

            try:
                raw_videos = self.yt.fetch_new_videos(
                    channel_id=channel_id,
                    channel_handle=channel.handle,
                    channel_name=channel.display_name,
                    published_after=last_run,
                    max_results=MAX_VIDEOS_PER_CHANNEL,
                )
            except Exception as exc:
                logger.error("Fetch failed for %s: %s", channel.handle, exc)
                stats["errors"] += 1
                continue

            stats["videos_scanned"] += len(raw_videos)

            # ── STEP 3: Filter → transcript → analyse ─────────────────────
            for video in raw_videos:
                # Differential: skip already-processed
                if self.db.is_processed(video.video_id):
                    stats["skipped_already_processed"] += 1
                    continue

                # Duration gate: > 10 minutes only
                if video.duration_seconds < MIN_VIDEO_DURATION_SECONDS:
                    logger.debug(
                        "Dropped short video (%dm %ds): %s",
                        video.duration_seconds // 60,
                        video.duration_seconds % 60,
                        video.title[:60],
                    )
                    stats["skipped_too_short"] += 1
                    continue

                logger.info(
                    "  [%s] Extracting transcript: %s",
                    channel.handle,
                    video.title[:70],
                )
                transcript = fetch_transcript(video.video_id, TRANSCRIPT_LANGUAGES)
                if transcript is None:
                    stats["no_transcript"] += 1

                analyzed = analyze_video(
                    metadata=video,
                    transcript=transcript,
                    segment=channel.segment,
                    base_cadence=channel.cadence,
                )
                videos_by_segment[channel.segment].append(analyzed)

                self.db.mark_processed(
                    video.video_id,
                    {
                        "title": video.title,
                        "channel": channel.handle,
                        "segment": channel.segment.value,
                        "published_at": video.published_at.isoformat(),
                        "duration_seconds": video.duration_seconds,
                        "had_transcript": transcript is not None,
                        "numbers_extracted": len(analyzed.extracted_numbers),
                    },
                )
                stats["processed"] += 1

            self.db.update_channel_run(channel.handle)

        # Commit updated ledger (local + Drive)
        self.db.commit()
        logger.info("STEP 3 — Processing complete. Stats: %s", stats)

        # ── STEP 4: Report generation ─────────────────────────────────────────
        report_files = self._write_reports(videos_by_segment, run_start)
        logger.info("STEP 4 — Reports written: %s", report_files)

        return {
            "stats": stats,
            "segments_with_data": [s.value for s in videos_by_segment],
            "report_files": report_files,
            "run_timestamp": run_start.isoformat(),
            "total_numbers_extracted": sum(
                len(av.extracted_numbers)
                for avs in videos_by_segment.values()
                for av in avs
            ),
        }

    def _write_reports(
        self,
        videos_by_segment: Dict[SegmentID, List[AnalyzedVideo]],
        run_start: datetime,
    ) -> List[str]:
        ts = run_start.strftime("%Y%m%d_%H%M%S")
        files: List[str] = []

        # Segment analytical records
        seg_md = build_segment_reports(videos_by_segment)
        seg_path = self.reports_dir / f"anti_gravity_segments_{ts}.md"
        seg_path.write_text(seg_md, encoding="utf-8")
        files.append(str(seg_path))

        # The Juice master dossier
        juice_md = build_the_juice(videos_by_segment, run_start)
        juice_path = self.reports_dir / f"THE_JUICE_{ts}.md"
        juice_path.write_text(juice_md, encoding="utf-8")
        files.append(str(juice_path))

        return files
