import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search } from 'lucide-react'
import { useCompanySearch } from '@/hooks/useCompany'

export function CompanySearch() {
  const [query, setQuery] = useState('')
  const [isOpen, setIsOpen] = useState(false)
  const { data, isLoading } = useCompanySearch(query)
  const navigate = useNavigate()
  const wrapperRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleSelect = (ticker: string) => {
    setQuery('')
    setIsOpen(false)
    navigate(`/research/${ticker}`)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && query.trim()) {
      handleSelect(query.trim().toUpperCase())
    }
  }

  return (
    <div ref={wrapperRef} className="relative">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--muted-foreground)]" />
        <input
          type="text"
          value={query}
          onChange={(e) => { setQuery(e.target.value); setIsOpen(true) }}
          onFocus={() => setIsOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder="Search ticker or company..."
          className="input w-full pl-9 py-1.5 text-sm"
        />
      </div>

      {isOpen && query.length >= 1 && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-[var(--card)] border border-[var(--border)] rounded-lg shadow-lg z-50 overflow-hidden">
          {isLoading && (
            <div className="px-4 py-3 text-sm text-[var(--muted-foreground)]">Searching...</div>
          )}
          {data?.results?.map((result) => (
            <button
              key={result.ticker}
              onClick={() => handleSelect(result.ticker)}
              className="w-full px-4 py-2.5 text-left hover:bg-[var(--muted)] transition-colors flex items-center justify-between"
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
          {data?.results?.length === 0 && !isLoading && (
            <div className="px-4 py-3 text-sm text-[var(--muted-foreground)]">
              No results. Press Enter to search for "{query.toUpperCase()}"
            </div>
          )}
        </div>
      )}
    </div>
  )
}
