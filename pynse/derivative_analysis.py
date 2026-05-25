"""
Derivative analysis module for Nifty and Bank Nifty.
Covers option chain analysis, OI buildup, PCR, max pain,
FII/DII positioning, and macro-economic signals.
"""
import datetime as dt
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


# ─── Option chain helpers ────────────────────────────────────────────────────

def parse_option_chain(oc: pd.DataFrame) -> pd.DataFrame:
    """Flatten the nested option_chain DataFrame returned by Nse.option_chain()."""
    rows = []
    for _, row in oc.iterrows():
        strike = row.get("strikePrice", row.get("CE.strikePrice", None))
        expiry = row.get("expiryDate", None)

        ce = {}
        pe = {}
        for col in row.index:
            if col.startswith("CE."):
                ce[col[3:]] = row[col]
            elif col.startswith("PE."):
                pe[col[3:]] = row[col]

        rows.append({
            "strike": strike,
            "expiry": expiry,
            "ce_oi": ce.get("openInterest", 0),
            "ce_chg_oi": ce.get("changeinOpenInterest", 0),
            "ce_vol": ce.get("totalTradedVolume", 0),
            "ce_iv": ce.get("impliedVolatility", np.nan),
            "ce_ltp": ce.get("lastPrice", np.nan),
            "ce_bid": ce.get("bidprice", np.nan),
            "ce_ask": ce.get("askPrice", np.nan),
            "pe_oi": pe.get("openInterest", 0),
            "pe_chg_oi": pe.get("changeinOpenInterest", 0),
            "pe_vol": pe.get("totalTradedVolume", 0),
            "pe_iv": pe.get("impliedVolatility", np.nan),
            "pe_ltp": pe.get("lastPrice", np.nan),
            "pe_bid": pe.get("bidprice", np.nan),
            "pe_ask": pe.get("askPrice", np.nan),
        })

    df = pd.DataFrame(rows).sort_values("strike").reset_index(drop=True)
    df = df.fillna(0)
    return df


def pcr(df: pd.DataFrame) -> dict:
    """Put-Call Ratio by OI and by Volume."""
    total_ce_oi = df["ce_oi"].sum()
    total_pe_oi = df["pe_oi"].sum()
    total_ce_vol = df["ce_vol"].sum()
    total_pe_vol = df["pe_vol"].sum()

    return {
        "pcr_oi": round(total_pe_oi / total_ce_oi, 3) if total_ce_oi else 0,
        "pcr_vol": round(total_pe_vol / total_ce_vol, 3) if total_ce_vol else 0,
        "total_ce_oi": int(total_ce_oi),
        "total_pe_oi": int(total_pe_oi),
        "total_ce_vol": int(total_ce_vol),
        "total_pe_vol": int(total_pe_vol),
    }


def max_pain(df: pd.DataFrame) -> float:
    """
    Max-pain strike — the strike where total option buyers lose the most
    (i.e., writers collect maximum premium at expiry).
    """
    strikes = sorted(df["strike"].unique())
    pain = {}
    for s in strikes:
        ce_pain = df.loc[df["strike"] < s, "ce_oi"].sum() * 0  # CE above strike expire worthless
        # CE writers profit if spot < strike  → profit on CE = OI * (strike - spot) for strikes > spot
        ce_loss = ((df["strike"] - s).clip(lower=0) * df["ce_oi"]).sum()
        pe_loss = ((s - df["strike"]).clip(lower=0) * df["pe_oi"]).sum()
        pain[s] = ce_loss + pe_loss

    return min(pain, key=pain.get)


