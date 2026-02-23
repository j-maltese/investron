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
