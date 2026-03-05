/**
 * TickerAutocomplete — reusable autocomplete input for searching stocks by
 * ticker or company name. Queries the backend company search endpoint and
 * displays a dropdown of matching results.
 *
 * Used in three places:
 *   1. Header search bar (navigates to /research/{ticker})
 *   2. Watchlist add form (fills ticker for adding to watchlist)
 *   3. Value Screener search (filters screener results)
 */

import { useState, useRef, useEffect, useCallback } from 'react'
import { Search } from 'lucide-react'
import { useCompanySearch } from '@/hooks/useCompany'
import type { CompanySearchResult } from '@/lib/types'

interface TickerAutocompleteProps {
  /** Called when the user selects a result from the dropdown or presses Enter */
  onSelect: (result: CompanySearchResult) => void
  /** Placeholder text for the input */
  placeholder?: string
  /** Additional CSS classes for the input */
  inputClassName?: string
  /** Whether to show the search icon */
  showIcon?: boolean
  /** Controlled value — when set, the component becomes controlled */
  value?: string
  /** Called on every input change (for controlled mode) */
  onChange?: (value: string) => void
  /** Whether to clear the input after selection (default: true) */
  clearOnSelect?: boolean
  /** Whether Enter on empty/no-match submits the raw text as a ticker (default: false) */
  allowRawTicker?: boolean
}

export function TickerAutocomplete({
  onSelect,
  placeholder = 'Search ticker or company...',
  inputClassName = '',
  showIcon = true,
  value: controlledValue,
  onChange: controlledOnChange,
  clearOnSelect = true,
  allowRawTicker = false,
}: TickerAutocompleteProps) {
  const [internalValue, setInternalValue] = useState('')
  const [isOpen, setIsOpen] = useState(false)
  // Track which dropdown item is highlighted via keyboard
  const [highlightIndex, setHighlightIndex] = useState(-1)
  const wrapperRef = useRef<HTMLDivElement>(null)

  // Support both controlled and uncontrolled modes
  const query = controlledValue ?? internalValue
  const setQuery = useCallback((v: string) => {
    if (controlledOnChange) controlledOnChange(v)
    else setInternalValue(v)
  }, [controlledOnChange])

  const { data, isLoading } = useCompanySearch(query)
  const results = data?.results ?? []

  // Reset highlight when results change
  useEffect(() => { setHighlightIndex(-1) }, [results.length])

  // Close dropdown on click outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleSelect = (result: CompanySearchResult) => {
    onSelect(result)
    setIsOpen(false)
    if (clearOnSelect) setQuery('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlightIndex(prev => Math.min(prev + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlightIndex(prev => Math.max(prev - 1, -1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (highlightIndex >= 0 && highlightIndex < results.length) {
        // Select the highlighted dropdown item
        handleSelect(results[highlightIndex])
      } else if (results.length === 1) {
        // Single result — auto-select it
        handleSelect(results[0])
      } else if (allowRawTicker && query.trim()) {
        // Allow submitting raw text as a ticker (used in watchlist add)
        handleSelect({ ticker: query.trim().toUpperCase(), name: '' })
      }
    } else if (e.key === 'Escape') {
      setIsOpen(false)
    }
  }

  return (
    <div ref={wrapperRef} className="relative">
      <div className="relative">
        {showIcon && (
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--muted-foreground)]" />
        )}
        <input
          type="text"
          value={query}
          onChange={(e) => { setQuery(e.target.value); setIsOpen(true) }}
          onFocus={() => { if (query.length >= 1) setIsOpen(true) }}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          className={`input w-full text-sm ${showIcon ? 'pl-9' : ''} ${inputClassName}`}
        />
      </div>

      {isOpen && query.length >= 1 && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-[var(--card)] border border-[var(--border)] rounded-lg shadow-lg z-50 overflow-hidden">
          {isLoading && (
            <div className="px-4 py-3 text-sm text-[var(--muted-foreground)]">Searching...</div>
          )}
          {results.map((result, idx) => (
            <button
              key={result.ticker}
              onClick={() => handleSelect(result)}
              className={`w-full px-4 py-2.5 text-left transition-colors flex items-center justify-between ${
                idx === highlightIndex ? 'bg-[var(--muted)]' : 'hover:bg-[var(--muted)]'
              }`}
            >
              <div>
                <span className="font-semibold text-sm">{result.ticker}</span>
                <span className="text-sm text-[var(--muted-foreground)] ml-2">{result.name}</span>
              </div>
              {result.exchange && (
                <span className="text-xs text-[var(--muted-foreground)]">{result.exchange}</span>
              )}
            </button>
          ))}
          {results.length === 0 && !isLoading && (
            <div className="px-4 py-3 text-sm text-[var(--muted-foreground)]">
              {allowRawTicker
                ? `No results. Press Enter to add "${query.toUpperCase()}"`
                : `No results for "${query}"`}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
