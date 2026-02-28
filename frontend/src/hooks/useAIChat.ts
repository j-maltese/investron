/**
 * Custom hook for the AI Research Assistant chat.
 *
 * Manages conversation state, streams SSE responses from the backend,
 * and provides controls for sending, stopping, and clearing messages.
 *
 * On the first message, include_financials and include_growth are true
 * so the backend injects full data context. Follow-up messages send false
 * since the data is already in the LLM's conversation history via the
 * system prompt.
 */

import { useState, useCallback, useRef } from 'react'
import { api } from '@/lib/api'
import type { ChatMessage } from '@/lib/types'

function generateId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

export function useAIChat(ticker: string) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const sendMessage = useCallback(async (content: string) => {
    if (!content.trim() || isStreaming) return

    setError(null)

    const userMsg: ChatMessage = {
      id: generateId(),
      role: 'user',
      content: content.trim(),
      timestamp: Date.now(),
    }

    const assistantMsg: ChatMessage = {
      id: generateId(),
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      isStreaming: true,
    }

    setMessages(prev => [...prev, userMsg, assistantMsg])
    setIsStreaming(true)

    const abortController = new AbortController()
    abortRef.current = abortController

    try {
      // Build messages for the API (role + content only, no UI metadata)
      const apiMessages = [...messages, userMsg].map(m => ({
        role: m.role,
        content: m.content,
      }))

      // Full data context on first message only (cost optimization)
      const isFirstMessage = messages.length === 0

      const stream = api.streamAIChat(
        {
          ticker,
          messages: apiMessages,
          include_financials: isFirstMessage,
          include_growth: isFirstMessage,
        },
        abortController.signal,
      )

      let accumulated = ''
      for await (const event of stream) {
        if (event.error) {
          setError(event.error)
          break
        }
        if (event.status) {
          // Tool-call status message (e.g., "Searching filings: risk factors...")
          setMessages(prev =>
            prev.map(m =>
              m.id === assistantMsg.id ? { ...m, statusMessage: event.status } : m,
            ),
          )
        }
        if (event.token) {
          accumulated += event.token
          // Clear status message once content starts arriving
          setMessages(prev =>
            prev.map(m =>
              m.id === assistantMsg.id
                ? { ...m, content: accumulated, statusMessage: undefined }
                : m,
            ),
          )
        }
        if (event.done) break
      }

      // Mark streaming complete
      setMessages(prev =>
        prev.map(m =>
          m.id === assistantMsg.id ? { ...m, isStreaming: false } : m,
        ),
      )
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return
      const message = err instanceof Error ? err.message : 'An error occurred'
      setError(message)
      // Remove the empty assistant placeholder on error
      setMessages(prev => prev.filter(m => m.id !== assistantMsg.id))
    } finally {
      setIsStreaming(false)
      abortRef.current = null
    }
  }, [ticker, messages, isStreaming])

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort()
    setIsStreaming(false)
    // Mark any streaming message as done
    setMessages(prev =>
      prev.map(m => (m.isStreaming ? { ...m, isStreaming: false } : m)),
    )
  }, [])

  const clearChat = useCallback(() => {
    abortRef.current?.abort()
    setMessages([])
    setIsStreaming(false)
    setError(null)
  }, [])

  return { messages, isStreaming, error, sendMessage, stopStreaming, clearChat }
}
