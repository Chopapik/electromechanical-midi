/**
 * Progress bar z lokalna interpolacja pozycji.
 *
 * Zasady (wazne dla braku spamu po Serial):
 *  - backend przysyla pozycje ~7 razy na sekunde,
 *  - tutaj playhead jest interpolowany przez requestAnimationFrame,
 *  - podczas przeciagania NIE wysylamy niczego,
 *  - dopiero puszczenie (albo strzalka) wysyla JEDEN seek.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from 'react'

import { formatTime } from '../format'

interface Props {
  position: number
  duration: number
  playing: boolean
  loading?: boolean
  onSeek: (position: number) => void
}

export function ProgressBar({ position, duration, playing, loading=false, onSeek }: Props) {
  const barRef = useRef<HTMLDivElement | null>(null)
  const anchorRef = useRef({ position: 0, at: performance.now() })

  const [display, setDisplay] = useState(position)
  const [dragValue, setDragValue] = useState<number | null>(null)

  // Kazda wiadomosc z backendu ustawia nowa kotwice (backend = zrodlo prawdy).
  useEffect(() => {
    anchorRef.current = { position, at: performance.now() }
    setDisplay(position)
  }, [position, playing, loading])

  useEffect(()=>{if(loading)setDragValue(null)},[loading])

  // Plynne dokladanie czasu miedzy wiadomosciami.
  useEffect(() => {
    if (loading || !playing || dragValue !== null) return

    let frame = 0

    const tick = () => {
      setDisplay(anchorRef.current.position + Math.min(.2, Math.max(0, (performance.now() - anchorRef.current.at) / 1000)))
      frame = requestAnimationFrame(tick)
    }

    frame = requestAnimationFrame(tick)

    return () => cancelAnimationFrame(frame)
  }, [playing, position, dragValue, loading])

  const valueFromClientX = useCallback(
    (clientX: number): number => {
      const element = barRef.current

      if (!element || duration <= 0) return 0

      const rect = element.getBoundingClientRect()
      const ratio = rect.width > 0 ? (clientX - rect.left) / rect.width : 0

      return Math.min(duration, Math.max(0, ratio * duration))
    },
    [duration],
  )

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (loading || duration <= 0) return

    event.currentTarget.setPointerCapture(event.pointerId)
    setDragValue(valueFromClientX(event.clientX))
  }

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (loading || dragValue === null) return

    setDragValue(valueFromClientX(event.clientX))
  }

  const commit = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (loading || dragValue === null) return

    const target = valueFromClientX(event.clientX)
    setDragValue(null)
    onSeek(target)
  }

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (loading || duration <= 0) return

    const step = event.shiftKey ? 30 : 5
    const current = dragValue ?? display

    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      onSeek(Math.max(0, current - step))
    } else if (event.key === 'ArrowRight') {
      event.preventDefault()
      onSeek(Math.min(duration, current + step))
    } else if (event.key === 'Home') {
      event.preventDefault()
      onSeek(0)
    } else if (event.key === 'End') {
      event.preventDefault()
      onSeek(duration)
    }
  }

  const shown = dragValue ?? display
  const ratio = duration > 0 ? Math.min(1, Math.max(0, shown / duration)) : 0

  return (
    <div className={`progress${loading?' is-loading':''}`} aria-busy={loading}>
      <span className="time" aria-hidden={loading}>{!loading&&<>{formatTime(shown)}.{Math.floor(Math.max(0, shown) * 10) % 10}</>}</span>

      <div
        ref={barRef}
        className={`progress-track${dragValue !== null ? ' dragging' : ''}`}
        role={loading?'progressbar':'slider'}
        tabIndex={loading?-1:0}
        aria-label={loading?'Ładowanie MIDI':'Pozycja utworu'}
        aria-valuemin={loading?undefined:0}
        aria-valuemax={loading?undefined:Math.round(duration)}
        aria-valuenow={loading?undefined:Math.round(shown)}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={commit}
        onPointerCancel={commit}
        onKeyDown={handleKeyDown}
      >
        <div className="progress-fill" style={loading?undefined:{ width: `${ratio * 100}%` }} />
        {!loading&&<div className="progress-thumb" style={{ left: `${ratio * 100}%` }} />}
      </div>

      <span className="time" aria-hidden={loading}>{!loading&&<>{formatTime(duration)}.{Math.floor(duration * 10) % 10}</>}</span>
    </div>
  )
}
