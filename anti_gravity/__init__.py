"""
PROJECT ANTI-GRAVITY
Advanced Financial Research Orchestrator & Market Intelligence Analyst

Monitors 53 financial YouTube channels across 9 segments, maintains a
persistent state ledger, extracts transcripts, and synthesizes "The Juice"
– a unified market intelligence dossier.
"""
from __future__ import annotations

from .orchestrator import AntiGravityOrchestrator
from .config import CHANNELS, SegmentID, Cadence, SEGMENT_NAMES

__all__ = ["AntiGravityOrchestrator", "CHANNELS", "SegmentID", "Cadence", "SEGMENT_NAMES"]
__version__ = "1.0.0"
