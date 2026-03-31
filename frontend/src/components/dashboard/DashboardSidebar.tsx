import { X } from 'lucide-react'

/**
 * DashboardSidebar — slide-in panel for toggling dashboard cards on/off.
 *
 * Renders as a fixed left-side drawer with a semi-transparent backdrop.
 * Card visibility is managed by the parent (Dashboard) and persisted to localStorage.
 * New cards can be added to DASHBOARD_CARDS as the dashboard grows.
 */

export const DASHBOARD_CARDS = [
  { key: 'watchlist', label: 'Watchlist' },
  { key: 'screener', label: 'Value Screener' },
  { key: 'buffett', label: 'Buffett Scorecard' },
] as const

export type CardKey = typeof DASHBOARD_CARDS[number]['key']

interface DashboardSidebarProps {
  open: boolean
  onClose: () => void
  visibleCards: Record<CardKey, boolean>
  onToggle: (key: CardKey) => void
}

export function DashboardSidebar({ open, onClose, visibleCards, onToggle }: DashboardSidebarProps) {
  return (
    <>
      {/* Backdrop — click outside to close */}
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/20"
          onClick={onClose}
        />
      )}

      {/* Slide-in panel */}
      <div
        className={`fixed top-0 left-0 z-50 h-full w-56 bg-[var(--card)] border-r border-[var(--border)] shadow-2xl
          transform transition-transform duration-200 ease-in-out
          ${open ? 'translate-x-0' : '-translate-x-full'}`}
      >
        <div className="flex items-center justify-between px-4 py-4 border-b border-[var(--border)]">
          <span className="font-semibold text-sm">Dashboard Layout</span>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-[var(--muted)] text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
            title="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-4 py-4">
          <p className="text-xs text-[var(--muted-foreground)] mb-3">Show / hide cards</p>
          <div className="space-y-1">
            {DASHBOARD_CARDS.map(({ key, label }) => (
              <button
                key={key}
                onClick={() => onToggle(key)}
                className="w-full flex items-center justify-between py-2 px-2 rounded hover:bg-[var(--muted)] transition-colors"
              >
                <span className={`text-sm ${visibleCards[key] ? 'text-[var(--foreground)]' : 'text-[var(--muted-foreground)]'}`}>
                  {label}
                </span>
                {/* Toggle pill */}
                <div className={`relative flex-shrink-0 w-9 h-5 rounded-full transition-colors ${visibleCards[key] ? 'bg-[var(--accent)]' : 'bg-[var(--muted)]'}`}>
                  <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform duration-150 ${visibleCards[key] ? 'translate-x-4' : 'translate-x-0.5'}`} />
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}