import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus, Trash2, AlertTriangle, ExternalLink } from 'lucide-react'
import { PageLayout } from '@/components/layout/PageLayout'
import { useWatchlist, useAlerts, useAddToWatchlist, useRemoveFromWatchlist } from '@/hooks/useWatchlist'

function formatCurrency(value?: number | null): string {
  if (value == null) return 'N/A'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)
}

export function Dashboard() {
  const { data: watchlistData, isLoading: watchlistLoading } = useWatchlist()
  const { data: alertsData } = useAlerts()
  const addMutation = useAddToWatchlist()
  const removeMutation = useRemoveFromWatchlist()

  const [newTicker, setNewTicker] = useState('')
  const [newTarget, setNewTarget] = useState('')

  const handleAdd = () => {
    if (!newTicker.trim()) return
    addMutation.mutate({
      ticker: newTicker.trim().toUpperCase(),
      target_price: newTarget ? parseFloat(newTarget) : undefined,
    })
    setNewTicker('')
    setNewTarget('')
  }

  return (
    <PageLayout>
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Dashboard</h1>

        {/* Alerts */}
        {alertsData?.alerts && alertsData.alerts.length > 0 && (
          <div className="card border-yellow-500/30 bg-yellow-500/5">
            <div className="flex items-center gap-2 mb-3">
              <AlertTriangle className="w-4 h-4 text-yellow-500" />
              <h2 className="font-semibold text-sm">Price Alerts</h2>
            </div>
            <div className="space-y-2">
              {alertsData.alerts.map((alert) => (
                <div key={alert.ticker} className="text-sm">
                  <Link to={`/research/${alert.ticker}`} className="font-medium hover:text-[var(--accent)]">
                    {alert.ticker}
                  </Link>
                  <span className="text-[var(--muted-foreground)] ml-2">{alert.message}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Watchlist */}
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-lg">Watchlist</h2>
          </div>

          {/* Add ticker form */}
          <div className="flex gap-2 mb-4">
            <input
              type="text"
              value={newTicker}
              onChange={(e) => setNewTicker(e.target.value)}
              placeholder="Ticker (e.g. AAPL)"
              className="input flex-1 text-sm"
              onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            />
            <input
              type="number"
              value={newTarget}
              onChange={(e) => setNewTarget(e.target.value)}
              placeholder="Target price"
              className="input w-32 text-sm"
              onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            />
            <button onClick={handleAdd} className="btn-primary text-sm flex items-center gap-1" disabled={addMutation.isPending}>
              <Plus className="w-4 h-4" /> Add
            </button>
          </div>

          {/* Watchlist table */}
          {watchlistLoading ? (
            <div className="text-center py-8 text-[var(--muted-foreground)]">Loading watchlist...</div>
          ) : watchlistData?.items?.length === 0 ? (
            <div className="text-center py-8 text-[var(--muted-foreground)]">
              Your watchlist is empty. Add a ticker above to get started.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[var(--border)]">
                    <th className="text-left py-2 px-2 font-medium text-[var(--muted-foreground)]">Ticker</th>
                    <th className="text-left py-2 px-2 font-medium text-[var(--muted-foreground)]">Company</th>
                    <th className="text-right py-2 px-2 font-medium text-[var(--muted-foreground)]">Price</th>
                    <th className="text-right py-2 px-2 font-medium text-[var(--muted-foreground)]">Target</th>
                    <th className="text-left py-2 px-2 font-medium text-[var(--muted-foreground)]">Notes</th>
                    <th className="text-right py-2 px-2 font-medium text-[var(--muted-foreground)]">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {watchlistData?.items?.map((item) => (
                    <tr key={item.ticker} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--muted)] transition-colors">
                      <td className="py-2.5 px-2">
                        <Link to={`/research/${item.ticker}`} className="font-semibold hover:text-[var(--accent)]">
                          {item.ticker}
                        </Link>
                      </td>
                      <td className="py-2.5 px-2 text-[var(--muted-foreground)]">
                        {item.company_name || '-'}
                      </td>
                      <td className="py-2.5 px-2 text-right font-mono">
                        {formatCurrency(item.current_price)}
                      </td>
                      <td className="py-2.5 px-2 text-right font-mono text-[var(--muted-foreground)]">
                        {item.target_price ? formatCurrency(item.target_price) : '-'}
                      </td>
                      <td className="py-2.5 px-2 text-[var(--muted-foreground)] max-w-xs truncate">
                        {item.notes || '-'}
                      </td>
                      <td className="py-2.5 px-2 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Link to={`/research/${item.ticker}`} className="p-1 hover:text-[var(--accent)]" title="Research">
                            <ExternalLink className="w-3.5 h-3.5" />
                          </Link>
                          <button
                            onClick={() => removeMutation.mutate(item.ticker)}
                            className="p-1 hover:text-loss"
                            title="Remove"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </PageLayout>
  )
}
