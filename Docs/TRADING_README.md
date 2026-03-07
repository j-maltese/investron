# Automated Paper Trading — Alpaca Markets Integration

Investron can automatically trade on your behalf using Alpaca Markets' paper trading API. Two independent strategies run in the background, each with its own capital allocation and trading logic:

1. **Simple Stock Trading** ($500 paper) — AI-powered buy/sell of common stock, leveraging the screener scores and GPT-4o analysis
2. **The Wheel Strategy** ($30,000 paper) — Mechanical options income strategy: sell cash-secured puts, get assigned stock, sell covered calls, repeat. Screener-driven dynamic candidate selection with sector diversification. Full defensive suite with hard stops, rolling puts, adjusted cost basis tracking, and capital efficiency exits

## How It Works

```
Trading Engine (background loop, runs every 60s during market hours)
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│  For each strategy with status = 'running':                   │
│                                                               │
│  1. Safety check: Has drawdown exceeded max_loss_pct?         │
│     → If yes, auto-pause strategy (circuit breaker)           │
│                                                               │
│  2. Daily auto-index (once per day, first cycle only):         │
│     → Index SEC filings for top 10 screener candidates        │
│     → Skips already-indexed tickers (fresh within 7 days)     │
│     → Reuses existing filing_indexer.py RAG pipeline          │
│                                                               │
│  3. Run strategy-specific cycle:                              │
│                                                               │
│     Simple Stock:                                             │
│       a. Sync pending orders with Alpaca (poll for fills)     │
│       b. Check existing positions for sell signals:           │
│          - Stop-loss (3-layer confirm + stop-limit order)     │
│          - Take-profit (yfinance confirm + limit order)       │
│          - AI says sell with high confidence (limit order)    │
│       c. Find new buy opportunities:                          │
│          - Filter: screener composite scores (free)           │
│          - Confirm: GPT-4o trade signal (max 5/cycle)         │
│          - Safety: staleness, spread, yfinance checks         │
│          - Size: max 25% of capital per position              │
│          - Execute: limit order via Alpaca                    │
│                                                               │
│     Wheel:                                                    │
│       a. Get candidates from screener (or fixed list)        │
│       b. Merge open-position tickers (prevent orphaning)     │
│       c. Sync option orders with Alpaca (poll for fills)     │
│       d. Detect assignments (put/call exercises)             │
│       e. Per symbol: sell puts, manage puts (roll),          │
│          hard stop check, sell calls, manage calls           │
│       f. Track adjusted cost basis (premiums collected)      │
│                                                               │
│  4. Update last_run timestamp                                 │
│  5. Sync P&L from position data                               │
└──────────────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│  Frontend (/trading page, polls every 15-30s)                 │
│                                                               │
│  Overview tab:    Portfolio summary + strategy cards + recent  │
│                   activity (compact view)                      │
│  Positions tab:   Open/closed positions with P&L              │
│  Orders tab:      Complete order history with AI signals       │
│  Activity tab:    Event stream with filter pills (Decisions / │
│                   Executions / Blocked / Errors), date range   │
│                   picker, expandable JSONB detail rows, and    │
│                   load-more pagination                         │
└──────────────────────────────────────────────────────────────┘
```

## Architecture Decisions

### ADR-1: Alpaca Markets as brokerage

**Decision:** Use Alpaca Markets for all brokerage operations (paper and eventually live).

**Why Alpaca:**
- $0 minimum balance, $0 commissions on stocks and options
- Official Python SDK (`alpaca-py`) with async support
- Free paper trading environment — identical API to live
- Level 3 options available on paper accounts (needed for the Wheel strategy)
- Market data included (quotes, bars, option chains with greeks)

**Alternatives considered:** Interactive Brokers (complex API, $0 paper but painful setup), TD Ameritrade/Schwab (SDK deprecated post-merger), Tradier (good options API but smaller community).

### ADR-2: Two-tier signal approach (screener + AI)

**Decision:** Use pre-computed screener scores as a free filter, only sending top candidates to GPT-4o for confirmation.

**Why two tiers:**
- Screener scores are already in the DB (computed daily by the scanner) — querying them is free
- GPT-4o calls cost ~$0.01-0.03 each with full financial context
- With a $500 paper portfolio and 5 max AI calls per cycle, daily AI cost is < $0.50
- The screener eliminates ~80% of the universe before AI evaluation
- AI provides nuanced judgment that scores alone can't capture (momentum, sector rotation, news sentiment)

**Candidate sources:** Top N stocks from the screener by composite score (default: top 20 above score 60). No hardcoded watchlist — the screener and AI decide what's worth buying.

### ADR-3: Polling Alpaca (not WebSocket)

**Decision:** Poll Alpaca's REST API for order status every cycle (~60s), rather than using WebSocket streaming.

**Why:** Paper trading order fills are near-instant (market orders fill immediately in simulation). A 60-second polling cycle is more than adequate for a strategy that only trades during market hours. WebSocket adds connection management complexity, reconnection logic, and state synchronization concerns for minimal benefit.

**Trade-off:** In live trading with limit orders, fills could be delayed up to 60s in our local tracking. Acceptable for a paper trading experiment; WebSocket can be added later if needed for live.

### ADR-4: Local position tracking + Alpaca sync

**Decision:** Track positions, orders, and P&L in our own database, syncing with Alpaca each cycle.

**Why local tracking:**
- Enables per-strategy capital isolation (Alpaca gives one paper account; we allocate $500 vs $30,000 logically)
- Stores the AI signal that triggered each trade (audit trail)
- Tracks wheel phases (selling_puts → assigned → selling_calls) which Alpaca doesn't understand
- Supports historical P&L and activity logging
- Frontend reads from our DB, not Alpaca directly — faster, more structured

**Sync mechanism:** Each cycle, `_sync_pending_orders()` checks Alpaca for fills on our `pending`/`submitted` orders, updates local status/fills, adjusts cash/portfolio values.

### ADR-5: JSONB for strategy config

**Decision:** Store strategy configuration as a JSONB column rather than individual columns.

