import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { WatchlistView, TickerNotesByTicker } from '@/lib/types'

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

/** Fetch all ticker notes grouped by ticker */
export function useTickerNotes() {
  return useQuery({
    queryKey: ['ticker-notes'],
    queryFn: () => api.getTickerNotes(),
    staleTime: 60_000,
    select: (data) => data.notes as TickerNotesByTicker,
  })
}

/** Create or update the current user's note on a ticker (upsert) */
export function useCreateTickerNote() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ ticker, notes }: { ticker: string; notes: string }) =>
      api.createTickerNote(ticker, notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ticker-notes'] })
    },
  })
}

/** Edit any ticker note by ID */
export function useUpdateTickerNote() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ noteId, notes }: { noteId: number; notes: string }) =>
      api.updateTickerNote(noteId, notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ticker-notes'] })
    },
  })
}

/** Delete a ticker note by ID */
export function useDeleteTickerNote() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (noteId: number) => api.deleteTickerNote(noteId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ticker-notes'] })
    },
  })
}
