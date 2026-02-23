import { useState } from 'react'
import { ExternalLink, FileText } from 'lucide-react'
import { useFilings } from '@/hooks/useCompany'

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

  if (isLoading) {
    return <div className="text-[var(--muted-foreground)] py-8 text-center">Loading filings...</div>
  }

  return (
    <div className="space-y-4">
      {/* Filter buttons */}
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

      <div className="text-sm text-[var(--muted-foreground)]">
        {data?.total_count ?? 0} filings found
      </div>

      {/* Filings list */}
      <div className="space-y-2">
        {data?.filings?.map((filing) => (
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
