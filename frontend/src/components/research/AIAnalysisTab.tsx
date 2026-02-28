/**
 * AI Research Assistant — chat interface for the Research page.
 *
 * Renders a full-height chat with streaming markdown responses from GPT-4o.
 * The backend injects all available structured data (metrics, Graham score,
 * growth metrics, financials, screener data) into the system prompt so the
 * AI reasons with real numbers.
 */

import { useState, useEffect, useRef, type KeyboardEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useAIChat } from '@/hooks/useAIChat'
import { useFilingIndex } from '@/hooks/useFilingIndex'
import { Send, Square, Trash2, Sparkles, AlertCircle, Search, FileText, RefreshCw, Loader2 } from 'lucide-react'

interface AIAnalysisTabProps {
  ticker: string
}

const BASE_SUGGESTIONS = [
  'What valuation framework fits this company?',
  'Run a Bull / Base / Bear scenario analysis',
  'What are the key risks and catalysts?',
  'Walk me through a DCF analysis',
]

const FILING_SUGGESTIONS = [
  'What risk factors does the 10-K mention?',
  'Summarize the MD&A section',
  'Any recent acquisitions or material events?',
  'What does management say about competitive landscape?',
]

function MessageBubble({ role, content, isStreaming, statusMessage }: {
  role: 'user' | 'assistant'
  content: string
  isStreaming?: boolean
  statusMessage?: string
}) {
  if (role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-lg px-4 py-2 bg-[var(--accent)]/10 text-sm">
          {content}
        </div>
      </div>
    )
  }

  return (
    <div className="flex justify-start">
      <div className="max-w-[90%] text-sm prose-sm">
        {/* Tool-call status indicator */}
        {statusMessage && (
          <div className="flex items-center gap-2 mb-2 text-xs text-[var(--accent)]">
            <Search size={12} className="animate-pulse" />
            <span>{statusMessage}</span>
          </div>
        )}
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            // Style markdown elements to match the app theme
            h1: ({ children }) => <h3 className="text-lg font-bold mt-4 mb-2 text-[var(--foreground)]">{children}</h3>,
            h2: ({ children }) => <h4 className="text-base font-semibold mt-3 mb-1.5 text-[var(--foreground)]">{children}</h4>,
            h3: ({ children }) => <h5 className="text-sm font-semibold mt-2 mb-1 text-[var(--foreground)]">{children}</h5>,
            p: ({ children }) => <p className="mb-2 text-[var(--foreground)] leading-relaxed">{children}</p>,
            strong: ({ children }) => <strong className="font-semibold text-[var(--foreground)]">{children}</strong>,
            ul: ({ children }) => <ul className="list-disc pl-5 mb-2 space-y-0.5 text-[var(--foreground)]">{children}</ul>,
            ol: ({ children }) => <ol className="list-decimal pl-5 mb-2 space-y-0.5 text-[var(--foreground)]">{children}</ol>,
            li: ({ children }) => <li className="text-[var(--foreground)]">{children}</li>,
            blockquote: ({ children }) => (
              <blockquote className="border-l-2 border-[var(--accent)] pl-3 my-2 text-[var(--muted-foreground)] italic">
                {children}
              </blockquote>
            ),
            table: ({ children }) => (
              <div className="overflow-x-auto my-2">
                <table className="min-w-full text-xs border border-[var(--border)]">{children}</table>
              </div>
            ),
            thead: ({ children }) => <thead className="bg-[var(--muted)]">{children}</thead>,
            th: ({ children }) => <th className="px-2 py-1 text-left font-medium text-[var(--foreground)] border-b border-[var(--border)]">{children}</th>,
            td: ({ children }) => <td className="px-2 py-1 text-[var(--foreground)] border-b border-[var(--border)]">{children}</td>,
            code: ({ className, children }) => {
              const isInline = !className
              if (isInline) {
                return <code className="bg-[var(--muted)] px-1 py-0.5 rounded text-xs font-mono">{children}</code>
              }
              return (
                <pre className="bg-[var(--muted)] p-3 rounded text-xs font-mono overflow-x-auto my-2">
                  <code>{children}</code>
                </pre>
              )
            },
            hr: () => <hr className="my-3 border-[var(--border)]" />,
            em: ({ children }) => <em className="text-[var(--muted-foreground)]">{children}</em>,
          }}
        >
          {content}
        </ReactMarkdown>
        {isStreaming && !statusMessage && (
          <span className="inline-block w-2 h-4 bg-[var(--accent)] animate-pulse rounded-sm ml-0.5" />
        )}
      </div>
    </div>
  )
}

