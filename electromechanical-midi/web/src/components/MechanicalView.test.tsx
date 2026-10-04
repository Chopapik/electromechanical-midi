import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MechanicalView } from './MechanicalView'
import { indexMechanicalPlan, mechanicalState, type MechanicalPlan } from '../mechanical'
import type { PlayerState } from '../types'
import demo from '../fixtures/mechanical-demo.json'

const device = (id: string, type: string) => ({ id, type, name: id, track: null, role: '', volume: .6,
  pan: 0, mute: false, solo: false, transpose: 0, gate: 1, profile: '', mode: 'virtual' as const, overrides: {}, parameters: {} })
const plan: MechanicalPlan = {
  file: 'song.mid', revision: 1, hasPlan: true,
  devices: [device('fdd', 'FDD'), device('dvd', 'DVD_SLED'), device('hdd', 'HDD_VCM'), device('vhs', 'VHS'), device('tray', 'DVD_TRAY')],
  events: [{ id: 'tone', deviceId: 'fdd', actualStart: 1, performedDuration: 2, note: 60, playedNote: 72,
    playedHz: 523.25, name: 'C5', trackName: 'Guitar', role: 'harmony', velocity: 100, outcome: 'ACCEPTED' },
    { id: 'hit', deviceId: 'hdd', actualStart: 4, performedDuration: .105, note: 38, playedNote: 38,
      playedHz: 0, name: 'Snare', trackName: 'Drums', role: 'percussion', velocity: 120, outcome: 'ACCEPTED' }],
  reinforcements: [{ sourceId: 'tone', deviceId: 'dvd', start: 1.2, duration: .8, hz: 523.25, velocity: 100, kind: 'tone', role: 'harmony', reason: 'idle doubling' }],
  trays: [{ sourceId: 'hit', deviceId: 'tray', start: 4, duration: .2, cooldown: .15, note: 38, velocity: 120, direction: 1, sourceTrackName: 'Drums', reason: 'accent' }],
}
const state = (position: number, playback: PlayerState['state'] = 'paused') => ({ file: 'song.mid', position, duration: 10, state: playback, arrangementRevision: 1 } as PlayerState)
beforeEach(() => vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => plan }))))
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

async function open(position = 0) {
  const result = render(<MechanicalView state={state(position)} />)
  await screen.findByRole('button', { name: 'Inspect fdd' })
  return result
}

describe('Mechanical plan state', () => {
  const indexes = indexMechanicalPlan(plan)
  it('uses actual start and performed duration, excluding source timing and drops', () => {
    expect(mechanicalState(indexes[0], .99, 'playing').phase).toBe('IDLE')
    expect(mechanicalState(indexes[0], 1, 'playing').event?.kind).toBe('PRIMARY')
    expect(mechanicalState(indexes[0], 2.99, 'paused').event?.note).toBe(72)
    expect(mechanicalState(indexes[0], 3, 'playing').phase).toBe('IDLE')
    const dropped = indexMechanicalPlan({ ...plan, events: [{ ...plan.events[0], outcome: 'DROPPED' }], reinforcements: [] })
    expect(mechanicalState(dropped[0], 1.5, 'playing').phase).toBe('IDLE')
  })
  it('distinguishes reinforcement and supports backward seek and restart', () => {
    expect(mechanicalState(indexes[1], 1.5, 'playing').event?.kind).toBe('REINFORCEMENT')
    expect(mechanicalState(indexes[1], 2, 'playing').phase).toBe('IDLE')
    expect(mechanicalState(indexes[1], 1.5, 'paused')).toEqual(mechanicalState(indexes[1], 1.5, 'playing'))
    expect(mechanicalState(indexes[1], 0, 'playing').phase).toBe('IDLE')
    expect(mechanicalState(indexes[1], 1.5, 'stopped').phase).toBe('IDLE')
  })
  it('models tray recovery and resting position, and HDD hit cycle', () => {
    expect(mechanicalState(indexes[4], 4.1, 'playing').tray).toBeCloseTo(.5)
    expect(mechanicalState(indexes[4], 4.25, 'playing').phase).toBe('COOLDOWN')
    expect(mechanicalState(indexes[4], 4.35, 'playing').phase).toBe('IDLE')
    expect(mechanicalState(indexes[4], 5, 'playing').tray).toBe(1)
    expect(mechanicalState(indexes[2], 4.09, 'playing').angle).toBeGreaterThan(-25)
    expect(mechanicalState(indexes[2], 4.106, 'playing').phase).toBe('IDLE')
  })
  it('resolves real benchmark event samples using their actual plan timestamps', () => {
    const real = indexMechanicalPlan(demo as unknown as MechanicalPlan)
    expect(real).toHaveLength(15)
    for (const entry of real) for (const event of entry.events) {
      const motion = mechanicalState(entry, event.start + .000001, 'paused')
      expect(motion.event).not.toBeNull()
      expect(motion.event?.start).toBeLessThanOrEqual(event.start + .000001)
    }
  })
})

