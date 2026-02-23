"""yfinance wrapper for real-time prices, key metrics, and supplemental data."""

import yfinance as yf
from app.utils.rate_limiter import yfinance_rate_limiter


async def get_stock_info(ticker: str) -> dict | None:
    """Get current stock info and key metrics from yfinance.

    Returns a flat dict of key metrics, or None if ticker not found.
    """
    await yfinance_rate_limiter.acquire()
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

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
    except Exception:
        return None


async def get_price_history(ticker: str, period: str = "5y") -> list[dict]:
    """Get historical price data.

    Args:
        ticker: Stock ticker symbol.
        period: Time period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max).
    """
    await yfinance_rate_limiter.acquire()
    try:
        stock = yf.Ticker(ticker)
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
    except Exception:
        return []


async def get_insider_transactions(ticker: str) -> list[dict]:
    """Get recent insider transactions."""
    await yfinance_rate_limiter.acquire()
    try:
        stock = yf.Ticker(ticker)
        insiders = stock.insider_transactions
        if insiders is None or insiders.empty:
            return []
        return insiders.head(50).to_dict("records")
    except Exception:
        return []
