import { useEffect, useState } from 'react'

/** Smooth the audio-clock samples locally. Settings and usePlayer stay at WS cadence. */
export function usePlaybackPosition(position: number, advancing: boolean) {
  const [sample, setSample] = useState({ position, display: position })
  useEffect(() => {
    const anchor = performance.now()
    setSample({ position, display: position })
    if (!advancing) return
    const timer = window.setInterval(() => {
      const elapsed = Math.min(.2, Math.max(0, (performance.now() - anchor) / 1000))
      setSample({ position, display: position + elapsed })
    }, 50)
    return () => window.clearInterval(timer)
  }, [position, advancing])
  // A seek, pause or new server sample takes effect in the same render.
  return sample.position === position && advancing ? sample.display : position
}