def oi_buildup(df: pd.DataFrame, spot: float, width: int = 10) -> dict:
    """
    Classify OI change around spot ± `width` strikes as:
    - Long Buildup (CE/PE): price ↑ + OI ↑
    - Short Buildup: price ↓ + OI ↑
    - Long Unwinding: price ↓ + OI ↓
    - Short Covering: price ↑ + OI ↓

    Returns strike-level signals for the ATM ± width range.
    """
    strikes = sorted(df["strike"].unique())
    atm = min(strikes, key=lambda s: abs(s - spot))
    atm_idx = strikes.index(atm)
    near = strikes[max(0, atm_idx - width): atm_idx + width + 1]
    sub = df[df["strike"].isin(near)].copy()

    def classify(chg_oi, chg_price):
        if chg_oi > 0 and chg_price > 0:
            return "Long Buildup"
        if chg_oi > 0 and chg_price <= 0:
            return "Short Buildup"
        if chg_oi <= 0 and chg_price > 0:
            return "Short Covering"
        return "Long Unwinding"

    # use ltp change as proxy for price direction (ltp vs prev close approximated by bid)
    sub["ce_signal"] = sub.apply(
        lambda r: classify(r["ce_chg_oi"], r["ce_ltp"] - r["ce_bid"]), axis=1)
    sub["pe_signal"] = sub.apply(
        lambda r: classify(r["pe_chg_oi"], r["pe_ltp"] - r["pe_bid"]), axis=1)

    return sub[["strike", "ce_oi", "ce_chg_oi", "ce_signal",
                "pe_oi", "pe_chg_oi", "pe_signal"]].set_index("strike").to_dict("index")


def support_resistance_from_oi(df: pd.DataFrame, spot: float, top_n: int = 3) -> dict:
    """
    Identify key support/resistance levels from OI concentrations.
    - Resistance: top CE OI strikes above spot
    - Support: top PE OI strikes below spot
    """
    above = df[df["strike"] > spot].nlargest(top_n, "ce_oi")["strike"].tolist()
    below = df[df["strike"] <= spot].nlargest(top_n, "pe_oi")["strike"].tolist()
    return {
        "resistance": sorted(above),
        "support": sorted(below, reverse=True),
    }


def iv_skew(df: pd.DataFrame, spot: float) -> dict:
    """
    Compute simple IV skew: OTM put IV vs OTM call IV, and ATM IV.
    """
    strikes = sorted(df["strike"].unique())
    atm = min(strikes, key=lambda s: abs(s - spot))

    atm_row = df[df["strike"] == atm].iloc[0]
    atm_iv = (atm_row["ce_iv"] + atm_row["pe_iv"]) / 2

    # 2% OTM
    otm_call_strike = min([s for s in strikes if s > spot * 1.02], default=atm)
    otm_put_strike = max([s for s in strikes if s < spot * 0.98], default=atm)

    otm_call_iv = df[df["strike"] == otm_call_strike]["ce_iv"].iloc[0]
    otm_put_iv = df[df["strike"] == otm_put_strike]["pe_iv"].iloc[0]

    skew = otm_put_iv - otm_call_iv
    skew_bias = "Bearish (put premium elevated)" if skew > 2 else (
        "Bullish (call premium elevated)" if skew < -2 else "Neutral")

    return {
        "atm_strike": atm,
        "atm_iv": round(atm_iv, 2),
        "otm_call_strike": otm_call_strike,
        "otm_call_iv": round(otm_call_iv, 2),
        "otm_put_strike": otm_put_strike,
        "otm_put_iv": round(otm_put_iv, 2),
        "skew": round(skew, 2),
        "skew_bias": skew_bias,
    }


# ─── Trend & macro helpers ───────────────────────────────────────────────────

def trend_summary(hist: pd.DataFrame) -> dict:
    """
    Compute trend signals from price history.
    Expects columns: open, high, low, close, volume (or Open/High/Low/Close).
    """
    col_map = {c.lower(): c for c in hist.columns}
    close_col = col_map.get("close", "Close")
    high_col = col_map.get("high", "High")
    low_col = col_map.get("low", "Low")

    c = hist[close_col].dropna()
    if len(c) < 20:
        return {"error": "insufficient history"}

    last = float(c.iloc[-1])
    ma20 = float(c.rolling(20).mean().iloc[-1])
    ma50 = float(c.rolling(50).mean().iloc[-1]) if len(c) >= 50 else np.nan
    ma200 = float(c.rolling(200).mean().iloc[-1]) if len(c) >= 200 else np.nan

    high52 = float(hist[high_col].iloc[-252:].max()) if len(hist) >= 252 else float(hist[high_col].max())
    low52 = float(hist[low_col].iloc[-252:].min()) if len(hist) >= 252 else float(hist[low_col].min())

    dist_from_52h = round((last - high52) / high52 * 100, 2)
    dist_from_52l = round((last - low52) / low52 * 100, 2)

    trend = "Uptrend" if last > ma20 > ma50 else ("Downtrend" if last < ma20 < ma50 else "Sideways")

    return {
        "last_close": round(last, 2),
        "ma20": round(ma20, 2),
        "ma50": round(ma50, 2) if not np.isnan(ma50) else None,
        "ma200": round(ma200, 2) if not np.isnan(ma200) else None,
        "52w_high": round(high52, 2),
        "52w_low": round(low52, 2),
        "dist_from_52w_high_pct": dist_from_52h,
        "dist_from_52w_low_pct": dist_from_52l,
        "trend": trend,
    }


