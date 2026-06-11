"""
YouTube Data API v3 wrapper for Project Anti-Gravity.

Resolves channel handles to channel IDs, fetches video metadata (title,
duration, publish date), and applies the 10-minute duration gate.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

try:
    from googleapiclient.discovery import build as _build
    from googleapiclient.errors import HttpError
    _HAS_YT_API = True
except ImportError:
    _HAS_YT_API = False
    logger.warning(
        "google-api-python-client not installed. "
        "Install with: pip install google-api-python-client"
    )


@dataclass
class VideoMetadata:
    video_id: str
    title: str
    channel_handle: str
    channel_name: str
    channel_id: str
    published_at: datetime
    duration_seconds: int
    url: str = field(init=False)

    def __post_init__(self) -> None:
        self.url = f"https://www.youtube.com/watch?v={self.video_id}"


# ISO 8601 duration parser (e.g. PT1H23M45S → 5025)
_DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def _parse_duration(iso_duration: str) -> int:
    m = _DURATION_RE.match(iso_duration)
    if not m:
        return 0
    h = int(m.group(1) or 0)
    mn = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    return h * 3600 + mn * 60 + s


class YouTubeClient:
    """Thin wrapper around the YouTube Data API v3."""

    def __init__(self, api_key: str) -> None:
        if not _HAS_YT_API:
            raise RuntimeError(
                "google-api-python-client is required. "
                "Run: pip install google-api-python-client"
            )
        self._yt = _build(
            "youtube", "v3", developerKey=api_key, cache_discovery=False
        )

    # ── Channel resolution ────────────────────────────────────────────────────

    def resolve_channel_id(self, handle: str) -> Optional[str]:
        """Map a @handle to its stable YouTube channel ID."""
        clean = handle.lstrip("@")
        try:
            resp = self._yt.channels().list(
                part="id",
                forHandle=clean,
            ).execute()
            items = resp.get("items", [])
            if items:
                return items[0]["id"]
            # Fallback: search by channel name
            resp2 = self._yt.search().list(
                part="snippet",
                q=clean,
                type="channel",
                maxResults=1,
            ).execute()
            items2 = resp2.get("items", [])
            if items2:
                return items2[0]["snippet"]["channelId"]
        except HttpError as exc:
            logger.error("resolve_channel_id(%s) failed: %s", handle, exc)
        return None

    # ── Video fetching ────────────────────────────────────────────────────────

    def fetch_new_videos(
        self,
        channel_id: str,
        channel_handle: str,
        channel_name: str,
        published_after: Optional[datetime] = None,
        max_results: int = 10,
    ) -> List[VideoMetadata]:
        """
        Return videos uploaded after `published_after` (UTC datetime).
        Includes full duration data.  Does NOT apply the 10-min filter here —
        that responsibility belongs to the orchestrator.
        """
        search_kwargs = {
            "part": "snippet",
            "channelId": channel_id,
            "type": "video",
            "order": "date",
            "maxResults": max_results,
        }
        if published_after:
            # YouTube API wants RFC 3339 with 'Z' suffix
            pa = published_after.astimezone(timezone.utc)
            search_kwargs["publishedAfter"] = pa.strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            search_resp = self._yt.search().list(**search_kwargs).execute()
        except HttpError as exc:
            logger.error("Video search failed for %s: %s", channel_handle, exc)
            return []

        video_ids = [
            item["id"]["videoId"]
            for item in search_resp.get("items", [])
            if item.get("id", {}).get("videoId")
        ]
        if not video_ids:
            return []

        # Second call: get duration from contentDetails
        try:
            details_resp = self._yt.videos().list(
                part="contentDetails,snippet",
                id=",".join(video_ids),
            ).execute()
        except HttpError as exc:
            logger.error("Video details fetch failed: %s", exc)
            return []

        results: List[VideoMetadata] = []
        for item in details_resp.get("items", []):
            vid_id = item["id"]
            snippet = item["snippet"]
            duration_secs = _parse_duration(
                item["contentDetails"].get("duration", "PT0S")
            )
            pub_str = snippet["publishedAt"]  # "2024-01-15T14:30:00Z"
            published_at = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))

            results.append(
                VideoMetadata(
                    video_id=vid_id,
                    title=snippet["title"],
                    channel_handle=channel_handle,
                    channel_name=channel_name,
                    channel_id=channel_id,
                    published_at=published_at,
                    duration_seconds=duration_secs,
                )
            )

        return results
