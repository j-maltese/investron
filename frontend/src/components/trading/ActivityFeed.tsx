import {
  ArrowDownCircle, ArrowUpCircle, AlertTriangle, Play, Pause, Square,
  RotateCcw, CircleDot, ShieldAlert, Settings,
} from 'lucide-react'
import type { TradingActivityEvent } from '@/lib/types'

const EVENT_ICONS: Record<string, { icon: typeof Play; color: string }> = {
  order_placed: { icon: CircleDot, color: 'text-sky-400' },
  order_filled: { icon: ArrowDownCircle, color: 'text-emerald-400' },
  assignment: { icon: ArrowUpCircle, color: 'text-amber-400' },
  strategy_start: { icon: Play, color: 'text-emerald-400' },
  strategy_stop: { icon: Square, color: 'text-[var(--muted-foreground)]' },
  strategy_reset: { icon: RotateCcw, color: 'text-sky-400' },
  circuit_breaker: { icon: ShieldAlert, color: 'text-red-400' },
  config_update: { icon: Settings, color: 'text-sky-400' },
  error: { icon: AlertTriangle, color: 'text-red-400' },
  signal: { icon: CircleDot, color: 'text-[var(--accent)]' },
}

interface ActivityFeedProps {
  events: TradingActivityEvent[]
  totalCount: number
}

export function ActivityFeed({ events, totalCount }: ActivityFeedProps) {
  if (events.length === 0) {
    return (
      <div className="card text-center py-8 text-[var(--muted-foreground)]">
        No activity yet.
      </div>
    )
  }

  return (
    <div className="card space-y-1 max-h-[600px] overflow-y-auto">
      {events.map((event) => {
        const iconConfig = EVENT_ICONS[event.event_type] || EVENT_ICONS.signal
        const Icon = iconConfig.icon

        return (
          <div
            key={event.id}
            className="flex items-start gap-3 px-2 py-2 rounded-md hover:bg-[var(--muted)] transition-colors"
          >
            <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${iconConfig.color}`} />
            <div className="flex-1 min-w-0">
              <div className="text-sm">{event.message}</div>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-xs text-[var(--muted-foreground)]">
                  {new Date(event.created_at).toLocaleString()}
                </span>
                {event.ticker && (
                  <span className="text-xs font-mono text-[var(--accent)]">{event.ticker}</span>
                )}
              </div>
            </div>
          </div>
        )
      })}
      {totalCount > events.length && (
        <div className="text-center text-xs text-[var(--muted-foreground)] py-2">
          Showing {events.length} of {totalCount} events
        </div>
      )}
    </div>
  )
}
