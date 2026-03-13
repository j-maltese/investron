/**
 * NotePopup — Portal-based popup for viewing and editing ticker notes.
 *
 * Notes are decoupled from watchlist items — they follow the ticker, not
 * the watchlist entry. Each note is attributed to the user who wrote it.
 *
 * Used in both the Value Screener and the Watchlist table (same component).
 *
 * Multi-line support: Shift+Enter inserts a newline, Enter saves.
 */

import { useState, useRef, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { X, StickyNote, Pencil, Check, Plus, Trash2 } from 'lucide-react'
import type { TickerNote } from '@/lib/types'
import { useCreateTickerNote, useUpdateTickerNote, useDeleteTickerNote } from '@/hooks/useWatchlist'


interface NotePopupProps {
  /** Existing notes for this ticker (from ticker_notes table) */
  notes: TickerNote[]
  ticker: string
  /** Anchor element to position the popup near */
  anchorRect: DOMRect | null
  onClose: () => void
}


export function NotePopup({ notes, ticker, anchorRect, onClose }: NotePopupProps) {
  const createNote = useCreateTickerNote()
  const updateNote = useUpdateTickerNote()
  const deleteNote = useDeleteTickerNote()

  // Track which note ID is being edited (null = none, 'new' = adding a new note)
  const [editingId, setEditingId] = useState<number | 'new' | null>(null)
  const [editValue, setEditValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const popupRef = useRef<HTMLDivElement>(null)

  // Close on Escape or click outside
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
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

  const startEdit = useCallback((note: TickerNote) => {
    setEditingId(note.id)
    setEditValue(note.notes)
  }, [])

  const startNew = useCallback(() => {
    setEditingId('new')
    setEditValue('')
  }, [])

  const saveEdit = useCallback(() => {
    if (editingId == null || !editValue.trim()) return
    if (editingId === 'new') {
      createNote.mutate({ ticker, notes: editValue.trim() })
    } else {
      updateNote.mutate({ noteId: editingId, notes: editValue.trim() })
    }
    setEditingId(null)
    setEditValue('')
  }, [editingId, editValue, ticker, createNote, updateNote])

  const cancelEdit = useCallback(() => {
    setEditingId(null)
    setEditValue('')
  }, [])

  const handleDelete = useCallback((noteId: number) => {
    deleteNote.mutate(noteId)
  }, [deleteNote])

  if (!anchorRect) return null

  // Position the popup below the anchor, clamped to viewport
  const top = Math.min(anchorRect.bottom + 8, window.innerHeight - 320)
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
        <div className="flex items-center gap-1">
          {/* Add note button */}
          {editingId !== 'new' && (
            <button
              onClick={startNew}
              className="p-0.5 text-[var(--muted-foreground)] hover:text-[var(--accent)] transition-colors"
              title="Add a note"
            >
              <Plus className="w-3.5 h-3.5" />
            </button>
          )}
          <button onClick={onClose} className="p-0.5 hover:text-[var(--foreground)] text-[var(--muted-foreground)]">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Notes list */}
      <div className="max-h-64 overflow-auto p-3 space-y-3">
        {/* New note textarea (at the top when adding) */}
        {editingId === 'new' && (
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] font-semibold text-[var(--accent)] uppercase tracking-wide">
                New note
              </span>
              <div className="flex items-center gap-1">
                <button onClick={saveEdit} className="p-0.5 text-gain hover:text-gain/80" title="Save (Enter)">
                  <Check className="w-3 h-3" />
                </button>
                <button onClick={cancelEdit} className="p-0.5 text-[var(--muted-foreground)] hover:text-loss" title="Cancel (Esc)">
                  <X className="w-3 h-3" />
                </button>
              </div>
            </div>
            <textarea
              ref={textareaRef}
              value={editValue}
              onChange={(e) => {
                setEditValue(e.target.value)
                autoResize(e.target)
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveEdit() }
                if (e.key === 'Escape') cancelEdit()
              }}
              className="input w-full text-xs py-1.5 px-2 resize-none min-h-[2.5rem]"
              placeholder="Write a note... (Shift+Enter for new line)"
            />
          </div>
        )}

        {notes.length === 0 && editingId !== 'new' ? (
          <button
            onClick={startNew}
            className="text-xs text-[var(--muted-foreground)] italic hover:text-[var(--accent)] transition-colors w-full text-left"
          >
            No notes yet — click to add one...
          </button>
        ) : (
          notes.map((note) => (
            <div key={note.id} className="group">
              {/* Author badge + edit controls */}
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] font-semibold text-[var(--muted-foreground)] uppercase tracking-wide">
                  {note.author_name}
                </span>
                {editingId === note.id ? (
                  <div className="flex items-center gap-1">
                    <button onClick={saveEdit} className="p-0.5 text-gain hover:text-gain/80" title="Save (Enter)">
                      <Check className="w-3 h-3" />
                    </button>
                    <button onClick={cancelEdit} className="p-0.5 text-[var(--muted-foreground)] hover:text-loss" title="Cancel (Esc)">
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                ) : (
                  <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={() => startEdit(note)}
                      className="p-0.5 text-[var(--muted-foreground)] hover:text-[var(--accent)]"
                      title="Edit note"
                    >
                      <Pencil className="w-3 h-3" />
                    </button>
                    <button
                      onClick={() => handleDelete(note.id)}
                      className="p-0.5 text-[var(--muted-foreground)] hover:text-loss"
                      title="Delete note"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                )}
              </div>

              {/* Note content or edit textarea */}
              {editingId === note.id ? (
                <textarea
                  ref={textareaRef}
                  value={editValue}
                  onChange={(e) => {
                    setEditValue(e.target.value)
                    autoResize(e.target)
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveEdit() }
                    if (e.key === 'Escape') cancelEdit()
                  }}
                  className="input w-full text-xs py-1.5 px-2 resize-none min-h-[2.5rem]"
                  placeholder="Edit note... (Shift+Enter for new line)"
                />
              ) : (
                <p className="text-xs text-[var(--foreground)] whitespace-pre-wrap break-words">
                  {note.notes}
                </p>
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
// NoteIndicator — shown in the screener Flags column and watchlist Notes column.
// Amber dot if notes exist, pencil icon to add on any row.
// ============================================================================

interface NoteIndicatorProps {
  /** Existing notes for this ticker (may be empty) */
  notes: TickerNote[]
  ticker: string
}

export function NoteIndicator({ notes, ticker }: NoteIndicatorProps) {
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

  const hasNotes = notes.length > 0

  return (
    <>
      {hasNotes ? (
        <button
          ref={btnRef}
          onClick={handleClick}
          className="w-2 h-2 rounded-full bg-amber-400 hover:bg-amber-300 transition-colors cursor-pointer"
          title={`${notes.length} note${notes.length > 1 ? 's' : ''} on ${ticker} — click to view/edit`}
        />
      ) : (
        <button
          ref={btnRef}
          onClick={handleClick}
          className="p-0.5 text-[var(--muted-foreground)] opacity-0 group-hover:opacity-100 hover:text-[var(--accent)] transition-all cursor-pointer"
          title={`Add a note on ${ticker}`}
        >
          <Pencil className="w-3 h-3" />
        </button>
      )}
      {open && (
        <NotePopup
          notes={notes}
          ticker={ticker}
          anchorRect={anchorRect}
          onClose={handleClose}
        />
      )}
    </>
  )
}
