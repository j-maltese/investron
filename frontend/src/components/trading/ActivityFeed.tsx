/**
 * ActivityFeed — enhanced activity log with filter pills, date range picker,
 * expandable detail rows, and load-more pagination.
 *
 * Two rendering modes:
 * - **compact** (Overview tab): simple read-only list, events passed in as props,
 *   no filters/expand/pagination. Just a quick glance at recent events.
 * - **full** (Activity tab): self-managing component that calls useActivityLog
 *   internally, renders filter pills, date range controls, expandable JSONB
 *   details, and a "Load more" button for pagination.
 *
 * Filter pills group event types into categories (Decisions, Executions, Blocked,
 * Errors) and filter client-side on the currently loaded events. Date range
 * filtering goes through the API so the database handles the time window.
 */

import { useState, useMemo, useCallback } from 'react'
import {
  ArrowDownCircle, ArrowUpCircle, AlertTriangle, Play, Square,
  RotateCcw, CircleDot, ShieldAlert, Settings, Crosshair, RefreshCw,
  XCircle, Timer, Clock, Ban, ArrowRightCircle, ChevronDown, ChevronRight,
  Loader2,
} from 'lucide-react'
import { useActivityLog } from '@/hooks/useTrading'
import type { TradingActivityEvent } from '@/lib/types'

// ---------------------------------------------------------------------------
// Event type → icon + color mapping
// Covers Simple Stock events (order_placed, signal, etc.) and Wheel events
// (put_sold, assignment, hard_stop, blocked_*, etc.).
// ---------------------------------------------------------------------------

const EVENT_ICONS: Record<string, { icon: typeof Play; color: string }> = {
  // -- Execution events (things that happened) --
  order_placed:     { icon: CircleDot,        color: 'text-sky-400' },
  order_filled:     { icon: ArrowDownCircle,  color: 'text-emerald-400' },
  assignment:       { icon: ArrowUpCircle,    color: 'text-amber-400' },
  called_away:      { icon: ArrowRightCircle, color: 'text-emerald-400' },
  option_expired:   { icon: Clock,            color: 'text-[var(--muted-foreground)]' },
  phase_transition: { icon: ArrowRightCircle, color: 'text-sky-400' },
  roll_attempted:   { icon: RefreshCw,        color: 'text-amber-400' },

  // -- Decision events (why something was done) --
  option_selected:         { icon: Crosshair,       color: 'text-sky-400' },
  put_sold:                { icon: ArrowDownCircle,  color: 'text-emerald-400' },
  call_sold:               { icon: ArrowUpCircle,    color: 'text-emerald-400' },
  roll_executed:           { icon: RefreshCw,        color: 'text-sky-400' },
  hard_stop:               { icon: XCircle,          color: 'text-red-400' },
  capital_efficiency_exit: { icon: Timer,            color: 'text-amber-400' },

  // -- Strategy lifecycle --
  strategy_start: { icon: Play,      color: 'text-emerald-400' },
  strategy_stop:  { icon: Square,    color: 'text-[var(--muted-foreground)]' },
  strategy_reset: { icon: RotateCcw, color: 'text-sky-400' },
  config_update:  { icon: Settings,  color: 'text-sky-400' },

  // -- Errors & safety --
  error:           { icon: AlertTriangle, color: 'text-red-400' },
  circuit_breaker: { icon: ShieldAlert,   color: 'text-red-400' },

  // -- Signals (Simple Stock AI) --
  signal: { icon: CircleDot, color: 'text-[var(--accent)]' },
}

// All blocked_* events share the same muted icon — matched by prefix below
const BLOCKED_ICON = { icon: Ban, color: 'text-[var(--muted-foreground)]' }

/** Look up icon config, falling back to BLOCKED_ICON for blocked_* prefixes. */
function getIconConfig(eventType: string) {
  if (eventType.startsWith('blocked_')) return BLOCKED_ICON
  return EVENT_ICONS[eventType] || EVENT_ICONS.signal
}

// ---------------------------------------------------------------------------
// Filter categories — client-side grouping of event types into pill buttons.
// We filter client-side because categories span multiple unrelated event types
// that don't share a common prefix (except "blocked_*").
// ---------------------------------------------------------------------------

type FilterCategory = 'all' | 'decisions' | 'executions' | 'blocked' | 'errors'

