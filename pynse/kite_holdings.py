"""
Kite Connect integration for fetching holdings and performing sector rotation analysis.

Required env vars:
    KITE_API_KEY      - from Kite developer console
    KITE_ACCESS_TOKEN - generated daily after Kite login
"""

import os
import pickle
import datetime as dt
from typing import Optional

import pandas as pd
import numpy as np
import requests

try:
    from kiteconnect import KiteConnect
except ImportError:
    raise ImportError("Install kiteconnect: pip install kiteconnect")


# Priority-ordered sector mapping: first match wins (most specific sectors first)
SECTOR_PRIORITY = [
    ("NiftyPsuBank",     "PSU Banking"),
    ("NiftyPvtBank",     "Private Banking"),
    ("NiftyBank",        "Banking"),
    ("NiftyIt",          "Information Technology"),
    ("NiftyPharma",      "Pharmaceuticals"),
    ("NiftyAuto",        "Automobiles"),
    ("NiftyFmcg",        "FMCG"),
    ("NiftyMetal",       "Metals & Mining"),
    ("NiftyRealty",      "Real Estate"),
    ("NiftyMedia",       "Media"),
    ("NiftyEnergy",      "Energy"),
    ("NiftyFinService",  "Financial Services"),
    ("NiftyInfra",       "Infrastructure"),
    ("NiftyCommodities", "Commodities"),
    ("NiftyConsumption", "Consumption"),
    ("NiftyPse",         "Public Sector"),
    ("NiftyServSector",  "Services"),
    ("NiftyMnc",         "MNC"),
    ("Nifty50",          "Large Cap"),
    ("NiftyMidcap100",   "Mid Cap"),
    ("NiftySmlcap100",   "Small Cap"),
]

# NSE index names for fetching sector performance
SECTOR_INDEX_MAP = {
    "PSU Banking":            "NIFTY PSU BANK",
    "Private Banking":        "NIFTY PVT BANK",
    "Banking":                "NIFTY BANK",
    "Information Technology": "NIFTY IT",
    "Pharmaceuticals":        "NIFTY PHARMA",
    "Automobiles":            "NIFTY AUTO",
    "FMCG":                   "NIFTY FMCG",
    "Metals & Mining":        "NIFTY METAL",
    "Real Estate":            "NIFTY REALTY",
    "Media":                  "NIFTY MEDIA",
    "Energy":                 "NIFTY ENERGY",
    "Financial Services":     "NIFTY FIN SERVICE",
    "Infrastructure":         "NIFTY INFRA",
    "Commodities":            "NIFTY COMMODITIES",
    "Consumption":            "NIFTY CONSUMPTION",
    "Public Sector":          "NIFTY PSE",
    "Services":               "NIFTY SERV SECTOR",
    "MNC":                    "NIFTY MNC",
    "Large Cap":              "NIFTY 50",
    "Mid Cap":                "NIFTY MIDCAP 100",
    "Small Cap":              "NIFTY SMLCAP 100",
}


def _load_symbol_map() -> dict[str, str]:
    """Build stock → primary sector mapping from pynse symbol lists."""
    pkg_dir = os.path.dirname(__file__)
    symbol_list_dir = os.path.join(pkg_dir, "symbol_list")

    stock_sector: dict[str, str] = {}
    for pkl_name, sector_label in SECTOR_PRIORITY:
        path = os.path.join(symbol_list_dir, f"{pkl_name}.pkl")
        if not os.path.exists(path):
            continue
        with open(path, "rb") as f:
            symbols: list[str] = pickle.load(f)
        for sym in symbols:
            if sym not in stock_sector:
                stock_sector[sym] = sector_label
    return stock_sector


def get_kite_client(api_key: Optional[str] = None, access_token: Optional[str] = None) -> KiteConnect:
    api_key = api_key or os.environ.get("KITE_API_KEY")
    access_token = access_token or os.environ.get("KITE_ACCESS_TOKEN")
    if not api_key:
        raise ValueError("Set KITE_API_KEY env var or pass api_key")
    if not access_token:
        raise ValueError("Set KITE_ACCESS_TOKEN env var or pass access_token")
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    return kite


def fetch_holdings(kite: KiteConnect) -> pd.DataFrame:
    """Fetch holdings from Kite and return as DataFrame."""
    raw = kite.holdings()
    if not raw:
        return pd.DataFrame()

    df = pd.DataFrame(raw)
    cols = {
        "tradingsymbol": "symbol",
        "quantity":       "quantity",
        "average_price":  "avg_price",
        "last_price":     "ltp",
        "pnl":            "pnl",
        "day_change":     "day_change",
        "day_change_percentage": "day_chg_pct",
    }
    df = df.rename(columns=cols)
    keep = [c for c in cols.values() if c in df.columns]
    df = df[keep].copy()
    df["current_value"] = df["quantity"] * df["ltp"]
    df["invested_value"] = df["quantity"] * df["avg_price"]
    df["pnl_pct"] = ((df["ltp"] - df["avg_price"]) / df["avg_price"] * 100).round(2)
    return df


