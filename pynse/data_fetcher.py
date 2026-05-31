"""
Data fetcher with disk cache and yfinance fallback.

Priority order for each data type:
  1. Disk cache (if fresh enough)
  2. NSE live API
  3. yfinance (spot + historical only)

Cache lives in ~/.pynse/da_cache/
TTL: 15 min during market hours, 24 h off-market (or always 24 h for slow-moving data).
"""
import datetime as dt
import logging
import os
import pickle

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Cache config ─────────────────────────────────────────────────────────────

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".pynse", "da_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

MARKET_OPEN  = dt.time(9, 15)
MARKET_CLOSE = dt.time(15, 30)

# minutes; during off-market hours all TTLs are floored to 1440 (24 h)
_TTL = {
    "spot":         1,
    "option_chain": 15,
    "hist":         1440,
    "fii_dii":      1440,
    "futures":      5,
}

# yfinance ticker symbols for NSE indices
_YF_MAP = {
    "NIFTY":    "^NSEI",
    "BANKNIFTY": "^NSEBANK",
}

# NSE symbol used for get_hist() index calls
_NSE_HIST_MAP = {
    "NIFTY":     "NIFTY 50",
    "BANKNIFTY": "NIFTY BANK",
}


def _market_open() -> bool:
    now = dt.datetime.now()
    if now.weekday() >= 5:          # Saturday / Sunday
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


def _cache_file(key: str) -> str:
    return os.path.join(CACHE_DIR, f"{key}.pkl")


def _cache_age_minutes(key: str) -> float:
    path = _cache_file(key)
    if not os.path.exists(path):
        return float("inf")
    age_s = (dt.datetime.now() - dt.datetime.fromtimestamp(os.path.getmtime(path))).total_seconds()
    return age_s / 60


def _cache_fresh(key: str, ttl_type: str) -> bool:
    ttl = _TTL.get(ttl_type, 1440)
    if not _market_open():
        ttl = max(ttl, 1440)
    return _cache_age_minutes(key) < ttl


def _load(key: str):
    with open(_cache_file(key), "rb") as f:
        return pickle.load(f)


def _save(key: str, data):
    with open(_cache_file(key), "wb") as f:
        pickle.dump(data, f)
    logger.debug(f"cached {key}")


# ── yfinance helpers ──────────────────────────────────────────────────────────

def _yf_spot(symbol: str) -> float | None:
    ticker = _YF_MAP.get(symbol.upper())
    if ticker is None:
        return None
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).fast_info
        price = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
        if price:
            logger.info(f"yfinance spot for {symbol}: {price}")
            return float(price)
    except Exception as e:
        logger.warning(f"yfinance spot failed for {symbol}: {e}")
    return None


def _yf_hist(symbol: str, from_date: dt.date, to_date: dt.date) -> pd.DataFrame | None:
    ticker = _YF_MAP.get(symbol.upper())
    if ticker is None:
        return None
    try:
        import yfinance as yf
        df = yf.download(
            ticker,
            start=from_date.strftime("%Y-%m-%d"),
            end=(to_date + dt.timedelta(days=1)).strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )
        if df.empty:
            return None

        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0].lower() for col in df.columns]
        else:
            df.columns = [c.lower() for c in df.columns]

        df.index = pd.to_datetime(df.index)
        logger.info(f"yfinance hist for {symbol}: {len(df)} rows")
        return df
    except Exception as e:
        logger.warning(f"yfinance hist failed for {symbol}: {e}")
    return None


# ── Public fetch functions ────────────────────────────────────────────────────

def get_spot(symbol: str, nse=None) -> tuple[float, str]:
    """
    Return (spot_price, source) where source is 'nse', 'cache', or 'yfinance'.
    """
    key = f"spot_{symbol}"

    # 1. fresh cache
    if _cache_fresh(key, "spot"):
        val = _load(key)
        logger.debug(f"spot {symbol} from cache")
        return val, "cache"

    # 2. NSE live
    if nse is not None:
        try:
            from pynse.core import IndexSymbol
            idx_sym = IndexSymbol.Nifty50 if symbol.upper() == "NIFTY" else IndexSymbol.NiftyBank
            data = nse.get_indices(idx_sym)
            spot = float(data["last"].iloc[0])
            _save(key, spot)
            return spot, "nse"
        except Exception as e:
            logger.warning(f"NSE spot failed for {symbol}: {e}")

    # 3. yfinance
    spot = _yf_spot(symbol)
    if spot is not None:
        _save(key, spot)
        return spot, "yfinance"

    # 4. stale cache as last resort
    if os.path.exists(_cache_file(key)):
        logger.warning(f"Using stale cache for spot {symbol}")
        return _load(key), "stale_cache"

    raise RuntimeError(f"Cannot fetch spot price for {symbol}. Check network / NSE access.")


def get_hist(
    symbol: str,
    from_date: dt.date = None,
    to_date: dt.date = None,
    nse=None,
) -> tuple[pd.DataFrame, str]:
    """
    Return (DataFrame, source).  Columns: open/high/low/close/volume (lowercase).
    """
    if from_date is None:
        from_date = dt.date.today() - dt.timedelta(days=365)
    if to_date is None:
        to_date = dt.date.today()

    key = f"hist_{symbol}_{from_date}_{to_date}"

    # 1. fresh cache
    if _cache_fresh(key, "hist"):
        return _load(key), "cache"

    # 2. NSE live
    if nse is not None:
        try:
            nse_sym = _NSE_HIST_MAP.get(symbol.upper(), symbol)
            df = nse.get_hist(nse_sym, from_date=from_date, to_date=to_date)
            if df is not None and not df.empty:
                df.columns = [c.lower() for c in df.columns]
                _save(key, df)
                return df, "nse"
        except Exception as e:
            logger.warning(f"NSE hist failed for {symbol}: {e}")

    # 3. yfinance
    df = _yf_hist(symbol, from_date, to_date)
    if df is not None and not df.empty:
        _save(key, df)
        return df, "yfinance"

    # 4. stale cache
    if os.path.exists(_cache_file(key)):
        logger.warning(f"Using stale cache for hist {symbol}")
        return _load(key), "stale_cache"

    raise RuntimeError(f"Cannot fetch historical data for {symbol}.")


