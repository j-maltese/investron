import { useState, useRef, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Plus, Trash2, AlertTriangle, ExternalLink, StickyNote } from 'lucide-react'
import { PageLayout } from '@/components/layout/PageLayout'
import { useWatchlist, useAlerts, useAddToWatchlist, useRemoveFromWatchlist, useUpdateWatchlistItem, useTickerNotes } from '@/hooks/useWatchlist'
import { NotePopup } from '@/components/dashboard/NotePopup'
import { ValueScreener } from '@/components/dashboard/ValueScreener'
import { TickerAutocomplete } from '@/components/search/TickerAutocomplete'
import type { WatchlistView, TickerNote } from '@/lib/types'

function formatCurrency(value?: number | null): string {
  if (value == null) return 'N/A'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)
}

const VIEW_OPTIONS: { value: WatchlistView; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'john', label: 'John' },
  { value: 'mark', label: 'Mark' },
]

// Badge colors per owner — first letter shown in a small circle
const OWNER_COLORS: Record<string, string> = {
  John: 'bg-blue-500/20 text-blue-400',
  Mark: 'bg-emerald-500/20 text-emerald-400',
}

export function Dashboard() {
  const [view, setView] = useState<WatchlistView>('all')
  const { data: watchlistData, isLoading: watchlistLoading } = useWatchlist(view)
  const { data: alertsData } = useAlerts()
  const { data: notesByTicker } = useTickerNotes()
  const addMutation = useAddToWatchlist()
  const removeMutation = useRemoveFromWatchlist()
  const updateMutation = useUpdateWatchlistItem()

  const currentUserEmail = watchlistData?.current_user_email

  const [newTicker, setNewTicker] = useState('')
  const [newTarget, setNewTarget] = useState('')

  // Inline editing state: tracks which cell is being edited (target_price only — notes use popup)
  const [editingCell, setEditingCell] = useState<{ ticker: string; field: 'target_price' } | null>(null)
  const [editValue, setEditValue] = useState('')
  const editRef = useRef<HTMLInputElement>(null)

  // Note popup state
  const [notePopup, setNotePopup] = useState<{ ticker: string; notes: TickerNote[]; rect: DOMRect } | null>(null)

  // Auto-focus the input when editing starts
  useEffect(() => {
    if (editingCell && editRef.current) {
      editRef.current.focus()
      editRef.current.select()
    }
  }, [editingCell])

  const startEditing = (ticker: string, field: 'target_price', currentValue: string) => {
    setEditingCell({ ticker, field })
    setEditValue(currentValue)
  }

  const saveEdit = () => {
    if (!editingCell) return
    const { ticker } = editingCell
    updateMutation.mutate({ ticker, update: { target_price: editValue ? parseFloat(editValue) : undefined } })
    setEditingCell(null)
  }

  const cancelEdit = () => setEditingCell(null)

  /** Open the note popup for a ticker using data from ticker_notes */
  const openNotePopup = useCallback((ticker: string, el: HTMLElement) => {
    const notes = notesByTicker?.[ticker] ?? []
    setNotePopup({ ticker, notes, rect: el.getBoundingClientRect() })
  }, [notesByTicker])

  const closeNotePopup = useCallback(() => setNotePopup(null), [])

  const handleAdd = () => {
    if (!newTicker.trim()) return
    addMutation.mutate({
      ticker: newTicker.trim().toUpperCase(),
      target_price: newTarget ? parseFloat(newTarget) : undefined,
    })
    setNewTicker('')
    setNewTarget('')
  }

  /** Get a preview of the first note for a ticker (for the truncated display) */
  const getNotesPreview = (ticker: string): string | null => {
    const notes = notesByTicker?.[ticker]
    if (!notes || notes.length === 0) return null
    // Show first note text, with count if multiple
    const first = notes[0].notes
    return notes.length > 1 ? `${first} (+${notes.length - 1})` : first
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
            {/* View toggle pills */}
            <div className="flex gap-1 bg-[var(--muted)] rounded-lg p-0.5">
              {VIEW_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setView(opt.value)}
                  className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                    view === opt.value
                      ? 'bg-[var(--accent)] text-white'
                      : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)]'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Add ticker form — autocomplete searches by ticker or company name */}
          <div className="flex gap-2 mb-4">
            <div className="flex-1">
              <TickerAutocomplete
                value={newTicker}
                onChange={setNewTicker}
                onSelect={(result) => {
                  setNewTicker(result.ticker)
                  // Auto-submit if target price is empty (common flow: search → pick → add)
                }}
                placeholder="Search ticker or company..."
                showIcon={false}
                clearOnSelect={false}
                allowRawTicker={true}
              />
            </div>
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
              {view === 'all' ? 'No watchlist items yet.' : `No items in ${VIEW_OPTIONS.find(o => o.value === view)?.label}'s watchlist.`}
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
                  {watchlistData?.items?.map((item) => {
                    const isOwner = item.user_email === currentUserEmail
                    const ownerBadgeColor = OWNER_COLORS[item.owner_name ?? ''] ?? 'bg-gray-500/20 text-gray-400'
                    const notesPreview = getNotesPreview(item.ticker)

                    return (
                      <tr key={`${item.ticker}-${item.user_email}`} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--muted)] transition-colors group">
                        <td className="py-2.5 px-2">
                          <div className="flex items-center gap-1.5">
                            <Link to={`/research/${item.ticker}`} className="font-semibold hover:text-[var(--accent)]">
                              {item.ticker}
                            </Link>
                            {/* Owner badge — always visible so you know whose pick it is */}
                            {item.owner_name && (
                              <span className={`inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-bold ${ownerBadgeColor}`} title={item.owner_name}>
                                {item.owner_name[0]}
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="py-2.5 px-2 text-[var(--muted-foreground)]">
                          {item.company_name || '-'}
                        </td>
                        <td className="py-2.5 px-2 text-right font-mono">
                          {formatCurrency(item.current_price)}
                        </td>
                        <td className="py-2.5 px-2 text-right font-mono text-[var(--muted-foreground)]">
                          {isOwner && editingCell?.ticker === item.ticker && editingCell.field === 'target_price' ? (
                            <input
                              ref={editRef}
                              type="number"
                              value={editValue}
                              onChange={(e) => setEditValue(e.target.value)}
                              onBlur={saveEdit}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') saveEdit()
                                if (e.key === 'Escape') cancelEdit()
                              }}
                              className="input w-24 text-sm text-right font-mono py-0.5 px-1"
                              step="0.01"
                            />
                          ) : isOwner ? (
                            <span
                              className="cursor-pointer hover:text-[var(--accent)] transition-colors"
                              onClick={() => startEditing(item.ticker, 'target_price', item.target_price?.toString() ?? '')}
                              title="Click to edit target price"
                            >
                              {item.target_price ? formatCurrency(item.target_price) : '-'}
                            </span>
                          ) : (
                            <span>{item.target_price ? formatCurrency(item.target_price) : '-'}</span>
                          )}
                        </td>
                        <td className="py-2.5 px-2 text-[var(--muted-foreground)] max-w-xs">
                          <span
                            className="cursor-pointer hover:text-[var(--accent)] transition-colors truncate block flex items-center gap-1"
                            onClick={(e) => openNotePopup(item.ticker, e.currentTarget)}
                            title="Click to view/edit notes"
                          >
                            {notesPreview ? (
                              <>
                                <StickyNote className="w-3 h-3 text-amber-400 shrink-0" />
                                <span className="truncate">{notesPreview}</span>
                              </>
                            ) : (
                              '-'
                            )}
                          </span>
                        </td>
                        <td className="py-2.5 px-2 text-right">
                          <div className="flex items-center justify-end gap-1">
                            <Link to={`/research/${item.ticker}`} className="p-1 hover:text-[var(--accent)]" title="Research">
                              <ExternalLink className="w-3.5 h-3.5" />
                            </Link>
                            {/* Only show delete for items the current user owns */}
                            {isOwner && (
                              <button
                                onClick={() => removeMutation.mutate(item.ticker)}
                                className="p-1 hover:text-loss"
                                title="Remove"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Value Screener — shows ranked S&P 500 stocks by composite value score */}
        <ValueScreener />
      </div>

      {/* Note popup — portal rendered, positioned relative to the clicked cell */}
      {notePopup && (
        <NotePopup
          notes={notePopup.notes}
          ticker={notePopup.ticker}
          anchorRect={notePopup.rect}
          onClose={closeNotePopup}
        />
      )}
    </PageLayout>
  )
}
