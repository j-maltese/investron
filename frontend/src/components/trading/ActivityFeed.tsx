/**
 * ActivityFeed — enhanced activity log with filter pills, date range picker,
 * text search, expandable detail rows, and infinite-scroll pagination.
 *
 * Two rendering modes:
 * - **compact** (Overview tab): simple read-only list, events passed in as props,
 *   no filters/expand/pagination. Just a quick glance at recent events.
 * - **full** (Activity tab): self-managing component that calls useActivityLog
 *   internally, renders filter pills, date range controls, text search bar,
 *   expandable JSONB details, and infinite scroll for pagination.
 *
 * Date range filtering is deferred — the user sets From/To dates, then clicks
 * a Search button to apply. This avoids constant re-fetches while the user
 * is still selecting dates. Auto-refetch is also disabled when any filter
 * (dates or search text) is active.
 *
 * Filter pills group event types into categories (Decisions, Executions, Blocked,
 * Errors) and filter client-side on the currently loaded events. Date range
 * and text search go through the API so the database handles them.
 */

import { useState, useMemo, useCallback, useRef, useEffect } from 'react'
import {
  ArrowDownCircle, ArrowUpCircle, AlertTriangle, Play, Square,
  RotateCcw, CircleDot, ShieldAlert, Settings, Crosshair, RefreshCw,
  XCircle, Timer, Clock, Ban, ArrowRightCircle, ChevronDown, ChevronRight,
  Loader2, Search,
} from 'lucide-react'
import DatePicker from 'react-datepicker'
import 'react-datepicker/dist/react-datepicker.css'
import { useActivityLog } from '@/hooks/useTrading'
import type { TradingActivityEvent } from '@/lib/types'
import { formatDateTime } from '@/lib/dateUtils'

// ---------------------------------------------------------------------------
// Event type -> icon + color mapping
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
// Date range helpers for quick presets + API conversion
// ---------------------------------------------------------------------------

/** Convert a Date to an ISO-8601 string for the API, or undefined if null. */
function toAPIDatetime(d: Date | null): string | undefined {
  return d ? d.toISOString() : undefined
}

function getPresetDate(preset: 'today' | 'week' | 'month'): Date {
  const now = new Date()
  if (preset === 'today') {
    return new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0)
  }
  if (preset === 'week') {
    // Start of this week (Monday). Sunday=0, Monday=1, ..., Saturday=6.
    const day = now.getDay()
    const diff = day === 0 ? 6 : day - 1
    const monday = new Date(now)
    monday.setDate(now.getDate() - diff)
    monday.setHours(0, 0, 0, 0)
    return monday
  }
  // "month" preset: first day of current month at midnight
  return new Date(now.getFullYear(), now.getMonth(), 1, 0, 0, 0)
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