**Why JSONB:**
- Simple stock and wheel strategies have completely different config shapes
- Adding new config keys doesn't require schema migrations
- Frontend can display arbitrary config key/value pairs
- PATCH endpoint does shallow merge — partial updates just work

### ADR-6: Market hours gate in trading engine

**Decision:** The trading loop checks `_is_market_hours()` and sleeps 5 minutes outside market hours instead of running strategy cycles.

**Why:**
- Can't place orders when the market is closed (market orders would queue for next open, which may not match current price)
- Avoids wasting AI API calls analyzing stale quotes
- Reduces unnecessary DB writes and Alpaca API calls

**Implementation:** UTC-based check: weekdays only, 14:00-21:00 UTC (9 AM - 4 PM ET approximately). Not DST-aware — off by an hour during summer, but sufficient to avoid trading at 2 AM.

### ADR-7: Daily scanner (was hourly)

**Decision:** Changed the background screener from hourly scans to once daily at 5 PM ET (21:00 UTC).

**Why:**
- Fundamental financial data (P/E, ROE, debt ratios, etc.) doesn't change intraday
- A full scan of ~2,700 tickers takes ~35 minutes — hourly scans never fully completed before the next cycle started
- Daily at market close ensures scores reflect end-of-day prices
- On startup, runs immediately to ensure fresh data, then sleeps until the next preferred hour

### ADR-8: RAG-enhanced trade signals

**Decision:** Auto-index SEC filings for top screener candidates daily, then inject relevant filing excerpts into GPT-4o trade signal prompts.

**How it works:**
1. **Daily auto-index** — once per calendar day (before the first trading cycle), `run_auto_index_cycle()` indexes filings for the top 10 screener candidates. Reuses the existing `filing_indexer.py` pipeline (EDGAR fetch → parse → chunk → embed → pgvector). Skips tickers already indexed within the last 7 days.
2. **RAG search at trade time** — `_get_ai_trade_signal()` checks if a ticker has indexed filings. If so, runs a focused vector search (risk factors, MD&A, guidance/outlook) and appends up to 2,000 tokens of filing excerpts to the prompt.
3. **Graceful degradation** — if a ticker isn't indexed, the signal still works with metrics-only context. If RAG search fails, it logs a warning and proceeds without filing data.

**Why:** Summary metrics (P/E, ROE, margins) capture the "what" but miss the "why." SEC filings provide management commentary, risk disclosures, and forward guidance that help the AI make more informed decisions. The existing RAG infrastructure was built for the interactive AI Analysis chat — this just wires it into the automated trading path.

**Config:**
- `TRADING_RAG_ENABLED=true` — kill switch (disable RAG without disabling trading)
- `TRADING_AUTO_INDEX_TOP_N=10` — how many top candidates to auto-index daily
- `TRADING_RAG_MAX_TOKENS=2000` — max filing context tokens per trade signal prompt

**Cost:** ~$0.50-1.00/day for embedding API calls during auto-indexing. RAG search itself is free (pgvector cosine similarity).

## Architecture

### Database Tables

**`trading_strategies`** — One row per configured strategy.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | VARCHAR(30) PK | `simple_stock` or `wheel` |
| `display_name` | VARCHAR(100) | Human-readable name |
| `strategy_type` | VARCHAR(30) | Determines which cycle function to run |
| `status` | VARCHAR(20) | `stopped`, `running`, `paused`, `error` |
| `initial_capital` | DECIMAL(12,2) | Starting capital ($500 / $30,000) |
| `current_cash` | DECIMAL(12,2) | Full cash balance (includes collateral for sold puts) |
| `current_portfolio_value` | DECIMAL(12,2) | Sum of `current_value` from open positions (recomputed each cycle) |
| `total_pnl` / `total_pnl_pct` | DECIMAL | Overall P&L (absolute and %) |
| `realized_pnl` / `unrealized_pnl` | DECIMAL | Split P&L |
| `config` | JSONB | Strategy-specific settings (see below) |
| `max_loss_pct` | DECIMAL(6,2) | Circuit breaker threshold (default 20%) |
| `max_position_pct` | DECIMAL(6,2) | Max % of capital in one position (default 25%) |
| `last_run_at` | TIMESTAMPTZ | When the engine last ran this strategy |
| `last_error` / `error_count` | TEXT/INT | Error tracking |

**`trading_positions`** — Open and historical positions.

| Column | Type | Purpose |
|--------|------|---------|
| `strategy_id` | VARCHAR(30) FK | Which strategy owns this position |
| `ticker` | VARCHAR(10) | Stock symbol |
| `asset_type` | VARCHAR(10) | `stock` or `option` |
| `quantity` | DECIMAL(12,4) | Number of shares or contracts |
| `avg_entry_price` | DECIMAL(12,4) | Average fill price |
| `option_*` fields | Various | Option symbol, type, strike, expiry, contracts |
| `wheel_phase` | VARCHAR(20) | `selling_puts`, `assigned`, `selling_calls`, or null |
| `cost_basis` / `current_value` | DECIMAL | Position value tracking |
| `realized_pnl` / `unrealized_pnl` | DECIMAL | Position-level P&L |
| `status` | VARCHAR(20) | `open`, `closed`, `assigned`, `expired` |
| `close_reason` | VARCHAR(50) | `sold`, `assigned`, `expired`, `stop_loss`, `called_away` |

**`trading_orders`** — Every order submitted to Alpaca.

| Column | Type | Purpose |
|--------|------|---------|
| `alpaca_order_id` | VARCHAR(50) UNIQUE | Links to Alpaca's order record |
| `strategy_id` | VARCHAR(30) FK | Which strategy placed the order |
| `position_id` | INT FK | Which position this order relates to |
| `ticker` | VARCHAR(10) | Stock symbol |
| `side` | VARCHAR(10) | `buy` or `sell` |
| `order_type` | VARCHAR(20) | `market`, `limit`, `stop`, `stop_limit` |
| `quantity` / `limit_price` / `stop_price` | DECIMAL | Order parameters |
| `filled_quantity` / `filled_avg_price` / `filled_at` | Various | Fill info from Alpaca |
| `status` | VARCHAR(20) | `pending`, `submitted`, `filled`, `cancelled`, `rejected` |
| `reason` | TEXT | Human-readable explanation for why the trade was made |
| `ai_signal` | JSONB | Full AI response (`{action, confidence, reasoning}`) |