const FILTER_PILLS: { key: FilterCategory; label: string }[] = [
  { key: 'all',        label: 'All' },
  { key: 'decisions',  label: 'Decisions' },
  { key: 'executions', label: 'Executions' },
  { key: 'blocked',    label: 'Blocked' },
  { key: 'errors',     label: 'Errors' },
]

// Decision events: explain WHY something was done (scoring, reasoning, analysis)
const DECISION_TYPES = new Set([
  'option_selected', 'put_sold', 'call_sold', 'roll_executed',
  'hard_stop', 'capital_efficiency_exit',
])

// Execution events: factual triggers — something happened, here's what and when
const EXECUTION_TYPES = new Set([
  'order_placed', 'order_filled', 'assignment', 'called_away',
  'option_expired', 'phase_transition', 'roll_attempted',
  'strategy_start', 'strategy_stop', 'strategy_reset', 'config_update', 'signal',
])

// Error events: failures and safety triggers
const ERROR_TYPES = new Set(['error', 'circuit_breaker'])

function matchesFilter(eventType: string, filter: FilterCategory): boolean {
  if (filter === 'all') return true
  if (filter === 'decisions') return DECISION_TYPES.has(eventType)
  if (filter === 'executions') return EXECUTION_TYPES.has(eventType)
  if (filter === 'blocked') return eventType.startsWith('blocked_')
  if (filter === 'errors') return ERROR_TYPES.has(eventType)
  return true
}

// ---------------------------------------------------------------------------
// Date range helpers for quick presets
// ---------------------------------------------------------------------------

function toISODate(d: Date): string {
  return d.toISOString().slice(0, 10)
}

function getPresetDate(preset: 'today' | 'week' | 'month'): string {
  const now = new Date()
  if (preset === 'today') return toISODate(now)
  if (preset === 'week') {
    // Start of this week (Monday). Sunday=0, Monday=1, ..., Saturday=6.
    const day = now.getDay()
    const diff = day === 0 ? 6 : day - 1
    const monday = new Date(now)
    monday.setDate(now.getDate() - diff)
    return toISODate(monday)
  }
  // "month" preset: first day of current month
  return toISODate(new Date(now.getFullYear(), now.getMonth(), 1))
}

// ---------------------------------------------------------------------------
// DetailPanel — renders the JSONB `details` object as structured key-value pairs.
// The "reason" field (if present) is pulled to the top as an italic summary
// since it contains the decision reasoning that the user most cares about.
// ---------------------------------------------------------------------------