def get_option_chain(symbol: str, expiry: dt.date = None, nse=None) -> tuple[pd.DataFrame, str]:
    """Return (option_chain_df, source)."""
    key = f"option_chain_{symbol}_{expiry or 'nearest'}"

    # 1. fresh cache
    if _cache_fresh(key, "option_chain"):
        return _load(key), "cache"

    # 2. NSE live (only source for option chain)
    if nse is not None:
        try:
            oc = nse.option_chain(symbol, expiry=expiry)
            if oc is not None and not oc.empty:
                _save(key, oc)
                return oc, "nse"
        except Exception as e:
            logger.warning(f"NSE option chain failed for {symbol}: {e}")

    # 3. stale cache (no alternative source)
    if os.path.exists(_cache_file(key)):
        age = _cache_age_minutes(key)
        logger.warning(f"Using stale option chain cache for {symbol} (age: {age:.0f} min)")
        return _load(key), "stale_cache"

    raise RuntimeError(
        f"Cannot fetch option chain for {symbol}. "
        "NSE API unreachable and no cached data. "
        "Run with local network access at least once to populate cache."
    )


def get_fii_dii(nse=None) -> tuple[pd.DataFrame, str]:
    """Return (fii_dii_df, source)."""
    key = "fii_dii"

    if _cache_fresh(key, "fii_dii"):
        return _load(key), "cache"

    if nse is not None:
        try:
            df = nse.fii_dii()
            if df is not None and not df.empty:
                _save(key, df)
                return df, "nse"
        except Exception as e:
            logger.warning(f"NSE fii_dii failed: {e}")

    if os.path.exists(_cache_file(key)):
        logger.warning("Using stale FII/DII cache")
        return _load(key), "stale_cache"

    return None, "unavailable"


def get_futures_quote(symbol: str, nse=None) -> tuple[dict, str]:
    """Return (futures_quote_dict, source)."""
    key = f"futures_{symbol}"

    if _cache_fresh(key, "futures"):
        return _load(key), "cache"

    if nse is not None:
        try:
            from pynse.core import Segment
            fut = nse.get_quote(symbol, segment=Segment.FUT)
            if fut:
                _save(key, fut)
                return fut, "nse"
        except Exception as e:
            logger.warning(f"NSE futures quote failed for {symbol}: {e}")

    if os.path.exists(_cache_file(key)):
        logger.warning(f"Using stale futures cache for {symbol}")
        return _load(key), "stale_cache"

    return {}, "unavailable"


# ── Bulk refresh (call this daily / from scheduler) ───────────────────────────

def refresh_all(nse=None):
    """
    Force-refresh all cached data for NIFTY and BANKNIFTY.
    Safe to call from a cron job or scheduler.
    Returns a summary dict of {key: source}.
    """
    if nse is None:
        from pynse.core import Nse
        nse = Nse()

    summary = {}
    today = dt.date.today()
    year_ago = today - dt.timedelta(days=365)

    for sym in ["NIFTY", "BANKNIFTY"]:
        # invalidate caches so we force a fresh fetch
        for key_prefix in [f"spot_{sym}", f"hist_{sym}_{year_ago}_{today}",
                            f"option_chain_{sym}_nearest", f"futures_{sym}"]:
            path = _cache_file(key_prefix)
            if os.path.exists(path):
                os.remove(path)

        try:
            _, src = get_spot(sym, nse=nse)
            summary[f"spot_{sym}"] = src
        except Exception as e:
            summary[f"spot_{sym}"] = f"error: {e}"

        try:
            _, src = get_hist(sym, from_date=year_ago, nse=nse)
            summary[f"hist_{sym}"] = src
        except Exception as e:
            summary[f"hist_{sym}"] = f"error: {e}"

        try:
            _, src = get_option_chain(sym, nse=nse)
            summary[f"option_chain_{sym}"] = src
        except Exception as e:
            summary[f"option_chain_{sym}"] = f"error: {e}"

        try:
            _, src = get_futures_quote(sym, nse=nse)
            summary[f"futures_{sym}"] = src
        except Exception as e:
            summary[f"futures_{sym}"] = f"error: {e}"

    try:
        _, src = get_fii_dii(nse=nse)
        summary["fii_dii"] = src
    except Exception as e:
        summary["fii_dii"] = f"error: {e}"

    logger.info(f"refresh_all complete: {summary}")
    return summary


def cache_status() -> pd.DataFrame:
    """Return a DataFrame showing age and freshness of all cached items."""
    rows = []
    for fname in sorted(os.listdir(CACHE_DIR)):
        if not fname.endswith(".pkl"):
            continue
        key = fname[:-4]
        age = _cache_age_minutes(key)
        ttl_type = key.split("_")[0]
        ttl = _TTL.get(ttl_type, 1440)
        if not _market_open():
            ttl = max(ttl, 1440)
        rows.append({
            "key":          key,
            "age_min":      round(age, 1),
            "ttl_min":      ttl,
            "fresh":        age < ttl,
            "cached_at":    dt.datetime.fromtimestamp(
                os.path.getmtime(os.path.join(CACHE_DIR, fname))
            ).strftime("%Y-%m-%d %H:%M"),
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["key", "age_min", "ttl_min", "fresh", "cached_at"])
