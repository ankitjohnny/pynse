"""
Channel roster, segment definitions, and runtime constants for Project Anti-Gravity.
All 53 channels are defined here with their segment classification and cadence.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Set


class Cadence(Enum):
    DAILY_PREMARKET  = "Daily Pre-Market"
    DAILY_POSTMARKET = "Daily Post-Market"
    WEEKLY           = "Weekly/Weekend Deep Dive"
    DYNAMIC          = "Dynamic (Daily + Weekly)"
    HIGH_VOLUME      = "High Volume Data-Driven"


class SegmentID(Enum):
    SEG1_NEWS            = 1
    SEG2_BROKERAGE       = 2
    SEG3_MACRO           = 3
    SEG4_TECHNICAL       = 4
    SEG5_DERIVATIVES     = 5
    SEG6_PERSONAL_FINANCE = 6
    SEG7_CORPORATE       = 7
    SEG8_DATA_ANALYTICS  = 8
    SEG9_TRENDLYNE       = 9


SEGMENT_NAMES = {
    SegmentID.SEG1_NEWS:             "Mainstream Financial News & Live Media Flow",
    SegmentID.SEG2_BROKERAGE:        "Brokerage & Institutional Market Research",
    SegmentID.SEG3_MACRO:            "Macroeconomics, Global Asset Flow & Geopolitics",
    SegmentID.SEG4_TECHNICAL:        "Technical Analysis, Price Action & Market Dynamics",
    SegmentID.SEG5_DERIVATIVES:      "Derivatives, Options Trading & Volatility Tactics",
    SegmentID.SEG6_PERSONAL_FINANCE: "Personal Finance, Wealth Management & Asset Allocation",
    SegmentID.SEG7_CORPORATE:        "Corporate Tracking, Fundamental Analysis & Startup Themes",
    SegmentID.SEG8_DATA_ANALYTICS:   "Data Analytics & Quantitative Frameworks",
    SegmentID.SEG9_TRENDLYNE:        "Trendlyne Special Intelligence",
}

# Segments that require isolated processing environments (no cross-mixing)
ISOLATED_SEGMENTS: Set[SegmentID] = {
    SegmentID.SEG1_NEWS,       # Hard news isolation
    SegmentID.SEG9_TRENDLYNE,  # Standalone exclusive deep-dive
}


@dataclass
class Channel:
    handle: str          # e.g. "@cnbcawaaz"
    display_name: str
    segment: SegmentID
    cadence: Cadence
    # Resolved at runtime from YouTube API and cached in the state DB
    channel_id: Optional[str] = field(default=None, repr=False)

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/{self.handle}"


# ─────────────────────────────────────────────────────────────────────────────
# THE COMPLETE 53-CHANNEL ROSTER
# ─────────────────────────────────────────────────────────────────────────────
CHANNELS: list[Channel] = [

    # ── SEGMENT 1: MAINSTREAM NEWS (ISOLATED, DAILY) ─────────────────────────
    Channel("@cnbcawaaz",        "CNBC Awaaz",          SegmentID.SEG1_NEWS, Cadence.DAILY_PREMARKET),
    Channel("@CNBC-TV18",        "CNBC TV18",           SegmentID.SEG1_NEWS, Cadence.DAILY_PREMARKET),
    Channel("@livemint",         "Livemint",            SegmentID.SEG1_NEWS, Cadence.DAILY_PREMARKET),
    Channel("@Money9live",       "Money9 Live",         SegmentID.SEG1_NEWS, Cadence.DAILY_PREMARKET),
    Channel("@TheEconomicTimes", "The Economic Times",  SegmentID.SEG1_NEWS, Cadence.DAILY_PREMARKET),

    # ── SEGMENT 2: BROKERAGE (DYNAMIC: DAILY BRIEFS + WEEKLY DEEP DIVES) ─────
    Channel("@marketsbyzerodha",       "Markets by Zerodha",       SegmentID.SEG2_BROKERAGE, Cadence.DYNAMIC),
    Channel("@marketsbyzerodhahindi",  "Markets by Zerodha Hindi", SegmentID.SEG2_BROKERAGE, Cadence.DYNAMIC),
    Channel("@_sbisecurities",         "SBI Securities",           SegmentID.SEG2_BROKERAGE, Cadence.DYNAMIC),
    Channel("@HDFCsecuritiesofficial", "HDFC Securities",          SegmentID.SEG2_BROKERAGE, Cadence.DYNAMIC),
    Channel("@angelone",               "Angel One",                SegmentID.SEG2_BROKERAGE, Cadence.DYNAMIC),
    Channel("@MarketsByMO",            "Markets by MO",            SegmentID.SEG2_BROKERAGE, Cadence.DYNAMIC),
    Channel("@mstock_in",              "mStock",                   SegmentID.SEG2_BROKERAGE, Cadence.DYNAMIC),
    Channel("@MOFSL",                  "MOFSL",                    SegmentID.SEG2_BROKERAGE, Cadence.DYNAMIC),
    Channel("@kotakneo",               "Kotak Neo",                SegmentID.SEG2_BROKERAGE, Cadence.DYNAMIC),

    # ── SEGMENT 3: MACRO / GEOPOLITICS (WEEKLY) ──────────────────────────────
    Channel("@AngelOneEconomics", "Angel One Economics",  SegmentID.SEG3_MACRO, Cadence.WEEKLY),
    Channel("@BusinessInsider",   "Business Insider",     SegmentID.SEG3_MACRO, Cadence.WEEKLY),
    Channel("@markets",           "Bloomberg Markets",    SegmentID.SEG3_MACRO, Cadence.WEEKLY),
    Channel("@mebfabershow",      "Meb Faber Show",       SegmentID.SEG3_MACRO, Cadence.WEEKLY),
    Channel("@TheEconomist",      "The Economist",        SegmentID.SEG3_MACRO, Cadence.WEEKLY),
    Channel("@wsj",               "Wall Street Journal",  SegmentID.SEG3_MACRO, Cadence.WEEKLY),
    Channel("@blackstonegroup",   "Blackstone Group",     SegmentID.SEG3_MACRO, Cadence.WEEKLY),

    # ── SEGMENT 4: TECHNICAL ANALYSIS (DAILY POST-MARKET) ────────────────────
    Channel("@Anantladhaofficial", "Anant Ladha",          SegmentID.SEG4_TECHNICAL, Cadence.DAILY_POSTMARKET),
    Channel("@wealthsagaofficial", "WealthSaga",           SegmentID.SEG4_TECHNICAL, Cadence.DAILY_POSTMARKET),
    Channel("@indiacharts",        "India Charts",         SegmentID.SEG4_TECHNICAL, Cadence.DAILY_POSTMARKET),
    Channel("@AngelOneMarkets",    "Angel One Markets",    SegmentID.SEG4_TECHNICAL, Cadence.DAILY_POSTMARKET),
    Channel("@TradingwithGroww",   "Trading with Groww",   SegmentID.SEG4_TECHNICAL, Cadence.DAILY_POSTMARKET),
    Channel("@TradeWithAngelOne",  "Trade with Angel One", SegmentID.SEG4_TECHNICAL, Cadence.DAILY_POSTMARKET),

    # ── SEGMENT 5: DERIVATIVES / OPTIONS (DAILY POST-MARKET) ─────────────────
    Channel("@InTheMoneybyZerodha", "In The Money by Zerodha", SegmentID.SEG5_DERIVATIVES, Cadence.DAILY_POSTMARKET),
    Channel("@BeSensibull",         "Sensibull",               SegmentID.SEG5_DERIVATIVES, Cadence.DAILY_POSTMARKET),
    Channel("@DhanHQ",              "Dhan HQ",                 SegmentID.SEG5_DERIVATIVES, Cadence.DAILY_POSTMARKET),

    # ── SEGMENT 6: PERSONAL FINANCE (WEEKLY) ─────────────────────────────────
    Channel("@AUTheBonus",          "AU The Bonus",          SegmentID.SEG6_PERSONAL_FINANCE, Cadence.WEEKLY),
    Channel("@zerodhaonline",       "Zerodha Online",        SegmentID.SEG6_PERSONAL_FINANCE, Cadence.WEEKLY),
    Channel("@ThrivebyGroww",       "Thrive by Groww",       SegmentID.SEG6_PERSONAL_FINANCE, Cadence.WEEKLY),
    Channel("@Zero1byZerodha",      "Zero1 by Zerodha",      SegmentID.SEG6_PERSONAL_FINANCE, Cadence.WEEKLY),
    Channel("@UpstoxOfficial",      "Upstox Official",       SegmentID.SEG6_PERSONAL_FINANCE, Cadence.WEEKLY),
    Channel("@InvestwithMarcellus", "Invest with Marcellus", SegmentID.SEG6_PERSONAL_FINANCE, Cadence.WEEKLY),
    Channel("@Groww",               "Groww",                 SegmentID.SEG6_PERSONAL_FINANCE, Cadence.WEEKLY),
    Channel("@etmoneyhindi",        "ET Money Hindi",        SegmentID.SEG6_PERSONAL_FINANCE, Cadence.WEEKLY),
    Channel("@themoneypodcast91",   "The Money Podcast",     SegmentID.SEG6_PERSONAL_FINANCE, Cadence.WEEKLY),
    Channel("@valueresearchvideo",  "Value Research",        SegmentID.SEG6_PERSONAL_FINANCE, Cadence.WEEKLY),

    # ── SEGMENT 7: CORPORATE / FUNDAMENTAL (WEEKLY) ──────────────────────────
    Channel("@backstagewithmillionaires", "Backstage with Millionaires", SegmentID.SEG7_CORPORATE, Cadence.WEEKLY),
    Channel("@businessWithBansal",        "Business with Bansal",        SegmentID.SEG7_CORPORATE, Cadence.WEEKLY),
    Channel("@Howtheymadeitbygroww",      "How They Made It by Groww",   SegmentID.SEG7_CORPORATE, Cadence.WEEKLY),
    Channel("@InvestingWithUpsurge",      "Investing with Upsurge",      SegmentID.SEG7_CORPORATE, Cadence.WEEKLY),
    Channel("@StockEdge",                 "StockEdge",                   SegmentID.SEG7_CORPORATE, Cadence.WEEKLY),
    Channel("@AngelOneforInvestors",      "Angel One for Investors",     SegmentID.SEG7_CORPORATE, Cadence.WEEKLY),
    Channel("@InvestingwithDhan",         "Investing with Dhan",         SegmentID.SEG7_CORPORATE, Cadence.WEEKLY),
    Channel("@iporeviewbygroww",          "IPO Review by Groww",         SegmentID.SEG7_CORPORATE, Cadence.WEEKLY),
    Channel("@rainmatterin",              "Rainmatter",                  SegmentID.SEG7_CORPORATE, Cadence.WEEKLY),
    Channel("@G2GAjaySharma",             "G2G Ajay Sharma",             SegmentID.SEG7_CORPORATE, Cadence.WEEKLY),

    # ── SEGMENT 8: DATA ANALYTICS (WEEKLY) ───────────────────────────────────
    Channel("@AngelOneBytes",   "Angel One Bytes",  SegmentID.SEG8_DATA_ANALYTICS, Cadence.WEEKLY),
    Channel("@Analyticsvidhya", "Analytics Vidhya", SegmentID.SEG8_DATA_ANALYTICS, Cadence.WEEKLY),

    # ── SEGMENT 9: TRENDLYNE (ISOLATED, HIGH VOLUME) ─────────────────────────
    Channel("@trendlyne", "Trendlyne", SegmentID.SEG9_TRENDLYNE, Cadence.HIGH_VOLUME),
]

# Cadences that must be checked on every daily run
DAILY_CADENCES = {
    Cadence.DAILY_PREMARKET,
    Cadence.DAILY_POSTMARKET,
    Cadence.DYNAMIC,
    Cadence.HIGH_VOLUME,
}

# ─── Runtime constants ────────────────────────────────────────────────────────
MIN_VIDEO_DURATION_SECONDS = 600   # Drop anything under 10 minutes
MAX_VIDEOS_PER_CHANNEL     = 10    # YouTube API search results per channel
TRANSCRIPT_LANGUAGES       = ["en", "en-IN", "hi"]

DB_FILENAME   = "anti_gravity_market_db.json"
DATA_DIR      = os.path.expanduser("~/.anti_gravity")
REPORTS_DIR   = os.path.expanduser("~/.anti_gravity/reports")
