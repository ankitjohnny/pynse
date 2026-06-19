"""
StockEdge web scraper — no API key required.

Logs in to stockedge.com with your e-mail and password, captures the auth
token the browser receives, then calls the same internal REST endpoints that
the web app (web.stockedge.com) uses.  All data is returned as
``pandas.DataFrame``.

Quick start
-----------
>>> from pynse.stockedge import StockEdge, Period
>>> se = StockEdge()
>>> se.login("you@example.com", "yourpassword")
>>> results = se.search("Reliance")
>>> sid = int(results.iloc[0]["SecurityId"])
>>> se.get_profit_loss(sid)
>>> se.get_balance_sheet(sid)
>>> se.get_shareholding(sid)
>>> se.get_mf_holdings(sid)
"""

from __future__ import annotations

import enum
import json
import logging
import os
import pickle
import time
from typing import Any, Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# URL constants
# ---------------------------------------------------------------------------

_SITE   = "https://stockedge.com"
_API    = "https://api.stockedge.com/Api"
_WEB    = "https://web.stockedge.com"

# Internal endpoints the SPA uses — same calls we'll make after login
_EP: dict[str, str] = {
    # --- auth ---
    "login_email":      "/UserRegistrationApi/LoginWithEmailAndPassword",
    "login_mobile":     "/UserRegistrationApi/LoginWithMobileNumberAndMPIN",
    "send_otp":         "/UserRegistrationApi/GenerateOTPForLogin",
    "login_otp":        "/UserRegistrationApi/LoginWithMobileNumberAndOTP",
    "user_profile":     "/UserRegistrationApi/GetUserProfile",
    # --- search ---
    "search":           "/DashboardApi/GetSearchedEntityList/{q}/0",
    "all_securities":   "/SecurityApi/GetAllSecurities/0",
    # --- company ---
    "company_info":     "/DashboardApi/GetCompanyBySecurityId/{sid}",
    # --- financials (period 0=annual, 1=quarterly) ---
    "fin_results":      "/SecurityDashboardApi/GetFinancialResultsForSecurity/{sid}/{p}",
    "balance_sheet":    "/SecurityDashboardApi/GetBalanceSheetForSecurity/{sid}/{p}",
    "profit_loss":      "/SecurityDashboardApi/GetProfitAndLossForSecurity/{sid}/{p}",
    "cash_flow":        "/SecurityDashboardApi/GetCashFlowForSecurity/{sid}/{p}",
    "key_ratios":       "/SecurityDashboardApi/GetKeyRatiosForSecurity/{sid}/{p}",
    # --- portfolio ---
    "shareholding":     "/SecurityDashboardApi/GetShareholdingPatternForSecurity/{sid}/10",
    "mf_holdings":      "/SecurityDashboardApi/GetMutualFundHoldingForSecurity/{sid}/10",
    "fii_holdings":     "/SecurityDashboardApi/GetFIIHoldingForSecurity/{sid}/10",
    "bulk_deals":       "/SecurityDashboardApi/GetBulkAndBlockDealForSecurity/{sid}/10",
    "insider_trading":  "/SecurityDashboardApi/GetInsiderTradingForSecurity/{sid}/10",
    # --- misc ---
    "peer_comparison":  "/SecurityDashboardApi/GetPeerComparisonForSecurity/{sid}",
    "price_history":    "/SecurityDashboardApi/GetPriceHistoryForSecurity/{sid}/10",
    "edge_report":      "/SecurityDashboardApi/GetEdgeReportForSecurity/{sid}",
}

