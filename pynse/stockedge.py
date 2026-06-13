"""
StockEdge web scraper — extracts company financial and portfolio data.

StockEdge (stockedge.com / web.stockedge.com) uses a REST API at
api.stockedge.com.  This module authenticates with your StockEdge account
using e-mail + password (or mobile MPIN / OTP), then exposes methods for
financials, portfolio holdings, and more.

Quick start
-----------
>>> from pynse.stockedge import StockEdge, Period
>>> se = StockEdge()
>>> se.login(email="you@example.com", password="yourpassword")
>>> results = se.search("Reliance")
>>> security_id = results.iloc[0]["SecurityId"]
>>> se.get_profit_loss(security_id)
>>> se.get_balance_sheet(security_id)
>>> se.get_cash_flow(security_id)
>>> se.get_key_ratios(security_id)
>>> se.get_shareholding(security_id)
>>> se.get_mf_holdings(security_id)
"""

import enum
import logging
import os
import pickle
import time
from typing import Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Base URLs and endpoint map
# ---------------------------------------------------------------------------

_API_BASE = "https://api.stockedge.com/Api"
_WEB_BASE = "https://web.stockedge.com"
_SITE_BASE = "https://stockedge.com"

_ENDPOINTS: dict[str, str] = {
    # --- Authentication ---
    "login_email":          "/UserRegistrationApi/LoginWithEmailAndPassword",
    "login_mobile":         "/UserRegistrationApi/LoginWithMobileNumberAndMPIN",
    "send_otp":             "/UserRegistrationApi/GenerateOTPForLogin",
    "login_otp":            "/UserRegistrationApi/LoginWithMobileNumberAndOTP",
    "user_profile":         "/UserRegistrationApi/GetUserProfile",

    # --- Search ---
    "search":               "/DashboardApi/GetSearchedEntityList/{query}/0",
    "all_securities":       "/SecurityApi/GetAllSecurities/0",

    # --- Company info ---
    "company_info":         "/DashboardApi/GetCompanyBySecurityId/{sid}",

    # --- Financial statements (period: 0=annual, 1=quarterly) ---
    "financial_results":    "/SecurityDashboardApi/GetFinancialResultsForSecurity/{sid}/{period}",
    "balance_sheet":        "/SecurityDashboardApi/GetBalanceSheetForSecurity/{sid}/{period}",
    "profit_loss":          "/SecurityDashboardApi/GetProfitAndLossForSecurity/{sid}/{period}",
    "cash_flow":            "/SecurityDashboardApi/GetCashFlowForSecurity/{sid}/{period}",
    "key_ratios":           "/SecurityDashboardApi/GetKeyRatiosForSecurity/{sid}/{period}",

    # --- Portfolio / holdings ---
    "shareholding":         "/SecurityDashboardApi/GetShareholdingPatternForSecurity/{sid}/10",
    "mf_holdings":          "/SecurityDashboardApi/GetMutualFundHoldingForSecurity/{sid}/10",
    "fii_holdings":         "/SecurityDashboardApi/GetFIIHoldingForSecurity/{sid}/10",
    "bulk_deals":           "/SecurityDashboardApi/GetBulkAndBlockDealForSecurity/{sid}/10",
    "insider_trading":      "/SecurityDashboardApi/GetInsiderTradingForSecurity/{sid}/10",

    # --- Misc ---
    "peer_comparison":      "/SecurityDashboardApi/GetPeerComparisonForSecurity/{sid}",
    "price_history":        "/SecurityDashboardApi/GetPriceHistoryForSecurity/{sid}/10",
    "edge_report":          "/SecurityDashboardApi/GetEdgeReportForSecurity/{sid}",
}