def futures_premium(spot: float, futures_ltp: float, days_to_expiry: int) -> dict:
    """
    Compute annualised futures premium (cost of carry) and classify market sentiment.
    """
    if days_to_expiry <= 0 or spot <= 0:
        return {}

    premium = futures_ltp - spot
    annualised_coc = (premium / spot) * (365 / days_to_expiry) * 100

    if annualised_coc > 8:
        sentiment = "Bullish (high carry / leveraged longs)"
    elif annualised_coc > 3:
        sentiment = "Moderately Bullish"
    elif annualised_coc >= 0:
        sentiment = "Neutral"
    else:
        sentiment = "Bearish (futures at discount — unwinding or heavy hedging)"

    return {
        "spot": round(spot, 2),
        "futures_ltp": round(futures_ltp, 2),
        "premium": round(premium, 2),
        "annualised_coc_pct": round(annualised_coc, 2),
        "sentiment": sentiment,
    }


def fii_dii_summary(fii_dii_df: pd.DataFrame) -> dict:
    """
    Parse the FII/DII dataframe from Nse.fii_dii() and return a clean summary.
    """
    try:
        row = fii_dii_df.iloc[-1]
        result = {}
        for col in fii_dii_df.columns:
            top, sub = col
            key = f"{top.strip()}_{sub.strip()}"
            result[key] = row[col]
        return result
    except Exception:
        return {}


# ─── Composite report ────────────────────────────────────────────────────────

def derivative_report(
    symbol: str,
    oc: pd.DataFrame,
    spot: float,
    hist: pd.DataFrame,
    fii_dii_df: pd.DataFrame = None,
    futures_ltp: float = None,
    days_to_expiry: int = None,
) -> dict:
    """
    Build a full derivative analysis report for the given symbol.

    Parameters
    ----------
    symbol        : 'NIFTY' or 'BANKNIFTY'
    oc            : raw option_chain DataFrame from Nse.option_chain()
    spot          : current spot price
    hist          : price history DataFrame from Nse.get_hist()
    fii_dii_df    : optional DataFrame from Nse.fii_dii()
    futures_ltp   : optional near-month futures last traded price
    days_to_expiry: optional calendar days to nearest expiry
    """
    df = parse_option_chain(oc)

    report = {
        "symbol": symbol,
        "spot": spot,
        "as_of": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pcr": pcr(df),
        "max_pain": max_pain(df),
        "support_resistance": support_resistance_from_oi(df, spot),
        "iv_skew": iv_skew(df, spot),
        "trend": trend_summary(hist),
        "oi_buildup_atm": oi_buildup(df, spot, width=5),
    }

    if futures_ltp and days_to_expiry:
        report["futures"] = futures_premium(spot, futures_ltp, days_to_expiry)

    if fii_dii_df is not None:
        report["fii_dii"] = fii_dii_summary(fii_dii_df)

    report["bias"] = _derive_bias(report)
    return report


