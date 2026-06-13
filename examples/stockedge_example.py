"""
Example usage of the StockEdge scraper.

Run:
    python examples/stockedge_example.py
"""

from pynse.stockedge import StockEdge, Period

# --- 1. Create client and log in -------------------------------------------
se = StockEdge()

# Replace with your actual StockEdge credentials
EMAIL = "your_email@example.com"
PASSWORD = "your_password"

# Email + password login (web account)
# se.login(email=EMAIL, password=PASSWORD)

# Mobile + MPIN login (app account)
# se.login(mobile="9876543210", mpin="1234")

# OTP-based login
# se.send_otp("9876543210")
# otp = input("Enter OTP: ")
# se.login_with_otp("9876543210", otp)

print(se)  # StockEdge(not authenticated) until you call login()


# --- 2. Search for a company -------------------------------------------------
# results = se.search("Reliance")
# print(results[["SecurityId", "SecurityName", "SecurityCode", "ExchangeName"]])
# security_id = int(results.iloc[0]["SecurityId"])  # e.g. 2969 for Reliance


# --- 3. Company info ---------------------------------------------------------
# info = se.get_company_info(security_id)
# print(info)


# --- 4. Financial statements -------------------------------------------------
# Annual P&L
# pl = se.get_profit_loss(security_id)
# print(pl)

# Quarterly P&L
# pl_q = se.get_profit_loss(security_id, period=Period.Quarterly)
# print(pl_q)

# Balance sheet
# bs = se.get_balance_sheet(security_id)
# print(bs)

# Cash flow
# cf = se.get_cash_flow(security_id)
# print(cf)

# Key ratios (P/E, ROE, ROCE, ...)
# kr = se.get_key_ratios(security_id)
# print(kr)

# All financials at once
# fin = se.get_all_financials(security_id)
# for name, df in fin.items():
#     print(f"\n=== {name} ===")
#     print(df.head())


# --- 5. Portfolio / holdings data -------------------------------------------
# Shareholding pattern (promoters, FII, DII, public)
# sh = se.get_shareholding(security_id)
# print(sh)

# Mutual fund holdings
# mf = se.get_mf_holdings(security_id)
# print(mf)

# FII holdings
# fii = se.get_fii_holdings(security_id)
# print(fii)

# Bulk and block deals
# bd = se.get_bulk_deals(security_id)
# print(bd)

# Insider / promoter trading
# it = se.get_insider_trading(security_id)
# print(it)

# All portfolio data at once
# port = se.get_all_portfolio_data(security_id)
# for name, df in port.items():
#     print(f"\n=== {name} ===")
#     print(df.head())


# --- 6. Other data ----------------------------------------------------------
# Peer comparison
# peers = se.get_peer_comparison(security_id)
# print(peers)

# Historical prices
# prices = se.get_price_history(security_id)
# print(prices)

# Edge report
# report = se.get_edge_report(security_id)
# print(report)
