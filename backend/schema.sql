-- Investron Database Schema
-- Run this in the Supabase SQL editor to create all tables

-- Companies table
CREATE TABLE IF NOT EXISTS companies (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    cik VARCHAR(10),
    sector VARCHAR(100),
    industry VARCHAR(100),
    exchange VARCHAR(20),
    fiscal_year_end VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_companies_ticker ON companies(ticker);
CREATE INDEX IF NOT EXISTS idx_companies_cik ON companies(cik);

-- Financial data cache
CREATE TABLE IF NOT EXISTS financial_data_cache (
    id SERIAL PRIMARY KEY,
    company_id INT REFERENCES companies(id) ON DELETE CASCADE,
    source VARCHAR(20) NOT NULL,
    data_type VARCHAR(50) NOT NULL,
    period_type VARCHAR(10) NOT NULL,
    data JSONB NOT NULL,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    UNIQUE(company_id, source, data_type, period_type)
);

CREATE INDEX IF NOT EXISTS idx_financial_cache_lookup
    ON financial_data_cache(company_id, source, data_type, period_type);
CREATE INDEX IF NOT EXISTS idx_financial_cache_expiry
    ON financial_data_cache(expires_at);

-- SEC filings cache
CREATE TABLE IF NOT EXISTS filings_cache (
    id SERIAL PRIMARY KEY,
    company_id INT REFERENCES companies(id) ON DELETE CASCADE,
    filing_type VARCHAR(20) NOT NULL,
    filing_date DATE NOT NULL,
    accession_number VARCHAR(30),
    filing_url TEXT,
    description TEXT,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(company_id, accession_number)
);

CREATE INDEX IF NOT EXISTS idx_filings_company ON filings_cache(company_id);
CREATE INDEX IF NOT EXISTS idx_filings_type ON filings_cache(company_id, filing_type);
CREATE INDEX IF NOT EXISTS idx_filings_date ON filings_cache(filing_date DESC);

-- Watchlist
CREATE TABLE IF NOT EXISTS watchlist_items (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL UNIQUE,
    company_id INT REFERENCES companies(id) ON DELETE SET NULL,
    notes TEXT,
    target_price DECIMAL(12,2),
    added_at TIMESTAMPTZ DEFAULT NOW()
);

-- Saved valuation scenarios
CREATE TABLE IF NOT EXISTS saved_scenarios (
    id SERIAL PRIMARY KEY,
    company_id INT REFERENCES companies(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    assumptions JSONB NOT NULL,
    result JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scenarios_company ON saved_scenarios(company_id);

-- Value Screener: pre-computed scores for ranked stock discovery
-- Stores both raw yfinance metrics and derived score components so the API
-- serves results instantly without re-computation on every request.
CREATE TABLE IF NOT EXISTS screener_scores (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL UNIQUE,
    company_name VARCHAR(255),
    sector VARCHAR(100),
    industry VARCHAR(100),

    -- Raw metrics snapshot (from yfinance .info dict, single API call per ticker)
    price DECIMAL(12,4),
    market_cap BIGINT,
    pe_ratio DECIMAL(10,2),
    forward_pe DECIMAL(10,2),
    pb_ratio DECIMAL(10,2),
    ps_ratio DECIMAL(10,2),
    debt_to_equity DECIMAL(10,2),
    current_ratio DECIMAL(10,4),
    roe DECIMAL(10,6),
    eps DECIMAL(10,4),
    book_value DECIMAL(12,4),
    free_cash_flow BIGINT,
    total_revenue BIGINT,
    dividend_yield DECIMAL(10,6),
    revenue_growth DECIMAL(10,6),
    earnings_growth DECIMAL(10,6),
    net_margin DECIMAL(10,6),
    beta DECIMAL(6,4),
    fifty_two_week_high DECIMAL(12,4),
    fifty_two_week_low DECIMAL(12,4),

    -- Derived value scores (each 0.0-1.0, computed by screener.py)
    graham_number DECIMAL(12,4),
    margin_of_safety DECIMAL(10,4),       -- raw % (positive = undervalued)
    pe_score DECIMAL(6,4),
    pb_score DECIMAL(6,4),
    roe_score DECIMAL(6,4),
    debt_equity_score DECIMAL(6,4),
    fcf_yield DECIMAL(10,6),              -- raw FCF/market_cap ratio
    fcf_yield_score DECIMAL(6,4),
    earnings_yield DECIMAL(10,6),         -- raw 1/PE ratio
    earnings_yield_score DECIMAL(6,4),
    dividend_score DECIMAL(6,4),
    margin_of_safety_score DECIMAL(6,4),

    -- Composite: weighted blend of component scores, scaled 0-100
    composite_score DECIMAL(6,2),
    rank INT,                             -- 1 = best value, recomputed after each scan

    -- Warning flags as JSONB array: [{code, severity, message}, ...]
    -- Warnings inform but never filter — distressed stocks stay in results
    warnings JSONB DEFAULT '[]'::jsonb,

    -- Index memberships as JSONB array: ["S&P 500", "NASDAQ-100", "Dow 30"]
    -- A stock can belong to multiple indices. Uses GIN index for @> (contains) queries.
    indices JSONB DEFAULT '[]'::jsonb,

    -- When this row was last scored and when the underlying metrics were fetched
    scored_at TIMESTAMPTZ DEFAULT NOW(),
    metrics_fetched_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_screener_composite ON screener_scores(composite_score DESC);
CREATE INDEX IF NOT EXISTS idx_screener_rank ON screener_scores(rank ASC);
CREATE INDEX IF NOT EXISTS idx_screener_sector ON screener_scores(sector);
CREATE INDEX IF NOT EXISTS idx_screener_indices ON screener_scores USING GIN (indices);

-- Scanner status: single-row table tracking background scan progress.
-- The CHECK constraint on id ensures only one row ever exists.
CREATE TABLE IF NOT EXISTS scanner_status (
    id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    is_running BOOLEAN DEFAULT FALSE,
    current_ticker VARCHAR(10),
    tickers_scanned INT DEFAULT 0,
    tickers_total INT DEFAULT 0,
    tickers_no_data INT DEFAULT 0,            -- Tickers with no yfinance data (delisted, OTC)
    tickers_timeout INT DEFAULT 0,            -- Tickers that timed out
    tickers_error INT DEFAULT 0,              -- Tickers with unexpected errors
    last_full_scan_started_at TIMESTAMPTZ,
    last_full_scan_completed_at TIMESTAMPTZ,
    last_error TEXT,                           -- JSON failure summary after scan completion
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Seed the single status row (idempotent)
INSERT INTO scanner_status (id) VALUES (1) ON CONFLICT DO NOTHING;

-- Add failure counter columns to existing deployments (idempotent)
ALTER TABLE scanner_status ADD COLUMN IF NOT EXISTS tickers_no_data INT DEFAULT 0;
ALTER TABLE scanner_status ADD COLUMN IF NOT EXISTS tickers_timeout INT DEFAULT 0;
ALTER TABLE scanner_status ADD COLUMN IF NOT EXISTS tickers_error INT DEFAULT 0;

-- pgvector extension for SEC filing RAG (on-demand vectorization)
CREATE EXTENSION IF NOT EXISTS vector;

-- Tracks which companies have been indexed for RAG filing search
CREATE TABLE IF NOT EXISTS filing_index_status (
    id SERIAL PRIMARY KEY,
    company_id INT REFERENCES companies(id) ON DELETE CASCADE,
    ticker VARCHAR(10) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    filings_indexed INT DEFAULT 0,
    chunks_total INT DEFAULT 0,
    last_indexed_at TIMESTAMPTZ,
    last_filing_date DATE,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Filing chunks with vector embeddings for semantic search
CREATE TABLE IF NOT EXISTS filing_chunks (
    id SERIAL PRIMARY KEY,
    company_id INT REFERENCES companies(id) ON DELETE CASCADE,
    filing_id INT REFERENCES filings_cache(id) ON DELETE CASCADE,
    ticker VARCHAR(10) NOT NULL,
    filing_type VARCHAR(20) NOT NULL,
    filing_date DATE NOT NULL,
    section_name VARCHAR(100),
    category VARCHAR(50),
    topics TEXT[],
    chunk_index INT NOT NULL,
    chunk_text TEXT NOT NULL,
    token_count INT,
    is_table BOOLEAN DEFAULT FALSE,
    embedding vector(1536),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fc_ticker ON filing_chunks(ticker);
CREATE INDEX IF NOT EXISTS idx_fc_ticker_type ON filing_chunks(ticker, filing_type);
CREATE INDEX IF NOT EXISTS idx_fc_category ON filing_chunks(ticker, category);
CREATE INDEX IF NOT EXISTS idx_fc_filing_date ON filing_chunks(filing_date DESC);
CREATE INDEX IF NOT EXISTS idx_fc_filing_id ON filing_chunks(filing_id);
CREATE INDEX IF NOT EXISTS idx_fc_embedding ON filing_chunks
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- =====================================================================
-- Paper Trading: automated strategy execution via Alpaca Markets API
-- =====================================================================

-- Trading strategies — one row per configured strategy (simple_stock, wheel).
-- Each strategy has independent capital, state, and JSONB config.
CREATE TABLE IF NOT EXISTS trading_strategies (
    id VARCHAR(30) PRIMARY KEY,
    display_name VARCHAR(100) NOT NULL,
    strategy_type VARCHAR(30) NOT NULL,       -- 'simple_stock' or 'wheel'
    status VARCHAR(20) NOT NULL DEFAULT 'stopped',  -- stopped | running | paused | error
    initial_capital DECIMAL(12,2) NOT NULL,
    current_cash DECIMAL(12,2) NOT NULL,
    current_portfolio_value DECIMAL(12,2) DEFAULT 0,
    total_pnl DECIMAL(12,2) DEFAULT 0,
    total_pnl_pct DECIMAL(8,4) DEFAULT 0,
    realized_pnl DECIMAL(12,2) DEFAULT 0,
    unrealized_pnl DECIMAL(12,2) DEFAULT 0,

    -- Strategy-specific config (different shapes per strategy type)
    config JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Safety limits
    max_loss_pct DECIMAL(6,2) DEFAULT 20.0,       -- Pause strategy if drawdown exceeds this
    max_position_pct DECIMAL(6,2) DEFAULT 25.0,    -- Max % of capital in a single position

    last_run_at TIMESTAMPTZ,
    last_error TEXT,
    error_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Trading positions — open and historical positions for all strategies.
-- Option positions use option_* fields; stock positions leave them null.
CREATE TABLE IF NOT EXISTS trading_positions (
    id SERIAL PRIMARY KEY,
    strategy_id VARCHAR(30) NOT NULL REFERENCES trading_strategies(id),
    ticker VARCHAR(10) NOT NULL,
    asset_type VARCHAR(10) NOT NULL DEFAULT 'stock',  -- 'stock' or 'option'

    -- Stock fields
    quantity DECIMAL(12,4) DEFAULT 0,
    avg_entry_price DECIMAL(12,4),

    -- Option fields (null for stock positions)
    option_symbol VARCHAR(50),
    option_type VARCHAR(4),           -- 'put' or 'call'
    strike_price DECIMAL(12,2),
    expiration_date DATE,
    contracts INT,

    -- Wheel strategy phase tracking
    wheel_phase VARCHAR(20),          -- 'selling_puts' | 'assigned' | 'selling_calls' | null

    -- P&L tracking
    cost_basis DECIMAL(12,2),
    current_value DECIMAL(12,2),
    realized_pnl DECIMAL(12,2) DEFAULT 0,
    unrealized_pnl DECIMAL(12,2) DEFAULT 0,

    status VARCHAR(20) NOT NULL DEFAULT 'open',  -- open | closed | assigned | expired
    opened_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    close_reason VARCHAR(50),         -- sold | assigned | expired | stop_loss | called_away
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tp_strategy ON trading_positions(strategy_id);
CREATE INDEX IF NOT EXISTS idx_tp_strategy_status ON trading_positions(strategy_id, status);
CREATE INDEX IF NOT EXISTS idx_tp_ticker ON trading_positions(ticker);

-- Trading orders — every order submitted to Alpaca, with local metadata.
CREATE TABLE IF NOT EXISTS trading_orders (
    id SERIAL PRIMARY KEY,
    strategy_id VARCHAR(30) NOT NULL REFERENCES trading_strategies(id),
    position_id INT REFERENCES trading_positions(id),
    alpaca_order_id VARCHAR(50) UNIQUE,

    ticker VARCHAR(10) NOT NULL,
    asset_type VARCHAR(10) NOT NULL DEFAULT 'stock',
    side VARCHAR(10) NOT NULL,                -- 'buy' or 'sell'
    order_type VARCHAR(20) NOT NULL,          -- market | limit | stop | stop_limit
    time_in_force VARCHAR(10) DEFAULT 'day',

    quantity DECIMAL(12,4),
    limit_price DECIMAL(12,4),
    stop_price DECIMAL(12,4),

    -- Option fields
    option_symbol VARCHAR(50),
    option_type VARCHAR(4),
    strike_price DECIMAL(12,2),
    expiration_date DATE,
    contracts INT,

    -- Fill info (updated when order fills)
    filled_quantity DECIMAL(12,4),
    filled_avg_price DECIMAL(12,4),
    filled_at TIMESTAMPTZ,

    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending | submitted | filled | partially_filled | cancelled | rejected

    -- Decision audit trail
    reason TEXT,                       -- Human-readable explanation
    ai_signal JSONB,                  -- AI analysis that triggered this trade (simple_stock only)

    submitted_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_to_strategy ON trading_orders(strategy_id);
CREATE INDEX IF NOT EXISTS idx_to_alpaca_id ON trading_orders(alpaca_order_id);
CREATE INDEX IF NOT EXISTS idx_to_status ON trading_orders(status);
CREATE INDEX IF NOT EXISTS idx_to_submitted ON trading_orders(submitted_at DESC);

-- Trading activity log — append-only event stream for observability.
CREATE TABLE IF NOT EXISTS trading_activity_log (
    id SERIAL PRIMARY KEY,
    strategy_id VARCHAR(30) NOT NULL REFERENCES trading_strategies(id),
    event_type VARCHAR(30) NOT NULL,  -- order_placed | order_filled | assignment | strategy_start | strategy_stop | error | signal | rebalance
    ticker VARCHAR(10),
    message TEXT NOT NULL,
    details JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tal_strategy ON trading_activity_log(strategy_id);
CREATE INDEX IF NOT EXISTS idx_tal_created ON trading_activity_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tal_event ON trading_activity_log(event_type);

-- Seed the two strategy rows (idempotent)
INSERT INTO trading_strategies (id, display_name, strategy_type, initial_capital, current_cash, config)
VALUES
    ('simple_stock', 'Simple Stock Trading', 'simple_stock', 500.00, 500.00, '{
        "screener_top_n": 20,
        "max_position_pct": 25.0,
        "use_ai_signals": true,
        "min_screener_score": 60.0,
        "min_ai_confidence": 0.7,
        "stop_loss_pct": 10.0,
        "take_profit_pct": 20.0,
        "max_ai_calls_per_cycle": 5,
        "check_interval_minutes": 30
    }'::jsonb),
    ('wheel', 'The Wheel Strategy', 'wheel', 5000.00, 5000.00, '{
        "symbol_list": ["F", "SOFI", "INTC", "PLTR", "BAC", "AMD"],
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
    }'::jsonb)
ON CONFLICT (id) DO NOTHING;
