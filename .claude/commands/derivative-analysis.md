# Derivative Analysis — Nifty & Bank Nifty

Perform a comprehensive macro-economic derivative analysis for **Nifty** and/or **Bank Nifty**.

Data is fetched with a **three-tier strategy**:
1. **Disk cache** (`~/.pynse/da_cache/`) — 15 min TTL during market hours, 24 h off-market
2. **NSE live API** — works when run from India with a real browser session
3. **yfinance fallback** — for spot price and historical data when NSE is unreachable

## Quick Start (recommended)

```python
from pynse.derivative_analysis import run_analysis

# Both indices with full cache + fallback handling:
reports = run_analysis()

# Single index:
reports = run_analysis(symbol='NIFTY')

# Specific expiry:
import datetime as dt
reports = run_analysis(symbol='BANKNIFTY', expiry=dt.date(2025, 5, 29))
```

`run_analysis()` handles all data fetching, prints each report, and returns the report dicts for further use.

---

## Manual pipeline (step-by-step)

```python
from pynse import *
from pynse.derivative_analysis import derivative_report, print_report
from pynse.data_fetcher import (
    get_spot, get_hist, get_option_chain,
    get_fii_dii, get_futures_quote, cache_status,
)
import datetime as dt

nse = Nse()

# Check what's already cached:
print(cache_status())

# Fetch with automatic cache + fallback:
spot, src   = get_spot('NIFTY', nse=nse)
hist, src   = get_hist('NIFTY', nse=nse)
oc, src     = get_option_chain('NIFTY', nse=nse)
fii_df, src = get_fii_dii(nse=nse)
fut, src    = get_futures_quote('NIFTY', nse=nse)

report = derivative_report(
    symbol='NIFTY',
    oc=oc,
    spot=spot,
    hist=hist,
    fii_dii_df=fii_df,
    futures_ltp=fut.get('lastPrice'),
    days_to_expiry=(fut.get('expiryDate') - dt.date.today()).days if fut.get('expiryDate') else None,
)
print_report(report)
```

---

## Daily Data Refresh

To keep the cache fresh without needing to run the full analysis, schedule:

```bash
# Run once after market close (15:35 IST) on weekdays:
python -m pynse.refresh_data
```

**Cron (Linux/Mac):**
```
35 15 * * 1-5  cd /path/to/project && python -m pynse.refresh_data >> ~/.pynse/refresh.log 2>&1
```

**Windows Task Scheduler:**
- Action: `python -m pynse.refresh_data`
- Trigger: Daily, 3:35 PM, repeat Mon–Fri

The refresh script logs each data source (nse / yfinance / stale_cache / error) and exits with code 1 if any fetch fails.

---

## Macro-Economic Interpretation Framework

After `print_report()`, synthesise the following signals:

### A. Market Breadth & Positioning
- **PCR OI > 1.3** → Put writers dominant → bullish lean  
- **PCR OI < 0.7** → Call writers dominant → upside capped, bearish lean  
- **Max Pain** → Spot far above max pain = reversion drag into expiry; below = gravitational pull up  

### B. Open Interest Signals
- **CE OI wall above spot** → Confirmed resistance; breakout needs heavy short covering  
- **PE OI wall below spot** → Confirmed support; breakdown needs sustained selling  
- OI buildup patterns (from `oi_buildup()`):
  - *Long Buildup* above spot → bullish continuation  
  - *Short Buildup* below spot → breakdown risk  
  - *Short Covering* near support → bounce candidate  
  - *Long Unwinding* near resistance → distribution  

### C. IV Skew & Volatility Regime
- **Skew > +5** → Fear on downside → hedge / sell put spreads  
- **Skew < -3** → Complacency → watch for sharp reversal  
- **ATM IV > 20%** → High vol regime → prefer premium selling (strangles / iron condors)  
- **ATM IV < 12%** → Low vol regime → prefer buying ahead of events (straddles)  

### D. Futures Cost of Carry
- **Ann. CoC > 10%** → Speculative longs; watch for unwinding  
- **Ann. CoC 4–8%** → Normal bullish carry  
- **Futures at discount** → Hedge / short buildup → bearish  

### E. FII / DII Macro Flow
- **FII net buyers (cash) + net long (F&O)** → Strong bullish macro  
- **FII net sellers + DII absorbing** → Range-bound / mild correction  
- **FII net short in F&O** → Macro hedge or directional bear bet  

### F. Trend Context
- Spot **above MA20 > MA50** → Uptrend; buy dips  
- Spot **below MA20 < MA50** → Downtrend; sell rallies  
- **< 3% from 52W high** → Breakout watch zone  
- **> 15% below 52W high** → Oversold / bear market  

---

## Output Format

Present in this order:

1. **Raw report** via `print_report()` for Nifty, then Bank Nifty  
2. **Nifty Macro Narrative** — 4–6 bullet points synthesising all signals  
3. **Bank Nifty Macro Narrative** — 4–6 bullet points  
4. **Cross-Index Comparison** — BNF/Nifty ratio vs historical avg; PCR divergence  
5. **Trading Opportunities** — 2–3 strategies:
   - Format: `Strategy | Legs | Entry | Target/Stop | Rationale`  
6. **Key Risk Events** — upcoming macro events that could shift bias  

---

## Arguments (`$ARGUMENTS`)

- `NIFTY` or `BANKNIFTY` → analyse only that index  
- A date like `2025-05-29` → use as option expiry  
- `status` → show cache status table only (`cache_status()`)  
- `refresh` → force-refresh all data (`refresh_all()`)  

Examples:
```
/derivative-analysis
/derivative-analysis NIFTY
/derivative-analysis BANKNIFTY 2025-05-29
/derivative-analysis status
/derivative-analysis refresh
```

---

## Handling `$ARGUMENTS` in code

```python
import sys
args = "$ARGUMENTS".split()

if 'status' in args:
    from pynse.data_fetcher import cache_status
    print(cache_status().to_string(index=False))
elif 'refresh' in args:
    from pynse.data_fetcher import refresh_all
    print(refresh_all())
else:
    symbol  = next((a for a in args if a.upper() in ('NIFTY', 'BANKNIFTY')), None)
    expiry  = next((dt.date.fromisoformat(a) for a in args if '-' in a), None)
    from pynse.derivative_analysis import run_analysis
    run_analysis(symbol=symbol, expiry=expiry)
```

---

## Notes

- Option chain has **no public alternative** to NSE — cache is the only offline fallback  
- Lot sizes: Nifty = 75, Bank Nifty = 30 (verify current lot size before sizing positions)  
- OI is in contracts; multiply by lot size for notional  
- All analysis is for **educational / research purposes** — not financial advice  
