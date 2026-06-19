"""
StockEdge scraper — usage examples.

No API key needed.  Uses your stockedge.com email + password.
The auth token is cached after the first login so re-runs skip the login step.

Run:
    python examples/stockedge_example.py
"""

from pynse.stockedge import StockEdge, Period

# ── 1. Login ────────────────────────────────────────────────────────────────
se = StockEdge()

# Login with email + password (same credentials as stockedge.com)
se.login("your_email@example.com", "your_password")

# Alternatives:
# se.login_mobile("9876543210", "1234")   # mobile + MPIN
# se.send_otp("9876543210")               # request OTP
# se.login_otp("9876543210", "654321")    # complete OTP login

print(se)   # StockEdge(user_id=12345)


# ── 2. Search for a company ──────────────────────────────────────────────────
results = se.search("Reliance")
print(results[["SecurityId", "SecurityName", "SecurityCode", "ExchangeName"]])

# Pick the first result's SecurityId (use it for all data methods)
sid = int(results.iloc[0]["SecurityId"])   # e.g. 2969 for Reliance Industries


# ── 3. Company info ──────────────────────────────────────────────────────────
info = se.get_company_info(sid)
print(info)


# ── 4. Financial statements ──────────────────────────────────────────────────

# Annual P&L (Revenue, EBITDA, PAT, EPS, margins)
pl = se.get_profit_loss(sid)
print(pl)

# Quarterly P&L
pl_q = se.get_profit_loss(sid, period=Period.Quarterly)
print(pl_q)

# Balance sheet (assets, liabilities, equity)
bs = se.get_balance_sheet(sid)
print(bs)

# Cash flow (operating / investing / financing)
cf = se.get_cash_flow(sid)
print(cf)

# Key ratios (P/E, ROE, ROCE, D/E, EPS …)
kr = se.get_key_ratios(sid)
print(kr)

# All 5 financial statements in one shot
financials = se.get_all_financials(sid)         # dict of DataFrames
for name, df in financials.items():
    print(f"\n=== {name} ===")
    print(df.head())


# ── 5. Portfolio / holdings data ─────────────────────────────────────────────

# Shareholding pattern (promoters / FII / DII / retail %)
sh = se.get_shareholding(sid)
print(sh)

# Mutual fund holdings (which MFs own it, how much)
mf = se.get_mf_holdings(sid)
print(mf)

# FII / FPI holdings history
fii = se.get_fii_holdings(sid)
print(fii)

# Bulk & block deals
bd = se.get_bulk_deals(sid)
print(bd)

# Insider / promoter buy-sell disclosures
it = se.get_insider_trading(sid)
print(it)

# All portfolio data in one shot
portfolio = se.get_all_portfolio_data(sid)      # dict of DataFrames
for name, df in portfolio.items():
    print(f"\n=== {name} ===")
    print(df.head())


# ── 6. Other data ────────────────────────────────────────────────────────────

# Sector peers comparison
peers = se.get_peer_comparison(sid)
print(peers)

# Historical OHLCV prices
prices = se.get_price_history(sid)
print(prices)

# StockEdge Edge Report
report = se.get_edge_report(sid)
print(report)