describe('Mechanical View', () => {
  it('renders inventory, distinct mechanisms and idle states', async () => {
    await open()
    for (const d of plan.devices) {
      expect(screen.getByRole('button', { name: `Inspect ${d.id}` }).getAttribute('data-state')).toBe('IDLE')
      expect(screen.getByRole('img', { name: `${d.type} mechanism` })).toBeDefined()
    }
  })
  it('shows actual PRIMARY / REINFORCEMENT and inspector, and seeks without reloading the plan', async () => {
    const rendered = await open(1.5)
    expect(screen.getByRole('button', { name: 'Inspect fdd' }).getAttribute('data-state')).toBe('ACTIVE PRIMARY')
    expect(screen.getByRole('button', { name: 'Inspect dvd' }).getAttribute('data-state')).toBe('ACTIVE REINFORCEMENT')
    fireEvent.click(screen.getByRole('button', { name: 'Inspect dvd' }))
    expect(screen.getByText('Event: reinforcement:0 · source: tone')).toBeDefined()
    rendered.rerender(<MechanicalView state={state(5)} />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Inspect dvd' }).getAttribute('data-state')).toBe('IDLE'))
    rendered.rerender(<MechanicalView state={state(1.5)} />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Inspect dvd' }).getAttribute('data-state')).toBe('ACTIVE REINFORCEMENT'))
    expect(fetch).toHaveBeenCalledTimes(1)
  })
  it('interpolates only while playing and freezes motion when paused', async () => {
    let callback: FrameRequestCallback | undefined
    vi.spyOn(performance, 'now').mockReturnValue(1000)
    vi.stubGlobal('requestAnimationFrame', vi.fn((cb: FrameRequestCallback) => { callback = cb; return 1 }))
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    const rendered = await open(1.5)
    rendered.rerender(<MechanicalView state={state(1.5, 'playing')} />)
    vi.spyOn(performance, 'now').mockReturnValue(1100)
    act(() => callback?.(1100))
    expect(screen.getByText(/playing · 1.60 s/)).toBeDefined()
    rendered.rerender(<MechanicalView state={state(1.6, 'paused')} />)
    expect(cancelAnimationFrame).toHaveBeenCalled()
    expect(screen.getByText(/paused · 1.60 s/)).toBeDefined()
  })
  it('handles empty plan and HTTP failure with retry', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404 })))
    await openFailure()
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ ...plan, events: [], reinforcements: [], trays: [] }) })))
    fireEvent.click(screen.getByText('Retry'))
    await screen.findByText('The plan has no played events.')
    expect(screen.getByRole('button', { name: 'Inspect fdd' }).getAttribute('data-state')).toBe('IDLE')
  })
})
async function openFailure() {
  render(<MechanicalView state={state(0)} />)
  await screen.findByRole('alert')
}
