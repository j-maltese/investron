import { AlertCircle, RefreshCw } from 'lucide-react'

interface DataErrorProps {
  message?: string
  onRetry?: () => void
  /** Inline single-line banner (true) vs full centered card (false/default) */
  compact?: boolean
}

/**
 * Reusable error state with optional retry button.
 * Matches the red error style used in AIAnalysisTab (bg-red-500/10).
 */
export function DataError({ message, onRetry, compact }: DataErrorProps) {
  if (compact) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 text-xs">
        <AlertCircle size={14} className="text-red-400 shrink-0" />
        <span className="text-red-300">{message || 'Failed to load data'}</span>
        {onRetry && (
          <button
            onClick={onRetry}
            className="ml-auto flex items-center gap-1 px-2.5 py-1 rounded bg-red-500/20 text-red-300 hover:bg-red-500/30 transition-colors font-medium"
          >
            <RefreshCw size={12} />
            Retry
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="card flex flex-col items-center justify-center py-8 space-y-3">
      <AlertCircle size={24} className="text-red-400" />
      <p className="text-sm text-red-300">{message || 'Failed to load data'}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium bg-red-500/20 text-red-300 hover:bg-red-500/30 transition-colors"
        >
          <RefreshCw size={14} />
          Retry
        </button>
      )}
    </div>
  )
}
