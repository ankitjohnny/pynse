"""
Content analysis engine for Project Anti-Gravity.

Classifies video cadence, extracts all financial numerical metrics with
zero data loss, and generates tight bullet-point summaries from transcripts.
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from .config import Cadence, SegmentID
from .youtube_client import VideoMetadata
from .transcript import Transcript

logger = logging.getLogger(__name__)

# ── Cadence inference keywords ────────────────────────────────────────────────
_PRE_MARKET_RE = re.compile(
    r"pre.?market|pre.?open|opening bell|global cues|gift nifty|sgx nifty"
    r"|morning brief|before market|global markets|overnight|asia open"
    r"|dow futures|nasdaq futures|us markets|wall street",
    re.IGNORECASE,
)
_POST_MARKET_RE = re.compile(
    r"post.?market|closing|after market|end of day|eod|market wrap"
    r"|today.?s market|nifty closed|sensex closed|block deals|bulk deals"
    r"|derivative|options data|oi data|put call ratio|pcr|open interest",
    re.IGNORECASE,
)

# ── Financial number extraction patterns ──────────────────────────────────────
# Goal: capture EVERY metric mentioned — percentages, basis points, index levels,
# price targets, support/resistance, P/E, OI, FII/DII flows, sector metrics.
_FINANCIAL_PATTERNS = [
    # Percentages and basis points
    r"\b\d+(?:\.\d+)?\s*(?:%|percent|bps|basis points?)\b",
    # Indian currency with scale
    r"(?:Rs\.?|INR|₹)\s*\d[\d,]*(?:\.\d+)?(?:\s*(?:crore|lakh|thousand|cr|L|k|M|B|mn|bn))?\b",
    # Bare numbers with Indian scale
    r"\b\d[\d,]*(?:\.\d+)?\s*(?:crore|lakh|cr)\b",
    # P/E ratio
    r"\bP/?E\s*(?:of|ratio|:)?\s*\d+(?:\.\d+)?\b",
    # Nifty / Sensex levels
    r"\bNifty\s+\d{3,6}(?:\.\d+)?\b",
    r"\bSensex\s+\d{4,6}(?:\.\d+)?\b",
    # Support / resistance / target levels
    r"\b\d{3,6}(?:\.\d+)?\s*(?:support|resistance|target|level|pts|points)\b",
    r"\b(?:support|resistance|target)\s+(?:at|of|@)?\s*\d{3,6}(?:\.\d+)?\b",
    # Open interest
    r"\b(?:OI|open interest)\s+(?:of|at|:)?\s*\d[\d,]*(?:\s*(?:lakh|cr|contracts))?\b",
    # FII / DII flows
    r"\bFII\s+(?:bought|sold|net|inflow|outflow)\s+(?:Rs\.?|₹)?\s*\d[\d,]*(?:\s*(?:crore|cr|Cr))?\b",
    r"\bDII\s+(?:bought|sold|net|inflow|outflow)\s+(?:Rs\.?|₹)?\s*\d[\d,]*(?:\s*(?:crore|cr|Cr))?\b",
    # Price targets with stock context (number followed by "target" etc.)
    r"(?:price target|PT|TP)\s*(?:of|:)?\s*(?:Rs\.?|₹)?\s*\d[\d,]*(?:\.\d+)?\b",
    # EPS / dividend
    r"\bEPS\s+(?:of|:)?\s*(?:Rs\.?|₹)?\s*\d+(?:\.\d+)?\b",
    r"\bdividend\s+(?:of|:)?\s*(?:Rs\.?|₹)?\s*\d+(?:\.\d+)?\b",
    # Volume in crore / lakh shares
    r"\b\d[\d,]*(?:\.\d+)?\s*(?:lakh|crore)\s+(?:shares|units|contracts)\b",
    # IV / volatility
    r"\bIV\s*(?:at|of|:)?\s*\d+(?:\.\d+)?\s*%?\b",
    r"\bVIX\s+(?:at|of|:)?\s*\d+(?:\.\d+)?\b",
]
_FINANCIAL_RE = re.compile(
    "|".join(_FINANCIAL_PATTERNS), re.IGNORECASE
)


@dataclass
class AnalyzedVideo:
    metadata: VideoMetadata
    transcript: Optional[Transcript]
    segment: SegmentID
    effective_cadence: Cadence
    extracted_numbers: List[str] = field(default_factory=list)
    key_bullets: List[str] = field(default_factory=list)
    assertion: str = ""          # Core market claim
    data_backing: str = ""       # Numerical evidence
    risk_variables: str = ""     # Flagged risks / dependencies


def _infer_cadence(video: VideoMetadata, base_cadence: Cadence) -> Cadence:
    """
    Refine DYNAMIC cadence to PRE or POST based on title keywords and
    publish day.  All other cadences are returned unchanged.
    """
    if base_cadence != Cadence.DYNAMIC:
        return base_cadence

    title = video.title
    if _PRE_MARKET_RE.search(title):
        return Cadence.DAILY_PREMARKET
    if _POST_MARKET_RE.search(title):
        return Cadence.DAILY_POSTMARKET
    # Weekday → treat as daily; weekend → weekly deep dive
    if video.published_at.weekday() < 5:
        return Cadence.DAILY_POSTMARKET
    return Cadence.WEEKLY


def _extract_numbers(text: str) -> List[str]:
    """Return all unique financial metrics found in text, order-preserved."""
    seen: dict = {}
    for match in _FINANCIAL_RE.finditer(text):
        val = match.group().strip()
        if val not in seen:
            seen[val] = None
    return list(seen.keys())


def _generate_bullets(text: str, max_bullets: int = 10) -> List[str]:
    """
    Split transcript into sentence-level bullet points.
    Skips fragments shorter than 60 characters (low signal noise).
    """
    sentences = re.split(r"(?<=[.!?])\s+", text)
    bullets: List[str] = []
    for sent in sentences:
        sent = sent.strip()
        if len(sent) >= 60:
            bullets.append(sent)
        if len(bullets) >= max_bullets:
            break
    return bullets


def _extract_thesis(text: str, numbers: List[str]) -> tuple[str, str, str]:
    """
    Derive a rough (assertion, data_backing, risk_variables) triple from text.
    This is a heuristic approximation — works best with clean English transcripts.
    """
    # Assertion: first sentence that contains a market opinion keyword
    opinion_re = re.compile(
        r"\b(bullish|bearish|buy|sell|target|outperform|underperform|upside|downside"
        r"|breakout|breakdown|rally|correction|consolidation|accumulate|avoid)\b",
        re.IGNORECASE,
    )
    assertion = ""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sent in sentences:
        if opinion_re.search(sent) and len(sent) >= 40:
            assertion = sent.strip()
            break

    data_backing = "; ".join(numbers[:8]) if numbers else "No numerical data extracted"

    # Risk signals
    risk_re = re.compile(
        r"\b(risk|concern|caution|watch out|caveat|if|unless|provided|assuming"
        r"|subject to|geopolit|inflation|rate hike|global|volatility)\b",
        re.IGNORECASE,
    )
    risk_sentences: List[str] = []
    for sent in sentences:
        if risk_re.search(sent) and len(sent) >= 40:
            risk_sentences.append(sent.strip())
        if len(risk_sentences) >= 3:
            break
    risk_variables = " | ".join(risk_sentences) if risk_sentences else "None flagged"

    return assertion, data_backing, risk_variables


def analyze_video(
    metadata: VideoMetadata,
    transcript: Optional[Transcript],
    segment: SegmentID,
    base_cadence: Cadence,
) -> AnalyzedVideo:
    effective_cadence = _infer_cadence(metadata, base_cadence)

    extracted_numbers: List[str] = []
    key_bullets: List[str] = []
    assertion = data_backing = risk_variables = ""

    if transcript and transcript.text:
        extracted_numbers = _extract_numbers(transcript.text)
        key_bullets       = _generate_bullets(transcript.text)
        assertion, data_backing, risk_variables = _extract_thesis(
            transcript.text, extracted_numbers
        )
        logger.debug(
            "Analyzed '%s': %d numbers, %d bullets",
            metadata.title[:50],
            len(extracted_numbers),
            len(key_bullets),
        )

    return AnalyzedVideo(
        metadata=metadata,
        transcript=transcript,
        segment=segment,
        effective_cadence=effective_cadence,
        extracted_numbers=extracted_numbers,
        key_bullets=key_bullets,
        assertion=assertion,
        data_backing=data_backing,
        risk_variables=risk_variables,
    )
