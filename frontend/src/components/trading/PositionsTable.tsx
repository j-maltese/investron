import { Link } from 'react-router-dom'
import type { TradingPosition } from '@/lib/types'
import { formatDate } from '@/lib/dateUtils'

function formatMoney(value?: number | null): string {
  if (value == null) return '-'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)
}

const WHEEL_PHASE_LABELS: Record<string, { label: string; color: string }> = {
  selling_puts: { label: 'Selling Puts', color: 'text-sky-400' },
  assigned: { label: 'Assigned', color: 'text-amber-400' },
  selling_calls: { label: 'Selling Calls', color: 'text-emerald-400' },
}

const STRATEGY_BADGES: Record<string, { label: string; color: string }> = {
  simple_stock: { label: 'SS', color: 'bg-sky-500/15 text-sky-400' },
  wheel: { label: 'WH', color: 'bg-amber-500/15 text-amber-400' },
}

// ---------------------------------------------------------------------------
// Header tooltip definitions — brief descriptions for every column
// ---------------------------------------------------------------------------

const HEADER_TOOLTIPS: Record<string, string> = {
  ticker: 'Stock ticker symbol',
  type: 'Stock position or option type (PUT/CALL)',
  strike: 'Option strike price / current underlying stock price (updated ~15 min during market hours)',
  premium: 'Total premium collected = entry price x 100 shares x contracts',
  exp: 'Option expiration date',
  qty: 'Number of shares (stocks) or contracts (options)',
  entry: 'Per-share fill price (stocks) or per-share premium received (options). Blank = order not yet filled.',
  value: 'Current mark-to-market value (updated ~15 min during market hours)',
  pnl: 'Unrealized gain/loss (open positions) or realized gain/loss (closed)',
  phase: 'Wheel lifecycle: Selling Puts \u2192 Assigned \u2192 Selling Calls \u2192 Called Away',
  status: 'Position status: open, closed, assigned, or expired',
  opened: 'Date the position was opened',
}

/** Tooltip-enabled table header cell */
function TH({ id, children, className = '' }: { id: string; children: React.ReactNode; className?: string }) {
  return (
    <th
      className={`px-3 py-2.5 font-medium ${className}`}
      title={HEADER_TOOLTIPS[id]}
    >
      <span className="border-b border-dotted border-[var(--muted-foreground)] cursor-help">
        {children}
      </span>
    </th>
  )
}

interface PositionsTableProps {
  positions: TradingPosition[]
  totalCount: number
}

