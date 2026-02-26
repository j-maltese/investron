/**
 * TanStack Query hooks for the Value Screener feature.
 *
 * These hooks follow the same patterns as useWatchlist.ts:
 *   - queryKey arrays for cache identity
 *   - staleTime to avoid unnecessary refetches
 *   - refetchInterval for auto-polling on the Dashboard
 *
 * The screener data changes at scan intervals (~1 hour), so we use longer
 * stale times than the watchlist. The scanner status polls more frequently
 * so the "Scanning..." progress indicator stays responsive.
 */

import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

/** Parameters for filtering/sorting screener results */
interface ScreenerParams {
  sort_by?: string
  sort_order?: 'asc' | 'desc'
  sector?: string
  index?: string
  min_score?: number
  limit?: number
  offset?: number
}

/**
 * Fetch ranked screener results with optional sorting/filtering.
 * Params are included in the queryKey so changing sort or filters triggers a refetch.
 */
export function useScreenerResults(params?: ScreenerParams) {
  return useQuery({
    queryKey: ['screener-results', params],
    queryFn: () => api.getScreenerResults(params),
    staleTime: 5 * 60_000,        // 5 min — data only changes on scan completion
    refetchInterval: 10 * 60_000,  // Auto-refresh every 10 min while tab is open
  })
}

/**
 * Fetch the scanner's current status (running, progress, last completion).
 * Polls frequently so the "Scanning... (150/503)" indicator stays up to date.
 */
export function useScannerStatus() {
  return useQuery({
    queryKey: ['scanner-status'],
    queryFn: () => api.getScannerStatus(),
    staleTime: 30_000,          // 30 seconds
    refetchInterval: 60_000,    // Poll every minute while viewing the Dashboard
  })
}

/**
 * Fetch distinct sectors for the filter dropdown.
 * Sectors rarely change, so we cache aggressively.
 */
export function useScreenerSectors() {
  return useQuery({
    queryKey: ['screener-sectors'],
    queryFn: () => api.getScreenerSectors(),
    staleTime: 10 * 60_000,    // 10 min — sectors don't change often
  })
}

/**
 * Fetch distinct index names for the index filter dropdown.
 * Indices are static (derived from CSVs), so we cache aggressively.
 */
export function useScreenerIndices() {
  return useQuery({
    queryKey: ['screener-indices'],
    queryFn: () => api.getScreenerIndices(),
    staleTime: 10 * 60_000,    // 10 min — indices don't change often
  })
}