**`trading_activity_log`** — Append-only event stream.

| Column | Type | Purpose |
|--------|------|---------|
| `strategy_id` | VARCHAR(30) FK | Which strategy generated this event |
| `event_type` | VARCHAR(30) | `order_placed`, `order_filled`, `signal`, `error`, `strategy_start`, `circuit_breaker`, `auto_index`, etc. |
| `ticker` | VARCHAR(10) | Related ticker (if applicable) |
| `message` | TEXT | Human-readable event description |
| `details` | JSONB | Structured event data |

### Strategy Config (JSONB)

**Simple Stock:**
```json
{
    "screener_top_n": 20,
    "max_position_pct": 25.0,
    "use_ai_signals": true,
    "min_screener_score": 60.0,
    "min_ai_confidence": 0.7,
    "stop_loss_pct": 10.0,
    "take_profit_pct": 20.0,
    "max_ai_calls_per_cycle": 5,
    "check_interval_minutes": 30
}
```

**Wheel:**
```json
{
    "screener_enabled": true,
    "screener_min_score": 40.0,
    "screener_max_price": 200.0,
    "screener_min_market_cap": 1000000000,
    "screener_top_n": 20,
    "max_per_sector": 2,
    "symbol_list": [],
    "delta_min": 0.15,
    "delta_max": 0.30,
    "yield_min": 0.04,
    "yield_max": 1.00,
    "expiration_min_days": 7,
    "expiration_max_days": 45,
    "open_interest_min": 100,
    "max_stock_loss_pct": 25.0,
    "roll_threshold_pct": 10.0,
    "roll_min_net_credit": 0.10,
    "call_min_strike_pct": -5.0,
    "capital_efficiency_days": 60,
    "pdt_protection": true,
    "check_interval_minutes": 15
}
```

| Key | Default | Purpose |
|-----|---------|---------|
| `screener_enabled` | `true` | Use screener-driven dynamic candidates (vs legacy fixed list) |
| `screener_min_score` | 40.0 | Minimum composite score to qualify as a Wheel candidate |
| `screener_max_price` | $200 | Max stock price (assignment must be affordable) |
| `screener_min_market_cap` | $1B | Minimum market cap for options liquidity |
| `screener_top_n` | 20 | Max candidates to evaluate per cycle |
| `max_per_sector` | 2 | Sector diversification limit |
| `symbol_list` | `[]` | Legacy fixed ticker list (used when `screener_enabled=false`) |
| `delta_min` / `delta_max` | 0.15-0.30 | Target delta range for sold options (probability of assignment) |
| `yield_min` / `yield_max` | 4%-100% | Annualized premium yield filter |
| `expiration_min_days` / `expiration_max_days` | 7-45 | DTE window for option selection |
| `open_interest_min` | 100 | Minimum open interest for liquidity |
| `max_stock_loss_pct` | 25% | Hard stop: sell assigned stock if down more than this |
| `roll_threshold_pct` | 10% | Roll put if stock is more than this % below strike near expiry |
| `roll_min_net_credit` | $0.10 | Only roll if the roll produces at least this net credit per share |
| `call_min_strike_pct` | -5% | Allow selling calls up to 5% below adjusted cost basis for capital efficiency |
| `capital_efficiency_days` | 60 | Review assigned stock if held longer than this with no recovery |
| `pdt_protection` | true | Track day trades, block if would exceed 3-per-5-day PDT limit |

### Backend Services

```
backend/app/
├── services/
│   ├── alpaca_client.py          # Thin wrapper around alpaca-py SDK
│   │                              #   Cached client singletons (TradingClient, StockDataClient, OptionDataClient)
│   │                              #   submit_stock_order(), submit_option_order(), get_order_status()
│   │                              #   get_positions(), get_account_info(), get_option_chain(), cancel_order()
│   │                              #   parse_occ_symbol(), build_occ_symbol() — OCC option symbol helpers
│   │
│   ├── trading_db.py             # All CRUD for trading tables (raw SQL + text())
│   │                              #   Strategies: get/update
│   │                              #   Positions: get/insert/close/update
│   │                              #   Orders: insert/update_status/get
│   │                              #   Activity: log/get
│   │                              #   Portfolio: get_summary, sync_strategy_pnl
│   │
│   ├── trading_engine.py         # Background loop (like scanner.py)
│   │                              #   trading_loop() — infinite async coroutine
│   │                              #   run_trading_cycle() — safety check + dispatch to strategy
│   │                              #   _is_market_hours() — UTC-based gate
│   │                              #   Daily auto-index gate (_last_auto_index_date)
│   │
│   ├── simple_stock_strategy.py  # AI-powered stock trading logic
│   │                              #   run_simple_stock_cycle() — sync → sells → buys
│   │                              #   run_auto_index_cycle() — daily SEC filing indexing
│   │                              #   _get_candidate_tickers() — screener top N by composite score
│   │                              #   _get_ai_trade_signal() — GPT-4o with financials + RAG filing context
│   │                              #   _validate_price_for_trade() — Layer 1 safety (staleness/spread/yfinance)
│   │                              #   _get_price_details() — Alpaca price + timestamp + spread data
│   │                              #   _sync_pending_orders() — poll Alpaca for fills
│   │                              #   _execute_buy() / _execute_sell() — limit/stop-limit order management
│   │
│   └── wheel_strategy.py         # Mechanical options income strategy (The Wheel)
│                                  #   run_wheel_cycle() — sync → detect assignments → per-symbol processing
│                                  #   _sync_option_orders() — poll Alpaca for option fills, handle premiums
│                                  #   _detect_assignments() — compare Alpaca positions vs local DB
│                                  #   _sell_put() — sell cash-secured put (phase 1)
│                                  #   _sell_call() — sell covered call with adjusted cost basis (phase 3)
│                                  #   _select_best_option() — filter + score option chain
│                                  #   _manage_put_position() — expiration monitoring + rolling
│                                  #   _manage_call_position() — call expiration monitoring
│                                  #   _check_hard_stop() — sell if down > max_stock_loss_pct
│                                  #   _check_capital_efficiency() — exit if held > N days, no recovery
│                                  #   _get_adjusted_cost_basis() — true break-even (entry - premiums)
│                                  #   _would_exceed_pdt() — PDT day trade limit check
│
└── api/
    └── trading.py                # REST API at /api/trading
                                   #   GET:  strategies, positions, orders, activity, portfolio
                                   #   POST: start, stop, pause, reset
                                   #   PATCH: config update (shallow merge)
```