// Page size for infinite scroll
const PAGE_SIZE = 100

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
  // -- Full-mode state --
  const [filter, setFilter] = useState<FilterCategory>('all')
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())

  // Date picker state is local — only committed to the query on Search click
  const [dateFromInput, setDateFromInput] = useState<Date | null>(null)
  const [dateToInput, setDateToInput] = useState<Date | null>(null)

  // Committed filter state — what's actually sent to the API
  const [committedDateFrom, setCommittedDateFrom] = useState<Date | null>(null)
  const [committedDateTo, setCommittedDateTo] = useState<Date | null>(null)
  const [committedSearch, setCommittedSearch] = useState<string>('')

  // Text search input (local, committed on Enter or Search click)
  const [searchInput, setSearchInput] = useState('')

  // Infinite scroll: how many items to load
  const [loadedCount, setLoadedCount] = useState(PAGE_SIZE)

  // Sentinel ref for IntersectionObserver-based infinite scroll
  const sentinelRef = useRef<HTMLDivElement>(null)

  // Date validation: end before start
  const dateError = dateFromInput && dateToInput && dateToInput < dateFromInput
    ? 'End date must be after start date'
    : null

  // Fetch data internally in full mode; disabled in compact mode to avoid
  // duplicate fetches (parent already supplies events via props).
  const { data, isLoading, isFetching } = useActivityLog(
    compact
      ? { enabled: false }
      : {
          strategyId,
          dateFrom: toAPIDatetime(committedDateFrom),
          dateTo: toAPIDatetime(committedDateTo),
          search: committedSearch || undefined,
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

  // -- Infinite scroll via IntersectionObserver --
  const hasMore = !compact && totalCount > allEvents.length
  useEffect(() => {
    if (compact || !hasMore) return
    const sentinel = sentinelRef.current
    if (!sentinel) return

    const observer = new IntersectionObserver(
      (entries) => {
        // When the sentinel scrolls into view and we're not already fetching, load more
        if (entries[0]?.isIntersecting && !isFetching) {
          setLoadedCount((prev) => prev + PAGE_SIZE)
        }
      },
      { rootMargin: '200px' }
    )

    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [compact, hasMore, isFetching])

  // -- Callbacks --

  const toggleExpanded = useCallback((id: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  /** Commit date range and search text to the query — triggered by Search button or Enter */
  const applyFilters = useCallback(() => {
    if (dateError) return
    setCommittedDateFrom(dateFromInput)
    setCommittedDateTo(dateToInput)
    setCommittedSearch(searchInput)
    setLoadedCount(PAGE_SIZE) // Reset pagination on new search
  }, [dateFromInput, dateToInput, searchInput, dateError])

  const clearFilters = useCallback(() => {
    setDateFromInput(null)
    setDateToInput(null)
    setSearchInput('')
    setCommittedDateFrom(null)
    setCommittedDateTo(null)
    setCommittedSearch('')
    setLoadedCount(PAGE_SIZE)
  }, [])

  const applyPreset = useCallback((preset: 'today' | 'week' | 'month') => {
    const from = getPresetDate(preset)
    setDateFromInput(from)
    setDateToInput(null)
    // Auto-commit presets since both values are known
    setCommittedDateFrom(from)
    setCommittedDateTo(null)
    setCommittedSearch(searchInput)
    setLoadedCount(PAGE_SIZE)
  }, [searchInput])

  const hasAnyFilter = !!(committedDateFrom || committedDateTo || committedSearch)

  // -- Loading state (full mode only — initial load, not background refetch) --
  if (!compact && isLoading && !data) {
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
          <SearchAndDateBar
            dateFrom={dateFromInput}
            dateTo={dateToInput}
            setDateFrom={setDateFromInput}
            setDateTo={setDateToInput}
            searchInput={searchInput}
            setSearchInput={setSearchInput}
            applyFilters={applyFilters}
            clearFilters={clearFilters}
            applyPreset={applyPreset}
            hasAnyFilter={hasAnyFilter}
            dateError={dateError}
          />
        )}
        <div className="card text-center py-8 text-[var(--muted-foreground)]">
          No activity
          {filter !== 'all'
            ? ` matching "${FILTER_PILLS.find((p) => p.key === filter)?.label}"`
            : ''}
          {committedDateFrom ? ` from ${committedDateFrom.toLocaleString()}` : ''}
          {committedDateTo ? ` to ${committedDateTo.toLocaleString()}` : ''}
          {committedSearch ? ` containing "${committedSearch}"` : ''}
          .
        </div>
      </div>
    )
  }

  return (
    <div className={compact ? '' : 'space-y-3'}>
      {/* Filter pills — only in full mode */}
      {!compact && <FilterBar filter={filter} setFilter={setFilter} />}

      {/* Search bar + date range controls — only in full mode */}
      {!compact && (
        <SearchAndDateBar
          dateFrom={dateFromInput}
          dateTo={dateToInput}
          setDateFrom={setDateFromInput}
          setDateTo={setDateToInput}
          searchInput={searchInput}
          setSearchInput={setSearchInput}
          applyFilters={applyFilters}
          clearFilters={clearFilters}
          applyPreset={applyPreset}
          hasAnyFilter={hasAnyFilter}
          dateError={dateError}
        />
      )}

      {/* Event list */}
      <div className="card space-y-0.5 max-h-[calc(100vh-320px)] overflow-y-auto">
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
                  <div className="text-sm truncate" title={event.message}>{event.message}</div>
                  <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                    <span className="text-xs text-[var(--muted-foreground)]">
                      {formatDateTime(event.created_at)}
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

        {/* Infinite scroll sentinel — triggers loading more when scrolled into view */}
        {hasMore && (
          <div ref={sentinelRef} className="flex items-center justify-center py-3">
            {isFetching ? (
              <Loader2 className="w-4 h-4 animate-spin text-[var(--muted-foreground)]" />
            ) : (
              <span className="text-xs text-[var(--muted-foreground)]">
                {allEvents.length} of {totalCount} events
              </span>
            )}
          </div>
        )}

        {/* Show count when all events are loaded */}
        {!hasMore && !compact && allEvents.length > 0 && (
          <div className="text-center text-xs text-[var(--muted-foreground)] py-2">
            {totalCount} event{totalCount !== 1 ? 's' : ''}
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
// SearchAndDateBar — text search + From/To date pickers + Search button
// Dates are local state until the user clicks Search (deferred query).
// ---------------------------------------------------------------------------

function SearchAndDateBar({
  dateFrom,
  dateTo,
  setDateFrom,
  setDateTo,
  searchInput,
  setSearchInput,
  applyFilters,
  clearFilters,
  applyPreset,
  hasAnyFilter,
  dateError,
}: {
  dateFrom: Date | null
  dateTo: Date | null
  setDateFrom: (v: Date | null) => void
  setDateTo: (v: Date | null) => void
  searchInput: string
  setSearchInput: (v: string) => void
  applyFilters: () => void
  clearFilters: () => void
  applyPreset: (p: 'today' | 'week' | 'month') => void
  hasAnyFilter: boolean
  dateError: string | null
}) {
  return (
    <div className="space-y-2">
      {/* Search bar + action button row */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[var(--muted-foreground)]" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && applyFilters()}
            placeholder="Search logs..."
            className="w-full bg-[var(--muted)] border border-[var(--border)] rounded px-2 py-1.5 pl-8 text-[var(--foreground)] text-xs placeholder:text-[var(--muted-foreground)]"
          />
        </div>
        <button
          onClick={applyFilters}
          disabled={!!dateError}
          className="px-3 py-1.5 text-xs rounded bg-[var(--accent)] text-white hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Search
        </button>
        {hasAnyFilter && (
          <button
            onClick={clearFilters}
            className="px-2 py-1.5 text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
          >
            Clear All
          </button>
        )}
      </div>

      {/* Date range row */}
      <div className="flex items-center gap-3 flex-wrap text-xs">
        <label className="flex items-center gap-1.5 text-[var(--muted-foreground)]">
          From
          <DatePicker
            selected={dateFrom}
            onChange={(date: Date | null) => setDateFrom(date)}
            showTimeSelect
            timeIntervals={15}
            dateFormat="MMM d, yyyy h:mm aa"
            placeholderText="Select start..."
            isClearable
            className="bg-[var(--muted)] border border-[var(--border)] rounded px-2 py-1 text-[var(--foreground)] text-xs w-[170px]"
            calendarClassName="investron-datepicker"
            popperPlacement="bottom-start"
          />
        </label>
        <label className="flex items-center gap-1.5 text-[var(--muted-foreground)]">
          To
          <DatePicker
            selected={dateTo}
            onChange={(date: Date | null) => setDateTo(date)}
            showTimeSelect
            timeIntervals={15}
            dateFormat="MMM d, yyyy h:mm aa"
            placeholderText="Select end..."
            isClearable
            className="bg-[var(--muted)] border border-[var(--border)] rounded px-2 py-1 text-[var(--foreground)] text-xs w-[170px]"
            calendarClassName="investron-datepicker"
            popperPlacement="bottom-start"
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
      </div>

      {/* Date validation warning */}
      {dateError && (
        <div className="text-xs text-red-400 flex items-center gap-1.5">
          <AlertTriangle className="w-3.5 h-3.5" />
          {dateError}
        </div>
      )}
    </div>
  )
}
