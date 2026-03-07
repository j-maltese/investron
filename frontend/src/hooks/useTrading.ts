/**
 * TanStack Query hooks for the paper trading feature.
 *
 * Strategies and portfolio data poll more frequently than the screener
 * because the trading engine may update state every 15-60 seconds.
 */

import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import { api } from '@/lib/api'

export function useStrategies() {
  return useQuery({
    queryKey: ['trading-strategies'],
    queryFn: () => api.getStrategies(),
    staleTime: 10_000,
    refetchInterval: 30_000,
  })
}

export function useStrategy(strategyId: string) {
  return useQuery({
    queryKey: ['trading-strategy', strategyId],
    queryFn: () => api.getStrategy(strategyId),
    staleTime: 10_000,
    refetchInterval: 30_000,
    enabled: !!strategyId,
  })
}

export function usePositions(strategyId?: string, status?: string) {
  return useQuery({
    queryKey: ['trading-positions', strategyId, status],
    queryFn: () => api.getTradingPositions({ strategy_id: strategyId, status }),
    staleTime: 15_000,
    refetchInterval: 30_000,
  })
}

export function useOrders(strategyId?: string) {
  return useQuery({
    queryKey: ['trading-orders', strategyId],
    queryFn: () => api.getTradingOrders({ strategy_id: strategyId, limit: 50 }),
    staleTime: 15_000,
    refetchInterval: 30_000,
  })
}

/**
 * Activity log hook with support for event type filtering, date range, and pagination.
 *
 * The ActivityFeed component manages its own filter/pagination state and passes
 * the params here. The query key includes all filter params so TanStack Query
 * refetches when filters change.
 */
export function useActivityLog(params?: {
  strategyId?: string
  eventType?: string
  /** Comma-separated event types for server-side category filtering */
  eventTypes?: string
  dateFrom?: string
  dateTo?: string
  search?: string
  limit?: number
  offset?: number
  /** Set false to disable fetching — used when ActivityFeed is in compact mode
   *  and events are supplied externally by the parent component. */
  enabled?: boolean
}) {
  // Disable auto-refetch when the user has active filters — constant re-fetches
  // cause the page to flash/re-render and fight with the user's selections.
  const hasActiveFilters = !!(params?.dateFrom || params?.dateTo || params?.search || params?.eventTypes)

  return useQuery({
    queryKey: [
      'trading-activity',
      params?.strategyId, params?.eventType, params?.eventTypes,
      params?.dateFrom, params?.dateTo,
      params?.search,
      params?.limit, params?.offset,
    ],
    queryFn: () => api.getTradingActivity({
      strategy_id: params?.strategyId,
      event_type: params?.eventType,
      event_types: params?.eventTypes,
      date_from: params?.dateFrom,
      date_to: params?.dateTo,
      search: params?.search,
      limit: params?.limit || 100,
      offset: params?.offset || 0,
    }),
    staleTime: 10_000,
    // Keep old rows visible while loading more — prevents scroll jump on infinite scroll
    placeholderData: keepPreviousData,
    // Only auto-poll when no filters are active — avoids fighting with user input
    refetchInterval: params?.enabled === false ? false : (hasActiveFilters ? false : 30_000),
    enabled: params?.enabled !== false,
  })
}

export function usePortfolio() {
  return useQuery({
    queryKey: ['trading-portfolio'],
    queryFn: () => api.getTradingPortfolio(),
    staleTime: 10_000,
    refetchInterval: 30_000,
  })
}

// Mutations — invalidate strategy queries on success

export function useStartStrategy() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (strategyId: string) => api.startStrategy(strategyId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trading-strategies'] })
      queryClient.invalidateQueries({ queryKey: ['trading-portfolio'] })
      queryClient.invalidateQueries({ queryKey: ['trading-activity'] })
    },
  })
}

export function useStopStrategy() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (strategyId: string) => api.stopStrategy(strategyId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trading-strategies'] })
      queryClient.invalidateQueries({ queryKey: ['trading-portfolio'] })
      queryClient.invalidateQueries({ queryKey: ['trading-activity'] })
    },
  })
}

export function usePauseStrategy() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (strategyId: string) => api.pauseStrategy(strategyId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trading-strategies'] })
      queryClient.invalidateQueries({ queryKey: ['trading-portfolio'] })
      queryClient.invalidateQueries({ queryKey: ['trading-activity'] })
    },
  })
}

export function useResetStrategy() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (strategyId: string) => api.resetStrategy(strategyId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trading-strategies'] })
      queryClient.invalidateQueries({ queryKey: ['trading-portfolio'] })
      queryClient.invalidateQueries({ queryKey: ['trading-positions'] })
      queryClient.invalidateQueries({ queryKey: ['trading-orders'] })
      queryClient.invalidateQueries({ queryKey: ['trading-activity'] })
    },
  })
}

export function useUpdateStrategyConfig() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ strategyId, config }: { strategyId: string; config: Record<string, unknown> }) =>
      api.updateStrategyConfig(strategyId, config),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trading-strategies'] })
    },
  })
}
