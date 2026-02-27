import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { PageLayout } from '@/components/layout/PageLayout'
import { useCompany, useMetrics } from '@/hooks/useCompany'
import { OverviewTab } from '@/components/research/OverviewTab'
import { FinancialsTab } from '@/components/research/FinancialsTab'
import { FilingsTab } from '@/components/research/FilingsTab'
import { ValuationTab } from '@/components/research/ValuationTab'
import { AIAnalysisTab } from '@/components/research/AIAnalysisTab'

type Tab = 'overview' | 'financials' | 'filings' | 'valuation' | 'ai'

const TABS: { key: Tab; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'financials', label: 'Financials' },
  { key: 'filings', label: 'Filings' },
  { key: 'valuation', label: 'Valuation' },
  { key: 'ai', label: 'AI Analysis' },
]

function formatLargeNumber(value?: number | null): string {
  if (value == null) return 'N/A'
  if (Math.abs(value) >= 1e12) return `$${(value / 1e12).toFixed(2)}T`
  if (Math.abs(value) >= 1e9) return `$${(value / 1e9).toFixed(2)}B`
  if (Math.abs(value) >= 1e6) return `$${(value / 1e6).toFixed(1)}M`
  return `$${value.toFixed(2)}`
}

export function Research() {
  const { ticker } = useParams<{ ticker: string }>()
  const [activeTab, setActiveTab] = useState<Tab>('overview')
  const { data: company, isLoading: companyLoading } = useCompany(ticker || '')
  const { data: metrics } = useMetrics(ticker || '')

  if (!ticker) return null

  return (
    <PageLayout>
      <div className="space-y-4">
        {/* Company header */}
        <div className="flex items-start justify-between">
          <div>
            {companyLoading ? (
              <div className="h-8 w-48 bg-[var(--muted)] rounded animate-pulse" />
            ) : (
              <>
                <h1 className="text-2xl font-bold">
                  {ticker.toUpperCase()}
                  {company?.name && (
                    <span className="text-[var(--muted-foreground)] font-normal text-lg ml-2">
                      {company.name}
                    </span>
                  )}
                </h1>
                <div className="flex items-center gap-3 mt-1 text-sm text-[var(--muted-foreground)]">
                  {company?.sector && <span>{company.sector}</span>}
                  {company?.industry && <span>/ {company.industry}</span>}
                  {company?.exchange && <span>({company.exchange})</span>}
                </div>
              </>
            )}
          </div>

          {metrics?.price && (
            <div className="text-right">
              <div className="text-2xl font-bold font-mono">${metrics.price.toFixed(2)}</div>
              <div className="text-sm text-[var(--muted-foreground)]">
                Mkt Cap: {formatLargeNumber(metrics.market_cap)}
              </div>
            </div>
          )}
        </div>

        {/* Tab navigation */}
        <div className="flex gap-1 border-b border-[var(--border)]">
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === key
                  ? 'border-[var(--accent)] text-[var(--accent)]'
                  : 'border-transparent text-[var(--muted-foreground)] hover:text-[var(--foreground)]'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div>
          {activeTab === 'overview' && <OverviewTab ticker={ticker} />}
          {activeTab === 'financials' && <FinancialsTab ticker={ticker} />}
          {activeTab === 'filings' && <FilingsTab ticker={ticker} />}
          {activeTab === 'valuation' && <ValuationTab ticker={ticker} />}
          {activeTab === 'ai' && <AIAnalysisTab ticker={ticker} />}
        </div>
      </div>
    </PageLayout>
  )
}
