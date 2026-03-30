import { useState, useCallback, useRef } from 'react'

/**
 * useResizable — drag-to-resize hook for dashboard cards.
 *
 * Returns a height (px) and a mousedown handler to attach to a drag handle element.
 * Height is persisted to localStorage by storageKey so it survives page reloads.
 *
 * Uses a ref to read the latest height inside the drag handler so the callback
 * stays stable (no deps on height itself) — avoids recreating on every pixel dragged.
 */
export function useResizable(storageKey: string, defaultHeight: number) {
  const [height, setHeight] = useState<number>(() => {
    const saved = localStorage.getItem(`resizable-${storageKey}`)
    return saved ? Math.max(200, parseInt(saved, 10)) : defaultHeight
  })

  // Ref so the mousedown closure always reads the latest height without being a dep
  const heightRef = useRef(height)
  heightRef.current = height

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    const startY = e.clientY
    const startH = heightRef.current

    const onMove = (ev: MouseEvent) => {
      const newH = Math.max(200, startH + ev.clientY - startY)
      setHeight(newH)
    }

    const onUp = () => {
      // Functional update reads latest height — avoids stale closure on persist
      setHeight(h => {
        localStorage.setItem(`resizable-${storageKey}`, String(h))
        return h
      })
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }

    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [storageKey])

  return { height, handleMouseDown }
}