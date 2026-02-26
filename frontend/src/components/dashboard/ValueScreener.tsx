/**
 * ValueScreener — Dashboard panel showing ranked stocks by composite value score.
 *
 * Architecture:
 *   - Fetches pre-computed scores from GET /api/screener/results (background scanner populates these)
 *   - Supports server-side sorting (click column headers), sector filtering, and index filtering
 *   - Covers ~2000 unique stocks across S&P 500, NASDAQ-100, Dow 30, S&P MidCap 400, Russell 2000
 *   - Shows scanner progress when a scan is running
 *   - Warning indicators use CSS-only hover tooltips (no tooltip library)
 *
 * Sub-components (defined below, not exported — only used within this panel):
 *   - SortableHeader: Column header that toggles sort direction
 *   - ScreenerRow: Single stock row with score coloring and warning dots
 *   - WarningIndicators: Colored dots with hover tooltip showing warning messages
 */

import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  TrendingDown, Clock, Plus, ExternalLink,
  ArrowUp, ArrowDown, ArrowUpDown, Loader2,
} from 'lucide-react'
import { useScreenerResults, useScannerStatus, useScreenerSectors, useScreenerIndices } from '@/hooks/useScreener'
import { useAddToWatchlist } from '@/hooks/useWatchlist'
import type { ScreenerScore, ScreenerWarning } from '@/lib/types'


// ============================================================================
// Helpers
// ============================================================================

/** Format a number as currency (e.g., $312.90) */
function formatCurrency(value?: number | null): string {
  if (value == null) return 'N/A'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)
}


/**
 * Map composite score to a color class.
 * Uses the app's color palette: green for strong value, amber for moderate, red for weak.
 * Thresholds are somewhat generous — most S&P 500 stocks score 20-50 in this market.
 */
function scoreColor(score: number): string {
  if (score >= 55) return 'text-gain'
  if (score >= 35) return 'text-amber-400'
  return 'text-loss'
}

/**
 * Map composite score to a subtle background highlight for top performers.
 * Only the highest-scoring stocks get a background tint to draw the eye.
 */
function scoreBgClass(score: number): string {
  if (score >= 60) return 'bg-gain/5'
  return ''
}


// ============================================================================
// SortableHeader — clickable column header with sort direction indicator
// ============================================================================

/**
 * HeaderTooltip — CSS-only tooltip shown on hover for column header descriptions.
 * Uses the same group-hover pattern as WarningIndicators (no JS state or library).
 * Renders BELOW the header (top-full) so it isn't clipped by the scroll container's overflow.
 */
function HeaderTooltip({ text }: { text: string }) {
  return (
    <div className="absolute top-full left-1/2 -translate-x-1/2 mt-2 hidden group-hover:block z-30 pointer-events-none whitespace-normal w-48">
      <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg px-3 py-2 text-xs text-[var(--foreground)] shadow-lg font-normal text-left">
        {text}
      </div>
    </div>
  )
}

interface SortableHeaderProps {
  label: string
  column: string
  currentSort: string
  currentOrder: 'asc' | 'desc'
  onSort: (column: string) => void
  align?: 'left' | 'right'
  tooltip?: string
}

