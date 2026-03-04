import type { TradingOrder } from '@/lib/types'
import { formatDateTime } from '@/lib/dateUtils'

function formatMoney(value?: number | null): string {
  if (value == null) return '-'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)
}

const STATUS_STYLES: Record<string, string> = {
  filled: 'bg-emerald-500/15 text-emerald-400',
  pending: 'bg-amber-500/15 text-amber-400',
  submitted: 'bg-sky-500/15 text-sky-400',
  cancelled: 'bg-[var(--muted)] text-[var(--muted-foreground)]',
  rejected: 'bg-red-500/15 text-red-400',
  partially_filled: 'bg-amber-500/15 text-amber-400',
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
              <th className="text-left px-4 py-2.5 font-medium">Date</th>
              <th className="text-left px-4 py-2.5 font-medium">Ticker</th>
              <th className="text-left px-4 py-2.5 font-medium">Side</th>
              <th className="text-left px-4 py-2.5 font-medium">Type</th>
              <th className="text-right px-4 py-2.5 font-medium">Qty</th>
              <th className="text-right px-4 py-2.5 font-medium">Price</th>
              <th className="text-right px-4 py-2.5 font-medium">Fill Price</th>
              <th className="text-left px-4 py-2.5 font-medium">Status</th>
              <th className="text-left px-4 py-2.5 font-medium">Reason</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => (
              <tr
                key={order.id}
                className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--muted)] transition-colors"
              >
                <td className="px-4 py-2.5 text-xs text-[var(--muted-foreground)]">
                  {formatDateTime(order.submitted_at)}
                </td>
                <td className="px-4 py-2.5 font-mono font-medium">{order.ticker}</td>
                <td className="px-4 py-2.5">
                  <span className={`text-xs font-medium ${
                    order.side === 'buy' ? 'text-gain' : 'text-loss'
                  }`}>
                    {order.side.toUpperCase()}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-[var(--muted-foreground)]">
                  {order.asset_type === 'option' ? 'Option' : order.order_type}
                </td>
                <td className="px-4 py-2.5 text-right font-mono">
                  {order.contracts || order.quantity}
                </td>
                <td className="px-4 py-2.5 text-right font-mono">
                  {formatMoney(order.limit_price)}
                </td>
                <td className="px-4 py-2.5 text-right font-mono">
                  {formatMoney(order.filled_avg_price)}
                </td>
                <td className="px-4 py-2.5">
                  <span className={`text-xs px-1.5 py-0.5 rounded ${STATUS_STYLES[order.status] || STATUS_STYLES.pending}`}>
                    {order.status}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-xs text-[var(--muted-foreground)] max-w-[200px] truncate" title={order.reason || ''}>
                  {order.reason || '-'}
                </td>
              </tr>
            ))}
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
