import type { TradingStrategy } from '@/lib/types'

const STRATEGY_LABELS: Record<string, string> = {
  simple_stock: 'Simple Stock',
  wheel: 'The Wheel',
}

interface StrategyFilterPillsProps {
  strategies: TradingStrategy[]
  selected: string | null
  onChange: (strategyId: string | null) => void
}

export function StrategyFilterPills({ strategies, selected, onChange }: StrategyFilterPillsProps) {
  return (
    <div className="flex gap-1.5 flex-wrap">
      <button
        onClick={() => onChange(null)}
        className={`px-3 py-1 text-xs rounded-full border transition-colors ${
          selected === null
            ? 'bg-[var(--accent)] text-white border-[var(--accent)]'
            : 'border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:border-[var(--foreground)]'
        }`}
      >
        All
      </button>
      {strategies.map((s) => (
        <button
          key={s.id}
          onClick={() => onChange(selected === s.id ? null : s.id)}
          className={`px-3 py-1 text-xs rounded-full border transition-colors ${
            selected === s.id
              ? 'bg-[var(--accent)] text-white border-[var(--accent)]'
              : 'border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:border-[var(--foreground)]'
          }`}
        >
          {STRATEGY_LABELS[s.id] || s.display_name}
        </button>
      ))}
    </div>
  )
}
