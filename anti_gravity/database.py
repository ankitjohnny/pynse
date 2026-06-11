"""
Persistent state ledger for Project Anti-Gravity.

Stores processed video IDs, channel run timestamps, and resolved channel IDs
in a local JSON file.  When a GoogleDriveClient is injected, the database is
also synced to Google Drive so state survives across machines and sessions.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class StateDatabase:
    """
    JSON-backed state ledger with optional Google Drive mirroring.

    Layout of the JSON document:
    {
        "_meta": { "last_updated": "<iso>", "last_run": "<iso>" },
        "processed_videos": { "<video_id>": { ...metadata... } },
        "channel_runs":     { "<handle>": "<iso>" },
        "channel_ids":      { "<handle>": "<channel_id>" }
    }
    """

    def __init__(
        self,
        local_path: str,
        drive_client=None,
        drive_filename: str = "anti_gravity_market_db.json",
    ):
        self.local_path = Path(local_path)
        self.drive_client = drive_client
        self.drive_filename = drive_filename
        self._data: Dict[str, Any] = {}
        self._load()

    # ── Loading ───────────────────────────────────────────────────────────────

    def _load(self) -> None:
        self.local_path.parent.mkdir(parents=True, exist_ok=True)

        if self.local_path.exists():
            try:
                with open(self.local_path, encoding="utf-8") as f:
                    self._data = json.load(f)
                logger.info(
                    "Loaded local ledger: %d processed videos",
                    self.get_processed_count(),
                )
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Corrupt local ledger (%s) — starting fresh.", exc)
                self._data = {}

        # If Google Drive has a newer copy, prefer it
        if self.drive_client:
            try:
                drive_data = self.drive_client.read_json(self.drive_filename)
                if drive_data:
                    drive_ts = drive_data.get("_meta", {}).get("last_updated", "")
                    local_ts = self._data.get("_meta", {}).get("last_updated", "")
                    if drive_ts > local_ts:
                        self._data = drive_data
                        logger.info(
                            "Using fresher Google Drive ledger (%s > %s)",
                            drive_ts[:19],
                            local_ts[:19] or "never",
                        )
            except Exception as exc:
                logger.warning("Google Drive load failed: %s", exc)

    # ── Saving ────────────────────────────────────────────────────────────────

    def _save(self) -> None:
        self._data.setdefault("_meta", {})["last_updated"] = (
            datetime.now(timezone.utc).isoformat()
        )
        with open(self.local_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, default=str)
        logger.debug("Saved local ledger → %s", self.local_path)

        if self.drive_client:
            try:
                self.drive_client.write_json(self.drive_filename, self._data)
                logger.info("Synced ledger to Google Drive")
            except Exception as exc:
                logger.warning("Google Drive sync failed: %s", exc)

    # ── Video tracking ────────────────────────────────────────────────────────

    def is_processed(self, video_id: str) -> bool:
        return video_id in self._data.get("processed_videos", {})

    def mark_processed(self, video_id: str, metadata: Dict[str, Any]) -> None:
        self._data.setdefault("processed_videos", {})[video_id] = {
            **metadata,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_processed_count(self) -> int:
        return len(self._data.get("processed_videos", {}))

    # ── Channel run tracking ──────────────────────────────────────────────────

    def get_channel_last_run(self, handle: str) -> Optional[datetime]:
        ts = self._data.get("channel_runs", {}).get(handle)
        return datetime.fromisoformat(ts) if ts else None

    def update_channel_run(self, handle: str) -> None:
        self._data.setdefault("channel_runs", {})[handle] = (
            datetime.now(timezone.utc).isoformat()
        )

    # ── Channel ID cache ──────────────────────────────────────────────────────

    def get_cached_channel_id(self, handle: str) -> Optional[str]:
        return self._data.get("channel_ids", {}).get(handle)

    def cache_channel_id(self, handle: str, channel_id: str) -> None:
        self._data.setdefault("channel_ids", {})[handle] = channel_id

    # ── Global run metadata ───────────────────────────────────────────────────

    def get_last_run_time(self) -> Optional[datetime]:
        ts = self._data.get("_meta", {}).get("last_run")
        return datetime.fromisoformat(ts) if ts else None

    def update_last_run(self) -> None:
        self._data.setdefault("_meta", {})["last_run"] = (
            datetime.now(timezone.utc).isoformat()
        )

    # ── Commit (call at end of a successful run) ──────────────────────────────

    def commit(self) -> None:
        self.update_last_run()
        self._save()