_BROWSER_HEADERS: dict[str, str] = {
    "Accept":           "application/json, text/plain, */*",
    "Accept-Language":  "en-US,en;q=0.9",
    "Accept-Encoding":  "gzip, deflate, br",
    "Connection":       "keep-alive",
    "Origin":           _WEB_BASE,
    "Referer":          _WEB_BASE + "/",
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
    """Period type for financial statements."""
    Annual = 0
    Quarterly = 1


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class StockEdge:
    """
    Client for StockEdge (stockedge.com) financial data.

    Authentication
    --------------
    Login once with your StockEdge credentials.  The session token is cached
    to ``~/.pynse/stockedge/session.pkl`` so you don't need to log in on
    every run.

    >>> se = StockEdge()
    >>> se.login(email="you@example.com", password="secret")

    Mobile login (MPIN):
    >>> se.login(mobile="9876543210", mpin="1234")

    Mobile login (OTP):
    >>> se.send_otp("9876543210")
    >>> se.login_with_otp("9876543210", "654321")

    Data methods
    ------------
    All data methods return a ``pandas.DataFrame``.

    Parameters
    ----------
    timeout : int
        HTTP request timeout in seconds (default 20).
    cache_dir : str, optional
        Directory used to cache the auth session.
        Defaults to ``~/.pynse/stockedge/``.
    """

    def __init__(self, timeout: int = 20, cache_dir: Optional[str] = None):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(_BROWSER_HEADERS)

        self._token: Optional[str] = None
        self._user_id: Optional[int] = None

        cache_root = cache_dir or os.path.join(
            os.path.expanduser("~"), ".pynse", "stockedge"
        )
        os.makedirs(cache_root, exist_ok=True)
        self._cache_dir = cache_root
        self._token_file = os.path.join(cache_root, "session.pkl")

        self._load_cached_session()

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------

    def _load_cached_session(self) -> None:
        if not os.path.exists(self._token_file):
            return
        try:
            with open(self._token_file, "rb") as f:
                data = pickle.load(f)
            self._token = data.get("token")
            self._user_id = data.get("user_id")
            if self._token:
                self._session.headers["Authorization"] = f"Bearer {self._token}"
                logger.debug("Loaded cached StockEdge session (user_id=%s).", self._user_id)
        except Exception as exc:
            logger.warning("Could not load cached session: %s", exc)

    def _persist_session(self) -> None:
        with open(self._token_file, "wb") as f:
            pickle.dump({"token": self._token, "user_id": self._user_id}, f)
        logger.debug("Session saved to %s", self._token_file)

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def login(
        self,
        *,
        email: Optional[str] = None,
        password: Optional[str] = None,
        mobile: Optional[str] = None,
        mpin: Optional[str] = None,
    ) -> dict:
        """
        Log in to StockEdge.

        Supply either ``email`` + ``password`` (web account)
        or ``mobile`` + ``mpin`` (app account).

        Parameters
        ----------
        email : str, optional
            E-mail address registered with StockEdge.
        password : str, optional
            Account password.
        mobile : str, optional
            10-digit mobile number registered with StockEdge.
        mpin : str, optional
            4–6 digit MPIN set in the StockEdge app.

        Returns
        -------
        dict  Raw API response.

        Examples
        --------
        >>> se.login(email="you@example.com", password="secret")
        >>> se.login(mobile="9876543210", mpin="1234")
        """
        if email and password:
            url = _API_BASE + _ENDPOINTS["login_email"]
            payload = {
                "Email": email,
                "Password": password,
                "DeviceType": "W",
            }
        elif mobile and mpin:
            url = _API_BASE + _ENDPOINTS["login_mobile"]
            payload = {
                "MobileNumber": mobile,
                "MPIN": mpin,
                "DeviceType": "W",
            }
        else:
            raise ValueError(
                "Provide either (email + password) or (mobile + mpin)."
            )
        return self._execute_login(url, payload)

    def send_otp(self, mobile: str) -> dict:
        """
        Request an OTP SMS to *mobile*.

        Parameters
        ----------
        mobile : str
            10-digit mobile number.

        Returns
        -------
        dict  API response (check IsSuccess field).
        """
        url = _API_BASE + _ENDPOINTS["send_otp"]
        payload = {"MobileNumber": mobile, "DeviceType": "W"}
        resp = self._session.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        logger.info("OTP sent to %s", mobile)
        return resp.json()

    def login_with_otp(self, mobile: str, otp: str) -> dict:
        """
        Complete OTP-based login.

        Parameters
        ----------
        mobile : str
        otp : str
            One-time password from SMS.

        Returns
        -------
        dict  Raw API response.
        """
        url = _API_BASE + _ENDPOINTS["login_otp"]
        payload = {"MobileNumber": mobile, "OTP": otp, "DeviceType": "W"}
        return self._execute_login(url, payload)

    def _execute_login(self, url: str, payload: dict) -> dict:
        resp = self._session.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()

        # Token may be nested under different keys depending on API version
        token = (
            data.get("Token")
            or data.get("token")
            or data.get("AuthToken")
            or (data.get("Data") or {}).get("Token")
            or (data.get("Result") or {}).get("Token")
        )
        user_id = (
            data.get("UserId")
            or data.get("userId")
            or (data.get("Data") or {}).get("UserId")
            or (data.get("Result") or {}).get("UserId")
        )

        if token:
            self._token = token
            self._user_id = user_id
            self._session.headers["Authorization"] = f"Bearer {token}"
            self._persist_session()
            logger.info("StockEdge login successful (user_id=%s).", user_id)
        else:
            logger.warning(
                "Login response received but no token found. "
                "Check credentials or inspect the response: %s", data
            )

        return data

    def get_user_profile(self) -> dict:
        """Return the authenticated user's profile."""
        self._require_auth()
        return self._get(_ENDPOINTS["user_profile"])

    def logout(self) -> None:
        """Clear the cached session."""
        self._token = None
        self._user_id = None
        self._session.headers.pop("Authorization", None)
        if os.path.exists(self._token_file):
            os.remove(self._token_file)
        logger.info("Logged out and cleared cached session.")

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    def _require_auth(self) -> None:
        if not self._token:
            raise RuntimeError(
                "Not authenticated. "
                "Call se.login(email='...', password='...') first."
            )

    def _get(self, path: str, params: Optional[dict] = None, retries: int = 3):
        url = _API_BASE + path
        for attempt in range(retries):
            try:
                resp = self._session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 401:
                    raise PermissionError(
                        "Session expired or unauthorized. "
                        "Call se.login(...) to re-authenticate."
                    )
                resp.raise_for_status()
                return resp.json()
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt < retries - 1:
                    delay = 2 ** attempt
                    logger.warning("Request failed (%s). Retrying in %ds…", exc, delay)
                    time.sleep(delay)
                else:
                    raise

    def _post(self, path: str, payload: dict, retries: int = 3):
        url = _API_BASE + path
        for attempt in range(retries):
            try:
                resp = self._session.post(url, json=payload, timeout=self.timeout)
                resp.raise_for_status()
                return resp.json()
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt < retries - 1:
                    delay = 2 ** attempt
                    logger.warning("Request failed (%s). Retrying in %ds…", exc, delay)
                    time.sleep(delay)
                else:
                    raise

    # ------------------------------------------------------------------
    # Search and company info
    # ------------------------------------------------------------------

    def search(self, query: str) -> pd.DataFrame:
        """
        Search for stocks, ETFs, or indices by name or ticker.

        Parameters
        ----------
        query : str
            Company name or NSE/BSE symbol  (e.g. ``"Reliance"`` or ``"TCS"``).

        Returns
        -------
        pd.DataFrame
            Columns include ``SecurityId``, ``SecurityName``, ``SecurityCode``,
            ``ExchangeName``, ``Sector``.  Use ``SecurityId`` as the key for
            all other methods.

        Examples
        --------
        >>> df = se.search("Infosys")
        >>> security_id = df.iloc[0]["SecurityId"]
        """
        path = _ENDPOINTS["search"].format(query=query)
        data = self._get(path)
        return _to_df(data)

    def get_company_info(self, security_id: int) -> dict:
        """
        Detailed company profile for *security_id*.

        Parameters
        ----------
        security_id : int
            StockEdge SecurityId (obtain via :meth:`search`).

        Returns
        -------
        dict  Company metadata (name, sector, ISIN, market cap, …).

        Examples
        --------
        >>> se.get_company_info(2969)   # Reliance Industries
        """
        path = _ENDPOINTS["company_info"].format(sid=security_id)
        return self._get(path)

    # ------------------------------------------------------------------
    # Financial statements
    # ------------------------------------------------------------------

    def get_financials(
        self,
        security_id: int,
        period: Period = Period.Annual,
    ) -> pd.DataFrame:
        """
        Consolidated financial results (Revenue, PAT, EPS, …).

        Parameters
        ----------
        security_id : int
        period : Period
            ``Period.Annual`` (default) or ``Period.Quarterly``.

        Returns
        -------
        pd.DataFrame

        Examples
        --------
        >>> se.get_financials(2969)
        >>> se.get_financials(2969, period=Period.Quarterly)
        """
        self._require_auth()
        path = _ENDPOINTS["financial_results"].format(
            sid=security_id, period=period.value
        )
        return _to_df(self._get(path))

    def get_profit_loss(
        self,
        security_id: int,
        period: Period = Period.Annual,
    ) -> pd.DataFrame:
        """
        Profit & Loss statement (Revenue, EBITDA, PAT, margins).

        Parameters
        ----------
        security_id : int
        period : Period

        Returns
        -------
        pd.DataFrame

        Examples
        --------
        >>> se.get_profit_loss(2969)
        """
        self._require_auth()
        path = _ENDPOINTS["profit_loss"].format(
            sid=security_id, period=period.value
        )
        return _to_df(self._get(path))

    def get_balance_sheet(
        self,
        security_id: int,
        period: Period = Period.Annual,
    ) -> pd.DataFrame:
        """
        Balance sheet (total assets, liabilities, equity, borrowings, …).

        Parameters
        ----------
        security_id : int
        period : Period

        Returns
        -------
        pd.DataFrame

        Examples
        --------
        >>> se.get_balance_sheet(2969)
        """
        self._require_auth()
        path = _ENDPOINTS["balance_sheet"].format(
            sid=security_id, period=period.value
        )
        return _to_df(self._get(path))

    def get_cash_flow(
        self,
        security_id: int,
        period: Period = Period.Annual,
    ) -> pd.DataFrame:
        """
        Cash flow statement (operating, investing, financing).

        Parameters
        ----------
        security_id : int
        period : Period

        Returns
        -------
        pd.DataFrame

        Examples
        --------
        >>> se.get_cash_flow(2969)
        """
        self._require_auth()
        path = _ENDPOINTS["cash_flow"].format(
            sid=security_id, period=period.value
        )
        return _to_df(self._get(path))

    def get_key_ratios(
        self,
        security_id: int,
        period: Period = Period.Annual,
    ) -> pd.DataFrame:
        """
        Key financial ratios (P/E, ROE, ROCE, D/E, EPS, Book Value, …).

        Parameters
        ----------
        security_id : int
        period : Period

        Returns
        -------
        pd.DataFrame

        Examples
        --------
        >>> se.get_key_ratios(2969)
        """
        self._require_auth()
        path = _ENDPOINTS["key_ratios"].format(
            sid=security_id, period=period.value
        )
        return _to_df(self._get(path))

    def get_all_financials(
        self,
        security_id: int,
        period: Period = Period.Annual,
    ) -> dict[str, pd.DataFrame]:
        """
        Fetch all five financial statements in one call.

        Returns
        -------
        dict with keys:
            ``financial_results``, ``profit_loss``, ``balance_sheet``,
            ``cash_flow``, ``key_ratios``

        Examples
        --------
        >>> fin = se.get_all_financials(2969)
        >>> fin["profit_loss"]
        >>> fin["balance_sheet"]
        """
        return {
            "financial_results": self.get_financials(security_id, period),
            "profit_loss":       self.get_profit_loss(security_id, period),
            "balance_sheet":     self.get_balance_sheet(security_id, period),
            "cash_flow":         self.get_cash_flow(security_id, period),
            "key_ratios":        self.get_key_ratios(security_id, period),
        }

    # ------------------------------------------------------------------
    # Portfolio / holdings data
    # ------------------------------------------------------------------

    def get_shareholding(self, security_id: int) -> pd.DataFrame:
        """
        Shareholding pattern — promoters, FII, DII, public (quarterly).

        Parameters
        ----------
        security_id : int

        Returns
        -------
        pd.DataFrame  Rows per category with percentage holdings over time.

        Examples
        --------
        >>> se.get_shareholding(2969)
        """
        self._require_auth()
        path = _ENDPOINTS["shareholding"].format(sid=security_id)
        return _to_df(self._get(path))

    def get_mf_holdings(self, security_id: int) -> pd.DataFrame:
        """
        Mutual fund holdings — funds that own the stock, quantity, and value.

        Parameters
        ----------
        security_id : int

        Returns
        -------
        pd.DataFrame

        Examples
        --------
        >>> se.get_mf_holdings(2969)
        """
        self._require_auth()
        path = _ENDPOINTS["mf_holdings"].format(sid=security_id)
        return _to_df(self._get(path))

    def get_fii_holdings(self, security_id: int) -> pd.DataFrame:
        """
        FII (Foreign Institutional Investor) holdings history.

        Parameters
        ----------
        security_id : int

        Returns
        -------
        pd.DataFrame

        Examples
        --------
        >>> se.get_fii_holdings(2969)
        """
        self._require_auth()
        path = _ENDPOINTS["fii_holdings"].format(sid=security_id)
        return _to_df(self._get(path))

    def get_bulk_deals(self, security_id: int) -> pd.DataFrame:
        """
        Bulk and block deal history (buyer, seller, quantity, price).

        Parameters
        ----------
        security_id : int

        Returns
        -------
        pd.DataFrame

        Examples
        --------
        >>> se.get_bulk_deals(2969)
        """
        self._require_auth()
        path = _ENDPOINTS["bulk_deals"].format(sid=security_id)
        return _to_df(self._get(path))

    def get_insider_trading(self, security_id: int) -> pd.DataFrame:
        """
        Insider / promoter trading disclosures.

        Parameters
        ----------
        security_id : int

        Returns
        -------
        pd.DataFrame

        Examples
        --------
        >>> se.get_insider_trading(2969)
        """
        self._require_auth()
        path = _ENDPOINTS["insider_trading"].format(sid=security_id)
        return _to_df(self._get(path))

    def get_all_portfolio_data(
        self, security_id: int
    ) -> dict[str, pd.DataFrame]:
        """
        Fetch all portfolio / ownership data in one call.

        Returns
        -------
        dict with keys:
            ``shareholding``, ``mf_holdings``, ``fii_holdings``,
            ``bulk_deals``, ``insider_trading``

        Examples
        --------
        >>> port = se.get_all_portfolio_data(2969)
        >>> port["shareholding"]
        >>> port["mf_holdings"]
        """
        return {
            "shareholding":    self.get_shareholding(security_id),
            "mf_holdings":     self.get_mf_holdings(security_id),
            "fii_holdings":    self.get_fii_holdings(security_id),
            "bulk_deals":      self.get_bulk_deals(security_id),
            "insider_trading": self.get_insider_trading(security_id),
        }

    # ------------------------------------------------------------------
    # Misc / other data
    # ------------------------------------------------------------------

    def get_peer_comparison(self, security_id: int) -> pd.DataFrame:
        """
        Sector peers with key metrics side-by-side.

        Parameters
        ----------
        security_id : int

        Returns
        -------
        pd.DataFrame

        Examples
        --------
        >>> se.get_peer_comparison(2969)
        """
        self._require_auth()
        path = _ENDPOINTS["peer_comparison"].format(sid=security_id)
        return _to_df(self._get(path))

    def get_price_history(self, security_id: int) -> pd.DataFrame:
        """
        Historical OHLCV price data.

        Parameters
        ----------
        security_id : int

        Returns
        -------
        pd.DataFrame  Columns: Date, Open, High, Low, Close, Volume, …

        Examples
        --------
        >>> se.get_price_history(2969)
        """
        self._require_auth()
        path = _ENDPOINTS["price_history"].format(sid=security_id)
        return _to_df(self._get(path))

    def get_edge_report(self, security_id: int) -> pd.DataFrame:
        """
        StockEdge Edge Report — curated analysis summary for the company.

        Parameters
        ----------
        security_id : int

        Returns
        -------
        pd.DataFrame

        Examples
        --------
        >>> se.get_edge_report(2969)
        """
        self._require_auth()
        path = _ENDPOINTS["edge_report"].format(sid=security_id)
        return _to_df(self._get(path))

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    @property
    def is_logged_in(self) -> bool:
        """True if an auth token is present in the session."""
        return self._token is not None

    def __repr__(self) -> str:
        state = f"user_id={self._user_id}" if self._token else "not authenticated"
        return f"StockEdge({state})"


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _to_df(data) -> pd.DataFrame:
    """Convert a JSON API response (list | dict | None) to a DataFrame."""
    if data is None:
        return pd.DataFrame()
    if isinstance(data, list):
        return pd.DataFrame(data)
    if isinstance(data, dict):
        # Many StockEdge endpoints wrap records under a specific key
        for key in ("Data", "data", "Result", "result", "Items", "items", "Records"):
            if key in data and isinstance(data[key], list):
                return pd.DataFrame(data[key])
        # Flat dict — single record
        return pd.DataFrame([data])
    return pd.DataFrame()
