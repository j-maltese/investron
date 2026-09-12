# %% [markdown]
# # Phase 1 (+ 1.5) — Build the historical training set
#
# Goal: turn market history into **labeled examples** for a stock buy/skip model.
# Each example is one (ticker, month-end date T):
#
#     features known AS OF T   ->   label = did it beat the market over the next 3 months?
#
# This is the single most important file to get right, because the #1 way amateur
# financial ML lies to you is **look-ahead bias**: accidentally feeding the model
# information it could not have had at time T. Every design choice below exists to
# prevent that. Read the comments — the concepts matter more than the code.
#
# v2 adds a VALUE feature family (P/E, P/B, FCF yield, earnings yield, Graham Number
# margin-of-safety) on top of v1's price/technical features, sourced from point-in-time
# SEC EDGAR data via `edgar_pit.py` — see that module's docstring for why a fundamental
# value needs its own look-ahead-safety logic, distinct from price/technical features.
#
# Run it two ways:
#   * whole script:      python build_dataset.py
#   * cell-by-cell:      open in VS Code, Shift+Enter on each "# %%" cell
#
# Output: research/data/dataset_v2.parquet

# %%
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

import edgar_pit

# --- Config ---------------------------------------------------------------
# Universe = the 57 liquid large-caps from the app's seed list. Liquid names have
# long, clean price history and tight spreads.
#
# CAVEAT (survivorship bias): this is today's list of large-caps. Companies that
# blew up and got removed from the index aren't here, so a model trained on this
# universe sees a rosier world than reality. It's an acceptable simplification for
# a *first* learning dataset; we note it honestly and can widen the universe later.
UNIVERSE = [
    "AAPL", "ABBV", "ADBE", "AMD", "AMT", "AMZN", "APD", "AVGO", "BAC", "BLK",
    "BMY", "CAT", "CMCSA", "COP", "COST", "CRM", "CSCO", "CVX", "DIS", "DUK",
    "FCX", "GE", "GOOG", "GS", "HD", "HON", "IBM", "INTC", "JNJ", "JPM",
    "KO", "LIN", "LLY", "MCD", "META", "MRK", "MSFT", "NEE", "NFLX", "NKE",
    "NVDA", "ORCL", "PEP", "PFE", "PG", "PLD", "QCOM", "RTX", "SCHW", "SO",
    "TSLA", "TXN", "UNH", "UNP", "V", "WMT", "XOM",
]
BENCHMARK = "SPY"           # market proxy — used only for the label, never as a feature
START = "2015-01-01"        # ~10 years of history
HORIZON_MONTHS = 3          # label horizon (plan says 1-3 months; 3m is less noisy than 1m)
BEAT_THRESHOLD = 0.0        # "beat the market" = excess forward return > this
OUT = Path(__file__).resolve().parent / "data" / "dataset_v2.parquet"

# %% [markdown]
# ## 1. Download prices
# `auto_adjust=True` gives split/dividend-adjusted closes, so a % return means what
# you'd actually earn. We pull daily data (needed for volatility / moving-average
# features) and later sample it at month-ends.

# %%
try:
    # Browser-impersonating session avoids yfinance rate-limiting (same trick the backend uses).
    from curl_cffi.requests import Session
    _session = Session(impersonate="chrome")
except ImportError:
    _session = None

tickers = UNIVERSE + [BENCHMARK]
raw = yf.download(
    tickers, start=START, auto_adjust=True, progress=False,
    session=_session, group_by="column",
)
# yf.download returns a column MultiIndex like ("Close", "AAPL"); grab the Close block.
close = raw["Close"].sort_index()
print(f"Downloaded {close.shape[0]} daily rows x {close.shape[1]} tickers "
      f"({close.index.min().date()} -> {close.index.max().date()})")


# %% [markdown]
# ## 1b. Download point-in-time fundamentals (value features)
# One SEC EDGAR "company facts" call per ticker gets a company's ENTIRE XBRL filing
# history in one shot (disk-cached under `data/edgar_cache/`, see `edgar_pit.py`).
# We fetch it once here; `edgar_pit.get_point_in_time_annuals()` is then called
# per-ticker-per-month-end later with zero extra HTTP calls, re-querying this same
# in-memory dict each time.

# %%
cik_map = edgar_pit.lookup_all_ciks(UNIVERSE)
print(f"Resolved {len(cik_map)}/{len(UNIVERSE)} tickers to a CIK")

facts_cache = {}
for tkr in UNIVERSE:
    cik = cik_map.get(tkr)
    if not cik:
        continue
    facts = edgar_pit.fetch_company_facts(cik)
    if facts is not None:
        facts_cache[tkr] = facts
print(f"Fetched EDGAR company facts for {len(facts_cache)}/{len(UNIVERSE)} tickers")


