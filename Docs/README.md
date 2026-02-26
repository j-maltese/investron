# Investron

A fundamental value investing research platform built for long-term investors who follow Warren Buffett and Benjamin Graham's principles. Investron pulls financial data from SEC EDGAR and yfinance, providing structured analysis tools including Graham's defensive investor criteria, DCF valuation, and scenario modeling.

## Architecture

```
Frontend (React + TypeScript)         Backend (FastAPI + Python)         Data Sources
┌──────────────────────────┐     ┌──────────────────────────────┐     ┌────────────────┐
│  React 19 + Vite         │     │  FastAPI                     │     │  SEC EDGAR     │
│  React Router v6         │────>│  ├── /api/companies          │────>│  (XBRL / JSON) │
│  TanStack Query          │     │  ├── /api/financials         │     │                │
│  Recharts                │     │  ├── /api/filings            │     │  yfinance      │
│  Tailwind CSS v3         │     │  ├── /api/valuation          │     │  (prices,      │
│  Supabase Auth           │     │  └── /api/watchlist          │     │   metrics)     │
└──────────────────────────┘     └──────────┬───────────────────┘     └────────────────┘
                                            │
                                 ┌──────────▼───────────────────┐
                                 │  PostgreSQL (Supabase)       │
                                 │  ├── companies               │
                                 │  ├── filings_cache           │
                                 │  ├── financial_data_cache    │
                                 │  └── watchlist_items         │
                                 └──────────────────────────────┘
```

## Quick Start

### Prerequisites

- Node.js 18+ and npm
- Python 3.11+
- A [Supabase](https://supabase.com) project (free tier works)
- A Google OAuth app configured in Supabase for authentication

### 1. Clone and install

```bash
git clone https://github.com/j-maltese/investron.git
cd investron

# Backend
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Frontend
cd ../frontend
npm install
```

### 2. Configure environment variables

Copy the example and fill in your values:

```bash
cp .env.example backend/.env
```

Edit `backend/.env`:

| Variable | Description |
|----------|-------------|
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_PUBLISHABLE_KEY` | Supabase anon/public key |
| `SUPABASE_SECRET_KEY` | Supabase service role key |
| `DATABASE_URL` | PostgreSQL connection string (use Supabase session pooler) |
| `SEC_EDGAR_USER_AGENT` | **Required by SEC** — your name and email (e.g., `Investron john@example.com`) |
| `DEBUG` | `true` or `false` |
| `CORS_ORIGINS` | JSON array of allowed origins (default: `["http://localhost:5173"]`) |

Create `frontend/.env`:

```
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=your-publishable-key
VITE_API_BASE_URL=http://localhost:8000
```

### 3. Set up the database

Run the SQL migrations in your Supabase SQL editor to create the required tables: `companies`, `filings_cache`, `financial_data_cache`, and `watchlist_items`.

### 4. Run both servers

```bash
# Terminal 1 — Backend
cd backend
uvicorn app.main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend
npm run dev
```

The app will be available at `http://localhost:5173`.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19, TypeScript, Vite 5, Tailwind CSS v3, React Router v6, TanStack Query v5, Recharts, Supabase JS |
| Backend | FastAPI, SQLAlchemy (async), asyncpg, httpx, yfinance, Pydantic |
| Database | PostgreSQL via Supabase |
| Auth | Supabase Auth with Google OAuth |
| Data | SEC EDGAR XBRL API, yfinance |

## Project Structure

```
investron/
├── backend/                  # FastAPI application
│   ├── app/
│   │   ├── api/              # Route handlers
│   │   ├── auth/             # Authentication middleware
│   │   ├── models/           # DB setup + Pydantic schemas
│   │   ├── services/         # Business logic + external APIs
│   │   ├── utils/            # Caching, rate limiting
│   │   ├── config.py         # Environment settings
│   │   └── main.py           # App initialization
│   └── requirements.txt
├── frontend/                 # React application
│   ├── src/
│   │   ├── components/       # UI components (layout, research, search, charts)
│   │   ├── pages/            # Route pages (Dashboard, Research, Login, Docs)
│   │   ├── hooks/            # Custom React hooks
│   │   ├── lib/              # API client, Supabase, types
│   │   └── styles/           # CSS + Tailwind config
│   └── package.json
├── .env.example              # Environment template
└── README.md
```

## Features

- **Company Research** — Search by ticker, view company overview with sector/industry/exchange info
- **Financial Statements** — Income statement, balance sheet, cash flow from SEC EDGAR XBRL data (annual + quarterly)
- **SEC Filings** — Browse 10-K, 10-Q, 8-K filings with direct links to SEC documents
- **Graham Score** — Evaluate stocks against Benjamin Graham's 7 criteria for defensive investors
- **DCF Valuation** — Discounted cash flow calculator with customizable growth/discount rates
- **Scenario Modeling** — Bull/base/bear analysis with probability-weighted intrinsic value
- **Growth Lens** — Metrics for pre-profit companies: cash runway, burn rate, dilution, R&D intensity
- **Watchlist & Alerts** — Track stocks with target prices, get alerts when price is within 10% of target
- **Dark/Light Theme** — Toggle between themes with persistent preference

See [frontend/README.md](frontend/README.md) and [backend/README.md](backend/README.md) for detailed documentation.
