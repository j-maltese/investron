/**
 * Hooks for the Buffett 4-Rules Intrinsic Value Calculator.
 *
 * useBuffettAnalysis — fetches the full 4-rule scorecard from GET /api/buffett/{ticker}.
 *   Data is cached 15 minutes on the server. The hook re-fetches when the
 *   ticker changes and does not auto-refresh (staleTime = cache TTL).
 *
 * useBuffettAI — manages streaming state for the on-demand Rule 2 AI analysis.
 *   The AI is NOT auto-triggered; the user must click the button.
 *
 * useBuffettValuationAI — manages the 3-phase Option B AI valuation flow:
 *   Phase 1: Check filing index status for the ticker.
 *   Phase 2: If not indexed, trigger indexing and poll until ready — shows
 *            animated progress so the user knows embedding is happening.
 *   Phase 3: Fire the /valuation-ai SSE stream and render the markdown response.
 *   Used only when Rule 4 is inapplicable (negative equity, insufficient history).
 */

import { useQuery } from '@tanstack/react-query'
import { useCallback, useRef, useState } from 'react'
import { api } from '@/lib/api'
import type { BuffettAnalysis } from '@/lib/types'

// Polling interval while filing indexing is in progress (ms)
const INDEX_POLL_INTERVAL = 3000
// Maximum time to wait for indexing before giving up (ms) — 5 minutes
const INDEX_POLL_TIMEOUT = 5 * 60 * 1000

export function useBuffettAnalysis(ticker: string | null) {
  return useQuery<BuffettAnalysis>({
    queryKey: ['buffett', ticker],
    queryFn: () => api.getBuffettAnalysis(ticker!),
    enabled: !!ticker,
    staleTime: 15 * 60 * 1000,   // 15 min — matches server-side cache TTL
    retry: 1,
  })
}

export function useBuffettAI(ticker: string | null) {
  const [content, setContent] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const trigger = useCallback(async () => {
    if (!ticker || isStreaming) return

    // Reset on each trigger (allows re-running)
    setContent('')
    setError(null)
    setIsStreaming(true)

    const ctrl = new AbortController()
    abortRef.current = ctrl

    try {
      for await (const event of api.streamBuffettAI(ticker, ctrl.signal)) {
        if (event.error) {
          setError(event.error)
          break
        }
        if (event.token) {
          setContent(prev => prev + event.token)
        }
        if (event.done) break
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return
      setError(err instanceof Error ? err.message : 'Streaming failed')
    } finally {
      setIsStreaming(false)
      abortRef.current = null
    }
  }, [ticker, isStreaming])

  const stop = useCallback(() => {
    abortRef.current?.abort()
    setIsStreaming(false)
  }, [])

  const reset = useCallback(() => {
    abortRef.current?.abort()
    setContent('')
    setError(null)
    setIsStreaming(false)
  }, [])

  return { content, isStreaming, error, trigger, stop, reset }
}

export function useBuffettValuationAI(ticker: string | null) {
  const [content, setContent] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  // statusMessage covers both the indexing phase ("Indexing SEC filings...")
  // and the pre-stream data-gather phase ("Gathering financial data and news...").
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  // Tracks whether indexing was triggered by this hook (so we can show the right message)
  const indexTriggeredRef = useRef(false)

  const trigger = useCallback(async () => {
    if (!ticker || isStreaming) return

    setContent('')
    setError(null)
    setStatusMessage(null)
    setIsStreaming(true)
    indexTriggeredRef.current = false

    const ctrl = new AbortController()
    abortRef.current = ctrl

    try {
      // ── Phase 1: Check filing index status ──────────────────────────────
      const status = await api.getFilingIndexStatus(ticker)

      if (status.status !== 'ready') {
        // ── Phase 2: Trigger indexing and poll until ready ─────────────────
        // Indexing is triggered once; polling handles the progress display.
        indexTriggeredRef.current = true
        setStatusMessage(`Indexing SEC filings for ${ticker} — this may take a minute...`)

        if (status.status !== 'indexing' && status.status !== 'pending') {
          // Not already in-flight — trigger it
          await api.triggerFilingIndex(ticker)
        }

        // Poll until ready or timeout
        const deadline = Date.now() + INDEX_POLL_TIMEOUT
        while (true) {
          if (ctrl.signal.aborted) return

          await new Promise(resolve => setTimeout(resolve, INDEX_POLL_INTERVAL))

          if (ctrl.signal.aborted) return

          const poll = await api.getFilingIndexStatus(ticker)

          if (poll.status === 'ready') {
            setStatusMessage('Filing index ready — gathering data and news...')
            break
          }

          if (poll.status === 'error') {
            // Indexing failed — proceed anyway, the backend will note the gap
            setStatusMessage('Filing index unavailable — proceeding with available data...')
            break
          }

          if (Date.now() > deadline) {
            setStatusMessage('Filing index timed out — proceeding with available data...')
            break
          }

          // Show live progress from the indexer if available
          const progress = poll.progress_message
            || `Indexing ${ticker} filings (${poll.filings_indexed} processed)...`
          setStatusMessage(progress)
        }
      }

      // ── Phase 3: Stream the valuation AI response ────────────────────────
      if (!indexTriggeredRef.current) {
        // Already indexed — show a brief status before the stream starts
        setStatusMessage('Gathering financial data, news, and filing context...')
      }

      for await (const event of api.streamBuffettValuationAI(ticker, ctrl.signal)) {
        if (event.error) {
          setError(event.error)
          break
        }
        if (event.status) {
          // Backend status event (e.g. "Gathering financial data...")
          setStatusMessage(event.status)
        }
        if (event.token) {
          setStatusMessage(null)  // clear status once tokens start flowing
          setContent(prev => prev + event.token)
        }
        if (event.done) break
      }

    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return
      setError(err instanceof Error ? err.message : 'Analysis failed')
    } finally {
      setIsStreaming(false)
      abortRef.current = null
    }
  }, [ticker, isStreaming])

  const stop = useCallback(() => {
    abortRef.current?.abort()
    setIsStreaming(false)
  }, [])

  const reset = useCallback(() => {
    abortRef.current?.abort()
    setContent('')
    setError(null)
    setStatusMessage(null)
    setIsStreaming(false)
  }, [])

  return { content, isStreaming, statusMessage, error, trigger, stop, reset }
}