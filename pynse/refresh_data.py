"""
CLI: python -m pynse.refresh_data

Refreshes all derivative analysis cache for NIFTY and BANKNIFTY.
Intended for daily cron / Task Scheduler use.

Cron example (runs at 15:35 IST every weekday):
    35 15 * * 1-5  cd /your/project && python -m pynse.refresh_data

Windows Task Scheduler:
    Action: python -m pynse.refresh_data
    Trigger: Daily at 3:35 PM
"""
import datetime as dt
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    logger.info("=== pynse derivative data refresh starting ===")
    start = dt.datetime.now()

    try:
        from pynse.core import Nse
        from pynse.data_fetcher import refresh_all, cache_status
    except ImportError as e:
        logger.error(f"Import failed: {e}")
        sys.exit(1)

    nse = None
    try:
        nse = Nse()
        logger.info("NSE session initialised")
    except Exception as e:
        logger.warning(f"NSE init failed ({e}) — will use yfinance fallback where possible")

    summary = refresh_all(nse=nse)

    logger.info("─── Refresh summary ───────────────────────────────")
    for key, src in summary.items():
        status = "✓" if "error" not in str(src) else "✗"
        logger.info(f"  {status}  {key:<40}  source: {src}")

    logger.info("─── Cache status ───────────────────────────────────")
    df = cache_status()
    if df.empty:
        logger.warning("  No cache files found.")
    else:
        for _, row in df.iterrows():
            flag = "FRESH" if row["fresh"] else "STALE"
            logger.info(f"  [{flag}]  {row['key']:<42}  age: {row['age_min']} min  cached: {row['cached_at']}")

    elapsed = (dt.datetime.now() - start).seconds
    errors = [k for k, v in summary.items() if "error" in str(v)]
    logger.info(f"=== Done in {elapsed}s  |  {len(summary) - len(errors)} ok  |  {len(errors)} errors ===")

    if errors:
        logger.warning("Failed items: " + ", ".join(errors))
        sys.exit(1)


if __name__ == "__main__":
    main()