# %% [markdown]
# ## 2. Feature engineering (point-in-time)
# For each ticker we compute features from DAILY data, then sample the last value in
# each calendar month (`resample("ME").last()`). "Last value in the month" = the
# value as of the final trading day — so a feature dated 2020-03-31 uses only data
# up to and including that day. Nothing from the future leaks in.
#
# Alongside these price/technical features (momentum, volatility, trend position),
# `build_value_features()` below adds VALUE features (P/E, P/B, FCF yield, earnings
# yield, Graham Number margin-of-safety) using `edgar_pit.get_point_in_time_annuals()`
# — the point-in-time EDGAR puller, which only ever uses a fundamental value that had
# actually been FILED with the SEC by that row's date (not just true as of the fiscal
# period-end). Other fundamental families (growth, quality, regime, pre-profit) are
# later iterations.

# %%
def build_features(daily_close: pd.Series) -> pd.DataFrame:
    """One ticker's daily close -> month-end feature rows. Everything here uses
    only past/current data (rolling windows look backward), so it's look-ahead safe."""
    s = daily_close.dropna()
    daily_ret = s.pct_change()

    # Backward-looking rolling stats (in TRADING days: ~21/mo, 63=3mo, 252=1yr).
    sma50 = s.rolling(50).mean()
    sma200 = s.rolling(200).mean()
    high_52w = s.rolling(252).max()
    low_52w = s.rolling(252).min()
    vol_3m = daily_ret.rolling(63).std() * np.sqrt(252)    # annualized volatility
    vol_6m = daily_ret.rolling(126).std() * np.sqrt(252)

    m = s.resample("ME").last()            # month-end price (last trading day's close)
    feat = pd.DataFrame(index=m.index)
    feat["price"] = m
    # Trailing total returns (momentum) — classic predictive features.
    feat["ret_1m"] = m.pct_change(1)
    feat["ret_3m"] = m.pct_change(3)
    feat["ret_6m"] = m.pct_change(6)
    feat["ret_12m"] = m.pct_change(12)
    # Volatility (risk) — sampled at month-end.
    feat["vol_3m"] = vol_3m.resample("ME").last()
    feat["vol_6m"] = vol_6m.resample("ME").last()
    # Trend position: where is price relative to its own moving averages / 52w range.
    feat["px_vs_sma50"] = (s / sma50 - 1).resample("ME").last()
    feat["px_vs_sma200"] = (s / sma200 - 1).resample("ME").last()
    feat["dist_52w_high"] = (s / high_52w - 1).resample("ME").last()   # <= 0
    feat["dist_52w_low"] = (s / low_52w - 1).resample("ME").last()     # >= 0
    return feat


def build_value_features(feat: pd.DataFrame, facts: dict | None) -> pd.DataFrame:
    """Point-in-time value ratios (P/E, P/B, FCF yield, earnings yield, Graham Number
    margin-of-safety), one row per date in `feat.index`. Formulas ported from
    backend/app/services/screener.py; the difference here is that EPS/book-value/FCF
    come from `edgar_pit.get_point_in_time_annuals()` (as-of-filing-date EDGAR data)
    instead of yfinance's current-snapshot-only multiples, so they're valid history."""
    cols = ["pe", "pb", "fcf_yield", "earnings_yield", "margin_of_safety"]
    if facts is None:
        return pd.DataFrame(np.nan, index=feat.index, columns=cols)

    rows = []
    for dt, price in feat["price"].items():
        pit = edgar_pit.get_point_in_time_annuals(facts, dt.date())
        eps = pit["eps_basic"] or (
            pit["net_income"] / pit["shares"] if pit["net_income"] and pit["shares"] else None
        )
        bvps = pit["equity"] / pit["shares"] if pit["equity"] and pit["shares"] else None
        fcf_ps = (
            (pit["ocf"] - pit["capex"]) / pit["shares"]
            if pit["ocf"] is not None and pit["capex"] is not None and pit["shares"]
            else None
        )

        pe = price / eps if eps and eps > 0 else None
        pb = price / bvps if bvps and bvps > 0 else None
        fcf_yield = fcf_ps / price if fcf_ps is not None and price else None
        earnings_yield = 1 / pe if pe else None
        graham_number = np.sqrt(22.5 * eps * bvps) if eps and eps > 0 and bvps and bvps > 0 else None
        margin_of_safety = (graham_number - price) / price * 100 if graham_number is not None else None

        rows.append([pe, pb, fcf_yield, earnings_yield, margin_of_safety])

    return pd.DataFrame(rows, index=feat.index, columns=cols)


FEATURE_COLS = [
    "ret_1m", "ret_3m", "ret_6m", "ret_12m",
    "vol_3m", "vol_6m",
    "px_vs_sma50", "px_vs_sma200", "dist_52w_high", "dist_52w_low",
]
VALUE_FEATURE_COLS = ["pe", "pb", "fcf_yield", "earnings_yield", "margin_of_safety"]
FEATURE_COLS = FEATURE_COLS + VALUE_FEATURE_COLS

