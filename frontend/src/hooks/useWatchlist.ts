import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { WatchlistView, WatchlistNotesByTicker } from '@/lib/types'

export function useWatchlist(view?: WatchlistView) {
  return useQuery({
    queryKey: ['watchlist', view],
    queryFn: () => api.getWatchlist(view),
    staleTime: 60_000,
  })
}

export function useAlerts() {
  return useQuery({
    queryKey: ['alerts'],
    queryFn: () => api.getAlerts(),
    staleTime: 5 * 60_000,
  })
}

export function useAddToWatchlist() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (item: { ticker: string; notes?: string; target_price?: number }) =>
      api.addToWatchlist(item),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchlist'] })
    },
  })
}

export function useRemoveFromWatchlist() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (ticker: string) => api.removeFromWatchlist(ticker),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchlist'] })
    },
  })
}

export function useUpdateWatchlistItem() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ ticker, update }: { ticker: string; update: { notes?: string; target_price?: number } }) =>
      api.updateWatchlistItem(ticker, update),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchlist'] })
    },
  })
}

/** Fetch all watchlist notes grouped by ticker — lightweight endpoint (no prices) */
export function useWatchlistNotes() {
  return useQuery({
    queryKey: ['watchlist-notes'],
    queryFn: () => api.getWatchlistNotes(),
    staleTime: 60_000,
    select: (data) => data.notes as WatchlistNotesByTicker,
  })
}

/** Cross-user note editing by watchlist item ID */
export function useUpdateNoteById() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ itemId, notes }: { itemId: number; notes: string }) =>
      api.updateNoteById(itemId, notes),
    onSuccess: () => {
      // Invalidate both the notes cache and the main watchlist
      queryClient.invalidateQueries({ queryKey: ['watchlist-notes'] })
      queryClient.invalidateQueries({ queryKey: ['watchlist'] })
    },
  })
}
