# Local Development Setup

Run the full Investron stack locally with a single command — no Supabase account needed.

## Prerequisites

- **Docker Desktop** (running)
- **Python 3.11+** (available via `py` launcher on Windows)
- **Node.js 18+** with npm

## Quick Start

```bash
bash scripts/dev.sh
```

This starts everything:
- **PostgreSQL** on `localhost:5433` (Docker container, auto-initialized with schema + seed data)
- **Backend** on `http://localhost:8000` (FastAPI with hot reload)
- **Frontend** on `http://localhost:5173` (Vite dev server, proxies API calls to backend)

Press `Ctrl+C` to stop all services.

## How It Works

### Database

A local PostgreSQL 16 container replaces the production Supabase database. On first run, Docker automatically executes:

1. `backend/schema.sql` — creates all tables
2. `backend/seed_dev.sql` — inserts 58 sample stocks with realistic metrics across 11 sectors

Data persists in a Docker volume (`investron_pgdata`) across restarts. To reset:

```bash
docker compose -f docker-compose.dev.yml down -v   # destroy volume
docker compose -f docker-compose.dev.yml up -d      # recreate fresh
```

### Authentication

When `DEBUG=true` (the local dev default), the backend skips JWT verification and returns a hardcoded dev user for all authenticated endpoints. The frontend detects that Supabase is not configured and bypasses the login screen automatically.

No tokens, no Google OAuth, no Supabase project needed.

### Scanner

The background stock scanner is disabled locally (`SCANNER_ENABLED=false`) to avoid unnecessary yfinance API calls. The seed data provides enough rows to work with the Value Screener UI. To enable it:

```
# backend/.env
SCANNER_ENABLED=true
```

## Manual Setup (Without the Script)

If you prefer to run services individually:

### 1. Start PostgreSQL

```bash
docker compose -f docker-compose.dev.yml up -d
```

### 2. Configure Environment

Copy the templates (only needed once):

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

Then edit `backend/.env` to set your `SEC_EDGAR_USER_AGENT` (real name + email required by the SEC).

### 3. Start Backend

```bash
cd backend
py -3.11 -m venv .venv
source .venv/Scripts/activate    # Windows/Git Bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 4. Start Frontend

```bash
cd frontend
npm install
npm run dev
```

## Environment Variables

### Backend (`backend/.env`)

| Variable | Local Dev Default | Purpose |
|----------|------------------|---------|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5433/investron` | Local Docker Postgres |
| `DEBUG` | `true` | Enables auth bypass + SQL echo logging |
| `SCANNER_ENABLED` | `false` | Disables background yfinance scanner |
| `SEC_EDGAR_USER_AGENT` | *(must set)* | Required by SEC — use your real name and email |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed frontend origin |
| `SUPABASE_*` | *(not needed)* | Only needed when `DEBUG=false` |

### Frontend (`frontend/.env`)

| Variable | Local Dev Default | Purpose |
|----------|------------------|---------|
| `VITE_API_BASE_URL` | *(empty)* | Empty = use Vite proxy (recommended) |
| `VITE_SUPABASE_URL` | *(empty)* | Empty = dev mode (skip auth) |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | *(empty)* | Empty = dev mode (skip auth) |

## Connecting to the Local Database

```bash
# Via Docker
docker compose -f docker-compose.dev.yml exec postgres psql -U postgres -d investron

# Via any Postgres client
Host: localhost
Port: 5433
User: postgres
Password: postgres
Database: investron
```

## Deploying to Production

Work on the `dev` branch, then create a PR to `main` when ready:

```bash
git push origin dev
gh pr create --base main --head dev --title "Brief description of changes" --body "Details here"
```

After review, merge from the CLI or GitHub:

```bash
gh pr merge --squash
```

Merging to `main` automatically triggers:
- **Vercel** deploys the frontend
- **Railway** deploys the backend
- **GitHub Action** generates release notes and creates a version tag

## Troubleshooting

**CORS errors (OPTIONS 400)**
Check that `CORS_ORIGINS` in `backend/.env` matches your frontend URL. Supports both formats: `http://localhost:5173` or `["http://localhost:5173"]`.

**"Database not configured" error**
Ensure the Docker Postgres container is running: `docker compose -f docker-compose.dev.yml ps`

**Port 5433 in use**
Change the port in `docker-compose.dev.yml` (line 10) and update `DATABASE_URL` in `backend/.env` to match.

**Schema changes not applied**
Docker only runs init scripts on a fresh volume. After changing `schema.sql`, destroy and recreate: `docker compose -f docker-compose.dev.yml down -v && docker compose -f docker-compose.dev.yml up -d`
