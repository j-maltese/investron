"""Alpaca Markets API client — thin wrapper around alpaca-py.

Isolates all direct Alpaca SDK calls so strategy services never import alpaca-py
directly. Provides a cached client singleton and typed helper functions.

Paper vs live trading is controlled by ALPACA_BASE_URL in config:
  - Paper: https://paper-api.alpaca.markets (default)
  - Live:  https://api.alpaca.markets
"""

import logging
from functools import lru_cache

from app.config import get_settings

logger = logging.getLogger(__name__)


class AlpacaError(Exception):
    """Raised when an Alpaca API call fails."""
    pass


def _check_configured() -> None:
    """Raise if Alpaca API keys are not set."""
    settings = get_settings()
    if not settings.alpaca_api_key or not settings.alpaca_secret_key:
        raise AlpacaError("Alpaca API keys not configured")


@lru_cache
def get_trading_client():
    """Return a cached TradingClient instance configured for paper or live."""
    from alpaca.trading.client import TradingClient

    settings = get_settings()
    _check_configured()

    is_paper = "paper" in settings.alpaca_base_url
    logger.info("Initializing Alpaca TradingClient (paper=%s)", is_paper)

    return TradingClient(
        api_key=settings.alpaca_api_key,
        secret_key=settings.alpaca_secret_key,
        paper=is_paper,
    )


@lru_cache
def get_stock_data_client():
    """Return a cached StockHistoricalDataClient for market data."""
    from alpaca.data.historical import StockHistoricalDataClient

    settings = get_settings()
    _check_configured()

    return StockHistoricalDataClient(
        api_key=settings.alpaca_api_key,
        secret_key=settings.alpaca_secret_key,
    )


@lru_cache
def get_option_data_client():
    """Return a cached OptionHistoricalDataClient for options chain data."""
    from alpaca.data.historical import OptionHistoricalDataClient

    settings = get_settings()
    _check_configured()

    return OptionHistoricalDataClient(
        api_key=settings.alpaca_api_key,
        secret_key=settings.alpaca_secret_key,
    )


async def get_account_info() -> dict:
    """Get Alpaca account balance, portfolio value, and buying power."""
    try:
        client = get_trading_client()
        account = client.get_account()
        return {
            "cash": float(account.cash),
            "portfolio_value": float(account.portfolio_value),
            "buying_power": float(account.buying_power),
            "equity": float(account.equity),
            "status": account.status.value if account.status else "unknown",
        }
    except Exception as e:
        logger.error("Failed to get Alpaca account info: %s", e)
        raise AlpacaError(f"Account info failed: {e}") from e


async def get_positions() -> list[dict]:
    """Get all current Alpaca positions."""
    try:
        client = get_trading_client()
        positions = client.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "asset_class": p.asset_class.value if p.asset_class else "us_equity",
                "qty": float(p.qty),
                "side": p.side.value if p.side else "long",
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price) if p.current_price else None,
                "market_value": float(p.market_value) if p.market_value else None,
                "unrealized_pl": float(p.unrealized_pl) if p.unrealized_pl else None,
                "unrealized_plpc": float(p.unrealized_plpc) if p.unrealized_plpc else None,
            }
            for p in positions
        ]
    except Exception as e:
        logger.error("Failed to get Alpaca positions: %s", e)
        raise AlpacaError(f"Get positions failed: {e}") from e


async def submit_stock_order(
    ticker: str,
    qty: float,
    side: str,
    order_type: str = "market",
    limit_price: float | None = None,
    time_in_force: str = "day",
) -> dict:
    """Submit a stock order to Alpaca. Returns order details including alpaca_order_id."""
    from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    try:
        client = get_trading_client()
        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        tif = TimeInForce.DAY if time_in_force == "day" else TimeInForce.GTC

        if order_type == "limit" and limit_price is not None:
            request = LimitOrderRequest(
                symbol=ticker,
                qty=qty,
                side=order_side,
                time_in_force=tif,
                limit_price=limit_price,
            )
        else:
            request = MarketOrderRequest(
                symbol=ticker,
                qty=qty,
                side=order_side,
                time_in_force=tif,
            )

        order = client.submit_order(request)
        logger.info("Submitted %s order: %s %s x%.2f", order_type, side, ticker, qty)

        return {
            "alpaca_order_id": str(order.id),
            "status": order.status.value if order.status else "pending",
            "symbol": order.symbol,
            "qty": float(order.qty) if order.qty else qty,
            "side": side,
            "order_type": order_type,
            "filled_qty": float(order.filled_qty) if order.filled_qty else 0,
            "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
        }
    except Exception as e:
        logger.error("Failed to submit stock order %s %s: %s", side, ticker, e)
        raise AlpacaError(f"Order submission failed: {e}") from e


