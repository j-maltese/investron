# Investron — Backend

FastAPI application serving financial data, valuation models, and watchlist management. Integrates with SEC EDGAR for structured XBRL financial data and yfinance for real-time market metrics.

## Tech Stack

- **FastAPI** — Async Python web framework
- **SQLAlchemy 2.0** (async) + **asyncpg** — PostgreSQL ORM with native async driver
- **Supabase** — Managed PostgreSQL + Auth (JWT verification)
- **httpx** — Async HTTP client for SEC EDGAR API calls
- **yfinance** — Real-time stock prices, metrics, insider data
- **Pydantic** — Request/response validation and settings management

## API Routes

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/api/companies/search?q={query}` | Search companies by ticker or name |
| `GET` | `/api/companies/{ticker}` | Get company details (creates if not in DB) |
| `GET` | `/api/financials/{ticker}/statements?statement_type=income_statement&period_type=annual` | Financial statements (income, balance sheet, cash flow) |
| `GET` | `/api/financials/{ticker}/metrics` | Key metrics: P/E, P/B, ROE, margins, dividend yield |
| `GET` | `/api/financials/{ticker}/graham-score` | Graham's 7 criteria evaluation with score and Graham Number |
| `GET` | `/api/financials/{ticker}/growth-metrics` | Growth metrics: burn rate, cash runway, dilution, R&D intensity |
| `GET` | `/api/filings/{ticker}?types=10-K,10-Q` | SEC filings list with links to EDGAR documents |
| `POST` | `/api/valuation/{ticker}/dcf` | DCF valuation with custom growth/discount rates |
| `POST` | `/api/valuation/{ticker}/scenario` | Bull/base/bear scenario analysis |
| `GET` | `/api/watchlist` | Get watchlist items with current prices |
| `POST` | `/api/watchlist` | Add ticker to watchlist |
| `DELETE` | `/api/watchlist/{ticker}` | Remove from watchlist |
| `PATCH` | `/api/watchlist/{ticker}` | Update notes or target price |
| `GET` | `/api/watchlist/alerts` | Get price alerts (within 10% of target) |

## Data Flow

```
User Request
     │
     ▼
FastAPI Route (/api/...)
     │
     ▼
Service Layer (services/*.py)
     │
     ├──► Check DB cache (financial_data_cache / filings_cache)
     │         │
     │    Cache hit? ──► Return cached data
     │         │
     │    Cache miss ▼
     │
     ├──► SEC EDGAR API (httpx)          ──► XBRL company facts, submissions, filings
     │         │                                rate-limited: 10 req/sec
     │         ▼
     │    Parse & normalize data
     │         │
     ├──► yfinance (yfinance lib)        ──► Prices, P/E, margins, insider trades
     │         │                                rate-limited: 5 req/sec
     │         ▼
     │    Store in DB cache (with TTL)
     │
     ▼
JSON Response
```

## Services

| Service | File | Purpose |
|---------|------|---------|
| **EDGAR** | `services/edgar.py` | CIK lookup, XBRL company facts, filing submissions, financial time series extraction |
| **yfinance** | `services/yfinance_svc.py` | Stock info (25+ fields), price history, insider transactions |
| **Company** | `services/company.py` | Company search, get-or-create with EDGAR + yfinance data |
| **Financials** | `services/financials.py` | Financial statement aggregation, key metrics, growth analysis |
| **Filings** | `services/filings.py` | Filing retrieval with DB caching |
| **Valuation** | `services/valuation.py` | Graham Score (7 criteria), DCF calculation, scenario modeling |

### EDGAR Integration

The SEC EDGAR integration uses three main endpoints:

1. **`company_tickers.json`** — Maps ticker symbols to CIK numbers (the SEC's primary identifier)
2. **`submissions/CIK{cik}.json`** — Company metadata and recent filing history
3. **`api/xbrl/companyfacts/CIK{cik}.json`** — Structured financial data (US-GAAP) as time series

Financial concepts are mapped from XBRL taxonomy names to readable fields:

- **Income statement**: Revenue, gross profit, operating income, net income, EPS, shares outstanding
- **Balance sheet**: Cash, receivables, total assets, debt, equity, retained earnings
- **Cash flow**: Operating/investing/financing cash flows, CapEx, dividends, share repurchases

### Valuation Models

**Graham Score** evaluates 7 criteria from *The Intelligent Investor*:
1. Adequate size (revenue > $2B)
2. Strong financial condition (current ratio >= 2.0)
3. Earnings stability (positive earnings 5+ consecutive years)
4. Dividend record (currently pays dividends)
5. Earnings growth (>= 33% EPS growth)
6. Moderate P/E (<= 15)
7. Moderate price-to-assets (P/B <= 1.5 or P/E x P/B <= 22.5)

Also calculates: Graham Number = sqrt(22.5 x EPS x Book Value) and Margin of Safety.

**DCF** projects free cash flows over N years with a terminal value (perpetuity growth model), discounting back to present value.

**Scenario Modeling** runs bull/base/bear cases with independent assumptions for revenue growth, terminal margin, discount rate, and share dilution. Results are probability-weighted into a single intrinsic value estimate.

## Database Schema

Five tables in PostgreSQL (Supabase):

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `companies` | Company master data | `id`, `ticker` (unique), `name`, `cik`, `sector`, `industry`, `exchange`, `fiscal_year_end` |
| `filings_cache` | Cached SEC filings | `company_id` (FK), `filing_type`, `filing_date`, `accession_number`, `filing_url` |
| `financial_data_cache` | Cached financial data (JSONB) | `company_id` (FK), `source`, `data_type`, `period_type`, `data` (jsonb), `expires_at` |
| `watchlist_items` | User watchlist | `ticker` (unique), `company_id` (FK), `target_price`, `notes` |
| `auth.users` | Supabase-managed auth | (managed by Supabase) |

## Caching Strategy

All external API data is cached in PostgreSQL with configurable TTLs:

| Data Type | TTL | Rationale |
|-----------|-----|-----------|
| Financial statements (XBRL) | 24 hours | Quarterly filings; daily refresh sufficient |
| SEC filings list | 24 hours | New filings appear daily at most |
| Stock prices & metrics | 15 minutes | Price-sensitive; balance freshness with API limits |
| Company info | 7 days | Rarely changes (sector, CIK, name) |

Cache is stored in `financial_data_cache` as JSONB with `expires_at` timestamps. Expired entries are re-fetched on next request.

## Rate Limiting

External APIs are rate-limited to comply with provider policies:

| API | Limit | Implementation |
|-----|-------|---------------|
| SEC EDGAR | 10 requests/second | Token bucket via `utils/rate_limiter.py` |
| yfinance | 5 requests/second | Token bucket via `utils/rate_limiter.py` |

## Running Locally

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Environment Variables

Create a `.env` file in this directory:

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_PUBLISHABLE_KEY` | Yes | Supabase anon key |
| `SUPABASE_SECRET_KEY` | Yes | Supabase service role key |
| `DATABASE_URL` | Yes | PostgreSQL connection string (session pooler recommended) |
| `SEC_EDGAR_USER_AGENT` | Yes | Your name + email — required by SEC EDGAR fair access policy |
| `DEBUG` | No | Enable debug logging (default: `false`) |
| `CORS_ORIGINS` | No | Allowed origins JSON array (default: `["http://localhost:5173"]`) |

### API Documentation

FastAPI auto-generates interactive docs:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
