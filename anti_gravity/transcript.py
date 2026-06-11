"""
Transcript extraction for Project Anti-Gravity.

Uses the youtube-transcript-api library (no authentication required) to pull
auto-generated and manual captions.  Prefers English, falls back to Hindi,
and finally accepts any available language.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

try:
    from youtube_transcript_api import (
        NoTranscriptFound,
        TranscriptsDisabled,
        YouTubeTranscriptApi,
    )
    _HAS_TRANSCRIPT_API = True
except ImportError:
    _HAS_TRANSCRIPT_API = False
    logger.warning(
        "youtube-transcript-api not installed. "
        "Run: pip install youtube-transcript-api"
    )


@dataclass
class Transcript:
    video_id: str
    language: str
    text: str
    is_auto_generated: bool

    @property
    def word_count(self) -> int:
        return len(self.text.split())


def fetch_transcript(
    video_id: str,
    preferred_languages: Optional[List[str]] = None,
) -> Optional[Transcript]:
    """
    Fetch the best available transcript for a YouTube video.

    Priority: manual transcripts in preferred languages → auto-generated in
    preferred languages → any available transcript.
    """
    if not _HAS_TRANSCRIPT_API:
        return None

    if preferred_languages is None:
        preferred_languages = ["en", "en-IN", "hi"]

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
    except TranscriptsDisabled:
        logger.debug("Transcripts disabled for %s", video_id)
        return None
    except NoTranscriptFound:
        logger.debug("No transcript found for %s", video_id)
        return None
    except Exception as exc:
        logger.warning("Transcript list failed for %s: %s", video_id, exc)
        return None

    def _fetch(t) -> Transcript:
        entries = t.fetch()
        text = " ".join(e.get("text", "") for e in entries)
        return Transcript(
            video_id=video_id,
            language=t.language_code,
            text=text,
            is_auto_generated=t.is_generated,
        )

    # 1. Manual transcripts in preferred order
    for lang in preferred_languages:
        try:
            t = transcript_list.find_manually_created_transcript([lang])
            result = _fetch(t)
            logger.debug(
                "Got manual %s transcript for %s (%d words)",
                lang, video_id, result.word_count,
            )
            return result
        except Exception:
            pass

    # 2. Auto-generated in preferred order
    for lang in preferred_languages:
        try:
            t = transcript_list.find_generated_transcript([lang])
            result = _fetch(t)
            logger.debug(
                "Got auto %s transcript for %s (%d words)",
                lang, video_id, result.word_count,
            )
            return result
        except Exception:
            pass

    # 3. Accept anything available
    try:
        t = next(iter(transcript_list))
        result = _fetch(t)
        logger.debug(
            "Got fallback %s transcript for %s (%d words)",
            t.language_code, video_id, result.word_count,
        )
        return result
    except Exception as exc:
        logger.warning("All transcript strategies failed for %s: %s", video_id, exc)
        return None