async def submit_option_order(
    option_symbol: str,
    qty: int,
    side: str,
    order_type: str = "limit",
    limit_price: float | None = None,
    time_in_force: str = "day",
) -> dict:
    """Submit an option order to Alpaca."""
    from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    try:
        client = get_trading_client()
        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        tif = TimeInForce.DAY if time_in_force == "day" else TimeInForce.GTC

        # Options typically use limit orders
        if limit_price is not None:
            request = LimitOrderRequest(
                symbol=option_symbol,
                qty=qty,
                side=order_side,
                time_in_force=tif,
                limit_price=limit_price,
            )
        else:
            request = MarketOrderRequest(
                symbol=option_symbol,
                qty=qty,
                side=order_side,
                time_in_force=tif,
            )

        order = client.submit_order(request)
        logger.info("Submitted option order: %s %s x%d", side, option_symbol, qty)

        return {
            "alpaca_order_id": str(order.id),
            "status": order.status.value if order.status else "pending",
            "symbol": order.symbol,
            "qty": qty,
            "side": side,
            "order_type": order_type,
            "filled_qty": float(order.filled_qty) if order.filled_qty else 0,
            "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
        }
    except Exception as e:
        logger.error("Failed to submit option order %s %s: %s", side, option_symbol, e)
        raise AlpacaError(f"Option order failed: {e}") from e


async def get_order_status(alpaca_order_id: str) -> dict:
    """Check the status of a specific order."""
    try:
        client = get_trading_client()
        order = client.get_order_by_id(alpaca_order_id)
        return {
            "alpaca_order_id": str(order.id),
            "status": order.status.value if order.status else "unknown",
            "filled_qty": float(order.filled_qty) if order.filled_qty else 0,
            "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
            "filled_at": order.filled_at.isoformat() if order.filled_at else None,
        }
    except Exception as e:
        logger.error("Failed to get order status %s: %s", alpaca_order_id, e)
        raise AlpacaError(f"Order status check failed: {e}") from e


async def cancel_order(alpaca_order_id: str) -> None:
    """Cancel an open order."""
    try:
        client = get_trading_client()
        client.cancel_order_by_id(alpaca_order_id)
        logger.info("Cancelled order %s", alpaca_order_id)
    except Exception as e:
        logger.error("Failed to cancel order %s: %s", alpaca_order_id, e)
        raise AlpacaError(f"Order cancel failed: {e}") from e


# ---------------------------------------------------------------------------
# OCC Symbol Helpers
# ---------------------------------------------------------------------------
# OCC (Options Clearing Corporation) symbols encode the underlying ticker,
# expiration date, option type, and strike price into a single string.
# Format: {TICKER}{YYMMDD}{P|C}{STRIKE*1000 zero-padded to 8 digits}
# Example: INTC260320P00035000 = INTC, 2026-03-20, Put, $35.00
# The ticker is variable-length (1-6 chars), so we parse from the RIGHT:
# the last 15 characters are always YYMMDD + P/C + 8-digit strike.


