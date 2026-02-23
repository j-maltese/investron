import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

export function useCompanySearch(query: string) {
  return useQuery({
    queryKey: ['company-search', query],
    queryFn: () => api.searchCompanies(query),
    enabled: query.length >= 1,
    staleTime: 60_000,
  })
}

export function useCompany(ticker: string) {
  return useQuery({
    queryKey: ['company', ticker],
    queryFn: () => api.getCompany(ticker),
    enabled: !!ticker,
    staleTime: 5 * 60_000,
  })
}

export function useMetrics(ticker: string) {
  return useQuery({
    queryKey: ['metrics', ticker],
    queryFn: () => api.getMetrics(ticker),
    enabled: !!ticker,
    staleTime: 60_000,
  })
}

export function useStatements(ticker: string, type: string, period: string) {
  return useQuery({
    queryKey: ['statements', ticker, type, period],
    queryFn: () => api.getStatements(ticker, type, period),
    enabled: !!ticker,
    staleTime: 5 * 60_000,
  })
}

export function useGrahamScore(ticker: string) {
  return useQuery({
    queryKey: ['graham-score', ticker],
    queryFn: () => api.getGrahamScore(ticker),
    enabled: !!ticker,
    staleTime: 5 * 60_000,
  })
}

export function useGrowthMetrics(ticker: string) {
  return useQuery({
    queryKey: ['growth-metrics', ticker],
    queryFn: () => api.getGrowthMetrics(ticker),
    enabled: !!ticker,
    staleTime: 5 * 60_000,
  })
}

export function useFilings(ticker: string, types?: string) {
  return useQuery({
    queryKey: ['filings', ticker, types],
    queryFn: () => api.getFilings(ticker, types),
    enabled: !!ticker,
    staleTime: 5 * 60_000,
  })
}
