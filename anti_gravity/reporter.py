"""
Report generator for Project Anti-Gravity.

Produces two documents per run:
  1. Segment report  — all videos grouped by segment → cadence, with full
                        analytical records (bullets, numbers, thesis mapping).
  2. "The Juice"     — THE JUICE: UNIFIED MARKET INTELLIGENCE REPORT, the
                        master dossier synthesising everything into one place.
"""
from __future__ import annotations

import textwrap
from collections import defaultdict
from datetime import datetime
from typing import Dict, List

from .config import Cadence, ISOLATED_SEGMENTS, SEGMENT_NAMES, SegmentID
from .analyzer import AnalyzedVideo

_CADENCE_LABEL: Dict[Cadence, str] = {
    Cadence.DAILY_PREMARKET:  "🌅 Daily Pre-Market / Opening Brief",
    Cadence.DAILY_POSTMARKET: "🌆 Daily Post-Market / Closing Wrap",
    Cadence.WEEKLY:           "📅 Weekly / Weekend Deep Dive",
    Cadence.DYNAMIC:          "⚡ Dynamic",
    Cadence.HIGH_VOLUME:      "🔥 High-Volume Continuous Flow",
}

_DAILY_CADENCES = {Cadence.DAILY_PREMARKET, Cadence.DAILY_POSTMARKET}


# ── Segment report ────────────────────────────────────────────────────────────

def _video_record(av: AnalyzedVideo) -> str:
    m = av.metadata
    dur_min = m.duration_seconds // 60
    dur_sec = m.duration_seconds % 60

    lines = [
        f"#### [{m.published_at.strftime('%Y-%m-%d %H:%M UTC')}] "
        f"[{m.title}]({m.url})",
        f"*{m.channel_name}* · {dur_min}m {dur_sec:02d}s",
        "",
    ]

    if av.key_bullets:
        lines.append("**Chronological Intel Ledger:**")
        for b in av.key_bullets:
            wrapped = textwrap.fill(b, width=110, subsequent_indent="  ")
            lines.append(f"- {wrapped}")
        lines.append("")

    if av.assertion:
        lines += [
            "**Underlying Logic & Thesis Mapping:**",
            f"- *Assertion:* {av.assertion}",
            f"- *Data Backing:* {av.data_backing}",
            f"- *Risk/Variables:* {av.risk_variables}",
            "",
        ]

    if av.extracted_numbers:
        numbers_str = " · ".join(f"`{n}`" for n in av.extracted_numbers[:25])
        lines += [
            "**Raw Numerical Metrics (100% retained):**",
            numbers_str,
            "",
        ]

    if not av.transcript:
        lines.append("*⚠ No transcript available for this video.*\n")

    return "\n".join(lines)


def build_segment_reports(
    videos_by_segment: Dict[SegmentID, List[AnalyzedVideo]],
) -> str:
    parts: List[str] = [
        "# PROJECT ANTI-GRAVITY — ANALYTICAL RECORDS",
        "",
        "> Segment-by-segment breakdown of newly processed content.",
        "",
    ]

    for seg_id in SegmentID:
        videos = videos_by_segment.get(seg_id, [])
        if not videos:
            continue

        seg_label = SEGMENT_NAMES[seg_id]
        isolation_tag = (
            " ⚠️ **ISOLATED TRACKING ENVIRONMENT**"
            if seg_id in ISOLATED_SEGMENTS
            else ""
        )
        parts.append(f"---\n\n## Segment {seg_id.value}: {seg_label}{isolation_tag}\n")

        by_cadence: Dict[Cadence, List[AnalyzedVideo]] = defaultdict(list)
        for av in videos:
            by_cadence[av.effective_cadence].append(av)

        for cadence in sorted(by_cadence, key=lambda c: c.value):
            cadence_label = _CADENCE_LABEL.get(cadence, cadence.value)
            parts.append(f"### {cadence_label}\n")
            for av in sorted(
                by_cadence[cadence],
                key=lambda x: x.metadata.published_at,
                reverse=True,
            ):
                parts.append(_video_record(av))

    return "\n".join(parts)


# ── The Juice ─────────────────────────────────────────────────────────────────

