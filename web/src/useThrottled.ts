/** Throttling dla suwakow sterujacych sprzetem.
 *
 * Zasada: podczas przeciagania wysylamy najwyzej jedno zdarzenie na
 * `intervalMs` (plus jeden "ogon" po ustaleniu), a po puszczeniu ZAWSZE
 * leci wartosc finalna. Dzieki temu suwak nie spamuje Serial, ale ostatnia
 * pozycja nigdy nie ginie.
 */

import { useCallback, useEffect, useRef } from 'react'

export type Push = (value: number, immediate?: boolean) => void

export function useThrottled(
  commit: (value: number) => void,
  intervalMs = 80,
): Push {
  const lastRef = useRef(0)
  const timerRef = useRef<number | null>(null)
  const pendingRef = useRef<number | null>(null)

  // Zawsze wolamy najswieższy callback, bez przestawiania throttlera.
  const commitRef = useRef(commit)
  commitRef.current = commit

  const cancelTimer = () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  useEffect(() => cancelTimer, [])

  return useCallback(
    (value: number, immediate = false) => {
      const now = performance.now()
      const elapsed = now - lastRef.current

      if (immediate || elapsed >= intervalMs) {
        cancelTimer()
        pendingRef.current = null
        lastRef.current = now
        commitRef.current(value)
        return
      }

      // Za wczesnie - zapamietaj i doslij po cichu po uplywie okna.
      pendingRef.current = value

      if (timerRef.current === null) {
        timerRef.current = window.setTimeout(() => {
          timerRef.current = null

          const pending = pendingRef.current
          pendingRef.current = null

          if (pending !== null) {
            lastRef.current = performance.now()
            commitRef.current(pending)
          }
        }, intervalMs - elapsed)
      }
    },
    [intervalMs],
  )
}
