"""Multi-index stock universe management — loads and merges tickers from CSV files.

Each index has its own CSV (backend/data/<name>.csv) with the same format: ticker,name,sector.
The loader merges all CSVs, deduplicates by ticker, and tracks which indices each ticker
belongs to via a list of index names.

Adding a new index: drop a CSV in backend/data/ and add one entry to INDEX_REGISTRY below.
"""

import csv
import logging
import pathlib

logger = logging.getLogger(__name__)

# ---- Index registry ----
# Maps display name → CSV filename. Order determines dropdown order in the UI.
INDEX_REGISTRY: dict[str, str] = {
    "S&P 500": "sp500.csv",
    "NASDAQ-100": "nasdaq100.csv",
    "Dow 30": "dow30.csv",
    "S&P MidCap 400": "sp400.csv",
    "Russell 2000": "russell2000.csv",
}

# Module-level cache: loaded once, reused for the lifetime of the process
_UNIVERSE: list[dict] | None = None


def _find_data_dir() -> pathlib.Path | None:
    """Locate the data/ directory across Docker and local dev environments."""
    candidates = [
        pathlib.Path(__file__).resolve().parent.parent.parent / "data",
        pathlib.Path("data"),
        pathlib.Path("backend/data"),
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return None


def load_universe() -> list[dict]:
    """Load and merge all index CSVs into a deduplicated ticker universe.

    Returns:
        List of dicts: [{ticker, name, sector, indices: ["S&P 500", "Dow 30"]}, ...]
        Each ticker appears once; its `indices` list contains every index it belongs to.
        Empty list if no data directory or CSVs can be found.
    """
    global _UNIVERSE
    if _UNIVERSE is not None:
        return _UNIVERSE

    data_dir = _find_data_dir()
    if not data_dir:
        logger.error("Could not find data/ directory for universe CSVs")
        _UNIVERSE = []
        return _UNIVERSE

    # ticker → {ticker, name, sector, indices: set()}
    merged: dict[str, dict] = {}
    total_loaded = 0

    for index_name, csv_filename in INDEX_REGISTRY.items():
        csv_path = data_dir / csv_filename
        if not csv_path.exists():
            logger.warning("Index CSV not found: %s (skipping %s)", csv_path, index_name)
            continue

        count = 0
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ticker = row.get("ticker", "").strip()
                if not ticker:
                    continue

                if ticker in merged:
                    # Already seen — just add this index to its membership set
                    merged[ticker]["indices"].add(index_name)
                else:
                    merged[ticker] = {
                        "ticker": ticker,
                        "name": row.get("name", "").strip(),
                        "sector": row.get("sector", "").strip(),
                        "indices": {index_name},
                    }
                count += 1
        total_loaded += count
        logger.info("Loaded %d tickers from %s (%s)", count, csv_filename, index_name)

    # Convert sets to sorted lists for JSON serialization
    _UNIVERSE = [
        {**entry, "indices": sorted(entry["indices"])}
        for entry in merged.values()
    ]

    logger.info(
        "Universe: %d unique tickers across %d indices (%d total rows loaded)",
        len(_UNIVERSE), len(INDEX_REGISTRY), total_loaded,
    )
    return _UNIVERSE


def get_ticker_list() -> list[str]:
    """Return just the ticker symbols as a flat deduplicated list."""
    return [entry["ticker"] for entry in load_universe()]


def get_available_indices() -> list[str]:
    """Return the list of index display names (for the filter dropdown)."""
    return list(INDEX_REGISTRY.keys())