### Frontend Components

```
frontend/src/
├── lib/
│   ├── types.ts                  # TradingStrategy, TradingPosition, TradingOrder,
│   │                              # TradingActivityEvent, TradingPortfolio
│   └── api.ts                    # getStrategies, startStrategy, stopStrategy, pauseStrategy,
│                                  # resetStrategy, updateStrategyConfig, getTradingPositions,
│                                  # getTradingOrders, getTradingActivity, getTradingPortfolio
├── hooks/
│   └── useTrading.ts             # TanStack Query hooks (15-30s polling) + mutations
│                                  #   useStrategies, usePortfolio, usePositions, useOrders, useActivityLog
│                                  #   useActivityLog supports filter params (eventType, dateFrom, dateTo)
│                                  #   and `enabled` flag for conditional fetching (compact mode)
│                                  #   useStartStrategy, useStopStrategy, usePauseStrategy, useResetStrategy
│
├── pages/
│   └── Trading.tsx               # Tab navigation: Overview | Positions | Orders | Activity
│
└── components/trading/
    ├── StrategyCard.tsx           # Status badge, capital, P&L, start/stop/pause buttons, ticker chips
    ├── PortfolioSummary.tsx       # Combined portfolio value with "Paper" badge
    ├── PositionsTable.tsx         # Table with wheel phase indicators, P&L coloring
    ├── OrdersTable.tsx            # Order history with status badges
    └── ActivityFeed.tsx           # Two modes: compact (Overview tab, props-driven) and
                                    #   full (Activity tab, self-managing with useActivityLog).
                                    #   Full mode: filter pills (All/Decisions/Executions/Blocked/Errors),
                                    #   date range picker with presets, expandable JSONB detail rows
                                    #   with "reason" field highlighted, load-more pagination.
                                    #   23 event type icons + prefix matching for blocked_* events
```

## API Endpoints

All endpoints require authentication and are mounted at `/api/trading`.

### Strategies

```
GET    /strategies                   List all strategies with status + P&L
GET    /strategies/{id}              Detailed view of one strategy
POST   /strategies/{id}/start       Set status to 'running' (requires TRADING_ENABLED + Alpaca keys)
POST   /strategies/{id}/stop        Set status to 'stopped'
POST   /strategies/{id}/pause       Set status to 'paused'
POST   /strategies/{id}/reset       Reset to initial capital, clear P&L
PATCH  /strategies/{id}/config      Partial update of JSONB config (shallow merge)
```

**GET /strategies response:**
```json
{
  "strategies": [
    {
      "id": "simple_stock",
      "display_name": "Simple Stock Trading",
      "strategy_type": "simple_stock",
      "status": "running",
      "initial_capital": 500.0,
      "current_cash": 375.50,
      "current_portfolio_value": 130.25,
      "total_pnl": 5.75,
      "total_pnl_pct": 1.15,
      "config": {"screener_top_n": 20, "use_ai_signals": true, ...},
      "last_run_at": "2026-03-02T18:30:00Z"
    }
  ]
}
```

**POST /strategies/{id}/start error responses:**
- `503` — `TRADING_ENABLED=false` or Alpaca API keys not configured
- `404` — Strategy not found

**PATCH /strategies/{id}/config body:**
```json
{
  "config": {
    "min_ai_confidence": 0.8,
    "stop_loss_pct": 15.0
  }
}
```
Only the provided keys are updated; existing config keys are preserved (shallow merge).

### Positions, Orders, Activity

```
GET    /positions?strategy_id=simple_stock&status=open&limit=50&offset=0
GET    /orders?strategy_id=simple_stock&limit=50&offset=0
GET    /activity?strategy_id=wheel&event_type=blocked&date_from=2026-03-01&date_to=2026-03-03&limit=50&offset=0
```

All return paginated results with a `total_count` field.

The activity endpoint supports additional filters:
- `event_type` — exact match or prefix match (e.g., `blocked` matches all `blocked_*` events)
- `date_from` / `date_to` — ISO date strings for time range filtering

### Portfolio

```
GET    /portfolio
```

Returns aggregated values across all strategies:
```json
{
  "total_value": 5505.75,
  "total_cash": 5375.50,
  "total_portfolio_value": 130.25,
  "total_initial_capital": 5500.0,
  "total_pnl": 5.75,
  "total_pnl_pct": 0.1045,
  "strategies": [...]
}
```

## Configuration

Settings in `backend/app/config.py`, overridable via environment variables:

| Setting | Default | Purpose |
|---------|---------|---------|
| `ALPACA_API_KEY` | `""` (disabled) | Alpaca API key (from dashboard) |
| `ALPACA_SECRET_KEY` | `""` (disabled) | Alpaca secret key |
| `ALPACA_BASE_URL` | `https://paper-api.alpaca.markets` | Paper vs live trading endpoint |
| `ALPACA_DATA_URL` | `https://data.alpaca.markets` | Market data endpoint |
| `TRADING_ENABLED` | `false` | Master kill switch for the trading engine |
| `TRADING_CHECK_INTERVAL` | `60` | Seconds between strategy check cycles |
| `TRADING_RAG_ENABLED` | `true` | Enable/disable RAG filing context in trade signals |
| `TRADING_AUTO_INDEX_TOP_N` | `10` | How many top screener candidates to auto-index daily |
| `TRADING_RAG_MAX_TOKENS` | `2000` | Max filing context tokens per trade signal prompt |
| `PRICE_CONFIRM_DIVERGENCE_PCT` | `5.0` | Max % divergence between Alpaca & yfinance before blocking a sell |
| `SPREAD_MAX_PCT` | `2.0` | Block trades when bid/ask spread exceeds this % (illiquid/bad data) |
| `PRICE_STALENESS_MAX_SECONDS` | `300` | Reject prices with last trade older than this during market hours |
| `BUY_LIMIT_OFFSET_PCT` | `0.5` | Buy limit price = current price × (1 + this%) — buffer to ensure fill |
| `STOP_LOSS_LIMIT_OFFSET_PCT` | `2.0` | Stop-limit sell: limit price offset below stop trigger price |
| `SCANNER_PREFERRED_HOUR_UTC` | `21` | Daily scan start hour (21 = 5 PM ET) |

