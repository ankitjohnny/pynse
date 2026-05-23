# Derivative Analysis — Nifty & Bank Nifty

Perform a comprehensive macro-economic derivative analysis for **Nifty** and/or **Bank Nifty** using live NSE data via the `pynse` library.

## What this skill does

When invoked, run the following analysis pipeline and present results clearly:

### 1. Setup
```python
from pynse import *
from pynse.derivative_analysis import (
    parse_option_chain, pcr, max_pain, oi_buildup,
    support_resistance_from_oi, iv_skew, trend_summary,
    futures_premium, fii_dii_summary, derivative_report, print_report
)
import datetime as dt

nse = Nse()
```

### 2. Fetch data for both indices

For each index in `['NIFTY', 'BANKNIFTY']`:

```python
# Option chain (nearest expiry by default)
oc = nse.option_chain('NIFTY')          # or 'BANKNIFTY'
expiry_list = nse.expiry_list

# Spot price from live index
idx_data = nse.get_indices(IndexSymbol.Nifty50)   # or IndexSymbol.NiftyBank
spot = float(idx_data['last'].iloc[0])

# Near-month futures quote
fut = nse.get_quote('NIFTY', segment=Segment.FUT)
futures_ltp = fut.get('lastPrice', spot)
expiry_date  = fut.get('expiryDate', expiry_list[0])
days_to_expiry = (expiry_date - dt.date.today()).days

# 1-year price history for trend
hist = nse.get_hist('NIFTY 50', from_date=dt.date.today() - dt.timedelta(days=365))

# FII/DII (once, shared)
fii_dii_df = nse.fii_dii()
```

### 3. Build and print report

```python
report = derivative_report(
    symbol='NIFTY',
    oc=oc,
    spot=spot,
    hist=hist,
    fii_dii_df=fii_dii_df,
    futures_ltp=futures_ltp,
    days_to_expiry=days_to_expiry,
)
print_report(report)
```

Repeat for `BANKNIFTY` using `IndexSymbol.NiftyBank` and `get_hist('NIFTY BANK', ...)`.

---

## Macro-Economic Interpretation Framework

After printing the raw report, synthesise and narrate these macro signals:

### A. Market Breadth & Positioning
- **PCR OI > 1.3** → Put writers dominant → markets expect support, bullish lean  
- **PCR OI < 0.7** → Call writers dominant → markets capping upside, bearish lean  
- **Max Pain** → Identify gravitational pull; if spot is far above, expect reversion pressure into expiry  

### B. Open Interest & Smart Money Flow
- **CE OI buildup at resistance** → Confirmed resistance wall; breakout requires heavy short covering  
- **PE OI buildup at support** → Confirmed support zone; breakdown requires sustained selling  
- **Change-in-OI signal patterns** (from `oi_buildup()`):
  - *Long Buildup* at strikes above spot → bullish continuation  
  - *Short Buildup* at strikes below spot → bearish breakdown expected  
  - *Short Covering* near support → possible bounce  
  - *Long Unwinding* near resistance → distribution phase  

### C. IV Skew & Volatility Regime
- **Skew > +5** → Fear elevated on downside → hedge or sell put spreads  
- **Skew < -3** → Complacency or bullish speculation → watch for sharp correction  
- **ATM IV > 20%** → High volatility regime → prefer selling strategies (strangles/iron condors)  
- **ATM IV < 12%** → Low volatility → prefer buying strategies (long straddles ahead of events)  

### D. Futures Premium (Cost of Carry)
- **Ann. CoC > 10%** → Speculative long buildup → unsustainable, watch for unwinding  
- **Ann. CoC 4–8%** → Normal/bullish carry  
- **Futures at discount** → Heavy hedging or short buildup → bearish  

### E. FII / DII Macro Flow
- **FII net buyers in cash** + **FII net long in index futures** → Strong bullish macro  
- **FII net sellers** + **DII absorbing** → Range-bound or mild correction  
- **FII net short in F&O** → Macro hedge or bearish directional bet  

### F. Trend Context
- Spot **above MA20 > MA50** → Primary uptrend; buy dips  
- Spot **below MA20 < MA50** → Distribution/downtrend; sell rallies  
- **< 3% from 52W High** → Breakout watch zone  
- **> 15% from 52W High** → Oversold or bear market zone  

---

## Output Format

Present results in this order:

1. **Raw report** via `print_report()` for Nifty, then Bank Nifty  
2. **Nifty Macro Narrative** — 4–6 bullet points synthesising all signals  
3. **Bank Nifty Macro Narrative** — 4–6 bullet points  
4. **Cross-Index Comparison** — Is Bank Nifty outperforming/underperforming Nifty? What does the spread signal?  
5. **Trading Opportunities** — List 2–3 specific option strategies with strikes, expiry, rationale  
   - Format: `Strategy | Legs | Entry | Target | Stop | Rationale`  
6. **Key Risk Events** — mention upcoming events (RBI policy, earnings season, global macro) that could shift the bias  

---

## Arguments

If the user passes `$ARGUMENTS`:
- A specific symbol like `NIFTY` or `BANKNIFTY` → analyse only that index  
- An expiry date like `2024-05-30` → use that expiry for option chain  
- A number of strikes like `20` → show top-N strikes in OI table  

Example: `/derivative-analysis NIFTY 2024-05-30`

---

## Error Handling

- If NSE API is unreachable, print a clear message and suggest checking `nse.market_status()`  
- If option chain is empty, note that the market may be closed or data unavailable  
- If history is insufficient (< 20 days), skip trend signals and note it  

---

## Notes

- All analysis uses the `pynse.derivative_analysis` module at `pynse/derivative_analysis.py`  
- Option chain lot sizes: Nifty = 50, Bank Nifty = 15 (verify current lot size before position sizing)  
- OI is in number of contracts; multiply by lot size for notional exposure  
- This analysis is for **educational and research purposes** — not financial advice  
