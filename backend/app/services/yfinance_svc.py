"""yfinance wrapper for real-time prices, key metrics, and supplemental data.

Retry strategy: each sync helper raises on transient errors (network, timeout)
so the _retry_sync wrapper can catch and retry with backoff. Returns None for
"no data found" (not transient — don't retry). Retries happen inside the thread
pool executor so backoff sleeps don't block the async event loop.
"""

import asyncio
import logging
import time
from functools import partial

import yfinance as yf
from app.utils.rate_limiter import yfinance_rate_limiter

logger = logging.getLogger(__name__)

try:
    from curl_cffi.requests import Session
    _session = Session(impersonate="chrome")
except ImportError:
    _session = None

# Retry config: 3 total attempts with 1s, 2s backoff between retries
_MAX_RETRIES = 3
_RETRY_BACKOFF = [1.0, 2.0]


def _retry_sync(fn, *args):
    """Retry a synchronous yfinance call with backoff.

    Distinguishes two failure modes:
    - Exception raised → transient error (network, timeout) → retry
    - None returned → no data for this ticker (delisted, invalid) → don't retry
    """
    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            result = fn(*args)
            return result  # None or valid data — either way, don't retry
        except Exception as e:
            last_exc = e
            if attempt < _MAX_RETRIES - 1:
                delay = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                logger.warning(
                    "yfinance attempt %d/%d failed for %s: %s — retrying in %.1fs",
                    attempt + 1, _MAX_RETRIES, args[0] if args else "?", e, delay,
                )
                time.sleep(delay)
    logger.error("yfinance exhausted %d retries for %s: %s", _MAX_RETRIES, args[0] if args else "?", last_exc)
    return None


def _ticker(symbol: str) -> yf.Ticker:
    """Create a Ticker with browser-impersonating session if available."""
    if _session:
        return yf.Ticker(symbol, session=_session)
    return yf.Ticker(symbol)


def _get_stock_info_sync(ticker: str) -> dict | None:
    """Synchronous helper — runs in a thread pool.

    Raises on network/timeout errors so _retry_sync can retry.
    Returns None when ticker has no data (not an error, don't retry).
    """
    stock = _ticker(ticker)
    info = stock.info

    # No data for this ticker — not a transient error
    if not info or info.get("regularMarketPrice") is None:
        return None

    return {
        "ticker": ticker.upper(),
        "name": info.get("longName") or info.get("shortName", ""),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "exchange": info.get("exchange"),
        "price": info.get("regularMarketPrice") or info.get("currentPrice"),
        "market_cap": info.get("marketCap"),
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "pb_ratio": info.get("priceToBook"),
        "ps_ratio": info.get("priceToSalesTrailing12Months"),
        "debt_to_equity": info.get("debtToEquity"),
        "current_ratio": info.get("currentRatio"),
        "roe": info.get("returnOnEquity"),
        "roa": info.get("returnOnAssets"),
        "net_margin": info.get("profitMargins"),
        "gross_margin": info.get("grossMargins"),
        "operating_margin": info.get("operatingMargins"),
        "eps": info.get("trailingEps"),
        "revenue_growth": info.get("revenueGrowth"),
        "earnings_growth": info.get("earningsGrowth"),
        "free_cash_flow": info.get("freeCashflow"),
        "total_revenue": info.get("totalRevenue"),
        "dividend_yield": info.get("dividendYield"),
        "beta": info.get("beta"),
        "book_value": info.get("bookValue"),
        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
        "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
    }


async def get_stock_info(ticker: str) -> dict | None:
    """Get current stock info and key metrics from yfinance.

    Returns a flat dict of key metrics, or None if ticker not found / all retries failed.
    Rate limiter acquired once per logical request (not per retry attempt).
    """
    await yfinance_rate_limiter.acquire()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, partial(_retry_sync, _get_stock_info_sync, ticker)
    )


def _get_price_history_sync(ticker: str, period: str) -> list[dict]:
    """Synchronous helper — runs in a thread pool.

    Raises on network/timeout errors so _retry_sync can retry.
    Returns empty list when no history available.
    """
    stock = _ticker(ticker)
    hist = stock.history(period=period)
    if hist.empty:
        return []
    return [
        {
            "date": idx.strftime("%Y-%m-%d"),
            "open": row["Open"],
            "high": row["High"],
            "low": row["Low"],
            "close": row["Close"],
            "volume": int(row["Volume"]),
        }
        for idx, row in hist.iterrows()
    ]


async def get_price_history(ticker: str, period: str = "5y") -> list[dict]:
    """Get historical price data.

    Args:
        ticker: Stock ticker symbol.
        period: Time period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max).
    """
    await yfinance_rate_limiter.acquire()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, partial(_retry_sync, _get_price_history_sync, ticker, period)
    )


def _get_insider_transactions_sync(ticker: str) -> list[dict]:
    """Synchronous helper — runs in a thread pool.

    Raises on network/timeout errors so _retry_sync can retry.
    Returns empty list when no insider data available.
    """
    stock = _ticker(ticker)
    insiders = stock.insider_transactions
    if insiders is None or insiders.empty:
        return []
    return insiders.head(50).to_dict("records")


async def get_insider_transactions(ticker: str) -> list[dict]:
    """Get recent insider transactions."""
    await yfinance_rate_limiter.acquire()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, partial(_retry_sync, _get_insider_transactions_sync, ticker)
    )
