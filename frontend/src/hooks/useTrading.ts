/**
 * TanStack Query hooks for the paper trading feature.
 *
 * Strategies and portfolio data poll more frequently than the screener
 * because the trading engine may update state every 15-60 seconds.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
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

export function useActivityLog(strategyId?: string) {
  return useQuery({
    queryKey: ['trading-activity', strategyId],
    queryFn: () => api.getTradingActivity({ strategy_id: strategyId, limit: 50 }),
    staleTime: 10_000,
    refetchInterval: 15_000,
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
