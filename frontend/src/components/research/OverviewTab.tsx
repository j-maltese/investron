import { useMetrics } from '@/hooks/useCompany'
import { MetricsGrid } from './MetricsGrid'
import { GrahamScore } from './GrahamScore'
import { GrowthLens } from './GrowthLens'

interface OverviewTabProps {
  ticker: string
}

export function OverviewTab({ ticker }: OverviewTabProps) {
  const { data: metrics, isLoading } = useMetrics(ticker)

  if (isLoading) {
    return <div className="text-[var(--muted-foreground)] py-8 text-center">Loading metrics...</div>
  }

  return (
    <div className="space-y-6">
      {/* Key Metrics Grid */}
      {metrics && <MetricsGrid metrics={metrics} />}

      {/* Analysis lenses side by side on large screens */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <GrahamScore ticker={ticker} />
        <GrowthLens ticker={ticker} />
      </div>
    </div>
  )
}
