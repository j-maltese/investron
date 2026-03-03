# Automated Paper Trading — Alpaca Markets Integration

Investron can automatically trade on your behalf using Alpaca Markets' paper trading API. Two independent strategies run in the background, each with its own capital allocation and trading logic:

1. **Simple Stock Trading** ($500 paper) — AI-powered buy/sell of common stock, leveraging the screener scores and GPT-4o analysis
2. **The Wheel Strategy** ($5,000 paper) — Mechanical options strategy: sell cash-secured puts, get assigned, sell covered calls, repeat *(Phase 3 — not yet implemented)*

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
│          - Stop-loss (price down > 10% from entry)            │
│          - Take-profit (price up > 20% from entry)            │
│          - AI says sell with high confidence                   │
│       c. Find new buy opportunities:                          │
│          - Filter: screener composite scores (free)           │
│          - Confirm: GPT-4o trade signal (max 5/cycle)         │
│          - Size: max 25% of capital per position              │
│          - Execute: market order via Alpaca                   │
│                                                               │
│     Wheel: (Phase 3 — not yet implemented)                    │
│       a. Sell cash-secured puts on selected tickers           │
│       b. If assigned, hold stock and sell covered calls       │
│       c. If called away, collect profit, restart cycle        │
│                                                               │
│  4. Update last_run timestamp                                 │
│  5. Sync P&L from position data                               │
└──────────────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│  Frontend (/trading page, polls every 15-30s)                 │
│                                                               │
│  Overview tab:    Portfolio summary + strategy cards           │
│  Positions tab:   Open/closed positions with P&L              │
│  Orders tab:      Complete order history with AI signals       │
│  Activity tab:    Event stream (orders, fills, errors, etc.)  │
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
- Enables per-strategy capital isolation (Alpaca gives one paper account; we allocate $500 vs $5,000 logically)
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
| `initial_capital` | DECIMAL(12,2) | Starting capital ($500 / $5,000) |
| `current_cash` | DECIMAL(12,2) | Available cash after open positions |
| `current_portfolio_value` | DECIMAL(12,2) | Market value of open positions |
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

**Wheel:** *(Phase 3)*
```json
{
    "symbol_list": ["F", "SOFI", "INTC", "PLTR", "BAC", "AMD"],
    "delta_min": 0.15,
    "delta_max": 0.30,
    "yield_min": 0.04,
    "yield_max": 1.00,
    "expiration_min_days": 7,
    "expiration_max_days": 45,
    "open_interest_min": 100,
    "score_min": 0.05,
    "check_interval_minutes": 15
}
```

### Backend Services

```
backend/app/
├── services/
│   ├── alpaca_client.py          # Thin wrapper around alpaca-py SDK
│   │                              #   Cached client singletons (TradingClient, StockDataClient, OptionDataClient)
│   │                              #   submit_stock_order(), submit_option_order(), get_order_status()
│   │                              #   get_positions(), get_account_info(), get_option_chain(), cancel_order()
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
│   └── simple_stock_strategy.py  # AI-powered stock trading logic
│                                  #   run_simple_stock_cycle() — sync → sells → buys
│                                  #   run_auto_index_cycle() — daily SEC filing indexing
│                                  #   _get_candidate_tickers() — screener top N by composite score
│                                  #   _get_ai_trade_signal() — GPT-4o with financials + RAG filing context
│                                  #   _sync_pending_orders() — poll Alpaca for fills
│                                  #   _execute_buy() / _execute_sell() — order + position management
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
│   └── useTrading.ts             # TanStack Query hooks (30s polling) + mutations
│                                  #   useStrategies, usePortfolio, usePositions, useOrders, useActivityLog
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
    └── ActivityFeed.tsx           # Event stream with Lucide icons per event type
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
GET    /activity?strategy_id=simple_stock&limit=50&offset=0
```

All return paginated results with a `total_count` field.

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

Navigate to `/trading` — you should see both strategy cards with $500 and $5,000 starting capital.

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
  → Get latest price from Alpaca market data (bid/ask midpoint)
  → Update unrealized P&L
  → Check stop-loss:  price dropped > 10% from entry → SELL (market order)
  → Check take-profit: price up > 20% from entry → SELL (market order)
  → AI sell check: call GPT-4o with "hold or sell" prompt
      → If action=sell AND confidence >= 0.7 → SELL
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
      → Calculate shares: floor(cash * 25% / price) — whole shares only
      → Submit market order to Alpaca
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

## Safety Features

| Feature | Behavior |
|---------|----------|
| **Circuit breaker** | Auto-pauses strategy if drawdown > `max_loss_pct` (default 20%) |
| **Position sizing** | Max 25% of capital in a single position |
| **Stop-loss** | Auto-sells if price drops > 10% from entry |
| **Take-profit** | Auto-sells if price rises > 20% from entry |
| **Market hours gate** | Only runs during US market hours (Mon-Fri, 9 AM - 4 PM ET) |
| **AI cost cap** | Max 5 AI calls per cycle to limit GPT-4o spending |
| **Master kill switch** | `TRADING_ENABLED=false` prevents engine from starting |
| **Alpaca key guard** | Start endpoint returns 503 if keys aren't configured |
| **Error resilience** | Individual strategy errors don't crash the engine; logged and retried next cycle |

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
INFO: Buy order placed: AAPL x3 @ ~$175.50
INFO: RAG: injected 4 filing chunks (1560 tokens) for MSFT trade signal
INFO: AI signal for MSFT: hold (conf=0.45)
INFO: Simple stock cycle complete
```

## Implementation Status

| Phase | Status | Description |
|-------|--------|-------------|
| **Phase 1** | Complete | DB schema, Alpaca client, trading DB helpers, API endpoints, frontend shell (strategy cards, positions/orders/activity tables, portfolio summary) |
| **Phase 2** | Complete | Simple stock strategy (AI signals + execution), trading engine wiring, market hours gate, scanner timing (hourly → daily at 5 PM ET), RAG-enhanced trade signals (daily auto-index + filing context injection) |
| **Phase 3** | Not started | Wheel options strategy (put/call/assignment state machine) |
| **Phase 4** | Not started | Polish — P&L charts, strategy config modal, trading section in User Guide |
