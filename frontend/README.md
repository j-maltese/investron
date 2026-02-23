# Investron — Frontend

React single-page application providing the research and analysis UI for Investron.

## Tech Stack

- **React 19** with TypeScript
- **Vite 5** — Dev server and bundler
- **React Router v6** — Client-side routing
- **TanStack Query v5** — Server state management and data fetching
- **Tailwind CSS v3** — Utility-first styling with CSS custom properties for theming
- **Recharts** — Financial charts and visualizations
- **Supabase JS** — Authentication (Google OAuth) and session management
- **Lucide React** — Icon library

## Project Structure

```
src/
├── components/
│   ├── layout/
│   │   ├── Header.tsx              # Top nav bar: logo, search, Dashboard/Docs links, theme toggle, sign out
│   │   └── PageLayout.tsx          # Wraps Header + main content area (max-w-7xl)
│   ├── research/
│   │   ├── OverviewTab.tsx         # Company info, key metrics grid, price chart
│   │   ├── FinancialsTab.tsx       # Financial statements table with annual/quarterly toggle
│   │   ├── FilingsTab.tsx          # SEC filings list with links to EDGAR documents
│   │   ├── ValuationTab.tsx        # DCF calculator + ScenarioModeler
│   │   ├── GrahamScore.tsx         # Graham's 7 criteria checklist with score
│   │   ├── GrowthLens.tsx          # Pre-profit metrics: runway, burn rate, dilution, R&D
│   │   ├── ScenarioModeler.tsx     # Bull/base/bear interactive scenario builder
│   │   └── MetricsGrid.tsx         # Reusable key-value metrics display
│   ├── search/
│   │   └── CompanySearch.tsx       # Autocomplete search with keyboard navigation
│   ├── dashboard/
│   │   └── ...                     # Dashboard-specific components
│   └── charts/
│       └── ...                     # Chart components (price history, financials)
├── pages/
│   ├── Dashboard.tsx               # Watchlist table + price alerts
│   ├── Research.tsx                # Tabbed research view (Overview, Financials, Filings, Valuation)
│   ├── Docs.tsx                    # In-app documentation (User Guide + Developer Guide)
│   └── Login.tsx                   # Google SSO login page
├── hooks/
│   ├── useAuth.ts                  # Auth state, user session, sign out
│   ├── useCompany.ts              # useCompany(), useMetrics(), useGrahamScore() — TanStack Query hooks
│   ├── useTheme.ts                # Dark/light theme toggle with localStorage persistence
│   └── useWatchlist.ts            # Watchlist CRUD queries and mutations
├── lib/
│   ├── api.ts                     # Typed API client (wraps fetch for all backend endpoints)
│   ├── supabase.ts                # Supabase client initialization
│   └── types.ts                   # Shared TypeScript interfaces
├── styles/
│   └── index.css                  # CSS variables, base styles, .card and .btn-primary classes
└── main.tsx                       # App entry point (React root, QueryClient, BrowserRouter)
```

## Component Architecture

```
App.tsx (auth gate + routes)
├── Login                           # Unauthenticated state
├── Dashboard                       # /
│   └── PageLayout
│       ├── Header
│       └── Watchlist + Alerts
├── Research                        # /research/:ticker
│   └── PageLayout
│       ├── Header
│       └── Tabs: Overview | Financials | Filings | Valuation
│           ├── OverviewTab → MetricsGrid, GrahamScore, GrowthLens
│           ├── FinancialsTab → statements table, charts
│           ├── FilingsTab → filings list
│           └── ValuationTab → DCF calculator, ScenarioModeler
└── Docs                            # /docs
    └── PageLayout
        ├── Header
        └── Toggle: User Guide | Developer Guide
```

## State Management

| What | How |
|------|-----|
| Server data (company, metrics, filings) | TanStack Query hooks with automatic caching and refetching |
| Auth session | Supabase `onAuthStateChange` listener via `useAuth` hook |
| Theme preference | `useTheme` hook with `localStorage` persistence |
| Form state (DCF inputs, scenario params) | Local `useState` within components |

## Styling

The app uses **Tailwind CSS v3** with **CSS custom properties** for theming. Key patterns:

- **Theme variables** defined in `styles/index.css`:
  - `--background`, `--foreground`, `--card`, `--border`, `--accent`, `--muted`, `--muted-foreground`
  - Switch between `:root` (light) and `[data-theme="dark"]` (dark) values
- **Utility classes**: `.card` (rounded border with bg), `.btn-primary` (accent-colored button), `.input` (form inputs)
- **Color semantics**: `.text-gain` (green), `.text-loss` (red), `.metric-positive` / `.metric-negative`
- **Layout**: `max-w-7xl` centered container, responsive grid columns via `grid-cols-2 md:grid-cols-4`

## Running Locally

```bash
npm install
npm run dev          # Dev server on http://localhost:5173
npm run build        # Production build
npm run preview      # Preview production build
```

### Environment Variables

Create a `.env` file in this directory:

```
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=your-publishable-key
VITE_API_BASE_URL=http://localhost:8000
```

## Key Hooks

| Hook | Purpose |
|------|---------|
| `useAuth()` | Returns `{ user, loading, signOut }` — wraps Supabase auth state |
| `useCompany(ticker)` | Fetches company details from `/api/companies/{ticker}` |
| `useMetrics(ticker)` | Fetches key metrics (P/E, price, market cap) from `/api/financials/{ticker}/metrics` |
| `useGrahamScore(ticker)` | Fetches Graham evaluation from `/api/financials/{ticker}/graham-score` |
| `useWatchlist()` | Returns watchlist items from `/api/watchlist` |
| `useAlerts()` | Returns price alerts from `/api/watchlist/alerts` |
| `useAddToWatchlist()` | Mutation for `POST /api/watchlist` |
| `useRemoveFromWatchlist()` | Mutation for `DELETE /api/watchlist/{ticker}` |
| `useTheme()` | Returns `{ theme, toggleTheme }` — persists to localStorage |