## Setup

### 1. Get Alpaca API keys

1. Create a free account at [alpaca.markets](https://alpaca.markets)
2. Go to the Paper Trading dashboard
3. Generate API keys (Key + Secret)

### 2. Add to environment

Add these to your `backend/.env` file:

```
ALPACA_API_KEY=your_paper_api_key_here
ALPACA_SECRET_KEY=your_paper_secret_key_here
TRADING_ENABLED=true
```

### 3. Restart Docker (local dev)

```bash
docker compose down && docker compose up -d
```

This reinitializes the database from `schema.sql`, which seeds both strategy rows with default config.

### 4. Start the app

```bash
bash scripts/dev.sh
```

Navigate to `/trading` — you should see both strategy cards with $500 and $30,000 starting capital.

### 5. Start a strategy

Click the "Start" button on the Simple Stock card (or use the API: `POST /api/trading/strategies/simple_stock/start`). The trading engine will begin running cycles during market hours.

## Simple Stock Strategy — Detailed Flow

Each cycle (`run_simple_stock_cycle`) follows this sequence:

### Step 1: Sync Pending Orders

```
For each order with status 'pending' or 'submitted':
  → GET Alpaca order status
  → If status changed (e.g., submitted → filled):
      → Update local order record
      → If filled BUY: update position with fill price, deduct cash
      → If filled SELL: close position, calculate realized P&L, add cash back
      → Log activity event
```

### Step 2: Check Existing Positions

```
For each open position:
  → Get latest price from Alpaca (last trade + bid/ask + trade timestamp + spread)
  → Update unrealized P&L

  → Check stop-loss (3-layer confirmation — prevents false-trigger sells):
      1. Alpaca price shows -10%+ drop from entry
      2. Re-fetch from Alpaca (same-source double-check)
      3. Run Layer 1 safety checks:
         a. Price staleness: reject if last trade > 5 min old (market hours)
         b. Bid/ask spread: reject if spread > 2% (illiquid/bad data)
         c. yfinance cross-check: reject if Alpaca vs yfinance diverge > 5%
      → All pass → SELL via stop-limit order (stop at current, limit 2% below)

  → Check take-profit:
      1. Price up > 20% from entry
      2. Run Layer 1 safety checks (staleness + spread + yfinance)
      → All pass → SELL via limit order at current price

  → AI sell check: call GPT-4o with "hold or sell" prompt
      → If action=sell AND confidence >= 0.7:
          → Run staleness + spread checks (no yfinance — not price-triggered)
          → SELL via limit order at ~current price
```

### Step 3: Find Buy Opportunities

```
If cash < 5% of capital → skip (not enough for a meaningful position)

Build candidate list:
  → Top 20 by composite_score from screener_scores table
  → Filter: composite_score >= 60.0 (min_screener_score)
  → Remove tickers we already hold

For each candidate (up to 5 AI calls per cycle):
  → Call GPT-4o with BUY prompt + full financial context + RAG filing excerpts
  → If action=buy AND confidence >= 0.7:
      → Fetch full price data (trade + bid/ask + timestamp + spread)
      → Run Layer 1 safety checks (staleness + spread)
      → Calculate shares: floor(cash * 25% / price) — whole shares only
      → Submit limit order (current price + 0.5% buffer) via Alpaca
      → Create local position + order records
      → Log activity
```

### AI Trade Signal

The `TRADE_SIGNAL_PROMPT` asks GPT-4o to respond with structured JSON:

```json
{"action": "buy", "confidence": 0.82, "reasoning": "Strong margin of safety at 35%, improving FCF yield, P/E below sector average"}
```

Financial context is built by `build_ticker_context()` from `ai_context.py` — the same data assembly used by the AI Analysis chat, including full financial statements (income, balance sheet, cash flow for the last 3 periods).

If the ticker has indexed SEC filings (via the daily auto-index or manual indexing from the AI Analysis tab), relevant filing excerpts are injected into the prompt under a `== SEC FILING EXCERPTS ==` header. The vector search targets risk factors, MD&A, and guidance/outlook sections, capped at 2,000 tokens. This gives the AI qualitative context (management commentary, risk disclosures) alongside the quantitative metrics.

## The Wheel Strategy — Detailed Flow

The Wheel is a mechanical options income strategy. Unlike the Simple Stock strategy (which uses AI to decide what to buy/sell), the Wheel follows a rigid state machine: sell puts → get assigned → sell calls → shares called away → repeat. The intelligence is in the option selection parameters and defensive exit rules.

### State Machine

```
IDLE ──sell put──→ SELLING_PUTS ──assigned──→ ASSIGNED ──sell call──→ SELLING_CALLS
  ↑                  │       │                  │    │                      │
  │           expired OTM    │            hard stop   │               expired OTM
  │           (keep premium) │            (sell stock, │              (keep premium,
  │                  │       │             take loss)  │              still hold stock)
  ←──────────────────┘       │                  │     │                     │
  ↑                          │                  ↓     │                     │
  │                    ROLL PUT              IDLE      │            called away
  │                    (buy back +                    │            (shares sold)
  │                     sell new put                  │                     │
  │                     at lower strike)              │                     │
  │                          │                        │                     │
  ←──────────────────────────┘                        │                     │
  ↑                                                   │                     │
  │                                          capital efficiency             │
  │                                          exit (sell after               │
  │                                          60+ days, no recovery)         │
  │                                                   │                     │
  ←───────────────────────────────────────────────────┘                     │
  ←─────────────────────────────────────────────────────────────────────────┘
```

### Each Cycle (`run_wheel_cycle`)

Called every ~60s by the trading engine during market hours. In screener mode (default), candidates are pulled dynamically from `screener_scores` — filtered by min composite score, max price, min market cap, and sector diversification. Tickers with open positions are always included even if they fall off the screener. In legacy mode (`screener_enabled=false`), processes `config.symbol_list`. Candidates are sorted by stock price ascending (cheapest first for affordability gating).

**Step 1: Sync Option Orders**

Polls Alpaca for fills on pending option orders. When a sell option fills: credits premium to strategy cash (fill_price × 100 × contracts). When a buy-to-close (roll) fills: debits cash.

**Step 2: Detect Assignments**

Compares Alpaca live positions vs local DB to detect option exercises:

| Scenario | Detection | Action |
|----------|-----------|--------|
| **Put assigned** | Option gone from Alpaca + stock appeared | Close put position, create stock position (`wheel_phase='assigned'`), debit cash (strike × 100) |
| **Put expired OTM** | Option gone + no stock | Close put position, keep premium, back to idle |
| **Call assigned (called away)** | Option gone + stock gone | Close call + stock positions, credit cash (strike × 100), wheel cycle complete |
| **Call expired OTM** | Option gone + stock still held | Close call position, keep premium, back to `assigned` phase |

**Step 3: Per-Symbol Processing**

For each symbol, based on its current phase:

- **Idle** (no open position) → `_sell_put()` — find and sell a cash-secured put
- **Selling Puts** → `_manage_put_position()` — monitor expiration, attempt rolling if needed
- **Assigned** (holding stock) → `_check_hard_stop()`, then `_check_capital_efficiency()`, then `_sell_call()`
- **Selling Calls** → `_manage_call_position()` — monitor for expiration or assignment

**Step 4: P&L Sync**

Updates strategy-level P&L aggregates from position data.

### Option Selection Logic

`_select_best_option()` filters the Alpaca option chain and scores candidates:

**Filters applied (all must pass):**
1. Correct option type (put for phase 1, call for phase 3)
2. Strike within constraint (puts: ≤ stock price; calls: ≥ min_strike from adjusted cost basis)
3. DTE within configured range (default 7-45 days)
4. Delta within configured range (default 0.15-0.30, using moneyness proxy if greeks unavailable)
5. Bid > 0 (option must have a market)
6. Annualized premium yield within range (default 4%-100%)

**Scoring formula (highest score wins):**
- 40% — Annualized yield (higher is better)
- 30% — Delta proximity to midpoint of range (closer to 0.225 is better)
- 30% — DTE proximity to midpoint of range (closer to 26 days is better)

**Moneyness fallback:** When Alpaca doesn't return greeks (common for some option chains), delta is estimated from how far the strike is from the stock price — a rough but usable proxy.

### Defensive Features

**Hard Stop (`_check_hard_stop`):** Before selling a covered call on assigned stock, checks if the stock has dropped more than `max_stock_loss_pct` (default 25%) from the entry price. If so, sells the stock immediately via market order — no bagholding broken positions. Logs: `hard_stop` event with full P&L breakdown including premiums collected.

**Rolling Puts (`_manage_put_position`):** When a sold put is deep in-the-money near expiration (stock > `roll_threshold_pct` below strike, DTE ≤ 3 days):
1. Estimates buy-to-close cost from current market data
2. Searches for a new put at a lower strike / later expiration
3. Only executes the roll if it produces a net credit ≥ `roll_min_net_credit` ($0.10/share)
4. Checks PDT limit before executing (rolling = 2 trades in one day)
5. If can't roll for credit: lets assignment happen (assignment is part of the Wheel's natural flow)

