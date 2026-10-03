/**
 * Testy progress bara - najwazniejsze jest to, ze podczas przeciagania
 * NIC nie leci do backendu, a po puszczeniu leci dokladnie JEDEN seek.
 */

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ProgressBar } from './ProgressBar'

const DURATION = 100

function setup(position = 0, playing = false) {
  const onSeek = vi.fn()

  render(
    <ProgressBar position={position} duration={DURATION} playing={playing} onSeek={onSeek} />,
  )

  const track = screen.getByRole('slider')

  // jsdom nie liczy ukladu - ustawiamy geometrie pasa recznie.
  track.getBoundingClientRect = () =>
    ({ left: 0, top: 0, width: 200, height: 10, right: 200, bottom: 10, x: 0, y: 0 }) as DOMRect

  // jsdom nie implementuje pointer capture.
  track.setPointerCapture = () => {}
  track.releasePointerCapture = () => {}
  ;(track as HTMLElement).hasPointerCapture = () => false

  return { onSeek, track }
}

describe('ProgressBar', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
  })

  it('klikniecie w pasek wysyla jeden seek', () => {
    const { onSeek, track } = setup()

    fireEvent.pointerDown(track, { clientX: 50, pointerId: 1 })
    fireEvent.pointerUp(track, { clientX: 50, pointerId: 1 })

    expect(onSeek).toHaveBeenCalledTimes(1)
    expect(onSeek.mock.calls[0][0]).toBeCloseTo(25, 5)
  })

  it('przeciaganie wysyla tylko JEDEN seek - po puszczeniu', () => {
    const { onSeek, track } = setup()

    fireEvent.pointerDown(track, { clientX: 20, pointerId: 1 })

    // Symulujemy dlugie przeciaganie suwaka.
    for (const x of [40, 60, 80, 100, 120, 140]) {
      fireEvent.pointerMove(track, { clientX: x, pointerId: 1 })
      expect(onSeek).not.toHaveBeenCalled()
    }

    fireEvent.pointerUp(track, { clientX: 140, pointerId: 1 })

    expect(onSeek).toHaveBeenCalledTimes(1)
    expect(onSeek.mock.calls[0][0]).toBeCloseTo(70, 5)
  })

  it('seek jest klamrowany do dlugosci utworu', () => {
    const { onSeek, track } = setup()

    fireEvent.pointerDown(track, { clientX: 999, pointerId: 1 })
    fireEvent.pointerUp(track, { clientX: 999, pointerId: 1 })

    expect(onSeek.mock.calls[0][0]).toBeCloseTo(DURATION, 5)
  })

  it('strzalka w prawo przesuwa o 5 s', () => {
    const { onSeek, track } = setup(40)

    fireEvent.keyDown(track, { key: 'ArrowRight' })

    expect(onSeek).toHaveBeenCalledTimes(1)
    expect(onSeek.mock.calls[0][0]).toBeCloseTo(45, 5)
  })

  it('strzalka w lewo nie schodzi ponizej zera', () => {
    const { onSeek, track } = setup(2)

    fireEvent.keyDown(track, { key: 'ArrowLeft' })

    expect(onSeek.mock.calls[0][0]).toBe(0)
  })

  it('Home i End dzialaja', () => {
    const { onSeek, track } = setup(30)

    fireEvent.keyDown(track, { key: 'Home' })
    fireEvent.keyDown(track, { key: 'End' })

    expect(onSeek).toHaveBeenNthCalledWith(1, 0)
    expect(onSeek).toHaveBeenNthCalledWith(2, DURATION)
  })

  it('bez utworu (duration 0) nic nie wysyla', () => {
    const onSeek = vi.fn()

    render(<ProgressBar position={0} duration={0} playing={false} onSeek={onSeek} />)

    const track = screen.getByRole('slider')

    fireEvent.pointerDown(track, { clientX: 50, pointerId: 1 })
    fireEvent.pointerUp(track, { clientX: 50, pointerId: 1 })

    expect(onSeek).not.toHaveBeenCalled()
  })
})
