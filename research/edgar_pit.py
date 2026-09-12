"""Point-in-time SEC EDGAR fundamentals.

The production backend (backend/app/services/screener.py) computes value ratios
(P/E, P/B, FCF yield, Graham Number) from yfinance's CURRENT-snapshot multiples only
-- there's no history to replay. backend/app/services/edgar.py *does* have the real
history (SEC XBRL company facts, one API call per company returns everything ever
filed) and each data point carries a `filed` date -- but its aggregation function,
extract_financial_time_series(), collapses each fiscal period down to whichever
entry was filed MOST RECENTLY ACROSS THE COMPANY'S ENTIRE HISTORY. That's correct
for "show today's restated numbers" (the live app's only use case) but WRONG for
point-in-time reconstruction: filtering that already-collapsed output by
`filed <= T` can still drop a period whose lone surviving row happens to have been
filed after T, even though an earlier, legitimate, look-ahead-safe filing for that
same period existed before T.

So this module applies the filed<=T cutoff FIRST, on the RAW per-entry list, before
any cross-period collapsing happens (see get_point_in_time_annuals). It's a small,
deliberately independent vendor of the concept tag names and duration threshold from
edgar.py -- not an import of it, since research/ is a separate, undeployed sandbox
(own venv, synchronous style) while every edgar.py function is async/httpx-based.
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import date
from pathlib import Path

SEC_BASE = "https://data.sec.gov"
USER_AGENT = "Investron-Research research@investron.app"  # SEC requires a real identifying UA
MIN_REQUEST_INTERVAL = 0.15  # seconds -- keeps us well under SEC's ~10 req/s guidance

CACHE_DIR = Path(__file__).resolve().parent / "data" / "edgar_cache"

# Concept tags ported from backend/app/services/edgar.py's INCOME_STATEMENT_CONCEPTS /
# BALANCE_SHEET_CONCEPTS / CASH_FLOW_CONCEPTS -- only the subset needed for value ratios.
# "equity" and "shares" are balance-sheet ("instant") values; everything else is a
# duration ("flow") value that only makes sense over a period (a fiscal year, here).
CONCEPTS = {
    "EarningsPerShareBasic": "eps_basic",
    "EarningsPerShareDiluted": "eps_basic",
    "NetIncomeLoss": "net_income",
    "ProfitLoss": "net_income",
    "StockholdersEquity": "equity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": "equity",
    "CommonStockSharesOutstanding": "shares",
    "WeightedAverageNumberOfDilutedSharesOutstanding": "shares",
    "NetCashProvidedByUsedInOperatingActivities": "ocf",
    "PaymentsToAcquirePropertyPlantAndEquipment": "capex",
    "PaymentsToAcquireProductiveAssets": "capex",
}
INSTANT_FIELDS = {"equity", "shares"}
ANNUAL_DAYS = (330, 400)  # ported threshold from edgar.py's duration classifier

_last_request_time = 0.0


def _get(url: str, params: dict | None = None) -> dict | None:
    """Rate-limited GET with SEC's required identifying User-Agent."""
    global _last_request_time
    if params:
        from urllib.parse import urlencode
        url = f"{url}?{urlencode(params)}"

    elapsed = time.monotonic() - _last_request_time
    if elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    _last_request_time = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read())
    except Exception as e:
        print(f"  EDGAR request failed for {url}: {e}")
        return None


def lookup_all_ciks(tickers: list[str]) -> dict[str, str]:
    """One GET to SEC's full ticker->CIK map, matched locally -- avoids one lookup
    call per ticker."""
    data = _get("https://www.sec.gov/files/company_tickers.json")
    if not data:
        return {}
    wanted = {t.upper() for t in tickers}
    out = {}
    for entry in data.values():
        tkr = entry.get("ticker", "").upper()
        if tkr in wanted:
            out[tkr] = str(entry["cik_str"]).zfill(10)
    missing = wanted - out.keys()
    if missing:
        print(f"  CIK lookup missing for: {sorted(missing)}")
    return out


def fetch_company_facts(cik: str) -> dict | None:
    """One GET per company (returns its full XBRL history) -- disk-cached so reruns
    of build_dataset.py don't re-hit SEC every time."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{cik}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    data = _get(f"{SEC_BASE}/api/xbrl/companyfacts/CIK{cik}.json")
    if data is not None:
        cache_file.write_text(json.dumps(data))
    return data


def _is_annual_duration(start: str | None, end: str) -> bool:
    if not start:
        return False
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    return ANNUAL_DAYS[0] <= days <= ANNUAL_DAYS[1]


def _raw_entries(facts: dict, tag: str) -> list[dict]:
    concept = facts.get("facts", {}).get("us-gaap", {}).get(tag)
    if not concept:
        return []
    entries = []
    for unit_entries in concept.get("units", {}).values():
        entries.extend(unit_entries)
    return entries


def get_point_in_time_annuals(facts: dict, as_of: date) -> dict[str, float | None]:
    """The value of each tracked field AS OF calendar date `as_of` -- i.e. the most
    recent annual figure that had actually been FILED with the SEC by that date.

    Algorithm (per field):
      1. Pull every raw entry across all XBRL tag aliases for that field.
      2. Keep only entries filed on or before `as_of` (the look-ahead-safe cutoff).
      3. For flow fields, keep only true annual-duration entries; instant
         (balance-sheet) fields have no duration to filter on.
      4. Group survivors by period end; within each period keep the entry with the
         latest filed date (the freshest vintage of THAT period known as of T).
      5. Return the value from the most recent surviving period end.
    """
    as_of_str = as_of.isoformat()
    result: dict[str, float | None] = {}

    for field in set(CONCEPTS.values()):
        tags = [t for t, f in CONCEPTS.items() if f == field]
        raw = [e for tag in tags for e in _raw_entries(facts, tag)]
        known = [e for e in raw if e.get("filed") and e["filed"] <= as_of_str and e.get("end")]

        if field not in INSTANT_FIELDS:
            known = [e for e in known if _is_annual_duration(e.get("start"), e["end"])]

        if not known:
            result[field] = None
            continue

        by_period_end: dict[str, dict] = {}
        for e in known:
            end = e["end"]
            if end not in by_period_end or e["filed"] > by_period_end[end]["filed"]:
                by_period_end[end] = e

        best_end = max(by_period_end)
        result[field] = float(by_period_end[best_end]["val"])

    return result