export function PositionsTable({ positions, totalCount }: PositionsTableProps) {
  if (positions.length === 0) {
    return (
      <div className="card text-center py-8 text-[var(--muted-foreground)]">
        No positions yet. Start a strategy to begin trading.
      </div>
    )
  }

  return (
    <div className="card p-0 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--border)] text-[var(--muted-foreground)] text-xs">
              <th className="text-left px-3 py-2.5 font-medium w-8"></th>
              <TH id="ticker" className="text-left">Ticker</TH>
              <TH id="type" className="text-left">Type</TH>
              <TH id="strike" className="text-right">Strike / Current</TH>
              <TH id="premium" className="text-right">Premium</TH>
              <TH id="exp" className="text-left">Exp</TH>
              <TH id="qty" className="text-right">Qty</TH>
              <TH id="entry" className="text-right">Entry</TH>
              <TH id="value" className="text-right">Value</TH>
              <TH id="pnl" className="text-right">P&L</TH>
              <TH id="phase" className="text-left">Phase</TH>
              <TH id="status" className="text-left">Status</TH>
              <TH id="opened" className="text-left">Opened</TH>
            </tr>
          </thead>
          <tbody>
            {positions.map((pos) => {
              const pnl = pos.status === 'open' ? pos.unrealized_pnl : pos.realized_pnl
              const pnlPositive = pnl >= 0
              const wheelPhase = pos.wheel_phase ? WHEEL_PHASE_LABELS[pos.wheel_phase] : null
              const badge = STRATEGY_BADGES[pos.strategy_id]
              const isOption = pos.asset_type === 'option'

              // Pending = option position with no fill yet (entry price is null/zero)
              const isPending = isOption && !pos.avg_entry_price

              return (
                <tr
                  key={pos.id}
                  className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--muted)] transition-colors"
                >
                  {/* Strategy badge */}
                  <td className="px-3 py-2.5">
                    {badge && (
                      <span
                        className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${badge.color}`}
                        title={pos.strategy_id === 'simple_stock' ? 'Simple Stock Trading' : 'The Wheel Strategy'}
                      >
                        {badge.label}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    <Link
                      to={`/research/${pos.ticker}`}
                      className="font-mono font-medium hover:text-[var(--accent)] transition-colors"
                      title={pos.company_name || pos.ticker}
                    >
                      {pos.ticker}
                    </Link>
                  </td>
                  {/* Type: Stock or PUT/CALL */}
                  <td className="px-3 py-2.5 text-[var(--muted-foreground)]">
                    {isOption ? pos.option_type?.toUpperCase() : 'Stock'}
                  </td>
                  {/* Strike / Current — shows strike price with underlying stock price for context */}
                  <td className="px-3 py-2.5 text-right font-mono">
                    {isOption && pos.strike_price ? (
                      <span title="Strike price / current underlying stock price">
                        ${pos.strike_price}
                        {pos.underlying_price != null && (
                          <span className="text-[var(--muted-foreground)]">
                            {' / '}${pos.underlying_price.toFixed(2)}
                          </span>
                        )}
                      </span>
                    ) : pos.asset_type === 'stock' && pos.underlying_price != null ? (
                      <span
                        className="text-[var(--muted-foreground)]"
                        title="Current stock price"
                      >
                        ${pos.underlying_price.toFixed(2)}
                      </span>
                    ) : '-'}
                  </td>
                  {/* Premium — cost_basis for sold options represents premium collected */}
                  <td className="px-3 py-2.5 text-right font-mono">
                    {isOption && pos.cost_basis != null ? formatMoney(pos.cost_basis) : '-'}
                  </td>
                  {/* Expiration — options only */}
                  <td className="px-3 py-2.5 text-xs text-[var(--muted-foreground)]">
                    {isOption && pos.expiration_date ? pos.expiration_date : '-'}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono">
                    {isOption ? pos.contracts : pos.quantity}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono">
                    {isPending ? (
                      <span
                        className="text-[var(--muted-foreground)] italic"
                        title="Order not yet filled — entry price will update when Alpaca confirms the fill"
                      >
                        pending
                      </span>
                    ) : (
                      formatMoney(pos.avg_entry_price)
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono">
                    {formatMoney(pos.current_value)}
                  </td>
                  <td className={`px-3 py-2.5 text-right font-mono font-medium ${pnlPositive ? 'text-gain' : 'text-loss'}`}>
                    {formatMoney(pnl)}
                  </td>
                  <td className="px-3 py-2.5">
                    {wheelPhase && (
                      <span className={`text-xs font-medium ${wheelPhase.color}`}>
                        {wheelPhase.label}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    {isPending ? (
                      // Orange outline badge for unfilled option positions
                      <span
                        className="text-xs px-1.5 py-0.5 rounded border border-amber-400 text-amber-400"
                        title="Order submitted but not yet filled by exchange"
                      >
                        pending
                      </span>
                    ) : (
                      <span className={`text-xs px-1.5 py-0.5 rounded ${
                        pos.status === 'open' ? 'bg-emerald-500/15 text-emerald-400' :
                        pos.status === 'closed' ? 'bg-[var(--muted)] text-[var(--muted-foreground)]' :
                        pos.status === 'assigned' ? 'bg-amber-500/15 text-amber-400' :
                        'bg-[var(--muted)] text-[var(--muted-foreground)]'
                      }`}>
                        {pos.status}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-xs text-[var(--muted-foreground)]">
                    {formatDate(pos.opened_at)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {totalCount > positions.length && (
        <div className="px-4 py-2 text-xs text-[var(--muted-foreground)] border-t border-[var(--border)]">
          Showing {positions.length} of {totalCount} positions
        </div>
      )}
    </div>
  )
}
