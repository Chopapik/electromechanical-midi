import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ArrangementEditor } from './ArrangementEditor'
import type { ArrangementView, PlayerState } from '../types'

const view: ArrangementView = {
  arrangement: {
    schemaVersion: 1, name: 'Song', midi: { file: 'song.mid', sha256: 'abc', tracks: [{ index: 0, name: 'Melody' }, { index: 1, name: 'Drums' }] },
    devices: [
      { id: 'fdd', type: 'FDD', name: 'FDD #1', track: 0, role: '', volume: .6, pan: 0, mute: false, solo: false, transpose: 0, gate: 1, profile: 'FDD_CURRENT', mode: 'virtual', overrides: {} },
      { id: 'hdd', type: 'HDD_VCM', name: 'HDD #1', track: 1, role: '', volume: .6, pan: 0, mute: false, solo: false, transpose: 0, gate: 1, profile: 'WD_CAVIAR_CURRENT', mode: 'virtual', overrides: {} },
    ],
    rules: [{ id: 'melody', source: { track: 0 }, destination: { deviceId: 'fdd' }, transform: { gate: 1, transpose: 0, octaveFold: true, strategy: 'first' } }],
  },
  midiIdentity: { file: 'song.mid', sha256: 'abc', tracks: [{ index: 0, name: 'Melody' }, { index: 1, name: 'Drums' }] },
  tracks: [{ index: 0, name: 'Melody', isDrums: false, noteCount: 1 }, { index: 1, name: 'Drums', isDrums: true, noteCount: 2 }],
  notes: [
    { id: '0:0', track: 0, trackName: 'Melody', channel: 1, note: 60, name: 'C4', start: 0, duration: .5, velocity: 90, isDrum: false, status: 'DROPPED', routes: [{ ruleId: 'melody', deviceId: 'fdd', status: 'DROPPED', reason: 'NOTE_DROPPED_POLYPHONY' }] },
    { id: '1:0', track: 1, trackName: 'Drums', channel: 10, note: 36, name: 'Stopa', start: .2, duration: .1, velocity: 110, isDrum: true, status: 'UNASSIGNED', routes: [] },
    { id: '1:1', track: 1, trackName: 'Drums', channel: 10, note: 42, name: 'Hi-hat', start: .4, duration: .1, velocity: 50, isDrum: true, status: 'UNASSIGNED', routes: [] },
  ], revision: 1,
}
const state = { position: .2, arrangementRevision: 1 } as PlayerState
let calls: Array<{ url: string; init?: RequestInit }> = []
let download = ''
beforeEach(() => {
  calls = []; download = ''
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init })
    const arrangement = init?.method === 'PUT' ? JSON.parse(String(init.body)) : view.arrangement
    return { ok: true, status: 200, json: async () => ({ ...view, arrangement }) } as Response
  }))
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:test') })
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { download = this.download })
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
async function open() {
  render(<ArrangementEditor file="song.mid" state={state} seek={() => {}} />)
  await waitFor(() => expect(screen.getByText('Song · 3 MIDI notes')).toBeDefined())
}

