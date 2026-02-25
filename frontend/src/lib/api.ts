import { supabase } from './supabase'
import type {
  CompanySearchResult, Company, FinancialStatementsResponse, KeyMetrics,
  GrahamScoreResponse, GrowthMetrics, FilingsResponse, DCFInput, DCFResult,
  ScenarioModelInput, ScenarioResult, WatchlistItem, Alert, ReleaseNotesResponse,
} from './types'

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

async function getAuthHeaders(): Promise<Record<string, string>> {
  const { data: { session } } = await supabase.auth.getSession()
  if (session?.access_token) {
    return { Authorization: `Bearer ${session.access_token}` }
  }
  return {}
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = await getAuthHeaders()
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...headers,
      ...options?.headers,
    },
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(error.detail || `API error: ${res.status}`)
  }

  return res.json()
}

// Company endpoints
export const api = {
  searchCompanies: (q: string) =>
    apiFetch<{ results: CompanySearchResult[] }>(`/api/companies/search?q=${encodeURIComponent(q)}`),

  getCompany: (ticker: string) =>
    apiFetch<Company>(`/api/companies/${ticker}`),

  getStatements: (ticker: string, type: string, period: string) =>
    apiFetch<FinancialStatementsResponse>(
      `/api/financials/${ticker}/statements?statement_type=${type}&period_type=${period}`
    ),

  getMetrics: (ticker: string) =>
    apiFetch<KeyMetrics>(`/api/financials/${ticker}/metrics`),

  getGrahamScore: (ticker: string) =>
    apiFetch<GrahamScoreResponse>(`/api/financials/${ticker}/graham-score`),

  getGrowthMetrics: (ticker: string) =>
    apiFetch<GrowthMetrics>(`/api/financials/${ticker}/growth-metrics`),

  getFilings: (ticker: string, types?: string) =>
    apiFetch<FilingsResponse>(`/api/filings/${ticker}${types ? `?types=${types}` : ''}`),

  runDCF: (ticker: string, inputs: DCFInput) =>
    apiFetch<DCFResult>(`/api/valuation/${ticker}/dcf`, {
      method: 'POST',
      body: JSON.stringify(inputs),
    }),

  runScenario: (ticker: string, inputs: ScenarioModelInput) =>
    apiFetch<ScenarioResult>(`/api/valuation/${ticker}/scenario`, {
      method: 'POST',
      body: JSON.stringify(inputs),
    }),

  // Watchlist
  getWatchlist: () =>
    apiFetch<{ items: WatchlistItem[] }>('/api/watchlist'),

  addToWatchlist: (item: { ticker: string; notes?: string; target_price?: number }) =>
    apiFetch<WatchlistItem>('/api/watchlist', {
      method: 'POST',
      body: JSON.stringify(item),
    }),

  removeFromWatchlist: (ticker: string) =>
    apiFetch<{ message: string }>(`/api/watchlist/${ticker}`, { method: 'DELETE' }),

  updateWatchlistItem: (ticker: string, update: { notes?: string; target_price?: number }) =>
    apiFetch<WatchlistItem>(`/api/watchlist/${ticker}`, {
      method: 'PATCH',
      body: JSON.stringify(update),
    }),

  getAlerts: () =>
    apiFetch<{ alerts: Alert[] }>('/api/watchlist/alerts'),

  // Release Notes
  getReleaseNotes: () =>
    apiFetch<ReleaseNotesResponse>('/api/release-notes'),
}
