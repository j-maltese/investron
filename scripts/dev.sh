#!/usr/bin/env bash
# =============================================================
# Investron — Local Development Startup
# =============================================================
# Usage:  bash scripts/dev.sh
#
# Starts the full stack: Docker Postgres, FastAPI backend, Vite frontend.
# Press Ctrl+C to shut everything down.
#
# Prerequisites: Docker Desktop running, Python 3.11+, Node 18+
# Platform: Windows (Git Bash / MSYS2). Uses `py` launcher for Python.
# =============================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# --- Track background PIDs for cleanup ---
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
    echo ""
    info "Shutting down..."
    [ -n "$BACKEND_PID" ]  && kill "$BACKEND_PID"  2>/dev/null || true
    [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null || true
    info "Stopping Docker containers..."
    docker compose -f docker-compose.dev.yml down 2>/dev/null || true
    info "Done. Postgres data is preserved in the Docker volume."
}
trap cleanup EXIT

# --- Step 1: Check Docker ---
if ! docker info > /dev/null 2>&1; then
    error "Docker is not running. Please start Docker Desktop and try again."
    exit 1
fi
info "Docker is running."

# --- Step 2: Start Postgres ---
info "Starting PostgreSQL container..."
docker compose -f docker-compose.dev.yml up -d

# --- Step 3: Wait for Postgres health ---
info "Waiting for PostgreSQL to be ready..."
RETRIES=30
until docker compose -f docker-compose.dev.yml exec -T postgres pg_isready -U postgres -d investron > /dev/null 2>&1; do
    RETRIES=$((RETRIES - 1))
    if [ "$RETRIES" -le 0 ]; then
        error "PostgreSQL did not become ready in time."
        exit 1
    fi
    sleep 1
done
info "PostgreSQL is ready on port 5433."

# --- Step 4: Copy .env files if missing ---
if [ ! -f backend/.env ]; then
    warn "backend/.env not found — copying from backend/.env.example"
    cp backend/.env.example backend/.env
    info "Created backend/.env — review and update SEC_EDGAR_USER_AGENT with your name/email."
fi

if [ ! -f frontend/.env ]; then
    warn "frontend/.env not found — copying from frontend/.env.example"
    cp frontend/.env.example frontend/.env
    info "Created frontend/.env"
fi

# --- Step 5: Python venv + backend deps ---
VENV_DIR="backend/.venv"
if [ ! -d "$VENV_DIR" ]; then
    info "Creating Python virtual environment..."
    py -3.11 -m venv "$VENV_DIR"
fi

# Activate venv (Windows / Git Bash path)
source "$VENV_DIR/Scripts/activate"

info "Installing backend dependencies..."
pip install -q -r backend/requirements.txt

# --- Step 6: Start backend ---
info "Starting backend (uvicorn --reload on port 8000)..."
cd backend
uvicorn app.main:app --reload --port 8000 &
BACKEND_PID=$!
cd "$REPO_ROOT"

sleep 2

# --- Step 7: Frontend ---
cd frontend
if [ ! -d "node_modules" ]; then
    info "Installing frontend dependencies..."
    npm install
fi

info "Starting frontend dev server (Vite on port 5173)..."
npm run dev &
FRONTEND_PID=$!
cd "$REPO_ROOT"

echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  Investron dev environment is running!${NC}"
echo -e "${CYAN}  Frontend:  http://localhost:5173${NC}"
echo -e "${CYAN}  Backend:   http://localhost:8000${NC}"
echo -e "${CYAN}  API docs:  http://localhost:8000/docs${NC}"
echo -e "${CYAN}  Postgres:  localhost:5433 (investron)${NC}"
echo -e "${CYAN}  Press Ctrl+C to stop everything.${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# Wait for any background process to exit (or Ctrl+C)
wait