describe('ArrangementEditor', () => {
  it('shows an actionable error when an older backend lacks the endpoint', async () => {
    let available = false
    vi.stubGlobal('fetch', vi.fn(async () => available
      ? { ok: true, status: 200, json: async () => view } as Response
      : { ok: false, status: 404, json: async () => ({ detail: 'Not Found' }) } as Response))
    render(<ArrangementEditor file="song.mid" state={state} seek={() => {}} />)
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Uruchom ponownie ./scripts/dev.sh'))
    available = true
    fireEvent.click(screen.getByRole('button', { name: 'Spróbuj ponownie' }))
    await waitFor(() => expect(screen.getByText('Song · 3 MIDI notes')).toBeDefined())
  })
  it('shows backend piano-roll data and switches source/device/simulation views', async () => {
    await open()
    expect(screen.getByLabelText('MIDI piano roll')).toBeDefined()
    expect(screen.getAllByText('0 — Melody').length).toBeGreaterThan(0)
    expect(screen.getAllByText('FDD #1').length).toBeGreaterThan(0)
    const mode = screen.getByLabelText('Piano roll view mode') as HTMLSelectElement
    fireEvent.change(mode, { target: { value: 'device' } }); expect(mode.value).toBe('device')
    fireEvent.change(mode, { target: { value: 'simulation' } }); expect(mode.value).toBe('simulation')
    expect(screen.getByText('× DROPPED')).toBeDefined()
    expect(screen.getByText('· UNASSIGNED')).toBeDefined()
  })
  it('selects a note and distinguishes dropped from unassigned', async () => {
    await open()
    fireEvent.click(screen.getByRole('button', { name: /C4 · 00:00.000 · DROPPED/ }))
    expect(screen.getByText(/NOTE_DROPPED_POLYPHONY/)).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: /Stopa · 00:00.200 · UNASSIGNED/ }))
    expect(screen.getByText('No routing rule matched this note.')).toBeDefined()
  })
  it('opens the note inspector from a piano-roll block', async () => {
    const context = Object.fromEntries(['setTransform', 'clearRect', 'fillRect', 'fillText', 'strokeRect', 'beginPath', 'moveTo', 'lineTo', 'stroke', 'fill', 'setLineDash'].map(name => [name, vi.fn()]))
    vi.mocked(HTMLCanvasElement.prototype.getContext).mockReturnValue(context as unknown as CanvasRenderingContext2D)
    await open()
    fireEvent.click(screen.getByLabelText('MIDI piano roll'), { clientX: 80, clientY: 80 })
    expect(screen.getByText(/NOTE_DROPPED_POLYPHONY/)).toBeDefined()
  })
  it('routes a drum pitch immediately and exports the arrangement', async () => {
    await open()
    fireEvent.click(screen.getByLabelText('Use drum 36'))
    await waitFor(() => expect(calls.some(c => c.init?.method === 'PUT')).toBe(true))
    const doc = JSON.parse(String(calls.find(c => c.init?.method === 'PUT')?.init?.body)) as ArrangementView['arrangement']
    expect(doc?.rules.find(r => r.source.includeNotes?.[0] === 36)?.destination.deviceId).toBe('hdd')
    fireEvent.click(screen.getByRole('button', { name: 'Export Arrangement JSON' }))
    expect(download).toBe('song.orchestra.json')
  })
  it('warns on imported MIDI mismatch and remaps tracks only after confirmation', async () => {
    const imported = structuredClone(view.arrangement!)
    imported.midi.file = 'other.mid'
    imported.midi.tracks[0].name = 'Old Guitar'
    imported.rules[0].source.track = 0
    Object.defineProperty(File.prototype, 'text', { configurable: true, value: vi.fn(async () => JSON.stringify(imported)) })
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init })
      if (init?.method === 'PUT') {
        const submitted = JSON.parse(String(init.body)) as typeof imported
        if (submitted.midi.file === 'other.mid') return {
          ok: false, status: 409,
          json: async () => ({ detail: { mismatches: [{ kind: 'midi', expected: 'other.mid', actual: 'song.mid' }] } }),
        } as Response
        return { ok: true, status: 200, json: async () => ({ ...view, arrangement: submitted }) } as Response
      }
      return { ok: true, status: 200, json: async () => view } as Response
    }))
    await open()
    fireEvent.change(screen.getByLabelText('Arrangement JSON file'), { target: { files: [new File(['{}'], 'other.json')] } })
    await waitFor(() => expect(screen.getByText('Arrangement MIDI mismatch')).toBeDefined())
    expect(screen.getByText('Song · 3 MIDI notes')).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: 'Apply remapping' }))
    await waitFor(() => expect(calls.filter(c => c.init?.method === 'PUT').length).toBe(2))
    const accepted = JSON.parse(String(calls.filter(c => c.init?.method === 'PUT')[1].init?.body)) as typeof imported
    expect(accepted.midi.file).toBe('song.mid')
    expect(accepted.rules[0].source.track).toBe(0)
  })
})
