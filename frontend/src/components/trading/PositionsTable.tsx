import { Link } from 'react-router-dom'
import type { TradingPosition } from '@/lib/types'

function formatMoney(value?: number | null): string {
  if (value == null) return '-'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)
}

const WHEEL_PHASE_LABELS: Record<string, { label: string; color: string }> = {
  selling_puts: { label: 'Selling Puts', color: 'text-sky-400' },
  assigned: { label: 'Assigned', color: 'text-amber-400' },
  selling_calls: { label: 'Selling Calls', color: 'text-emerald-400' },
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
              <th className="text-left px-4 py-2.5 font-medium">Ticker</th>
              <th className="text-left px-4 py-2.5 font-medium">Type</th>
              <th className="text-right px-4 py-2.5 font-medium">Qty</th>
              <th className="text-right px-4 py-2.5 font-medium">Entry</th>
              <th className="text-right px-4 py-2.5 font-medium">Value</th>
              <th className="text-right px-4 py-2.5 font-medium">P&L</th>
              <th className="text-left px-4 py-2.5 font-medium">Phase</th>
              <th className="text-left px-4 py-2.5 font-medium">Status</th>
              <th className="text-left px-4 py-2.5 font-medium">Opened</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((pos) => {
              const pnl = pos.status === 'open' ? pos.unrealized_pnl : pos.realized_pnl
              const pnlPositive = pnl >= 0
              const wheelPhase = pos.wheel_phase ? WHEEL_PHASE_LABELS[pos.wheel_phase] : null

              return (
                <tr
                  key={pos.id}
                  className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--muted)] transition-colors"
                >
                  <td className="px-4 py-2.5">
                    <Link
                      to={`/research/${pos.ticker}`}
                      className="font-mono font-medium hover:text-[var(--accent)] transition-colors"
                    >
                      {pos.ticker}
                    </Link>
                  </td>
                  <td className="px-4 py-2.5 text-[var(--muted-foreground)]">
                    {pos.asset_type === 'option' ? (
                      <span>
                        {pos.option_type?.toUpperCase()} {pos.strike_price && `$${pos.strike_price}`}
                        {pos.expiration_date && ` ${pos.expiration_date}`}
                      </span>
                    ) : (
                      'Stock'
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono">
                    {pos.asset_type === 'option' ? pos.contracts : pos.quantity}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono">
                    {formatMoney(pos.avg_entry_price)}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono">
                    {formatMoney(pos.current_value)}
                  </td>
                  <td className={`px-4 py-2.5 text-right font-mono font-medium ${pnlPositive ? 'text-gain' : 'text-loss'}`}>
                    {formatMoney(pnl)}
                  </td>
                  <td className="px-4 py-2.5">
                    {wheelPhase && (
                      <span className={`text-xs font-medium ${wheelPhase.color}`}>
                        {wheelPhase.label}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={`text-xs px-1.5 py-0.5 rounded ${
                      pos.status === 'open' ? 'bg-emerald-500/15 text-emerald-400' :
                      pos.status === 'closed' ? 'bg-[var(--muted)] text-[var(--muted-foreground)]' :
                      pos.status === 'assigned' ? 'bg-amber-500/15 text-amber-400' :
                      'bg-[var(--muted)] text-[var(--muted-foreground)]'
                    }`}>
                      {pos.status}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-xs text-[var(--muted-foreground)]">
                    {new Date(pos.opened_at).toLocaleDateString()}
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
