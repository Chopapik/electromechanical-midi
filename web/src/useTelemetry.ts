import { useEffect, useState } from 'react'
import type { TelemetryView } from './types'

export function useTelemetry(file: string | null, revision: number, tonalMode?: string, hddMode?: string, audioRevision = 0) {
  const [result, setResult] = useState<{ key: string; view: TelemetryView | null; error: string | null } | null>(null)
  const key = JSON.stringify([file, revision, tonalMode, hddMode, audioRevision])
  useEffect(() => {
    if (!file) return
    const controller = new AbortController()
    let retry: ReturnType<typeof setTimeout> | undefined
    const read = async (attempt = 0) => {
      try {
        const response = await fetch('/api/telemetry', { signal: controller.signal, cache: 'no-store' })
        if (!response.ok) throw new Error('Telemetry unavailable')
        const view: TelemetryView = await response.json()
        if (controller.signal.aborted) return
        if (Array.isArray(view.events) && view.file === file && view.revision === revision &&
            (view.audioRevision === undefined || view.audioRevision === audioRevision)) {
          setResult({ key, view, error: null })
        } else if (attempt < 3) {
          // The render can finish between the WebSocket snapshot and this response.
          retry = setTimeout(() => void read(attempt + 1), 250)
        } else {
          setResult({ key, view: null, error: 'Telemetry unavailable' })
        }
      } catch {
        if (!controller.signal.aborted) setResult({ key, view: null, error: 'Telemetry unavailable' })
      }
    }
    void read()
    return () => { controller.abort(); clearTimeout(retry) }

  }, [file, revision, key])
  return result?.key === key ? result : { view: null, error: null }
}