function DetailPanel({ details }: { details: Record<string, unknown> }) {
  const entries = Object.entries(details).filter(
    // Skip empty/null values — only show fields that have meaningful content
    ([, v]) =>
      v != null &&
      !(Array.isArray(v) && v.length === 0) &&
      !(typeof v === 'object' && !Array.isArray(v) && Object.keys(v as object).length === 0)
  )

  if (entries.length === 0) return null

  // Pull "reason" to the top — it's the most important field in decision logs
  const reasonEntry = entries.find(([k]) => k === 'reason')
  const otherEntries = entries.filter(([k]) => k !== 'reason')

  return (
    <div className="mt-1 mb-1 ml-11 p-3 rounded-md bg-[var(--muted)] space-y-1.5">
      {reasonEntry && (
        <div className="text-sm text-[var(--foreground)] italic mb-2">
          {String(reasonEntry[1])}
        </div>
      )}
      {otherEntries.length > 0 && (
        <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
          {otherEntries.map(([key, value]) => (
            <div key={key} className="contents">
              <span className="text-xs text-[var(--muted-foreground)] whitespace-nowrap">
                {key.replace(/_/g, ' ')}
              </span>
              <span className="text-xs font-mono text-[var(--foreground)]">
                {formatDetailValue(value)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Format a detail value for display — numbers get fixed decimals, arrays join. */
function formatDetailValue(value: unknown): string {
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : value.toFixed(2)
  }
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'object' && value !== null) return JSON.stringify(value)
  return String(value)
}

// ---------------------------------------------------------------------------
// ActivityFeed component
// ---------------------------------------------------------------------------

interface ActivityFeedProps {
  /** Compact mode for Overview tab — no filters, no expand, no pagination */
  compact?: boolean
  /** Pre-supplied events for compact mode */
  events?: TradingActivityEvent[]
  /** Total event count for compact mode's "Showing X of Y" text */
  totalCount?: number
  /** Optional strategy filter (both modes) */
  strategyId?: string
}

export function ActivityFeed({
  compact,
  events: externalEvents,
  totalCount: externalTotal,
  strategyId,
}: ActivityFeedProps) {
  // -- Full-mode state (filter pills, date range, pagination, expanded rows) --
  const [filter, setFilter] = useState<FilterCategory>('all')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [loadedCount, setLoadedCount] = useState(50)
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())

  // Fetch data internally in full mode; disabled in compact mode to avoid
  // duplicate fetches (parent already supplies events via props).
  const { data, isLoading } = useActivityLog(
    compact
      ? { enabled: false }
      : {
          strategyId,
          dateFrom: dateFrom || undefined,
          dateTo: dateTo || undefined,
          limit: loadedCount,
        }
  )

  // In compact mode use externally supplied events; in full mode use hook data
  const allEvents = compact ? (externalEvents || []) : (data?.events || [])
  const totalCount = compact ? (externalTotal || 0) : (data?.total_count || 0)

  // Client-side category filtering (only meaningful in full mode)
  const filteredEvents = useMemo(
    () => (compact ? allEvents : allEvents.filter((e) => matchesFilter(e.event_type, filter))),
    [allEvents, filter, compact]
  )

  // -- Callbacks --

  const toggleExpanded = useCallback((id: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const handleLoadMore = useCallback(() => {
    setLoadedCount((prev) => prev + 50)
  }, [])

  const clearDateRange = useCallback(() => {
    setDateFrom('')
    setDateTo('')
  }, [])

  const applyPreset = useCallback((preset: 'today' | 'week' | 'month') => {
    setDateFrom(getPresetDate(preset))
    setDateTo('') // No end date = up to now
  }, [])

  // -- Loading state (full mode only) --
  if (!compact && isLoading) {
    return (
      <div className="card flex items-center justify-center py-12">
        <Loader2 className="w-5 h-5 animate-spin text-[var(--muted-foreground)]" />
      </div>
    )
  }

  // -- Empty state --
  if (filteredEvents.length === 0 && !isLoading) {
    return (
      <div className={compact ? '' : 'space-y-3'}>
        {!compact && <FilterBar filter={filter} setFilter={setFilter} />}
        {!compact && (
          <DateRangeBar
            dateFrom={dateFrom}
            dateTo={dateTo}
            setDateFrom={setDateFrom}
            setDateTo={setDateTo}
            clearDateRange={clearDateRange}
            applyPreset={applyPreset}
          />
        )}
        <div className="card text-center py-8 text-[var(--muted-foreground)]">
          No activity
          {filter !== 'all'
            ? ` matching "${FILTER_PILLS.find((p) => p.key === filter)?.label}"`
            : ''}
          {dateFrom ? ` from ${dateFrom}` : ''}
          {dateTo ? ` to ${dateTo}` : ''}
          .
        </div>
      </div>
    )
  }

  return (
    <div className={compact ? '' : 'space-y-3'}>
      {/* Filter pills — only in full mode */}
      {!compact && <FilterBar filter={filter} setFilter={setFilter} />}

      {/* Date range controls — only in full mode */}
      {!compact && (
        <DateRangeBar
          dateFrom={dateFrom}
          dateTo={dateTo}
          setDateFrom={setDateFrom}
          setDateTo={setDateTo}
          clearDateRange={clearDateRange}
          applyPreset={applyPreset}
        />
      )}

      {/* Event list */}
      <div className="card space-y-0.5 max-h-[600px] overflow-y-auto">
        {filteredEvents.map((event) => {
          const iconConfig = getIconConfig(event.event_type)
          const Icon = iconConfig.icon
          const isExpanded = expandedIds.has(event.id)
          const hasDetails =
            !compact && event.details && Object.keys(event.details).length > 0

          return (
            <div key={event.id}>
              {/* Event row — clickable to expand if details exist */}
              <div
                onClick={() => hasDetails && toggleExpanded(event.id)}
                className={`flex items-start gap-3 px-2 py-2 rounded-md transition-colors ${
                  hasDetails
                    ? 'cursor-pointer hover:bg-[var(--muted)]'
                    : ''
                } ${isExpanded ? 'bg-[var(--muted)]' : ''}`}
              >
                {/* Expand chevron — only in full mode when details exist */}
                {!compact && hasDetails ? (
                  <span className="mt-0.5 shrink-0 text-[var(--muted-foreground)]">
                    {isExpanded ? (
                      <ChevronDown className="w-3.5 h-3.5" />
                    ) : (
                      <ChevronRight className="w-3.5 h-3.5" />
                    )}
                  </span>
                ) : !compact ? (
                  // Spacer to keep icon alignment when no chevron
                  <span className="w-3.5 shrink-0" />
                ) : null}

                {/* Event type icon */}
                <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${iconConfig.color}`} />

                {/* Message + metadata */}
                <div className="flex-1 min-w-0">
                  <div className="text-sm">{event.message}</div>
                  <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                    <span className="text-xs text-[var(--muted-foreground)]">
                      {new Date(event.created_at).toLocaleString()}
                    </span>
                    {event.ticker && (
                      <span className="text-xs font-mono text-[var(--accent)]">
                        {event.ticker}
                      </span>
                    )}
                    {/* Show event type label in full mode for extra context */}
                    {!compact && (
                      <span className="text-xs text-[var(--muted-foreground)] opacity-60">
                        {event.event_type.replace(/_/g, ' ')}
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Expanded detail panel — structured JSONB display */}
              {isExpanded && hasDetails && (
                <DetailPanel details={event.details} />
              )}
            </div>
          )
        })}

        {/* Load more button — full mode, when API has more events than loaded */}
        {!compact && totalCount > allEvents.length && (
          <div className="pt-3 pb-1 text-center">
            <button
              onClick={handleLoadMore}
              className="text-xs text-[var(--accent)] hover:underline"
            >
              Load more ({allEvents.length} of {totalCount} events)
            </button>
          </div>
        )}

        {/* Compact mode: simple count indicator when there are more events */}
        {compact && totalCount > filteredEvents.length && (
          <div className="text-center text-xs text-[var(--muted-foreground)] py-2">
            Showing {filteredEvents.length} of {totalCount} events
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// FilterBar — horizontal row of category pill buttons
// ---------------------------------------------------------------------------

function FilterBar({
  filter,
  setFilter,
}: {
  filter: FilterCategory
  setFilter: (f: FilterCategory) => void
}) {
  return (
    <div className="flex gap-1.5 flex-wrap">
      {FILTER_PILLS.map(({ key, label }) => (
        <button
          key={key}
          onClick={() => setFilter(key)}
          className={`px-3 py-1 text-xs rounded-full border transition-colors ${
            filter === key
              ? 'bg-[var(--accent)] text-white border-[var(--accent)]'
              : 'border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:border-[var(--foreground)]'
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// DateRangeBar — From/To date inputs + quick preset links
// ---------------------------------------------------------------------------

function DateRangeBar({
  dateFrom,
  dateTo,
  setDateFrom,
  setDateTo,
  clearDateRange,
  applyPreset,
}: {
  dateFrom: string
  dateTo: string
  setDateFrom: (v: string) => void
  setDateTo: (v: string) => void
  clearDateRange: () => void
  applyPreset: (p: 'today' | 'week' | 'month') => void
}) {
  return (
    <div className="flex items-center gap-3 flex-wrap text-xs">
      <label className="flex items-center gap-1.5 text-[var(--muted-foreground)]">
        From
        <input
          type="date"
          value={dateFrom}
          onChange={(e) => setDateFrom(e.target.value)}
          className="bg-[var(--muted)] border border-[var(--border)] rounded px-2 py-1 text-[var(--foreground)] text-xs"
        />
      </label>
      <label className="flex items-center gap-1.5 text-[var(--muted-foreground)]">
        To
        <input
          type="date"
          value={dateTo}
          onChange={(e) => setDateTo(e.target.value)}
          className="bg-[var(--muted)] border border-[var(--border)] rounded px-2 py-1 text-[var(--foreground)] text-xs"
        />
      </label>
      {/* Quick preset links */}
      <span className="text-[var(--border)]">|</span>
      <button
        onClick={() => applyPreset('today')}
        className="text-[var(--accent)] hover:underline"
      >
        Today
      </button>
      <button
        onClick={() => applyPreset('week')}
        className="text-[var(--accent)] hover:underline"
      >
        This Week
      </button>
      <button
        onClick={() => applyPreset('month')}
        className="text-[var(--accent)] hover:underline"
      >
        This Month
      </button>
      {/* Clear button — only shown when a date filter is active */}
      {(dateFrom || dateTo) && (
        <button
          onClick={clearDateRange}
          className="text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
        >
          Clear
        </button>
      )}
    </div>
  )
}
