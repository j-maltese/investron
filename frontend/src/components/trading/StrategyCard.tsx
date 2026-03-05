import { Play, Square, Pause, RotateCcw, AlertTriangle } from 'lucide-react'
import type { TradingStrategy } from '@/lib/types'
import { formatTime } from '@/lib/dateUtils'
import { useStartStrategy, useStopStrategy, usePauseStrategy, useResetStrategy } from '@/hooks/useTrading'

const STATUS_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  running: { bg: 'bg-emerald-500/15', text: 'text-emerald-400', label: 'Running' },
  paused: { bg: 'bg-amber-500/15', text: 'text-amber-400', label: 'Paused' },
  stopped: { bg: 'bg-[var(--muted)]', text: 'text-[var(--muted-foreground)]', label: 'Stopped' },
  error: { bg: 'bg-red-500/15', text: 'text-red-400', label: 'Error' },
}

function formatMoney(value: number): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)
}

function formatPct(value: number): string {
  const sign = value >= 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

interface StrategyCardProps {
  strategy: TradingStrategy
}

export function StrategyCard({ strategy }: StrategyCardProps) {
  const startMutation = useStartStrategy()
  const stopMutation = useStopStrategy()
  const pauseMutation = usePauseStrategy()
  const resetMutation = useResetStrategy()

  const status = STATUS_STYLES[strategy.status] || STATUS_STYLES.stopped
  const totalValue = strategy.current_cash + strategy.current_portfolio_value
  const pnlPositive = strategy.total_pnl >= 0

  const isLoading =
    startMutation.isPending || stopMutation.isPending ||
    pauseMutation.isPending || resetMutation.isPending

  // Wheel can run in screener-driven mode (dynamic candidates) or legacy fixed list
  const wheelScreenerEnabled = strategy.strategy_type === 'wheel' && strategy.config.screener_enabled
  const fixedTickers = strategy.strategy_type === 'wheel' && !wheelScreenerEnabled
    ? (strategy.config.symbol_list as string[] || [])
    : []

  return (
    <div className="card space-y-4">
      {/* Header: name + status badge */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-lg">{strategy.display_name}</h3>
          <p className="text-sm text-[var(--muted-foreground)]">
            {strategy.strategy_type === 'simple_stock' ? 'AI-powered stock trading' : 'Options wheel strategy'}
          </p>
        </div>
        <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${status.bg} ${status.text}`}>
          {status.label}
        </span>
      </div>

      {/* Capital + P&L metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div>
          <div className="text-xs text-[var(--muted-foreground)]">Total Value</div>
          <div className="font-mono font-semibold">{formatMoney(totalValue)}</div>
        </div>
        <div>
          <div className="text-xs text-[var(--muted-foreground)]">Cash</div>
          <div className="font-mono">{formatMoney(strategy.current_cash)}</div>
        </div>
        <div>
          <div className="text-xs text-[var(--muted-foreground)]">P&L</div>
          <div className={`font-mono font-semibold ${pnlPositive ? 'text-gain' : 'text-loss'}`}>
            {formatMoney(strategy.total_pnl)}
          </div>
        </div>
        <div>
          <div className="text-xs text-[var(--muted-foreground)]">Return</div>
          <div className={`font-mono font-semibold ${pnlPositive ? 'text-gain' : 'text-loss'}`}>
            {formatPct(strategy.total_pnl_pct)}
          </div>
        </div>
      </div>

      {/* Strategy discovery mode label */}
      {fixedTickers.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {fixedTickers.map((t) => (
            <span
              key={t}
              className="px-2 py-0.5 rounded text-xs font-mono bg-[var(--muted)] text-[var(--muted-foreground)]"
            >
              {t}
            </span>
          ))}
        </div>
      ) : (
        <div className="text-xs text-[var(--muted-foreground)]">
          {strategy.strategy_type === 'simple_stock'
            ? 'Discovers stocks via screener scores + AI signals'
            : wheelScreenerEnabled
              ? `Selects candidates from value screener (top ${strategy.config.screener_top_n ?? 20}, score ≥ ${strategy.config.screener_min_score ?? 40}, ≤ $${strategy.config.screener_max_price ?? 200})`
              : 'No tickers configured'}
        </div>
      )}

      {/* Error display */}
      {strategy.last_error && (
        <div className="flex items-start gap-2 text-sm text-red-400 bg-red-500/10 rounded-md p-2.5">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span className="break-all">{strategy.last_error}</span>
        </div>
      )}

      {/* Action buttons */}
      <div className="flex items-center gap-2 pt-1 border-t border-[var(--border)]">
        {strategy.status !== 'running' && (
          <button
            onClick={() => startMutation.mutate(strategy.id)}
            disabled={isLoading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 transition-colors disabled:opacity-50"
          >
            <Play className="w-3.5 h-3.5" />
            Start
          </button>
        )}
        {strategy.status === 'running' && (
          <>
            <button
              onClick={() => pauseMutation.mutate(strategy.id)}
              disabled={isLoading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium bg-amber-500/15 text-amber-400 hover:bg-amber-500/25 transition-colors disabled:opacity-50"
            >
              <Pause className="w-3.5 h-3.5" />
              Pause
            </button>
            <button
              onClick={() => stopMutation.mutate(strategy.id)}
              disabled={isLoading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium bg-red-500/15 text-red-400 hover:bg-red-500/25 transition-colors disabled:opacity-50"
            >
              <Square className="w-3.5 h-3.5" />
              Stop
            </button>
          </>
        )}
        <button
          onClick={() => resetMutation.mutate(strategy.id)}
          disabled={isLoading || strategy.status === 'running'}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium bg-[var(--muted)] text-[var(--muted-foreground)] hover:bg-[var(--border)] transition-colors disabled:opacity-50"
          title="Reset to initial capital"
        >
          <RotateCcw className="w-3.5 h-3.5" />
          Reset
        </button>

        {/* Last run timestamp */}
        {strategy.last_run_at && (
          <span className="ml-auto text-xs text-[var(--muted-foreground)]">
            Last run: {formatTime(strategy.last_run_at)}
          </span>
        )}
      </div>
    </div>
  )
}
