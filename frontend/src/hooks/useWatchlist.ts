import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'

export function useWatchlist() {
  return useQuery({
    queryKey: ['watchlist'],
    queryFn: () => api.getWatchlist(),
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