def _derive_bias(report: dict) -> str:
    """
    Synthesise a directional bias from multiple signals.
    """
    signals = []

    pcr_oi = report["pcr"].get("pcr_oi", 1.0)
    if pcr_oi > 1.3:
        signals.append(("Bullish", "PCR OI > 1.3 (put writers dominating)"))
    elif pcr_oi < 0.7:
        signals.append(("Bearish", "PCR OI < 0.7 (call writers dominating)"))
    else:
        signals.append(("Neutral", f"PCR OI {pcr_oi} in neutral zone"))

    trend = report["trend"].get("trend", "Sideways")
    if trend == "Uptrend":
        signals.append(("Bullish", "Price above MA20 > MA50"))
    elif trend == "Downtrend":
        signals.append(("Bearish", "Price below MA20 < MA50"))
    else:
        signals.append(("Neutral", "Sideways trend"))

    skew_bias = report["iv_skew"].get("skew_bias", "Neutral")
    if "Bearish" in skew_bias:
        signals.append(("Bearish", "IV skew elevated on puts"))
    elif "Bullish" in skew_bias:
        signals.append(("Bullish", "IV skew elevated on calls"))

    if "futures" in report:
        fut_sentiment = report["futures"].get("sentiment", "")
        if "Bullish" in fut_sentiment:
            signals.append(("Bullish", "Futures at premium"))
        elif "Bearish" in fut_sentiment:
            signals.append(("Bearish", "Futures at discount"))

    bull = sum(1 for s, _ in signals if s == "Bullish")
    bear = sum(1 for s, _ in signals if s == "Bearish")

    if bull > bear + 1:
        overall = "BULLISH"
    elif bear > bull + 1:
        overall = "BEARISH"
    else:
        overall = "NEUTRAL / SIDEWAYS"

    detail = "; ".join(f"{s}: {r}" for s, r in signals)
    return f"{overall} | {detail}"


def print_report(report: dict):
    """Pretty-print the derivative analysis report."""
    sep = "─" * 65

    print(f"\n{'═' * 65}")
    print(f"  DERIVATIVE ANALYSIS — {report['symbol']}    [{report['as_of']}]")
    print(f"  Spot: {report['spot']}")
    print(f"{'═' * 65}")

    print(f"\n{sep}")
    print("  PUT-CALL RATIO")
    print(sep)
    p = report["pcr"]
    print(f"  PCR (OI)  : {p['pcr_oi']}  {'⬆ Bullish' if p['pcr_oi'] > 1.2 else ('⬇ Bearish' if p['pcr_oi'] < 0.8 else '➡ Neutral')}")
    print(f"  PCR (Vol) : {p['pcr_vol']}")
    print(f"  Total CE OI: {p['total_ce_oi']:,}  |  Total PE OI: {p['total_pe_oi']:,}")

    print(f"\n{sep}")
    print("  MAX PAIN")
    print(sep)
    print(f"  Max Pain Strike : {report['max_pain']}")
    dist = report['spot'] - report['max_pain']
    print(f"  Spot vs Max Pain: {'+' if dist >= 0 else ''}{round(dist, 0)} pts  "
          f"({'Spot above max pain — some downward pull expected' if dist > 0 else 'Spot below max pain — some upward pull expected'})")

    print(f"\n{sep}")
    print("  SUPPORT & RESISTANCE (from OI)")
    print(sep)
    sr = report["support_resistance"]
    print(f"  Resistance : {sr['resistance']}")
    print(f"  Support    : {sr['support']}")

    print(f"\n{sep}")
    print("  IV SKEW")
    print(sep)
    iv = report["iv_skew"]
    print(f"  ATM Strike : {iv['atm_strike']}  |  ATM IV: {iv['atm_iv']}%")
    print(f"  OTM Call   : {iv['otm_call_strike']} → IV: {iv['otm_call_iv']}%")
    print(f"  OTM Put    : {iv['otm_put_strike']} → IV: {iv['otm_put_iv']}%")
    print(f"  Skew       : {iv['skew']}  [{iv['skew_bias']}]")

    print(f"\n{sep}")
    print("  TREND ANALYSIS")
    print(sep)
    t = report["trend"]
    if "error" not in t:
        print(f"  Last Close : {t['last_close']}")
        print(f"  MA20       : {t['ma20']}  |  MA50: {t['ma50']}  |  MA200: {t['ma200']}")
        print(f"  52W High   : {t['52w_high']} ({t['dist_from_52w_high_pct']}%)")
        print(f"  52W Low    : {t['52w_low']} ({t['dist_from_52w_low_pct']}%)")
        print(f"  Trend      : {t['trend']}")

    if "futures" in report:
        print(f"\n{sep}")
        print("  FUTURES ANALYSIS")
        print(sep)
        f = report["futures"]
        print(f"  Spot: {f['spot']}  |  Fut LTP: {f['futures_ltp']}")
        print(f"  Premium     : {f['premium']} pts")
        print(f"  Ann. CoC    : {f['annualised_coc_pct']}%  [{f['sentiment']}]")

    if "fii_dii" in report:
        print(f"\n{sep}")
        print("  FII / DII ACTIVITY")
        print(sep)
        for k, v in report["fii_dii"].items():
            print(f"  {k:<40}: {v}")

    print(f"\n{'═' * 65}")
    print("  OVERALL BIAS")
    print(f"{'═' * 65}")
    bias_parts = report["bias"].split(" | ", 1)
    print(f"  {bias_parts[0]}")
    if len(bias_parts) > 1:
        for seg in bias_parts[1].split("; "):
            print(f"    • {seg}")
    print(f"{'═' * 65}\n")


