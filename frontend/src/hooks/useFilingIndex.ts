/**
 * Hook for managing SEC filing index status and controls.
 *
 * Polls every 4s while indexing is in progress, then stops once
 * the status becomes 'ready' or 'error'.
 */

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import { api } from '@/lib/api'
import type { FilingIndexStatus } from '@/lib/types'

export function useFilingIndex(ticker: string) {
  const queryClient = useQueryClient()
  const queryKey = ['filing-index-status', ticker.toUpperCase()]

  const { data: status, isLoading } = useQuery<FilingIndexStatus>({
    queryKey,
    queryFn: () => api.getFilingIndexStatus(ticker),
    refetchInterval: (query) => {
      // Poll every 4s while indexing, stop otherwise
      const s = query.state.data?.status
      return s === 'indexing' || s === 'pending' ? 4000 : false
    },
    staleTime: 10_000,
  })

  const triggerIndexing = useCallback(async () => {
    await api.triggerFilingIndex(ticker)
    // Optimistically set to indexing — the 4s poll interval picks up real status.
    // No invalidateQueries here: an immediate refetch would race the background
    // task and could overwrite this optimistic update with stale data.
    queryClient.setQueryData(queryKey, (prev: FilingIndexStatus | undefined) => ({
      ...prev,
      ticker: ticker.toUpperCase(),
      status: 'indexing' as const,
      filings_indexed: 0,
      chunks_total: 0,
    }))
  }, [ticker, queryClient, queryKey])

  const deleteIndex = useCallback(async () => {
    await api.deleteFilingIndex(ticker)
    queryClient.setQueryData(queryKey, {
      ticker: ticker.toUpperCase(),
      status: 'not_indexed' as const,
      filings_indexed: 0,
      chunks_total: 0,
    })
  }, [ticker, queryClient, queryKey])

  return {
    status: status?.status ?? 'not_indexed',
    indexStatus: status,
    isLoading,
    isIndexing: status?.status === 'indexing' || status?.status === 'pending',
    isReady: status?.status === 'ready',
    triggerIndexing,
    deleteIndex,
  }
}