**Adjusted Cost Basis (`_get_adjusted_cost_basis`):** Tracks the true break-even for assigned stock by subtracting all premiums collected (from puts and prior calls) on that symbol. Used by `_sell_call()` to set intelligent strike selection — allows selling calls slightly below the raw entry price because premiums already offset some of the cost.

**Capital Efficiency Exits (`_check_capital_efficiency`):** Assigned stock held for more than `capital_efficiency_days` (default 60) with no price recovery is tying up capital unproductively. If down > 15%: sells and frees the capital. If down 5-15%: sells a more aggressive call (closer to ATM) to accelerate the exit.

**PDT Protection (`_would_exceed_pdt`):** Accounts under $25,000 are limited to 3 day trades per rolling 5 business days. Before executing a roll or same-day close, counts recent round-trip trades. If at limit, logs `blocked_pdt_limit` and skips the action.

### Cash Management

| Event | Cash Change | When |
|-------|-------------|------|
| Sell put fills | +premium (fill × 100) | Sync detects fill |
| Put assigned | −(strike × 100) | Assignment detection |
| Sell call fills | +premium (fill × 100) | Sync detects fill |
| Call assigned (called away) | +(strike × 100) | Assignment detection |
| Buy-to-close (roll) | −(fill × 100) | Sync detects fill |
| Hard stop / efficiency sell | +proceeds (fill × qty) | Sync detects fill |

Cash changes for order fills are asynchronous: the order is submitted immediately, but cash is adjusted when `_sync_option_orders` detects the fill from Alpaca (typically next cycle, ~60s). Assignment-related cash changes (put assigned, called away) happen synchronously during `_detect_assignments`.

**Cash reservation (collateral):** Before selling a new put, committed cash from existing open puts is subtracted:
```
committed = sum(strike × 100 × contracts for each open selling_puts position)
available = current_cash − committed
```
This prevents over-selling puts beyond what the account can cover if all assignments happen simultaneously. Importantly, collateral is tracked virtually — `current_cash` always reflects the full cash balance (including collateral). The reservation is computed on-the-fly each cycle and only used for position-sizing decisions, not deducted from the stored cash value.

### Portfolio Value Computation

Strategy cards show **Total Value = cash + portfolio_value**. The portfolio value is recomputed each cycle by `sync_strategy_pnl`, which sums `current_value` from all open positions:

**Simple Stock positions:**
- `current_value = latest_price × quantity` (updated each cycle from Alpaca market data)
- `unrealized_pnl = (latest_price − entry_price) × quantity`