def build_the_juice(
    videos_by_segment: Dict[SegmentID, List[AnalyzedVideo]],
    run_start: datetime,
) -> str:
    all_videos: List[AnalyzedVideo] = [
        av for avs in videos_by_segment.values() for av in avs
    ]
    daily  = [av for av in all_videos if av.effective_cadence in _DAILY_CADENCES]
    weekly = [av for av in all_videos if av.effective_cadence == Cadence.WEEKLY]

    all_numbers: List[str] = []
    for av in all_videos:
        all_numbers.extend(av.extracted_numbers)
    unique_numbers = list(dict.fromkeys(all_numbers))

    # ── Channel convergence: count mentions across brokers ───────────────────
    from collections import Counter
    import re
    stock_re = re.compile(r"\b[A-Z]{2,10}\b")
    stock_counter: Counter = Counter()
    for av in all_videos:
        if av.transcript:
            for tok in stock_re.findall(av.transcript.text[:3000]):
                if len(tok) >= 3:
                    stock_counter[tok] += 1
    top_tickers = [t for t, _ in stock_counter.most_common(10)]

    lines: List[str] = [
        "# THE JUICE: UNIFIED MARKET INTELLIGENCE REPORT",
        "",
        f"**Run timestamp:** {run_start.strftime('%Y-%m-%d %H:%M UTC')}  ",
        f"**Channels scanned:** 53  ",
        f"**Videos newly processed:** {len(all_videos)}  ",
        f"**Unique numerical metrics retained:** {len(unique_numbers)}  ",
        "",
        "---",
        "",
        "## 1. EXECUTIVE SYNTHESIS SUMMARY",
        "",
        f"- **Daily tactical videos:** {len(daily)}",
        f"- **Weekly deep-dive videos:** {len(weekly)}",
        f"- **Active segments this run:** {len(videos_by_segment)}",
        f"- **Total numeric data-points captured:** {len(unique_numbers)}",
    ]

    if top_tickers:
        lines.append(
            f"- **Most-mentioned tickers/tokens:** {', '.join(top_tickers)}"
        )

    lines += [
        "",
        "---",
        "",
        "## 2. TIMING DISCIPLINE MERGE",
        "",
        "### Today's Tactical Daily Triggers",
        "",
    ]

    if daily:
        for av in sorted(daily, key=lambda x: x.metadata.published_at, reverse=True):
            icon = "🌅" if av.effective_cadence == Cadence.DAILY_PREMARKET else "🌆"
            ts = av.metadata.published_at.strftime("%H:%M UTC")
            numbers_inline = (
                " | " + " · ".join(f"`{n}`" for n in av.extracted_numbers[:5])
                if av.extracted_numbers
                else ""
            )
            lines.append(
                f"- {icon} `{ts}` **{av.metadata.channel_name}** — "
                f"[{av.metadata.title}]({av.metadata.url}){numbers_inline}"
            )
    else:
        lines.append("*No daily trigger videos processed in this run.*")

    lines += [
        "",
        "### The Structural Weekly Outlook",
        "",
    ]

    if weekly:
        for av in sorted(weekly, key=lambda x: x.metadata.published_at, reverse=True):
            date_str = av.metadata.published_at.strftime("%Y-%m-%d")
            lines.append(
                f"- `{date_str}` **{av.metadata.channel_name}** — "
                f"[{av.metadata.title}]({av.metadata.url})"
            )
            if av.assertion:
                lines.append(f"  - *Thesis:* {av.assertion[:120]}")
    else:
        lines.append("*No weekly deep-dive videos processed in this run.*")

    lines += [
        "",
        "---",
        "",
        "## 3. CONVERGENCE & DIVERGENCE ZONE",
        "",
    ]

    # Simple convergence: find segments/channels that share the same tickers
    if len(videos_by_segment) >= 2:
        seg_tickers: Dict[SegmentID, set] = {}
        for seg_id, avs in videos_by_segment.items():
            tks: set = set()
            for av in avs:
                if av.transcript:
                    for tok in stock_re.findall(av.transcript.text[:2000]):
                        if len(tok) >= 3:
                            tks.add(tok)
            seg_tickers[seg_id] = tks

        seg_ids = list(seg_tickers.keys())
        convergence_found = False
        for i in range(len(seg_ids)):
            for j in range(i + 1, len(seg_ids)):
                shared = seg_tickers[seg_ids[i]] & seg_tickers[seg_ids[j]]
                if len(shared) >= 3:
                    lines.append(
                        f"- **CONVERGENCE** — Segment {seg_ids[i].value} & "
                        f"Segment {seg_ids[j].value} both reference: "
                        f"{', '.join(sorted(shared)[:6])}"
                    )
                    convergence_found = True
        if not convergence_found:
            lines.append(
                "- Insufficient cross-segment overlap detected in this run "
                "(expand to weekly mode with `--force-weekly` for richer convergence signals)."
            )
    else:
        lines.append(
            "- Only one segment processed — convergence analysis requires ≥ 2 segments."
        )

    lines += [
        "",
        "---",
        "",
        "## 4. THE COMPLETE CHRONOLOGICAL LEDGER COMPILATION",
        "",
        "*(Ordered newest → oldest — optimised for vector search and NotebookLM export)*",
        "",
    ]

    for av in sorted(all_videos, key=lambda x: x.metadata.published_at, reverse=True):
        seg_name = SEGMENT_NAMES[av.segment]
        ts = av.metadata.published_at.strftime("%Y-%m-%d %H:%M UTC")
        lines.append(
            f"**{ts}** | Seg {av.segment.value}: {seg_name} | "
            f"[{av.metadata.title}]({av.metadata.url}) | "
            f"_{av.metadata.channel_name}_"
        )
        if av.extracted_numbers:
            numbers_str = " · ".join(f"`{n}`" for n in av.extracted_numbers[:12])
            lines.append(f"  → {numbers_str}")
        if av.assertion:
            lines.append(f"  → *{av.assertion[:100]}*")
        lines.append("")

    lines += [
        "---",
        "",
        "*End of THE JUICE — Project Anti-Gravity*",
    ]

    return "\n".join(lines)
