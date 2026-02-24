import { CheckCircle2, XCircle } from 'lucide-react'
import { useGrahamScore } from '@/hooks/useCompany'
import type { GrahamCriterion } from '@/lib/types'

interface GrahamScoreProps {
  ticker: string
}

export function GrahamScore({ ticker }: GrahamScoreProps) {
  const { data, isLoading } = useGrahamScore(ticker)

  if (isLoading) return <div className="text-[var(--muted-foreground)]">Loading Graham analysis...</div>
  if (!data) return null

  const scoreColor = data.score >= 5 ? 'text-gain' : data.score >= 3 ? 'text-yellow-500' : 'text-loss'

  return (
    <div className="card space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-lg">Graham Score</h3>
        <div className={`text-2xl font-bold ${scoreColor}`}>
          {data.score}/{data.max_score}
        </div>
      </div>

      {data.graham_number != null && (
        <div className="flex gap-4 text-sm">
          <div>
            <span className="text-[var(--muted-foreground)]">Graham Number: </span>
            <span className="font-mono font-semibold">${data.graham_number.toFixed(2)}</span>
          </div>
          {data.margin_of_safety != null && (
            <div>
              <span className="text-[var(--muted-foreground)]">Margin of Safety: </span>
              <span className={`font-mono font-semibold ${data.margin_of_safety > 0 ? 'metric-positive' : 'metric-negative'}`}>
                {data.margin_of_safety > 0 ? '+' : ''}{data.margin_of_safety.toFixed(1)}%
              </span>
            </div>
          )}
        </div>
      )}

      <div className="space-y-2">
        {data.criteria.map((criterion: GrahamCriterion) => (
          <div key={criterion.name} className="flex items-start gap-2 text-sm">
            {criterion.passed ? (
              <CheckCircle2 className="w-4 h-4 text-gain shrink-0 mt-0.5" />
            ) : (
              <XCircle className="w-4 h-4 text-loss shrink-0 mt-0.5" />
            )}
            <div className="flex-1">
              <div className="font-medium">{criterion.name}</div>
              <div className="text-[var(--muted-foreground)]">
                {criterion.description}
                {criterion.value && <span className="ml-1">({criterion.value})</span>}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
