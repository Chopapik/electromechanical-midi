/** Testy panelu VHS Drum: Start/Stop, suwaki, throttle, status. */

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DrumPanel } from './DrumPanel'
import type { DrumState } from '../types'

const DRUM: DrumState = {
  value: 0,
  output: 0,
  toneHz: 0,
  lastValue: 64,
  running: false,
  connected: true,
  minHz: 20,
  maxHz: 2000,
  controlledBy: 'manual',
  drive: 74,
  range: { minHz: 110, maxHz: 880 },
  transpose: 'auto',
  strategy: 'highest',
  midiTrack: null,
  midiTrackName: null,
  midiNote: null,
  midiNoteName: null,
  midiFrequency: null,
}

function setup(overrides: Partial<DrumState> = {}) {
  const handlers = {
    onStart: vi.fn(),
    onStop: vi.fn(),
    onPwm: vi.fn(),
    onTone: vi.fn(),
  }

  render(<DrumPanel drum={{ ...DRUM, ...overrides }} {...handlers} />)

  return handlers
}

function pwmSlider(): HTMLInputElement {
  return screen.getByLabelText('PWM (głośność)') as HTMLInputElement
}

function toneSlider(): HTMLInputElement {
  return screen.getByLabelText('Ton (wysokość)') as HTMLInputElement
}

describe('DrumPanel', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
  })

  it('pokazuje status Stopped / Running / Disconnected', () => {
    const { unmount } = render(
      <DrumPanel
        drum={DRUM}
        onStart={vi.fn()}
        onStop={vi.fn()}
        onPwm={vi.fn()}
        onTone={vi.fn()}
      />,
    )

    expect(screen.getByText('Stopped')).toBeDefined()
    unmount()

    render(
      <DrumPanel
        drum={{ ...DRUM, value: 80, running: true }}
        onStart={vi.fn()}
        onStop={vi.fn()}
        onPwm={vi.fn()}
        onTone={vi.fn()}
      />,
    )
    expect(screen.getByText('Running')).toBeDefined()
    cleanup()

    render(
      <DrumPanel
        drum={{ ...DRUM, connected: false, running: false }}
        onStart={vi.fn()}
        onStop={vi.fn()}
        onPwm={vi.fn()}
        onTone={vi.fn()}
      />,
    )
    expect(screen.getByText('Disconnected')).toBeDefined()
  })

  it('Start i Stop wolaja akcje', () => {
    const handlers = setup()

    fireEvent.click(screen.getByTitle('Start bębna'))
    fireEvent.click(screen.getByTitle('Stop bębna'))

    expect(handlers.onStart).toHaveBeenCalledTimes(1)
    expect(handlers.onStop).toHaveBeenCalledTimes(1)
  })

  it('przy braku polaczenia przyciski i suwaki sa zablokowane', () => {
    const handlers = setup({ connected: false })

    expect((screen.getByTitle('Start bębna') as HTMLButtonElement).disabled).toBe(true)
    expect(pwmSlider().disabled).toBe(true)

    fireEvent.click(screen.getByTitle('Start bębna'))
    expect(handlers.onStart).not.toHaveBeenCalled()
  })

  it('wysyla PWM podczas przeciagania, ale nie na kazdy piksel', () => {
    const handlers = setup()

    fireEvent.pointerDown(pwmSlider())
    fireEvent.change(pwmSlider(), { target: { value: '10' } })
    fireEvent.change(pwmSlider(), { target: { value: '20' } })
    fireEvent.change(pwmSlider(), { target: { value: '30' } })
    fireEvent.change(pwmSlider(), { target: { value: '40' } })

    // Pierwsza wartosc leci od razu (okno throttlingu minelo), reszta jest
    // zbijana w jeden wysyl po oknie.
    expect(handlers.onPwm.mock.calls.length).toBeLessThanOrEqual(2)
    expect(handlers.onPwm).toHaveBeenCalledWith(10)
  })

  it('po puszczeniu ZAWSZE wysyla wartosc finalna', () => {
    const handlers = setup()

    fireEvent.pointerDown(pwmSlider())
    fireEvent.change(pwmSlider(), { target: { value: '10' } })
    fireEvent.change(pwmSlider(), { target: { value: '20' } })
    fireEvent.change(pwmSlider(), { target: { value: '137' } })

    handlers.onPwm.mockClear()

    fireEvent.pointerUp(pwmSlider())

    expect(handlers.onPwm).toHaveBeenCalledTimes(1)
    expect(handlers.onPwm).toHaveBeenCalledWith(137)
  })

  it('throttle ogranicza liczbe wyslan przy szybkim ruchu', () => {
    const handlers = setup()

    fireEvent.pointerDown(pwmSlider())

    // 40 zmian w tym samym oknie czasowym.
    for (let value = 1; value <= 40; value += 1) {
      fireEvent.change(pwmSlider(), { target: { value: String(value) } })
    }

    expect(handlers.onPwm.mock.calls.length).toBeLessThanOrEqual(3)

    // ...a i tak dojdzie "ogon" i wartosc finalna.
    act(() => {
      vi.advanceTimersByTime(200)
    })

    const sent = handlers.onPwm.mock.calls.map((call) => call[0])
    expect(sent[sent.length - 1]).toBe(40)
  })

  it('suwak tonu wysyla Hz i pokazuje DC dla zera', () => {
    const handlers = setup()

    expect(screen.getByText('DC — bez tonu')).toBeDefined()

    fireEvent.change(toneSlider(), { target: { value: '400' } })

    expect(handlers.onTone).toHaveBeenCalledWith(400)
  })

  it('readout pokazuje PWM potwierdzone przez firmware i wartosc zadana', () => {
    setup({ value: 80, output: 64 })

    expect(screen.getByText('64')).toBeDefined()
    expect(screen.getByText('80 / 255 (31%)')).toBeDefined()
  })

  it('brak potwierdzenia z firmware pokazuje myslnik', () => {
    setup({ value: 80, output: null })

    expect(screen.getByText('—')).toBeDefined()
  })
})