# ─── High-level convenience wrapper ─────────────────────────────────────────

def run_analysis(symbol: str = None, expiry: dt.date = None, nse=None) -> list[dict]:
    """
    Fetch all data (with cache + yfinance fallback) and return report dicts.

    Parameters
    ----------
    symbol  : 'NIFTY', 'BANKNIFTY', or None (both)
    expiry  : specific option expiry date, or None for nearest
    nse     : an Nse() instance; created automatically if not provided

    Returns list of report dicts (one per symbol).
    """
    from pynse.data_fetcher import (
        get_spot, get_hist, get_option_chain, get_fii_dii, get_futures_quote,
    )

    if nse is None:
        try:
            from pynse.core import Nse
            nse = Nse()
        except Exception:
            nse = None

    symbols = ([symbol.upper()] if symbol else ["NIFTY", "BANKNIFTY"])
    today = dt.date.today()

    # FII/DII fetched once and shared
    fii_df, fii_src = get_fii_dii(nse=nse)
    if fii_src != "unavailable":
        print(f"  [data] FII/DII source: {fii_src}")

    reports = []
    for sym in symbols:
        print(f"\n{'█' * 65}")
        print(f"  FETCHING DATA FOR: {sym}")
        print(f"{'█' * 65}")

        try:
            spot, spot_src = get_spot(sym, nse=nse)
            print(f"  [data] spot={spot}  source={spot_src}")
        except RuntimeError as e:
            print(f"  ERROR: {e}")
            continue

        try:
            hist, hist_src = get_hist(sym, from_date=today - dt.timedelta(days=365), nse=nse)
            print(f"  [data] hist={len(hist)} rows  source={hist_src}")
        except RuntimeError as e:
            print(f"  WARNING: {e}  — trend signals will be skipped")
            hist = pd.DataFrame()

        try:
            oc, oc_src = get_option_chain(sym, expiry=expiry, nse=nse)
            print(f"  [data] option_chain={len(oc)} strikes  source={oc_src}")
        except RuntimeError as e:
            print(f"  ERROR: {e}")
            continue

        fut_quote, fut_src = get_futures_quote(sym, nse=nse)
        futures_ltp = fut_quote.get("lastPrice") if fut_quote else None
        expiry_date = fut_quote.get("expiryDate") if fut_quote else None
        days_to_exp = (expiry_date - today).days if isinstance(expiry_date, dt.date) else None
        if fut_src != "unavailable":
            print(f"  [data] futures ltp={futures_ltp}  source={fut_src}")

        report = derivative_report(
            symbol=sym,
            oc=oc,
            spot=spot,
            hist=hist if not hist.empty else pd.DataFrame(),
            fii_dii_df=fii_df,
            futures_ltp=futures_ltp,
            days_to_expiry=days_to_exp,
        )
        print_report(report)
        reports.append(report)

    return reports
