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
    last_full_scan_started_at TIMESTAMPTZ,
    last_full_scan_completed_at TIMESTAMPTZ,
    last_error TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Seed the single status row (idempotent)
INSERT INTO scanner_status (id) VALUES (1) ON CONFLICT DO NOTHING;
