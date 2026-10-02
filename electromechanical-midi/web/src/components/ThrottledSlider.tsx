/** Suwak sprzetowy: lokalny podglad + dlawiona wysylka + finalna wartosc. */

import { useEffect, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'

import { useThrottled } from '../useThrottled'

interface Props {
  label: string
  min: number
  max: number
  value: number
  disabled?: boolean
  format: (value: number) => string
  onCommit: (value: number) => void
}

export function ThrottledSlider({
  label,
  min,
  max,
  value,
  disabled = false,
  format,
  onCommit,
}: Props) {
  const [local, setLocal] = useState(value)
  const localRef = useRef(value)
  const draggingRef = useRef(false)

  const push = useThrottled(onCommit, 80)

  // Backend jest zrodlem prawdy, ale nie szarpie suwakiem w trakcie ruchu.
  useEffect(() => {
    if (draggingRef.current) return

    setLocal(value)
    localRef.current = value
  }, [value])

  const handleChange = (next: number) => {
    localRef.current = next
    setLocal(next)
    push(next)
  }

  const flush = () => {
    draggingRef.current = false
    push(localRef.current, true)
  }

  const handlePointerDown = (_event: ReactPointerEvent<HTMLInputElement>) => {
    draggingRef.current = true
  }

  const percent = max > min ? ((local - min) / (max - min)) * 100 : 0

  return (
    <label className={`slider${disabled ? ' disabled' : ''}`}>
      <span className="slider-head">
        <span className="slider-label">{label}</span>
        <span className="slider-value">{format(local)}</span>
      </span>

      <input
        type="range"
        min={min}
        max={max}
        value={local}
        disabled={disabled}
        aria-label={label}
        onChange={(event) => handleChange(Number(event.target.value))}
        onPointerDown={handlePointerDown}
        onPointerUp={flush}
        onPointerCancel={flush}
        onKeyUp={flush}
        onBlur={flush}
        style={{ ['--fill' as string]: `${percent}%` }}
      />
    </label>
  )
}
