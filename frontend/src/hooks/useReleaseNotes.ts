import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

export function useReleaseNotes() {
  return useQuery({
    queryKey: ['release-notes'],
    queryFn: () => api.getReleaseNotes(),
    staleTime: 5 * 60_000,
  })
}