# Headers that match what Chrome sends when visiting web.stockedge.com
_HEADERS: dict[str, str] = {
    "Accept":           "application/json, text/plain, */*",
    "Accept-Language":  "en-US,en;q=0.9,hi;q=0.8",
    "Accept-Encoding":  "gzip, deflate, br",
    "Connection":       "keep-alive",
    "Origin":           _WEB,
    "Referer":          _WEB + "/",
    "Sec-Fetch-Dest":   "empty",
    "Sec-Fetch-Mode":   "cors",
    "Sec-Fetch-Site":   "same-site",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Period(enum.Enum):
    """Statement period."""
    Annual    = 0
    Quarterly = 1


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class StockEdge:
    """
    Browser-session scraper for StockEdge.

    No API key is required — only the e-mail and password you use to log in
    at stockedge.com.

    The auth token is cached in ``~/.pynse/stockedge/session.pkl`` so you
    only need to call :meth:`login` once per session.

    Parameters
    ----------
    timeout : int
        HTTP timeout in seconds (default 20).
    cache_dir : str, optional
        Override the default cache directory.

    Examples
    --------
    >>> se = StockEdge()
    >>> se.login("you@example.com", "password")
    >>> df = se.search("TCS")
    >>> sid = int(df.iloc[0]["SecurityId"])
    >>> se.get_profit_loss(sid)
    >>> se.get_balance_sheet(sid)
    >>> se.get_shareholding(sid)
    """

    def __init__(self, timeout: int = 20, cache_dir: Optional[str] = None):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

        self._token:   Optional[str] = None
        self._user_id: Optional[int] = None

        _dir = cache_dir or os.path.join(os.path.expanduser("~"), ".pynse", "stockedge")
        os.makedirs(_dir, exist_ok=True)
        self._cache_dir  = _dir
        self._token_file = os.path.join(_dir, "session.pkl")
        self._load_session()

    # ------------------------------------------------------------------
    # Session cache
    # ------------------------------------------------------------------

    def _load_session(self) -> None:
        if not os.path.exists(self._token_file):
            return
        try:
            with open(self._token_file, "rb") as f:
                d = pickle.load(f)
            self._token   = d.get("token")
            self._user_id = d.get("user_id")
            if self._token:
                self._session.headers["Authorization"] = f"Bearer {self._token}"
                logger.debug("Loaded cached session (user=%s).", self._user_id)
        except Exception as exc:
            logger.warning("Could not restore session: %s", exc)

    def _save_session(self) -> None:
        with open(self._token_file, "wb") as f:
            pickle.dump({"token": self._token, "user_id": self._user_id}, f)

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def login(self, email: str, password: str) -> dict:
        """
        Log in with your StockEdge e-mail and password.

        The token is cached locally so you don't need to log in on every run.

        Parameters
        ----------
        email : str
            E-mail registered at stockedge.com.
        password : str
            Your account password.

        Returns
        -------
        dict  Raw response (includes user profile on success).

        Examples
        --------
        >>> se.login("you@example.com", "secret")
        """
        url     = _API + _EP["login_email"]
        payload = {"Email": email, "Password": password, "DeviceType": "W"}
        return self._do_login(url, payload)

    def login_mobile(self, mobile: str, mpin: str) -> dict:
        """
        Log in with your registered mobile number and MPIN.

        Parameters
        ----------
        mobile : str
            10-digit mobile number.
        mpin : str
            4–6 digit MPIN.

        Returns
        -------
        dict

        Examples
        --------
        >>> se.login_mobile("9876543210", "1234")
        """
        url     = _API + _EP["login_mobile"]
        payload = {"MobileNumber": mobile, "MPIN": mpin, "DeviceType": "W"}
        return self._do_login(url, payload)

    def send_otp(self, mobile: str) -> dict:
        """
        Request an OTP SMS.

        Parameters
        ----------
        mobile : str

        Returns
        -------
        dict
        """
        url     = _API + _EP["send_otp"]
        payload = {"MobileNumber": mobile, "DeviceType": "W"}
        resp    = self._session.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        logger.info("OTP sent to %s.", mobile)
        return resp.json()

    def login_otp(self, mobile: str, otp: str) -> dict:
        """
        Complete OTP login.

        Parameters
        ----------
        mobile : str
        otp : str

        Returns
        -------
        dict
        """
        url     = _API + _EP["login_otp"]
        payload = {"MobileNumber": mobile, "OTP": otp, "DeviceType": "W"}
        return self._do_login(url, payload)

    def _do_login(self, url: str, payload: dict) -> dict:
        """POST credentials and store the returned Bearer token."""
        resp = self._session.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()

        # Token field name varies slightly across API versions
        token = (
            data.get("Token")
            or data.get("token")
            or data.get("AuthToken")
            or _deep(data, "Data", "Token")
            or _deep(data, "Result", "Token")
        )
        user_id = (
            data.get("UserId")
            or data.get("userId")
            or _deep(data, "Data", "UserId")
            or _deep(data, "Result", "UserId")
        )

        if token:
            self._token   = token
            self._user_id = user_id
            self._session.headers["Authorization"] = f"Bearer {token}"
            self._save_session()
            logger.info("Login successful (user_id=%s).", user_id)
        else:
            logger.warning(
                "Login POST succeeded but no token in response. "
                "Raw response: %s", json.dumps(data, indent=2)
            )
        return data

    def logout(self) -> None:
        """Clear the cached auth token."""
        self._token   = None
        self._user_id = None
        self._session.headers.pop("Authorization", None)
        if os.path.exists(self._token_file):
            os.remove(self._token_file)
        logger.info("Logged out.")

    def get_user_profile(self) -> dict:
        """Return the profile of the currently authenticated user."""
        self._require_auth()
        return self._get(_EP["user_profile"])

    # ------------------------------------------------------------------
    # Internal HTTP
    # ------------------------------------------------------------------

    def _require_auth(self) -> None:
        if not self._token:
            raise RuntimeError(
                "Not logged in.  Call se.login('email', 'password') first."
            )

    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        url = _API + path
        for attempt in range(3):
            try:
                resp = self._session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 401:
                    raise PermissionError(
                        "Session expired — call se.login() again."
                    )
                resp.raise_for_status()
                return resp.json()
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt < 2:
                    delay = 2 ** attempt
                    logger.warning("Network error (%s). Retrying in %ds…", exc, delay)
                    time.sleep(delay)
                else:
                    raise

    # ------------------------------------------------------------------
    # Search / company
    # ------------------------------------------------------------------

    def search(self, query: str) -> pd.DataFrame:
        """
        Search for a company, ETF, or index by name or symbol.

        Parameters
        ----------
        query : str
            E.g. ``"Reliance"``, ``"TCS"``, ``"HDFC Bank"``.

        Returns
        -------
        pd.DataFrame
            Key columns: ``SecurityId``, ``SecurityName``, ``SecurityCode``,
            ``ExchangeName``.  Pass ``SecurityId`` to all other methods.

        Examples
        --------
        >>> df = se.search("Infosys")
        >>> sid = int(df.iloc[0]["SecurityId"])
        """
        data = self._get(_EP["search"].format(q=query))
        return _df(data)

    def get_company_info(self, security_id: int) -> dict:
        """
        Company profile — sector, ISIN, market cap, listing date, etc.

        Parameters
        ----------
        security_id : int  (from :meth:`search`)

        Examples
        --------
        >>> se.get_company_info(2969)   # 2969 = Reliance Industries
        """
        return self._get(_EP["company_info"].format(sid=security_id))

    # ------------------------------------------------------------------
    # Financial statements
    # ------------------------------------------------------------------

    def get_financials(
        self, security_id: int, period: Period = Period.Annual
    ) -> pd.DataFrame:
        """
        Consolidated financial results — Revenue, PAT, EPS, etc.

        Parameters
        ----------
        security_id : int
        period : Period
            ``Period.Annual`` (default) or ``Period.Quarterly``.

        Examples
        --------
        >>> se.get_financials(2969)
        >>> se.get_financials(2969, Period.Quarterly)
        """
        self._require_auth()
        return _df(self._get(
            _EP["fin_results"].format(sid=security_id, p=period.value)
        ))

    def get_profit_loss(
        self, security_id: int, period: Period = Period.Annual
    ) -> pd.DataFrame:
        """
        Profit & Loss statement — Revenue, EBITDA, PAT, margins.

        Parameters
        ----------
        security_id : int
        period : Period

        Examples
        --------
        >>> se.get_profit_loss(2969)
        """
        self._require_auth()
        return _df(self._get(
            _EP["profit_loss"].format(sid=security_id, p=period.value)
        ))

    def get_balance_sheet(
        self, security_id: int, period: Period = Period.Annual
    ) -> pd.DataFrame:
        """
        Balance sheet — assets, liabilities, equity, borrowings.

        Parameters
        ----------
        security_id : int
        period : Period

        Examples
        --------
        >>> se.get_balance_sheet(2969)
        """
        self._require_auth()
        return _df(self._get(
            _EP["balance_sheet"].format(sid=security_id, p=period.value)
        ))

    def get_cash_flow(
        self, security_id: int, period: Period = Period.Annual
    ) -> pd.DataFrame:
        """
        Cash flow statement — operating, investing, financing.

        Parameters
        ----------
        security_id : int
        period : Period

        Examples
        --------
        >>> se.get_cash_flow(2969)
        """
        self._require_auth()
        return _df(self._get(
            _EP["cash_flow"].format(sid=security_id, p=period.value)
        ))

    def get_key_ratios(
        self, security_id: int, period: Period = Period.Annual
    ) -> pd.DataFrame:
        """
        Key ratios — P/E, ROE, ROCE, D/E, EPS, Book Value, …

        Parameters
        ----------
        security_id : int
        period : Period

        Examples
        --------
        >>> se.get_key_ratios(2969)
        """
        self._require_auth()
        return _df(self._get(
            _EP["key_ratios"].format(sid=security_id, p=period.value)
        ))

    def get_all_financials(
        self, security_id: int, period: Period = Period.Annual
    ) -> dict[str, pd.DataFrame]:
        """
        All five financial statements in one call.

        Returns
        -------
        dict with keys ``financial_results``, ``profit_loss``,
        ``balance_sheet``, ``cash_flow``, ``key_ratios``.

        Examples
        --------
        >>> fin = se.get_all_financials(2969)
        >>> fin["profit_loss"].head()
        """
        return {
            "financial_results": self.get_financials(security_id, period),
            "profit_loss":       self.get_profit_loss(security_id, period),
            "balance_sheet":     self.get_balance_sheet(security_id, period),
            "cash_flow":         self.get_cash_flow(security_id, period),
            "key_ratios":        self.get_key_ratios(security_id, period),
        }

    # ------------------------------------------------------------------
    # Portfolio / holdings
    # ------------------------------------------------------------------

    def get_shareholding(self, security_id: int) -> pd.DataFrame:
        """
        Shareholding pattern — promoters, FII, DII, retail (quarterly).

        Parameters
        ----------
        security_id : int

        Examples
        --------
        >>> se.get_shareholding(2969)
        """
        self._require_auth()
        return _df(self._get(_EP["shareholding"].format(sid=security_id)))

    def get_mf_holdings(self, security_id: int) -> pd.DataFrame:
        """
        Mutual fund holdings — which funds own the stock, how much.

        Parameters
        ----------
        security_id : int

        Examples
        --------
        >>> se.get_mf_holdings(2969)
        """
        self._require_auth()
        return _df(self._get(_EP["mf_holdings"].format(sid=security_id)))

    def get_fii_holdings(self, security_id: int) -> pd.DataFrame:
        """
        FII / FPI holdings history.

        Parameters
        ----------
        security_id : int

        Examples
        --------
        >>> se.get_fii_holdings(2969)
        """
        self._require_auth()
        return _df(self._get(_EP["fii_holdings"].format(sid=security_id)))

    def get_bulk_deals(self, security_id: int) -> pd.DataFrame:
        """
        Bulk and block deal disclosures.

        Parameters
        ----------
        security_id : int

        Examples
        --------
        >>> se.get_bulk_deals(2969)
        """
        self._require_auth()
        return _df(self._get(_EP["bulk_deals"].format(sid=security_id)))

    def get_insider_trading(self, security_id: int) -> pd.DataFrame:
        """
        Promoter / insider buy-sell disclosures.

        Parameters
        ----------
        security_id : int

        Examples
        --------
        >>> se.get_insider_trading(2969)
        """
        self._require_auth()
        return _df(self._get(_EP["insider_trading"].format(sid=security_id)))

    def get_all_portfolio_data(
        self, security_id: int
    ) -> dict[str, pd.DataFrame]:
        """
        All ownership / portfolio data in one call.

        Returns
        -------
        dict with keys ``shareholding``, ``mf_holdings``, ``fii_holdings``,
        ``bulk_deals``, ``insider_trading``.

        Examples
        --------
        >>> port = se.get_all_portfolio_data(2969)
        >>> port["shareholding"]
        """
        return {
            "shareholding":    self.get_shareholding(security_id),
            "mf_holdings":     self.get_mf_holdings(security_id),
            "fii_holdings":    self.get_fii_holdings(security_id),
            "bulk_deals":      self.get_bulk_deals(security_id),
            "insider_trading": self.get_insider_trading(security_id),
        }

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def get_peer_comparison(self, security_id: int) -> pd.DataFrame:
        """
        Sector peers with key metrics side-by-side.

        Parameters
        ----------
        security_id : int

        Examples
        --------
        >>> se.get_peer_comparison(2969)
        """
        self._require_auth()
        return _df(self._get(_EP["peer_comparison"].format(sid=security_id)))

    def get_price_history(self, security_id: int) -> pd.DataFrame:
        """
        Historical OHLCV prices.

        Parameters
        ----------
        security_id : int

        Examples
        --------
        >>> se.get_price_history(2969)
        """
        self._require_auth()
        return _df(self._get(_EP["price_history"].format(sid=security_id)))

    def get_edge_report(self, security_id: int) -> pd.DataFrame:
        """
        StockEdge curated Edge Report.

        Parameters
        ----------
        security_id : int

        Examples
        --------
        >>> se.get_edge_report(2969)
        """
        self._require_auth()
        return _df(self._get(_EP["edge_report"].format(sid=security_id)))

    # ------------------------------------------------------------------
    # Properties / dunder
    # ------------------------------------------------------------------

    @property
    def is_logged_in(self) -> bool:
        return bool(self._token)

    def __repr__(self) -> str:
        state = f"user_id={self._user_id}" if self._token else "not logged in"
        return f"StockEdge({state})"


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _df(data: Any) -> pd.DataFrame:
    """Coerce a JSON response (list | dict | None) into a DataFrame."""
    if data is None:
        return pd.DataFrame()
    if isinstance(data, list):
        return pd.DataFrame(data)
    if isinstance(data, dict):
        for key in ("Data", "data", "Result", "result", "Items", "items", "Records"):
            if key in data and isinstance(data[key], list):
                return pd.DataFrame(data[key])
        return pd.DataFrame([data])
    return pd.DataFrame()


def _deep(d: dict, *keys: str) -> Any:
    """Safely traverse nested dicts: _deep(d, 'Data', 'Token')."""
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d
