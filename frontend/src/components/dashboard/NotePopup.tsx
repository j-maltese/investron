/**
 * NotePopup — Portal-based popup for viewing and editing watchlist notes.
 *
 * Used in both the Value Screener (note indicator) and the Watchlist table.
 * Any authenticated user can edit any note (cross-user editing), so notes
 * function as shared annotations on a ticker rather than private per-user data.
 *
 * Shows ALL watchlist items for the ticker — items without notes get an
 * "Add note" prompt so users can add notes to any watchlist entry.
 *
 * Multi-line support: Shift+Enter inserts a newline, Enter saves.
 */

import { useState, useRef, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { X, StickyNote, Pencil, Check, Plus } from 'lucide-react'
import type { WatchlistNote } from '@/lib/types'
import { useUpdateNoteById } from '@/hooks/useWatchlist'


interface NotePopupProps {
  /** All watchlist items for this ticker (may or may not have notes) */
  items: WatchlistNote[]
  ticker: string
  /** Anchor element to position the popup near */
  anchorRect: DOMRect | null
  onClose: () => void
}


export function NotePopup({ items, ticker, anchorRect, onClose }: NotePopupProps) {
  const updateNote = useUpdateNoteById()
  // Track which item ID is being edited (null = none)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editValue, setEditValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const popupRef = useRef<HTMLDivElement>(null)

  // Close on Escape or click outside
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        // If editing, cancel edit instead of closing popup
        if (editingId != null) {
          setEditingId(null)
          setEditValue('')
        } else {
          onClose()
        }
      }
    }
    const handleClick = (e: MouseEvent) => {
      if (popupRef.current && !popupRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    document.addEventListener('keydown', handleKey)
    // Delay click listener to avoid immediately closing from the triggering click
    const timer = setTimeout(() => document.addEventListener('mousedown', handleClick), 0)
    return () => {
      document.removeEventListener('keydown', handleKey)
      document.removeEventListener('mousedown', handleClick)
      clearTimeout(timer)
    }
  }, [onClose, editingId])

  // Auto-focus and auto-resize textarea when editing starts
  useEffect(() => {
    if (editingId != null && textareaRef.current) {
      textareaRef.current.focus()
      textareaRef.current.selectionStart = textareaRef.current.value.length
      autoResize(textareaRef.current)
    }
  }, [editingId])

  const autoResize = (el: HTMLTextAreaElement) => {
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }

  const startEdit = useCallback((item: WatchlistNote) => {
    setEditingId(item.id)
    setEditValue(item.notes ?? '')
  }, [])

  const saveEdit = useCallback(() => {
    if (editingId == null) return
    updateNote.mutate({ itemId: editingId, notes: editValue })
    setEditingId(null)
  }, [editingId, editValue, updateNote])

  const cancelEdit = useCallback(() => {
    setEditingId(null)
    setEditValue('')
  }, [])

  if (!anchorRect) return null

  // Position the popup below the anchor, clamped to viewport
  const top = Math.min(anchorRect.bottom + 8, window.innerHeight - 300)
  const left = Math.min(Math.max(anchorRect.left, 16), window.innerWidth - 340)

  return createPortal(
    <div
      ref={popupRef}
      className="fixed z-50 w-80 bg-[var(--card)] border border-[var(--border)] rounded-lg shadow-xl"
      style={{ top, left }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border)]">
        <div className="flex items-center gap-1.5 text-sm font-medium">
          <StickyNote className="w-3.5 h-3.5 text-amber-400" />
          Notes — {ticker}
        </div>
        <button onClick={onClose} className="p-0.5 hover:text-[var(--foreground)] text-[var(--muted-foreground)]">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Items list — shows all watchlist entries for this ticker */}
      <div className="max-h-64 overflow-auto p-3 space-y-3">
        {items.length === 0 ? (
          <p className="text-xs text-[var(--muted-foreground)] italic">Not on any watchlist.</p>
        ) : (
          items.map((item) => (
            <div key={item.id} className="group">
              {/* Owner badge + edit controls */}
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] font-semibold text-[var(--muted-foreground)] uppercase tracking-wide">
                  {item.owner_name}
                </span>
                {editingId === item.id ? (
                  <div className="flex items-center gap-1">
                    <button onClick={saveEdit} className="p-0.5 text-gain hover:text-gain/80" title="Save (Enter)">
                      <Check className="w-3 h-3" />
                    </button>
                    <button onClick={cancelEdit} className="p-0.5 text-[var(--muted-foreground)] hover:text-loss" title="Cancel (Esc)">
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => startEdit(item)}
                    className="p-0.5 text-[var(--muted-foreground)] opacity-0 group-hover:opacity-100 hover:text-[var(--accent)] transition-opacity"
                    title={item.notes ? 'Edit note' : 'Add note'}
                  >
                    {item.notes ? <Pencil className="w-3 h-3" /> : <Plus className="w-3 h-3" />}
                  </button>
                )}
              </div>

              {/* Note content, edit textarea, or empty-state add prompt */}
              {editingId === item.id ? (
                <textarea
                  ref={textareaRef}
                  value={editValue}
                  onChange={(e) => {
                    setEditValue(e.target.value)
                    autoResize(e.target)
                  }}
                  onKeyDown={(e) => {
                    // Shift+Enter = newline (default), Enter alone = save
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      saveEdit()
                    }
                    if (e.key === 'Escape') cancelEdit()
                  }}
                  className="input w-full text-xs py-1.5 px-2 resize-none min-h-[2.5rem]"
                  placeholder="Add a note..."
                />
              ) : item.notes ? (
                <p className="text-xs text-[var(--foreground)] whitespace-pre-wrap break-words">
                  {item.notes}
                </p>
              ) : (
                <button
                  onClick={() => startEdit(item)}
                  className="text-xs text-[var(--muted-foreground)] italic hover:text-[var(--accent)] transition-colors"
                >
                  Click to add a note...
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </div>,
    document.body
  )
}


// ============================================================================
// NoteIndicator — shown in the screener Flags column for watchlisted tickers.
// Amber dot if notes exist, pencil icon if on watchlist but no notes.
// ============================================================================

interface NoteIndicatorProps {
  /** All watchlist items for this ticker (may or may not have notes) */
  items: WatchlistNote[]
  ticker: string
}

export function NoteIndicator({ items, ticker }: NoteIndicatorProps) {
  const [open, setOpen] = useState(false)
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null)
  const btnRef = useRef<HTMLButtonElement>(null)

  const handleClick = useCallback(() => {
    if (btnRef.current) {
      setAnchorRect(btnRef.current.getBoundingClientRect())
    }
    setOpen((prev) => !prev)
  }, [])

  const handleClose = useCallback(() => setOpen(false), [])

  // Nothing to show if ticker isn't on any watchlist
  if (!items || items.length === 0) return null

  const hasNotes = items.some((i) => i.notes)

  return (
    <>
      {hasNotes ? (
        <button
          ref={btnRef}
          onClick={handleClick}
          className="w-2 h-2 rounded-full bg-amber-400 hover:bg-amber-300 transition-colors cursor-pointer"
          title={`Notes on ${ticker} — click to view/edit`}
        />
      ) : (
        <button
          ref={btnRef}
          onClick={handleClick}
          className="p-0.5 text-[var(--muted-foreground)] hover:text-[var(--accent)] transition-colors cursor-pointer"
          title={`${ticker} is on a watchlist — click to add notes`}
        >
          <Pencil className="w-3 h-3" />
        </button>
      )}
      {open && (
        <NotePopup
          items={items}
          ticker={ticker}
          anchorRect={anchorRect}
          onClose={handleClose}
        />
      )}
    </>
  )
}