**Wheel positions:**
- **Stock positions** (assigned phase): `current_value = latest_price × shares` (updated each cycle)
- **Option positions** (sold puts/calls): `current_value = -(buyback_cost)` — mark-to-market via live Alpaca option quotes. Since premium is already in cash, the position value is the *negative* of what it would cost to buy back the option (it's a liability). This gives accurate P&L: `unrealized_pnl = premium_collected − buyback_cost`. Quotes are fetched in batch once per cycle (~60s) using `get_option_quotes()`. If no quote is available, falls back to `current_value = 0` with premium as P&L.

**Example with $30,000 initial, 5 sold puts collecting $145 total premium:**
```
cash = $30,145 (initial + premiums)
option positions current_value = -$370 (sum of buyback costs)
portfolio_value = -$370
total_value = $30,145 + (-$370) = $29,775
total_pnl = $29,775 - $30,000 = -$225
```
This matches the brokerage mark-to-market view. The **Premium** column on the Positions table shows what was collected; **Value** shows the current liability; **P&L** shows premium minus buyback cost.

**P&L formula:** `total_pnl = (cash + portfolio_value) − initial_capital`

**Circuit breaker:** Uses the same formula. The `max_loss_pct` (default 20%) triggers a strategy pause when drawdown exceeds the threshold. Because collateral is not deducted from cash and option positions don't double-count premiums, the circuit breaker measures actual economic loss rather than capital set aside for obligations.

### Position Sizing ($30,000 Capital)

With $30,000 and screener-driven candidates (max price $200), the Wheel can run multiple concurrent positions across sectors. Tickers are sorted by price ascending — cheapest first to maximize the number of simultaneous positions. Assignment cost = strike × 100, so a $50 stock ties up ~$5,000. The `max_per_sector` constraint (default 2) prevents concentration in a single sector. Tickers where assignment cost exceeds available cash are logged as `blocked_insufficient_cash` and skipped.

### Activity Log Event Types

Both strategies generate extensive activity logs for monitoring. Three categories:

**Decision logs** (WHY a decision was made):
| Event Type | Strategy | When |
|-----------|----------|------|
| `signal` | Simple Stock | AI evaluated a candidate — includes action, confidence, reasoning |
| `option_selected` | Wheel | Best option chosen from chain (includes score, delta, yield, candidates evaluated) |
| `put_sold` | Wheel | Put sell order submitted (includes strike, premium, cash committed/remaining) |
| `call_sold` | Wheel | Call sell order submitted (includes strike, premium, adjusted cost basis) |
| `roll_executed` | Wheel | Put rolled to new strike/date (includes old/new symbols, net credit) |
| `hard_stop` | Wheel | Stock sold on hard stop (includes entry/exit price, loss %, premiums collected) |
| `capital_efficiency_exit` | Wheel | Stock sold after extended hold (includes days held, loss %) |
| `auto_index` | Simple Stock | Daily SEC filing indexing started/completed (includes ticker list) |

**Execution logs** (what happened, when):
| Event Type | Strategy | When |
|-----------|----------|------|
| `order_placed` | Both | Order submitted to Alpaca (includes order type, limit/stop prices) |
| `order_filled` | Both | Fill confirmed (includes fill price, premium credited) |
| `assignment` | Wheel | Put exercised, now holding stock |
| `called_away` | Wheel | Call exercised, shares sold, wheel cycle complete |
| `option_expired` | Wheel | Option expired worthless (kept premium) |
| `phase_transition` | Wheel | Symbol moved to new wheel phase |

**Blocked logs** (what the program wanted to do but couldn't):
| Event Type | Strategy | When |
|-----------|----------|------|
| `blocked_stop_loss` | Simple Stock | Stop-loss not confirmed on Alpaca re-fetch (bad initial read) |
| `blocked_stop_loss_price_mismatch` | Simple Stock | Stop-loss blocked: Alpaca vs yfinance price divergence > 5% |
| `blocked_take_profit_price_mismatch` | Simple Stock | Take-profit blocked: Alpaca vs yfinance price divergence > 5% |
| `blocked_stale_price` | Simple Stock | Price too old during market hours (last trade > 5 min ago) |
| `blocked_wide_spread` | Simple Stock | Bid/ask spread > 2% — illiquid stock or bad data |
| `blocked_insufficient_cash` | Wheel | Wanted to sell put but can't afford assignment |
| `blocked_too_expensive` | Wheel | Ticker's 100 shares exceed total strategy capital |
| `blocked_no_options` | Wheel | No contracts passed filters (includes filter breakdown) |
| `blocked_no_greeks` | Wheel | Using moneyness fallback for delta |
| `blocked_position_exists` | Wheel | Already have an open position on this symbol |
| `blocked_roll_no_credit` | Wheel | Wanted to roll but can't get net credit |
| `blocked_pdt_limit` | Wheel | Day trade would exceed 3-per-5-day PDT limit |

All event details are stored in the `details` JSONB column and visible in the frontend Activity Feed via expandable detail rows.

## Safety Features

| Feature | Strategy | Behavior |
|---------|----------|----------|
| **Circuit breaker** | Both | Auto-pauses strategy if drawdown > `max_loss_pct` (default 20%) |
| **Position sizing** | Simple Stock | Max 25% of capital in a single position |
| **Stop-loss** | Simple Stock | Auto-sells if price drops > 10% from entry — 3-layer confirmation (Alpaca re-fetch + staleness/spread checks + yfinance cross-check), then stop-limit order |
| **Take-profit** | Simple Stock | Auto-sells if price rises > 20% from entry — validated with yfinance confirmation, then limit order |
| **Price confirmation** | Simple Stock | Independent yfinance price check for stop-loss/take-profit — blocks if Alpaca vs yfinance diverge > 5%. Falls back to bid/ask midpoint cross-check if yfinance unavailable |
| **Price staleness** | Simple Stock | Rejects prices with last trade > 5 minutes old during market hours (stale data = unreliable decisions) |
| **Spread check** | Simple Stock | Blocks all trades when bid/ask spread > 2% — indicates illiquidity or bad market data |
| **No market orders** | Simple Stock | All trades use limit or stop-limit orders — prevents runaway fills during volatility or flash crashes |
| **Hard stop** | Wheel | Sells assigned stock if down > 25% from entry |
| **Rolling puts** | Wheel | Rolls deep-ITM puts near expiry for net credit when possible |
| **Capital efficiency exits** | Wheel | Reviews assigned stock held > 60 days with no recovery |
| **Cash reservation** | Wheel | Prevents over-selling puts beyond assignment capacity |
| **PDT protection** | Wheel | Blocks trades that would exceed 3-per-5-day day trade limit |
| **Affordability gating** | Wheel | Skips tickers where assignment cost > available cash |
| **Market hours gate** | Both | Only runs during US market hours (Mon-Fri, 9 AM - 4 PM ET) |
| **AI cost cap** | Simple Stock | Max 5 AI calls per cycle to limit GPT-4o spending |
| **Master kill switch** | Both | `TRADING_ENABLED=false` prevents engine from starting |
| **Alpaca key guard** | Both | Start endpoint returns 503 if keys aren't configured |
| **Error resilience** | Both | Per-strategy (and per-symbol for Wheel) try/except — one failure doesn't block others |

## Cost Estimates

| Component | Per Cycle | Per Day (~8 cycles) | Per Month |
|-----------|-----------|---------------------|-----------|
| GPT-4o signals (max 5 buy + sell checks) | ~$0.05-0.15 | ~$0.40-1.20 | ~$8-25 |
| Daily auto-index (embeddings for ~10 tickers) | — | ~$0.50-1.00 | ~$10-20 |
| RAG search (query embeddings) | ~$0.001 | ~$0.01 | ~$0.20 |
| Alpaca API calls | $0 | $0 | $0 |
| Market data | $0 (included) | $0 | $0 |
| **Total** | **~$0.05-0.15** | **~$1.00-2.20** | **~$18-45** |

AI costs depend on how many candidates pass the screener filter. With a `min_screener_score` of 60 and `max_ai_calls_per_cycle` of 5, costs stay predictable. The auto-indexing cost is a one-time daily expense; RAG search itself is nearly free (one embedding per query, then pgvector does in-DB cosine similarity).

## Debugging

### Check strategy status

```sql
SELECT id, status, current_cash, current_portfolio_value, total_pnl,
       last_run_at, last_error, error_count
FROM trading_strategies;
```

### View recent orders

```sql
SELECT ticker, side, order_type, quantity, status,
       filled_avg_price, reason, submitted_at
FROM trading_orders
ORDER BY submitted_at DESC
LIMIT 20;
```

### View AI decisions

```sql
SELECT ticker, ai_signal->>'action' as action,
       ai_signal->>'confidence' as confidence,
       ai_signal->>'reasoning' as reasoning,
       submitted_at
FROM trading_orders
WHERE ai_signal IS NOT NULL
ORDER BY submitted_at DESC;
```

### Check open positions

```sql
SELECT ticker, quantity, avg_entry_price, current_value,
       unrealized_pnl, opened_at
FROM trading_positions
WHERE status = 'open'
ORDER BY opened_at DESC;
```

### Activity log

```sql
SELECT event_type, ticker, message, created_at
FROM trading_activity_log
ORDER BY created_at DESC
LIMIT 30;
```

### Backend logs

The trading engine logs at each stage:
```
INFO: Trading engine starting (interval=60s)...
INFO: Running daily auto-index for simple stock candidates...
INFO: Auto-index: indexing 3 tickers: ['AAPL', 'MSFT', 'INTC']
INFO: Auto-index: AAPL complete (8 filings, 245 chunks)
INFO: Auto-index: MSFT complete (7 filings, 198 chunks)
INFO: Auto-index: INTC complete (6 filings, 172 chunks)
INFO: Simple stock cycle starting (cash=$500.00)
INFO: Simple stock candidates: 8 from screener (min_score=60, top_n=20)
INFO: RAG: injected 5 filing chunks (1842 tokens) for AAPL trade signal
INFO: AI signal for AAPL: buy (conf=0.82)
INFO: Buy limit order placed: AAPL x3 @ limit=$176.38
INFO: RAG: injected 4 filing chunks (1560 tokens) for MSFT trade signal
INFO: AI signal for MSFT: hold (conf=0.45)
INFO: Simple stock cycle complete
```

**Layer 1 safety check logs:**
```
INFO: Price confirmed for stop_loss ACT: Alpaca=$41.42, yfinance=$41.38 (0.1% divergence)
WARNING: Stop-loss blocked for XYZ: Price mismatch: Alpaca=$36.34 vs yfinance=$41.42 (14.0% divergence, max 5%)
WARNING: buy ILLQ blocked — Spread too wide: 3.45% (max 2.0%)
WARNING: stop_loss STALE blocked — Price stale: last trade 342s ago (max 300s during market hours)
```

## Implementation Status

| Phase | Status | Description |
|-------|--------|-------------|
| **Phase 1** | Complete | DB schema, Alpaca client, trading DB helpers, API endpoints, frontend shell (strategy cards, positions/orders/activity tables, portfolio summary) |
| **Phase 2** | Complete | Simple stock strategy (AI signals + execution), trading engine wiring, market hours gate, scanner timing (hourly → daily at 5 PM ET), RAG-enhanced trade signals (daily auto-index + filing context injection) |
| **Phase 3** | Complete | Wheel options strategy — state machine, option selection, defensive suite (hard stops, rolling, adjusted cost basis, capital efficiency), enhanced Activity Feed with filters/expand/date range, comprehensive observability logging |
| **Phase 3.5** | Complete | Layer 1 Execution Safety — independent yfinance price confirmation, bid/ask spread checks, price staleness validation, limit/stop-limit orders (no market orders), 3-layer stop-loss confirmation |
| **Phase 4** | Not started | Layer 2 Smarter Entry/Exit — intrinsic value guardrails, trailing stop-loss, scaled entries (DCA), volatility-adjusted sizing |
| **Phase 5** | Not started | Polish — P&L charts, strategy config modal, report generation, CSV export |