function FilingIndexBanner({ ticker }: { ticker: string }) {
  const { status, indexStatus, isIndexing, isReady, triggerIndexing, deleteIndex } = useFilingIndex(ticker)

  if (status === 'not_indexed') {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-blue-500/10 text-xs">
        <FileText size={14} className="text-blue-400 shrink-0" />
        <span className="text-blue-300">
          SEC filings not indexed for deep search.
        </span>
        <button
          onClick={triggerIndexing}
          className="ml-auto px-2.5 py-1 rounded bg-blue-500/20 text-blue-300 hover:bg-blue-500/30 transition-colors font-medium"
        >
          Index Filings
        </button>
      </div>
    )
  }

  if (isIndexing) {
    const progress = indexStatus?.progress_message
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[var(--accent)]/10 text-xs">
        <Loader2 size={14} className="text-[var(--accent)] animate-spin shrink-0" />
        <div className="flex flex-col gap-0.5 min-w-0">
          <span className="text-[var(--accent)] font-medium">
            Indexing {ticker.toUpperCase()} filings...
            {indexStatus && indexStatus.filings_indexed > 0 && (
              <span className="font-normal opacity-80">
                {' '}({indexStatus.filings_indexed} indexed, {indexStatus.chunks_total} chunks)
              </span>
            )}
          </span>
          {progress && (
            <span
              key={progress}
              className="text-[var(--accent)]/70 truncate animate-[fadeSlideIn_0.3s_ease-out]"
            >
              {progress}
            </span>
          )}
        </div>
      </div>
    )
  }

  if (isReady && indexStatus) {
    // Build a human-readable breakdown like "3 10-K, 5 10-Q, 7 8-K"
    const breakdown = indexStatus.filing_type_breakdown
    const breakdownText = breakdown
      ? Object.entries(breakdown).map(([type, count]) => `${count} ${type}`).join(', ')
      : `${indexStatus.filings_indexed} filings`

    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-500/10 text-xs">
        <FileText size={14} className="text-emerald-400 shrink-0" />
        <span className="text-emerald-300">
          Filing search active — {breakdownText}, {indexStatus.chunks_total} chunks indexed
        </span>
        <button
          onClick={triggerIndexing}
          className="ml-auto p-1 rounded hover:bg-emerald-500/20 text-emerald-400 transition-colors"
          title="Re-index filings"
        >
          <RefreshCw size={12} />
        </button>
        <button
          onClick={deleteIndex}
          className="p-1 rounded hover:bg-red-500/20 text-[var(--muted-foreground)] hover:text-red-400 transition-colors"
          title="Remove index"
        >
          <Trash2 size={12} />
        </button>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 text-xs">
        <AlertCircle size={14} className="text-red-400 shrink-0" />
        <span className="text-red-300">
          Indexing failed{indexStatus?.error_message ? `: ${indexStatus.error_message}` : ''}
        </span>
        <button
          onClick={triggerIndexing}
          className="ml-auto px-2.5 py-1 rounded bg-red-500/20 text-red-300 hover:bg-red-500/30 transition-colors font-medium"
        >
          Retry
        </button>
      </div>
    )
  }

  return null
}

export function AIAnalysisTab({ ticker }: AIAnalysisTabProps) {
  const { messages, isStreaming, error, sendMessage, stopStreaming, clearChat } = useAIChat(ticker)
  const { isReady: filingsReady } = useFilingIndex(ticker)
  const [input, setInput] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const suggestions = filingsReady ? [...FILING_SUGGESTIONS, ...BASE_SUGGESTIONS].slice(0, 4) : BASE_SUGGESTIONS

  // Auto-scroll on new content
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 120) + 'px'
  }, [input])

  const handleSubmit = () => {
    if (input.trim() && !isStreaming) {
      sendMessage(input)
      setInput('')
    }
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className="card flex flex-col" style={{ height: 'calc(100vh - 280px)', minHeight: '400px' }}>
      {/* Header */}
      <div className="flex items-center justify-between pb-3 border-b border-[var(--border)]">
        <div className="flex items-center gap-2">
          <Sparkles size={18} className="text-[var(--accent)]" />
          <div>
            <h3 className="font-semibold text-sm">AI Research Assistant</h3>
            <p className="text-xs text-[var(--muted-foreground)]">
              Analyzing {ticker.toUpperCase()} with live financial data
            </p>
          </div>
        </div>
        {messages.length > 0 && (
          <button
            onClick={clearChat}
            className="p-1.5 rounded hover:bg-[var(--muted)] text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
            title="Clear conversation"
          >
            <Trash2 size={16} />
          </button>
        )}
      </div>

      {/* Filing index status banner */}
      <div className="pt-3">
        <FilingIndexBanner ticker={ticker} />
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto py-4 space-y-4">
        {messages.length === 0 ? (
          /* Empty state with suggestions */
          <div className="flex flex-col items-center justify-center h-full text-center px-4">
            <Sparkles size={32} className="text-[var(--muted-foreground)] mb-3" />
            <p className="text-sm text-[var(--muted-foreground)] mb-4">
              Ask about {ticker.toUpperCase()}'s fundamentals, valuation, risks, or run scenario analyses.
            </p>
            <div className="flex flex-wrap gap-2 justify-center">
              {suggestions.map(suggestion => (
                <button
                  key={suggestion}
                  onClick={() => sendMessage(suggestion)}
                  className="text-xs px-3 py-1.5 rounded-full border border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:border-[var(--accent)] transition-colors"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map(msg => (
            <MessageBubble
              key={msg.id}
              role={msg.role}
              content={msg.content}
              isStreaming={msg.isStreaming}
              statusMessage={msg.statusMessage}
            />
          ))
        )}

        {error && (
          <div className="flex items-center gap-2 px-3 py-2 rounded bg-red-500/10 text-red-400 text-xs">
            <AlertCircle size={14} />
            {error}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="pt-3 border-t border-[var(--border)]">
        <div className="flex gap-2 items-end">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={`Ask about ${ticker.toUpperCase()}...`}
            className="flex-1 resize-none rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--foreground)] placeholder:text-[var(--muted-foreground)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]"
            rows={1}
            disabled={isStreaming}
          />
          {isStreaming ? (
            <button
              onClick={stopStreaming}
              className="p-2 rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
              title="Stop generating"
            >
              <Square size={18} />
            </button>
          ) : (
            <button
              onClick={handleSubmit}
              disabled={!input.trim()}
              className="p-2 rounded-lg bg-[var(--accent)] text-white disabled:opacity-30 disabled:cursor-not-allowed hover:opacity-90 transition-opacity"
              title="Send message"
            >
              <Send size={18} />
            </button>
          )}
        </div>
        <p className="text-[10px] text-[var(--muted-foreground)] mt-1.5 text-center">
          For research purposes only — not investment advice. Shift+Enter for new line.
        </p>
      </div>
    </div>
  )
}
