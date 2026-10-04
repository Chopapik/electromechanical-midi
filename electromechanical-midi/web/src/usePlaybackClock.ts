import { useEffect, useRef, useState } from 'react'

/** The transport's interpolation: every backend update replaces the anchor. */
export function usePlaybackClock(position: number, playing: boolean, duration = Infinity) {
  const anchor = useRef({ position, at: performance.now() })
  const [display, setDisplay] = useState(position)
  useEffect(() => {
    anchor.current = { position, at: performance.now() }
    setDisplay(position)
    if (!playing) return
    let frame = 0
    const tick = () => {
      setDisplay(Math.min(duration, anchor.current.position + (performance.now() - anchor.current.at) / 1000))
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [position, playing, duration])
  return display
}