# %% [markdown]
# ## 3. Labels (strictly future)
# The label answers: from month-end T, over the NEXT `HORIZON_MONTHS`, did this stock
# beat SPY? Forward returns are computed with `.shift(-h)` — that pulls a FUTURE price
# back to row T. Features use data <= T, labels use data > T. That clean separation is
# the whole game.

# %%
def forward_return(month_close: pd.Series, h: int) -> pd.Series:
    """Return from T to T+h, placed on row T. (P_{T+h} / P_T) - 1."""
    return month_close.shift(-h) / month_close - 1.0


# Benchmark forward return, indexed by month-end date — the bar each stock must clear.
spy_month = close[BENCHMARK].resample("ME").last()
spy_fwd = forward_return(spy_month, HORIZON_MONTHS)

rows = []
for tkr in UNIVERSE:
    if tkr not in close.columns:
        print(f"  skip {tkr}: no price data")
        continue
    feat = build_features(close[tkr])
    feat[VALUE_FEATURE_COLS] = build_value_features(feat, facts_cache.get(tkr))
    m = close[tkr].resample("ME").last()

    feat["ticker"] = tkr
    feat["date"] = feat.index
    feat[f"fwd_ret_{HORIZON_MONTHS}m"] = forward_return(m, HORIZON_MONTHS)
    feat["spy_fwd_ret"] = spy_fwd.reindex(feat.index)
    feat["excess_ret"] = feat[f"fwd_ret_{HORIZON_MONTHS}m"] - feat["spy_fwd_ret"]
    feat["beat_market"] = (feat["excess_ret"] > BEAT_THRESHOLD).astype("Int64")
    rows.append(feat)

df = pd.concat(rows, ignore_index=True)

# %% [markdown]
# ## 4. Clean up
# Two kinds of rows must go:
#   * **Insufficient history** — the first ~12 months of any ticker have NaN momentum
#     features (nothing to look back on). Dropping them prevents the model from
#     imputing garbage.
#   * **Unmatured labels** — the most recent `HORIZON_MONTHS` rows have no known
#     future yet, so `excess_ret` is NaN. These are exactly the rows Phase 3's live
#     maturation job will fill in later; here they can't be training data.

# %%
print("null rate per value feature BEFORE dropping (coverage gaps -- EDGAR history")
print("starting later than 2015 for some tickers, or a failed CIK lookup):")
print(df[VALUE_FEATURE_COLS].isna().mean().round(4).to_string())

before = len(df)
df = df.dropna(subset=FEATURE_COLS)                 # need full feature history
df = df.dropna(subset=["excess_ret"])               # need a matured label
df["beat_market"] = df["beat_market"].astype(int)
df = df[["date", "ticker", *FEATURE_COLS,
         f"fwd_ret_{HORIZON_MONTHS}m", "spy_fwd_ret", "excess_ret", "beat_market"]]
df = df.sort_values(["date", "ticker"]).reset_index(drop=True)
print(f"Rows: {before} -> {len(df)} after dropping incomplete history / unmatured labels")

# %% [markdown]
# ## 5. Diagnostics + save
# Sanity checks you should ALWAYS eyeball before trusting a dataset: date coverage,
# how balanced the label is (a 50/50 beat/miss split means "predict the majority" is a
# weak baseline to beat), null rates, and per-year counts (no year should be empty).

# %%
h = HORIZON_MONTHS
print("\n=== dataset_v2 ===")
print(f"shape                : {df.shape}")
print(f"date range           : {df['date'].min().date()} -> {df['date'].max().date()}")
print(f"tickers              : {df['ticker'].nunique()}")
print(f"label balance (beat) : {df['beat_market'].mean():.1%} beat market "
      f"(baseline 'always guess majority' accuracy = {max(df['beat_market'].mean(), 1 - df['beat_market'].mean()):.1%})")
print(f"mean fwd_ret_{h}m     : {df[f'fwd_ret_{h}m'].mean():.2%}")
print(f"mean excess_ret      : {df['excess_ret'].mean():.2%}")
print("\nnull rates per column:")
print(df.isna().mean().round(4).to_string())
print("\nexamples per year:")
print(df.groupby(df["date"].dt.year).size().to_string())

OUT.parent.mkdir(parents=True, exist_ok=True)
df.to_parquet(OUT, index=False)
print(f"\nSaved -> {OUT}")

# %% [markdown]
# ## What you just built
# A leak-free supervised dataset: ~10 years x 57 stocks, one row per stock per month,
# 15 point-in-time features (10 price/technical + 5 value), and a binary "beat the
# market over the next 3 months" label. The value features are as look-ahead-safe as
# the price ones: each is computed from the most recent SEC filing that had actually
# been FILED as of that row's date, never a later restatement.
#
# ## Next
# Re-run `train.py` against `dataset_v2.parquet` and compare its walk-forward AUC /
# precision@top-decile / backtest-vs-SPY against the v1 (price-only) baseline already
# recorded in `LEARNING.md` — does value add real lift, or was price-only truly it?
