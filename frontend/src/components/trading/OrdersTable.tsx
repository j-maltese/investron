import type { TradingOrder } from '@/lib/types'
import { formatDateTime } from '@/lib/dateUtils'

function formatMoney(value?: number | null): string {
  if (value == null) return '-'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)
}

const STATUS_STYLES: Record<string, string> = {
  filled: 'bg-emerald-500/15 text-emerald-400',
  pending: 'bg-amber-500/15 text-amber-400',
  pending_new: 'bg-amber-500/15 text-amber-400',
  submitted: 'bg-sky-500/15 text-sky-400',
  cancelled: 'bg-[var(--muted)] text-[var(--muted-foreground)]',
  rejected: 'bg-red-500/15 text-red-400',
  partially_filled: 'bg-amber-500/15 text-amber-400',
}

const STRATEGY_BADGES: Record<string, { label: string; color: string }> = {
  simple_stock: { label: 'SS', color: 'bg-sky-500/15 text-sky-400' },
  wheel: { label: 'WH', color: 'bg-amber-500/15 text-amber-400' },
}

interface OrdersTableProps {
  orders: TradingOrder[]
  totalCount: number
}

export function OrdersTable({ orders, totalCount }: OrdersTableProps) {
  if (orders.length === 0) {
    return (
      <div className="card text-center py-8 text-[var(--muted-foreground)]">
        No orders yet.
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
              <th className="text-left px-3 py-2.5 font-medium">Date</th>
              <th className="text-left px-3 py-2.5 font-medium">Ticker</th>
              <th className="text-left px-3 py-2.5 font-medium">Side</th>
              <th className="text-left px-3 py-2.5 font-medium">Type</th>
              <th className="text-right px-3 py-2.5 font-medium">Strike</th>
              <th className="text-right px-3 py-2.5 font-medium">Premium</th>
              <th className="text-left px-3 py-2.5 font-medium">Exp</th>
              <th className="text-right px-3 py-2.5 font-medium">Qty</th>
              <th className="text-right px-3 py-2.5 font-medium">Fill Price</th>
              <th className="text-left px-3 py-2.5 font-medium">Status</th>
              <th className="text-left px-3 py-2.5 font-medium">Reason</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => {
              const badge = STRATEGY_BADGES[order.strategy_id]
              const isOption = order.asset_type === 'option'

              return (
                <tr
                  key={order.id}
                  className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--muted)] transition-colors"
                >
                  {/* Strategy badge */}
                  <td className="px-3 py-2.5">
                    {badge && (
                      <span
                        className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${badge.color}`}
                        title={order.strategy_id === 'simple_stock' ? 'Simple Stock Trading' : 'The Wheel Strategy'}
                      >
                        {badge.label}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-xs text-[var(--muted-foreground)]">
                    {formatDateTime(order.submitted_at)}
                  </td>
                  <td className="px-3 py-2.5 font-mono font-medium" title={order.company_name || order.ticker}>
                    {order.ticker}
                  </td>
                  <td className="px-3 py-2.5">
                    <span className={`text-xs font-medium ${
                      order.side === 'buy' ? 'text-gain' : 'text-loss'
                    }`}>
                      {order.side.toUpperCase()}
                    </span>
                  </td>
                  {/* Type: Stock/market or PUT/CALL */}
                  <td className="px-3 py-2.5 text-[var(--muted-foreground)]">
                    {isOption ? order.option_type?.toUpperCase() : order.order_type}
                  </td>
                  {/* Strike — options only */}
                  <td className="px-3 py-2.5 text-right font-mono">
                    {isOption && order.strike_price ? `$${order.strike_price}` : '-'}
                  </td>
                  {/* Premium — limit_price on option sells is the premium */}
                  <td className="px-3 py-2.5 text-right font-mono">
                    {isOption ? formatMoney(order.limit_price) : '-'}
                  </td>
                  {/* Expiration — options only */}
                  <td className="px-3 py-2.5 text-xs text-[var(--muted-foreground)]">
                    {isOption && order.expiration_date ? order.expiration_date : '-'}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono">
                    {order.contracts || order.quantity}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono">
                    {formatMoney(order.filled_avg_price)}
                  </td>
                  <td className="px-3 py-2.5">
                    <span className={`text-xs px-1.5 py-0.5 rounded ${STATUS_STYLES[order.status] || STATUS_STYLES.pending}`}>
                      {order.status.replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-xs text-[var(--muted-foreground)] max-w-[200px] truncate" title={order.reason || ''}>
                    {order.reason || '-'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {totalCount > orders.length && (
        <div className="px-4 py-2 text-xs text-[var(--muted-foreground)] border-t border-[var(--border)]">
          Showing {orders.length} of {totalCount} orders
        </div>
      )}
    </div>
  )
}