function SortableHeader({ label, column, currentSort, currentOrder, onSort, align = 'right', tooltip }: SortableHeaderProps) {
  const isActive = currentSort === column
  const alignClass = align === 'left' ? 'text-left' : 'text-right'

  return (
    <th
      className={`py-2 px-2 font-medium text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)] transition-colors select-none relative group ${alignClass}`}
      onClick={() => onSort(column)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {isActive ? (
          currentOrder === 'desc'
            ? <ArrowDown className="w-3 h-3" />
            : <ArrowUp className="w-3 h-3" />
        ) : (
          <ArrowUpDown className="w-3 h-3 opacity-30" />
        )}
      </span>
      {tooltip && <HeaderTooltip text={tooltip} />}
    </th>
  )
}

/** Static (non-sortable) column header with optional tooltip */
function StaticHeader({ label, align = 'right', tooltip }: { label: string; align?: 'left' | 'right' | 'center'; tooltip?: string }) {
  const alignClass = align === 'left' ? 'text-left' : align === 'center' ? 'text-center' : 'text-right'
  return (
    <th className={`py-2 px-2 font-medium text-[var(--muted-foreground)] relative group ${alignClass}`}>
      {label}
      {tooltip && <HeaderTooltip text={tooltip} />}
    </th>
  )
}


// ============================================================================
// WarningIndicators — colored dots with hover tooltip
// ============================================================================

function WarningIndicators({ warnings }: { warnings: ScreenerWarning[] }) {
  if (!warnings.length) return null

  const highCount = warnings.filter(w => w.severity === 'high').length
  const medCount = warnings.filter(w => w.severity === 'medium').length
  const lowCount = warnings.filter(w => w.severity === 'low').length

  return (
    // The `group` class enables the CSS-only tooltip pattern: the tooltip div
    // is hidden by default and shown on group-hover. No JS state or tooltip library needed.
    <div className="relative group flex items-center gap-0.5 justify-end">
      {highCount > 0 && (
        <span className="w-2 h-2 rounded-full bg-loss" />
      )}
      {medCount > 0 && (
        <span className="w-2 h-2 rounded-full bg-amber-500" />
      )}
      {lowCount > 0 && (
        <span className="w-2 h-2 rounded-full bg-sky-400" />
      )}

      {/* Tooltip: appears above/right on hover, uses card styling for consistency */}
      <div className="absolute bottom-full right-0 mb-2 hidden group-hover:block z-20 w-64 pointer-events-none">
        <div className="bg-[var(--card)] border border-[var(--border)] rounded-lg p-3 text-xs space-y-1.5 shadow-lg">
          {warnings.map((w, i) => (
            <div key={i} className="flex items-start gap-1.5">
              <span className={`w-1.5 h-1.5 rounded-full mt-1 shrink-0 ${
                w.severity === 'high' ? 'bg-loss'
                : w.severity === 'medium' ? 'bg-amber-500'
                : 'bg-sky-400'
              }`} />
              <span className="text-[var(--foreground)]">{w.message}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}


// ============================================================================
// ScreenerRow — single stock row in the screener table
// ============================================================================

interface ScreenerRowProps {
  stock: ScreenerScore
  onAddToWatchlist: (ticker: string) => void
}

function ScreenerRow({ stock, onAddToWatchlist }: ScreenerRowProps) {
  // Margin of Safety coloring: green if undervalued (positive), red if overvalued
  const mosColor = (stock.margin_of_safety ?? 0) > 0 ? 'text-gain' : 'text-loss'

  return (
    <tr className={`border-b border-[var(--border)] last:border-0 hover:bg-[var(--muted)] transition-colors ${scoreBgClass(stock.composite_score)}`}>
      {/* Rank */}
      <td className="py-2.5 px-2 text-[var(--muted-foreground)] text-center font-mono text-xs">
        {stock.rank || '-'}
      </td>

      {/* Ticker + Company Name */}
      <td className="py-2.5 px-2">
        <Link to={`/research/${stock.ticker}`} className="font-semibold hover:text-[var(--accent)]">
          {stock.ticker}
        </Link>
        <div className="text-xs text-[var(--muted-foreground)] truncate max-w-[160px]">
          {stock.company_name}
        </div>
      </td>

      {/* Composite Score — bold, color-coded */}
      <td className="py-2.5 px-2 text-right">
        <span className={`font-mono font-bold ${scoreColor(stock.composite_score)}`}>
          {stock.composite_score.toFixed(1)}
        </span>
      </td>

      {/* Price */}
      <td className="py-2.5 px-2 text-right font-mono">
        {formatCurrency(stock.price)}
      </td>

      {/* Margin of Safety */}
      <td className={`py-2.5 px-2 text-right font-mono ${mosColor}`}>
        {stock.margin_of_safety != null
          ? `${stock.margin_of_safety > 0 ? '+' : ''}${stock.margin_of_safety.toFixed(1)}%`
          : 'N/A'}
      </td>

      {/* P/E */}
      <td className="py-2.5 px-2 text-right font-mono">
        {stock.pe_ratio != null ? stock.pe_ratio.toFixed(1) : 'N/A'}
      </td>

      {/* P/B */}
      <td className="py-2.5 px-2 text-right font-mono">
        {stock.pb_ratio != null ? stock.pb_ratio.toFixed(1) : 'N/A'}
      </td>

      {/* ROE */}
      <td className="py-2.5 px-2 text-right font-mono">
        {stock.roe != null ? `${(stock.roe * 100).toFixed(1)}%` : 'N/A'}
      </td>

      {/* Dividend Yield */}
      <td className="py-2.5 px-2 text-right font-mono">
        {stock.dividend_yield != null && stock.dividend_yield > 0
          ? `${(stock.dividend_yield * 100).toFixed(1)}%`
          : '-'}
      </td>

      {/* Warning Flags */}
      <td className="py-2.5 px-2">
        <WarningIndicators warnings={stock.warnings} />
      </td>

      {/* Actions: Research link + Add to Watchlist */}
      <td className="py-2.5 px-2 text-right">
        <div className="flex items-center justify-end gap-1">
          <Link to={`/research/${stock.ticker}`} className="p-1 hover:text-[var(--accent)]" title="Research">
            <ExternalLink className="w-3.5 h-3.5" />
          </Link>
          <button
            onClick={() => onAddToWatchlist(stock.ticker)}
            className="p-1 hover:text-[var(--accent)]"
            title="Add to Watchlist"
          >
            <Plus className="w-3.5 h-3.5" />
          </button>
        </div>
      </td>
    </tr>
  )
}


// ============================================================================
// ValueScreener — the main panel component
// ============================================================================

export function ValueScreener() {
  // Sorting state — default: highest composite score first
  const [sortBy, setSortBy] = useState('composite_score')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [sectorFilter, setSectorFilter] = useState<string | undefined>()
  const [indexFilter, setIndexFilter] = useState<string | undefined>()
  const [showCount, setShowCount] = useState(25)

  // Data hooks
  const { data, isLoading } = useScreenerResults({
    sort_by: sortBy,
    sort_order: sortOrder,
    sector: sectorFilter,
    index: indexFilter,
    limit: showCount,
  })
  const { data: status } = useScannerStatus()
  const { data: sectorsData } = useScreenerSectors()
  const { data: indicesData } = useScreenerIndices()
  const addMutation = useAddToWatchlist()

  /**
   * Handle column sort clicks.
   * Clicking the active column toggles asc/desc.
   * Clicking a new column sets it as active with a sensible default direction:
   *   - P/E and P/B default to ASC (lower is better for value)
   *   - Everything else defaults to DESC (higher is better)
   */
  const handleSort = (column: string) => {
    if (sortBy === column) {
      setSortOrder(prev => prev === 'desc' ? 'asc' : 'desc')
    } else {
      setSortBy(column)
      setSortOrder(column === 'pe_ratio' || column === 'pb_ratio' ? 'asc' : 'desc')
    }
  }

  // Common props passed to all SortableHeader instances
  const sortProps = { currentSort: sortBy, currentOrder: sortOrder, onSort: handleSort }

  return (
    <div className="card">
      {/* Header: title, scan status, and sector filter */}
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div>
          <h2 className="font-semibold text-lg flex items-center gap-2">
            <TrendingDown className="w-5 h-5 text-teal-400" />
            Value Screener
          </h2>
          <div className="text-xs text-[var(--muted-foreground)] flex items-center gap-2 mt-1">
            {status?.is_running ? (
              // Show live progress during a scan
              <span className="text-teal-400 flex items-center gap-1">
                <Loader2 className="w-3 h-3 animate-spin" />
                Scanning... ({status.tickers_scanned}/{status.tickers_total})
              </span>
            ) : status?.last_full_scan_completed_at ? (
              // Show last-updated timestamp when idle
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3" />
                Updated {new Date(status.last_full_scan_completed_at).toLocaleString()}
              </span>
            ) : null}
            {data?.total_count != null && (
              <span className="text-[var(--muted-foreground)]">
                {data.total_count} companies scored
              </span>
            )}
          </div>
        </div>

        {/* Filter dropdowns: index and sector */}
        <div className="flex items-center gap-2 flex-wrap">
          {indicesData?.indices && indicesData.indices.length > 0 && (
            <select
              className="input text-sm w-auto"
              value={indexFilter || ''}
              onChange={(e) => {
                setIndexFilter(e.target.value || undefined)
                setShowCount(25)
              }}
            >
              <option value="">All Indices</option>
              {indicesData.indices.map(idx => (
                <option key={idx} value={idx}>{idx}</option>
              ))}
            </select>
          )}
          {sectorsData?.sectors && sectorsData.sectors.length > 0 && (
            <select
              className="input text-sm w-auto"
              value={sectorFilter || ''}
              onChange={(e) => {
                setSectorFilter(e.target.value || undefined)
                setShowCount(25)
              }}
            >
              <option value="">All Sectors</option>
              {sectorsData.sectors.map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          )}
        </div>
      </div>

      {/* Results table (or loading/empty states) */}
      {isLoading ? (
        <div className="text-center py-8 text-[var(--muted-foreground)] flex items-center justify-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading screener results...
        </div>
      ) : !data?.results?.length ? (
        <div className="text-center py-8 text-[var(--muted-foreground)]">
          {status?.is_running
            ? 'Background scanner is populating data — results will appear shortly...'
            : 'No screener results yet. The background scanner will start populating data automatically.'}
        </div>
      ) : (
        <>
          <div className="overflow-auto max-h-[600px]">
            <table className="w-full text-sm">
              <thead className="sticky top-0 z-10 bg-[var(--card)]">
                <tr className="border-b border-[var(--border)]">
                  <StaticHeader label="#" align="center" tooltip="Rank by composite value score (1 = best)" />
                  <StaticHeader label="Ticker" align="left" />
                  <SortableHeader label="Score" column="composite_score" {...sortProps} tooltip="Weighted composite of all value metrics (0-100). Higher = stronger value signal." />
                  <StaticHeader label="Price" tooltip="Current market share price from Yahoo Finance." />
                  <SortableHeader label="MoS %" column="margin_of_safety" {...sortProps} tooltip="Margin of Safety: how far the price is below the Graham Number (intrinsic value). Positive = potentially undervalued." />
                  <SortableHeader label="P/E" column="pe_ratio" {...sortProps} tooltip="Price-to-Earnings ratio. Lower is cheaper. Graham preferred P/E under 15." />
                  <SortableHeader label="P/B" column="pb_ratio" {...sortProps} tooltip="Price-to-Book ratio. Lower means you pay less per dollar of net assets. Graham preferred under 1.5." />
                  <SortableHeader label="ROE" column="roe" {...sortProps} tooltip="Return on Equity: how efficiently the company generates profit from shareholders' equity. Higher is better." />
                  <SortableHeader label="Div %" column="dividend_yield" {...sortProps} tooltip="Annual dividend yield. Shows income returned to shareholders as a percentage of share price." />
                  <StaticHeader label="Flags" tooltip="Warning indicators: red = high severity, amber = medium, blue = low. Hover over dots for details." />
                  <StaticHeader label="Actions" />
                </tr>
              </thead>
              <tbody>
                {data.results.map((stock) => (
                  <ScreenerRow
                    key={stock.ticker}
                    stock={stock}
                    onAddToWatchlist={(ticker) => addMutation.mutate({ ticker })}
                  />
                ))}
              </tbody>
            </table>
          </div>

          {/* "Show more" pagination — loads 25 more at a time */}
          {data.total_count > showCount && (
            <div className="text-center mt-3">
              <button
                className="btn-secondary text-sm"
                onClick={() => setShowCount(prev => prev + 25)}
              >
                Show more ({data.total_count - showCount} remaining)
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