def _fetch_index_quote(index_name: str) -> Optional[dict]:
    """Fetch current + historical quotes for an NSE index via NSE website."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com",
    }
    session = requests.Session()
    session.get("https://www.nseindia.com", headers=headers, timeout=10)

    encoded = index_name.replace(" ", "%20")
    today = dt.date.today()
    from_date = (today - dt.timedelta(days=200)).strftime("%d-%m-%Y")
    to_date = today.strftime("%d-%m-%Y")

    url = (
        f"https://www.nseindia.com/api/historical/indicesHistory"
        f"?indexType={encoded}&from={from_date}&to={to_date}"
    )
    try:
        resp = session.get(url, headers=headers, timeout=15)
        data = resp.json()
        rows = data.get("data", {}).get("indexCloseOnlineRecords", [])
        if not rows:
            return None
        closes = [(r["EOD_TIMESTAMP"], float(r["EOD_CLOSE_INDEX_VAL"])) for r in rows]
        closes.sort(key=lambda x: x[0])
        return closes
    except Exception:
        return None


def _calc_return(closes: list, days: int) -> Optional[float]:
    """Return % change over last `days` calendar days."""
    if not closes or len(closes) < 2:
        return None
    today_close = closes[-1][1]
    cutoff = dt.date.today() - dt.timedelta(days=days)
    past = [c for c in closes if dt.datetime.strptime(c[0], "%d-%b-%Y").date() <= cutoff]
    if not past:
        return None
    past_close = past[-1][1]
    return round((today_close - past_close) / past_close * 100, 2)


def fetch_sector_performance(sectors: list[str]) -> pd.DataFrame:
    """Fetch NSE index performance for each sector over multiple timeframes."""
    records = []
    for sector in sectors:
        index_name = SECTOR_INDEX_MAP.get(sector)
        if not index_name:
            records.append({"sector": sector, "1W": None, "1M": None, "3M": None, "6M": None})
            continue
        closes = _fetch_index_quote(index_name)
        records.append({
            "sector": sector,
            "1W":  _calc_return(closes, 7),
            "1M":  _calc_return(closes, 30),
            "3M":  _calc_return(closes, 90),
            "6M":  _calc_return(closes, 180),
        })
    df = pd.DataFrame(records).set_index("sector")
    return df


def build_sector_allocation(holdings: pd.DataFrame, symbol_map: dict[str, str]) -> pd.DataFrame:
    """Map holdings to sectors and compute portfolio allocation."""
    holdings = holdings.copy()
    holdings["sector"] = holdings["symbol"].map(symbol_map).fillna("Other")

    total_value = holdings["current_value"].sum()
    alloc = (
        holdings.groupby("sector")
        .agg(
            stocks=("symbol", lambda x: ", ".join(sorted(x))),
            current_value=("current_value", "sum"),
            invested_value=("invested_value", "sum"),
            pnl=("pnl", "sum") if "pnl" in holdings.columns else ("current_value", "count"),
        )
        .reset_index()
    )
    alloc["weight_pct"] = (alloc["current_value"] / total_value * 100).round(2)
    alloc["sector_pnl_pct"] = (
        (alloc["current_value"] - alloc["invested_value"]) / alloc["invested_value"] * 100
    ).round(2)
    alloc = alloc.sort_values("weight_pct", ascending=False).reset_index(drop=True)
    return alloc


def _momentum_score(row: pd.Series) -> float:
    """Weighted momentum score: 40% × 1M + 35% × 3M + 25% × 6M."""
    weights = {"1M": 0.40, "3M": 0.35, "6M": 0.25}
    score = 0.0
    total_w = 0.0
    for k, w in weights.items():
        if row.get(k) is not None and not pd.isna(row[k]):
            score += w * row[k]
            total_w += w
    return round(score / total_w, 2) if total_w > 0 else float("nan")


def sector_rotation_analysis(
    api_key: Optional[str] = None,
    access_token: Optional[str] = None,
) -> dict:
    """
    Full pipeline: fetch holdings → map sectors → fetch NSE performance → rotation signals.
    Returns a dict with keys: holdings, allocation, sector_perf, rotation_signals.
    """
    kite = get_kite_client(api_key, access_token)
    symbol_map = _load_symbol_map()

    print("Fetching Kite holdings...")
    holdings = fetch_holdings(kite)
    if holdings.empty:
        print("No holdings found.")
        return {}

    allocation = build_sector_allocation(holdings, symbol_map)
    sectors_in_portfolio = allocation["sector"].tolist()

    print(f"Found {len(holdings)} holdings across {len(sectors_in_portfolio)} sectors.")
    print("Fetching NSE sector index performance (this may take ~30s)...")

    sector_perf = fetch_sector_performance(sectors_in_portfolio)

    # Add momentum score
    sector_perf["momentum_score"] = sector_perf.apply(_momentum_score, axis=1)

    # Merge allocation with performance
    rotation = allocation.merge(sector_perf.reset_index(), on="sector", how="left")
    rotation["momentum_score"] = rotation.apply(_momentum_score, axis=1)

    # Signal: compare portfolio weight vs momentum rank
    rotation["momentum_rank"] = rotation["momentum_score"].rank(ascending=False, method="min")
    rotation["weight_rank"] = rotation["weight_pct"].rank(ascending=False, method="min")
    rotation["rank_gap"] = rotation["weight_rank"] - rotation["momentum_rank"]

    def signal(row):
        if pd.isna(row["momentum_score"]):
            return "—"
        if row["rank_gap"] > 1.5:
            return "REDUCE  ▼"
        if row["rank_gap"] < -1.5:
            return "ADD     ▲"
        return "HOLD    ─"

    rotation["signal"] = rotation.apply(signal, axis=1)

    return {
        "holdings":         holdings,
        "allocation":       allocation,
        "sector_perf":      sector_perf,
        "rotation_signals": rotation,
    }


def print_report(result: dict) -> None:
    """Pretty-print the sector rotation report."""
    if not result:
        return

    holdings    = result["holdings"]
    allocation  = result["allocation"]
    perf        = result["sector_perf"]
    rotation    = result["rotation_signals"]

    total_invested = holdings["invested_value"].sum()
    total_current  = holdings["current_value"].sum()
    total_pnl      = total_current - total_invested
    total_pnl_pct  = total_pnl / total_invested * 100

    sep = "─" * 90

    print(f"\n{'═'*90}")
    print(f"  KITE PORTFOLIO  │  {len(holdings)} stocks  │  "
          f"Invested: ₹{total_invested:,.0f}  │  "
          f"Current: ₹{total_current:,.0f}  │  "
          f"P&L: ₹{total_pnl:+,.0f} ({total_pnl_pct:+.1f}%)")
    print(f"{'═'*90}")

    # ── Holdings table ──────────────────────────────────────────────────────
    print("\n📋 HOLDINGS\n" + sep)
    print(f"{'Symbol':<15}{'Qty':>6}{'Avg Price':>12}{'LTP':>12}{'Curr Value':>14}{'P&L%':>8}")
    print(sep)
    for _, r in holdings.sort_values("current_value", ascending=False).iterrows():
        print(f"{r['symbol']:<15}{int(r['quantity']):>6}{r['avg_price']:>12.2f}"
              f"{r['ltp']:>12.2f}{r['current_value']:>14,.0f}{r['pnl_pct']:>+7.1f}%")

    # ── Sector allocation ────────────────────────────────────────────────────
    print(f"\n📊 SECTOR ALLOCATION\n" + sep)
    print(f"{'Sector':<24}{'Weight':>8}{'Curr Value':>14}{'P&L%':>8}  {'Holdings'}")
    print(sep)
    for _, r in allocation.iterrows():
        print(f"{r['sector']:<24}{r['weight_pct']:>7.1f}%{r['current_value']:>14,.0f}"
              f"{r['sector_pnl_pct']:>+7.1f}%  {r['stocks']}")

    # ── Sector momentum ──────────────────────────────────────────────────────
    print(f"\n📈 SECTOR MOMENTUM (NSE Index Returns)\n" + sep)
    print(f"{'Sector':<24}{'1W':>7}{'1M':>7}{'3M':>7}{'6M':>7}{'Score':>8}")
    print(sep)
    for _, r in perf.sort_values("momentum_score", ascending=False).iterrows():
        def fmt(v):
            return f"{v:>+6.1f}%" if pd.notna(v) else f"{'N/A':>7}"
        print(f"{r.name:<24}{fmt(r['1W'])}{fmt(r['1M'])}{fmt(r['3M'])}{fmt(r['6M'])}"
              f"{r['momentum_score']:>+8.1f}" if pd.notna(r["momentum_score"]) else
              f"{r.name:<24}{fmt(r['1W'])}{fmt(r['1M'])}{fmt(r['3M'])}{fmt(r['6M'])}{'N/A':>8}")

    # ── Rotation signals ─────────────────────────────────────────────────────
    print(f"\n🔄 ROTATION SIGNALS\n" + sep)
    print(f"{'Sector':<24}{'Weight%':>8}{'Momentum':>10}{'Signal'}")
    print(sep)
    for _, r in rotation.sort_values("weight_pct", ascending=False).iterrows():
        score = f"{r['momentum_score']:>+9.1f}" if pd.notna(r["momentum_score"]) else f"{'N/A':>9}"
        print(f"{r['sector']:<24}{r['weight_pct']:>7.1f}%{score}  {r['signal']}")

    print(f"\n{'═'*90}")
    print("  Signal logic: REDUCE if portfolio-weight rank >> momentum rank  │  ADD if << │  HOLD otherwise")
    print(f"{'═'*90}\n")
