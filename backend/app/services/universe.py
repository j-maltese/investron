"""S&P 500 universe management — loads the ticker list from a CSV file.

The CSV lives at backend/data/sp500.csv and is committed to the repo.
In Docker, the Dockerfile copies backend/ to /app/, so it ends up at /app/data/sp500.csv.
We try multiple candidate paths to handle both environments (same pattern as VERSION
file resolution in main.py).
"""

import csv
import logging
import pathlib

logger = logging.getLogger(__name__)

# Module-level cache: loaded once, reused for the lifetime of the process.
# This avoids re-reading the CSV on every scan cycle.
_SP500_TICKERS: list[dict] | None = None


def load_sp500() -> list[dict]:
    """Load S&P 500 tickers from the CSV file.

    Returns:
        List of dicts: [{"ticker": "AAPL", "name": "Apple Inc.", "sector": "Information Technology"}, ...]
        Empty list if the CSV cannot be found (logged as error).
    """
    global _SP500_TICKERS
    if _SP500_TICKERS is not None:
        return _SP500_TICKERS

    # Try multiple paths for Docker vs. local dev compatibility.
    # In Docker: working dir is /app, CSV is at /app/data/sp500.csv
    # In local dev: working dir varies, but __file__ is reliable
    candidates = [
        pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "sp500.csv",
        pathlib.Path("data/sp500.csv"),
        pathlib.Path("backend/data/sp500.csv"),
    ]

    for path in candidates:
        if path.exists():
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                _SP500_TICKERS = [
                    {
                        "ticker": row["ticker"].strip(),
                        "name": row["name"].strip(),
                        "sector": row.get("sector", "").strip(),
                    }
                    for row in reader
                    if row.get("ticker", "").strip()
                ]
            logger.info("Loaded %d S&P 500 tickers from %s", len(_SP500_TICKERS), path)
            return _SP500_TICKERS

    logger.error("Could not find sp500.csv in any expected location: %s", candidates)
    _SP500_TICKERS = []
    return _SP500_TICKERS


def get_ticker_list() -> list[str]:
    """Return just the ticker symbols as a flat list."""
    return [entry["ticker"] for entry in load_sp500()]