def parse_occ_symbol(symbol: str) -> dict:
    """Parse an OCC option symbol into its components.

    Example: 'INTC260320P00035000' -> {
        'underlying': 'INTC',
        'expiration': '2026-03-20',
        'option_type': 'put',
        'strike': 35.0,
    }

    The last 15 chars are always: YYMMDD (6) + P/C (1) + strike*1000 (8).
    Everything before that is the underlying ticker.
    """
    # Defensive: OCC symbols are at least 15 chars (1-char ticker + 15 suffix)
    if len(symbol) < 16:
        raise ValueError(f"Invalid OCC symbol (too short): {symbol}")

    # Split: ticker = everything before the last 15 chars
    suffix = symbol[-15:]
    underlying = symbol[:-15]

    # Parse the fixed-format suffix
    yy, mm, dd = suffix[0:2], suffix[2:4], suffix[4:6]
    option_char = suffix[6]  # 'P' for put, 'C' for call
    strike_raw = suffix[7:15]  # 8-digit integer = strike * 1000

    if option_char not in ("P", "C"):
        raise ValueError(f"Invalid option type '{option_char}' in OCC symbol: {symbol}")

    return {
        "underlying": underlying,
        "expiration": f"20{yy}-{mm}-{dd}",
        "option_type": "put" if option_char == "P" else "call",
        "strike": int(strike_raw) / 1000,
    }


def build_occ_symbol(
    underlying: str,
    expiration_date: str,
    option_type: str,
    strike: float,
) -> str:
    """Build an OCC option symbol from components.

    Args:
        underlying: Ticker symbol (e.g., 'INTC', 'F', 'SOFI')
        expiration_date: 'YYYY-MM-DD' format (e.g., '2026-03-20')
        option_type: 'put' or 'call'
        strike: Strike price as float (e.g., 35.0)

    Returns:
        OCC symbol string (e.g., 'INTC260320P00035000')
    """
    # Extract YY, MM, DD from the ISO date string
    yy = expiration_date[2:4]
    mm = expiration_date[5:7]
    dd = expiration_date[8:10]

    # P for put, C for call
    pc = "P" if option_type == "put" else "C"

    # Strike is stored as an integer = price * 1000, zero-padded to 8 digits
    strike_int = int(strike * 1000)

    return f"{underlying}{yy}{mm}{dd}{pc}{strike_int:08d}"


async def get_option_chain(
    ticker: str,
    expiration_date_gte: str | None = None,
    expiration_date_lte: str | None = None,
) -> list[dict]:
    """Fetch available options with greeks for a ticker.

    Returns a list of option contracts with strike, expiration, greeks, and bid/ask.
    Used by the Wheel strategy to find appropriate puts/calls to sell.
    """
    from alpaca.data.requests import OptionChainRequest

    try:
        client = get_option_data_client()
        request_params = {"underlying_symbol": ticker}
        if expiration_date_gte:
            request_params["expiration_date_gte"] = expiration_date_gte
        if expiration_date_lte:
            request_params["expiration_date_lte"] = expiration_date_lte

        request = OptionChainRequest(**request_params)
        chain = client.get_option_chain(request)

        results = []
        for symbol, snapshot in chain.items():
            contract = {
                "symbol": symbol,
                "close_price": float(snapshot.latest_quote.ask_price) if snapshot.latest_quote else None,
                "bid_price": float(snapshot.latest_quote.bid_price) if snapshot.latest_quote else None,
                "ask_price": float(snapshot.latest_quote.ask_price) if snapshot.latest_quote else None,
            }
            # Open interest — may be available on some snapshot responses.
            # We extract it if present so _select_best_option can filter
            # against the open_interest_min config threshold.
            if hasattr(snapshot, "open_interest") and snapshot.open_interest is not None:
                contract["open_interest"] = int(snapshot.open_interest)

            # Greeks may be available via snapshot
            if hasattr(snapshot, "greeks") and snapshot.greeks:
                contract["delta"] = snapshot.greeks.delta
                contract["gamma"] = snapshot.greeks.gamma
                contract["theta"] = snapshot.greeks.theta
                contract["vega"] = snapshot.greeks.vega
                contract["implied_volatility"] = snapshot.greeks.implied_volatility
            results.append(contract)

        logger.info("Fetched %d option contracts for %s", len(results), ticker)
        return results
    except Exception as e:
        logger.error("Failed to get option chain for %s: %s", ticker, e)
        raise AlpacaError(f"Option chain failed: {e}") from e
