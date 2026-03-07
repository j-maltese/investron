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

// Header tooltip definitions for every column
const HEADER_TOOLTIPS: Record<string, string> = {
  date: 'When the order was submitted to Alpaca',
  ticker: 'Stock ticker symbol',
  side: 'BUY or SELL',
  type: 'Stock order type (market/limit) or option type (PUT/CALL)',
  strike: 'Option strike price',
  premium: 'Limit price for option orders (per-share premium)',
  exp: 'Option expiration date',
  qty: 'Number of shares or contracts',
  fill_price: 'Actual price per share/contract when the order was filled',
  status: 'Order lifecycle: new (accepted) \u2192 filled | cancelled | rejected',
  reason: 'Why this order was placed (stop_loss, take_profit, ai_signal, etc.)',
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
              <TH id="date" className="text-left">Date</TH>
              <TH id="ticker" className="text-left">Ticker</TH>
              <TH id="side" className="text-left">Side</TH>
              <TH id="type" className="text-left">Type</TH>
              <TH id="strike" className="text-right">Strike</TH>
              <TH id="premium" className="text-right">Premium</TH>
              <TH id="exp" className="text-left">Exp</TH>
              <TH id="qty" className="text-right">Qty</TH>
              <TH id="fill_price" className="text-right">Fill Price</TH>
              <TH id="status" className="text-left">Status</TH>
              <TH id="reason" className="text-left">Reason</TH>
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
