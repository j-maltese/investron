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
              <th className="text-left px-3 py-2.5 font-medium">Ticker</th>
              <th className="text-left px-3 py-2.5 font-medium">Type</th>
              <th className="text-right px-3 py-2.5 font-medium">Strike</th>
              <th className="text-right px-3 py-2.5 font-medium">Premium</th>
              <th className="text-left px-3 py-2.5 font-medium">Exp</th>
              <th className="text-right px-3 py-2.5 font-medium">Qty</th>
              <th className="text-right px-3 py-2.5 font-medium">Entry</th>
              <th className="text-right px-3 py-2.5 font-medium">Value</th>
              <th className="text-right px-3 py-2.5 font-medium">P&L</th>
              <th className="text-left px-3 py-2.5 font-medium">Phase</th>
              <th className="text-left px-3 py-2.5 font-medium">Status</th>
              <th className="text-left px-3 py-2.5 font-medium">Opened</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((pos) => {
              const pnl = pos.status === 'open' ? pos.unrealized_pnl : pos.realized_pnl
              const pnlPositive = pnl >= 0
              const wheelPhase = pos.wheel_phase ? WHEEL_PHASE_LABELS[pos.wheel_phase] : null
              const badge = STRATEGY_BADGES[pos.strategy_id]
              const isOption = pos.asset_type === 'option'

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
                  {/* Strike — options only */}
                  <td className="px-3 py-2.5 text-right font-mono">
                    {isOption && pos.strike_price ? `$${pos.strike_price}` : '-'}
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
                    {formatMoney(pos.avg_entry_price)}
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
                    <span className={`text-xs px-1.5 py-0.5 rounded ${
                      pos.status === 'open' ? 'bg-emerald-500/15 text-emerald-400' :
                      pos.status === 'closed' ? 'bg-[var(--muted)] text-[var(--muted-foreground)]' :
                      pos.status === 'assigned' ? 'bg-amber-500/15 text-amber-400' :
                      'bg-[var(--muted)] text-[var(--muted-foreground)]'
                    }`}>
                      {pos.status}
                    </span>
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
