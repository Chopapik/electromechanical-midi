/**
 * Progress bar z lokalna interpolacja pozycji.
 *
 * Zasady (wazne dla braku spamu po Serial):
 *  - backend przysyla pozycje ~7 razy na sekunde,
 *  - tutaj playhead jest interpolowany przez requestAnimationFrame,
 *  - podczas przeciagania NIE wysylamy niczego,
 *  - dopiero puszczenie (albo strzalka) wysyla JEDEN seek.
 */

import { useCallback, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from 'react'

import { usePlaybackClock } from '../usePlaybackClock'
import { formatTime } from '../format'

interface Props {
  position: number
  duration: number
  playing: boolean
  onSeek: (position: number) => void
}

export function ProgressBar({ position, duration, playing, onSeek }: Props) {
  const barRef = useRef<HTMLDivElement | null>(null)
  const display = usePlaybackClock(position, playing, duration)
  const [dragValue, setDragValue] = useState<number | null>(null)

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
    if (duration <= 0) return

    event.currentTarget.setPointerCapture(event.pointerId)
    setDragValue(valueFromClientX(event.clientX))
  }

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (dragValue === null) return

    setDragValue(valueFromClientX(event.clientX))
  }

  const commit = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (dragValue === null) return

    const target = valueFromClientX(event.clientX)
    setDragValue(null)
    onSeek(target)
  }

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (duration <= 0) return

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
    <div className="progress">
      <span className="time">{formatTime(shown)}</span>

      <div
        ref={barRef}
        className={`progress-track${dragValue !== null ? ' dragging' : ''}`}
        role="slider"
        tabIndex={0}
        aria-label="Pozycja utworu"
        aria-valuemin={0}
        aria-valuemax={Math.round(duration)}
        aria-valuenow={Math.round(shown)}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={commit}
        onPointerCancel={commit}
        onKeyDown={handleKeyDown}
      >
        <div className="progress-fill" style={{ width: `${ratio * 100}%` }} />
        <div className="progress-thumb" style={{ left: `${ratio * 100}%` }} />
      </div>

      <span className="time">{formatTime(duration)}</span>
    </div>
  )
}
