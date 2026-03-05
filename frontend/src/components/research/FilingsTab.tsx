import { useState } from 'react'
import { ExternalLink, FileText, RefreshCw, Brain, Loader2, CheckCircle2, AlertCircle } from 'lucide-react'
import { useFilings } from '@/hooks/useCompany'
import { useFilingIndex } from '@/hooks/useFilingIndex'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { Filing } from '@/lib/types'

interface FilingsTabProps {
  ticker: string
}

const FILING_FILTERS = [
  { label: 'All', value: '' },
  { label: '10-K', value: '10-K' },
  { label: '10-Q', value: '10-Q' },
  { label: '8-K', value: '8-K' },
]

export function FilingsTab({ ticker }: FilingsTabProps) {
  const [filter, setFilter] = useState('')
  const { data, isLoading } = useFilings(ticker, filter || undefined)
  const queryClient = useQueryClient()

  // Filing refresh state — re-fetches the filing list from EDGAR
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [refreshResult, setRefreshResult] = useState<string | null>(null)

  // RAG indexing state — reuse the same hook that AIAnalysisTab uses
  const {
    status: indexStatus,
    indexStatus: indexStatusData,
    isIndexing,
    isReady: isIndexed,
    triggerIndexing,
  } = useFilingIndex(ticker)

  const handleRefresh = async () => {
    setIsRefreshing(true)
    setRefreshResult(null)
    try {
      const result = await api.refreshFilings(ticker)
      // Invalidate the filings cache so the list re-renders with new data
      queryClient.invalidateQueries({ queryKey: ['filings', ticker] })
      setRefreshResult(
        result.new_count > 0
          ? `Found ${result.new_count} new filing${result.new_count === 1 ? '' : 's'}`
          : 'No new filings found'
      )
      // Clear the message after 5 seconds
      setTimeout(() => setRefreshResult(null), 5000)
    } catch {
      setRefreshResult('Failed to refresh filings')
      setTimeout(() => setRefreshResult(null), 5000)
    } finally {
      setIsRefreshing(false)
    }
  }

  // Build a human-readable index status label
  const indexLabel = (() => {
    if (isIndexing) return indexStatusData?.progress_message || 'Indexing...'
    if (isIndexed) {
      const bd = indexStatusData?.filing_type_breakdown
      if (bd) {
        const parts = Object.entries(bd).map(([type, count]) => `${count} ${type}`)
        return `Indexed: ${parts.join(', ')} (${indexStatusData?.chunks_total ?? 0} chunks)`
      }
      return `Indexed (${indexStatusData?.chunks_total ?? 0} chunks)`
    }
    if (indexStatus === 'error') return 'Indexing failed'
    return 'Not indexed for AI'
  })()

  if (isLoading) {
    return <div className="text-[var(--muted-foreground)] py-8 text-center">Loading filings...</div>
  }

  return (
    <div className="space-y-4">
      {/* Filter buttons + action buttons */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex gap-2">
          {FILING_FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => setFilter(f.value)}
              className={filter === f.value ? 'btn-primary text-sm' : 'btn-secondary text-sm'}
            >
              {f.label}
            </button>
          ))}
        </div>

        {/* Action buttons: Refresh from EDGAR + Index for AI */}
        <div className="flex items-center gap-2">
          <button
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="btn-secondary text-sm flex items-center gap-1.5"
            title="Re-fetch filing list from SEC EDGAR to pick up new submissions"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
            {isRefreshing ? 'Refreshing...' : 'Refresh Filings'}
          </button>

          <button
            onClick={triggerIndexing}
            disabled={isIndexing}
            className={`text-sm flex items-center gap-1.5 ${
              isIndexed ? 'btn-secondary' : 'btn-primary'
            }`}
            title={isIndexed ? 'Re-index filings for AI analysis (RAG)' : 'Index filings so AI can search them'}
          >
            {isIndexing ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Brain className="w-3.5 h-3.5" />
            )}
            {isIndexing ? 'Indexing...' : isIndexed ? 'Re-index for AI' : 'Index for AI'}
          </button>
        </div>
      </div>

      {/* Status bar: refresh result + index status */}
      <div className="flex items-center justify-between gap-4 text-sm">
        <div className="text-[var(--muted-foreground)]">
          {refreshResult ? (
            <span className="text-[var(--accent)]">{refreshResult}</span>
          ) : (
            `${data?.total_count ?? 0} filings found`
          )}
        </div>

        {/* RAG index status indicator */}
        <div className="flex items-center gap-1.5 text-xs text-[var(--muted-foreground)]">
          {isIndexing && <Loader2 className="w-3 h-3 animate-spin text-blue-400" />}
          {isIndexed && <CheckCircle2 className="w-3 h-3 text-green-400" />}
          {indexStatus === 'error' && <AlertCircle className="w-3 h-3 text-red-400" />}
          {indexStatus === 'not_indexed' && <Brain className="w-3 h-3 opacity-40" />}
          <span>{indexLabel}</span>
        </div>
      </div>

      {/* Filings list */}
      <div className="space-y-2">
        {data?.filings?.map((filing: Filing) => (
          <div
            key={filing.accession_number}
            className="card flex items-start justify-between gap-4 hover:bg-[var(--muted)] transition-colors"
          >
            <div className="flex items-start gap-3">
              <FileText className="w-4 h-4 mt-0.5 text-[var(--muted-foreground)] shrink-0" />
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-sm px-2 py-0.5 rounded bg-[var(--muted)] border border-[var(--border)]">
                    {filing.filing_type}
                  </span>
                  <span className="text-sm text-[var(--muted-foreground)]">
                    {filing.filing_date}
                  </span>
                </div>
                {filing.description && (
                  <div className="text-sm text-[var(--muted-foreground)] mt-1">{filing.description}</div>
                )}
              </div>
            </div>
            {filing.filing_url && (
              <a
                href={filing.filing_url}
                target="_blank"
                rel="noopener noreferrer"
                className="shrink-0 p-1 hover:text-[var(--accent)] transition-colors"
                title="View on SEC.gov"
              >
                <ExternalLink className="w-4 h-4" />
              </a>
            )}
          </div>
        ))}
      </div>

      {data?.filings?.length === 0 && (
        <div className="text-[var(--muted-foreground)] py-8 text-center">No filings found</div>
      )}
    </div>
  )
}
