import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { Element } from 'vexflow/bravura'
import { TelemetryMonitor, arduinoStatus } from './components/TelemetryMonitor'
import { chooseFocus, eventAt, frequencyAt, indexTelemetry, streamAt } from './telemetry'
import type { PlayerState, TelemetryEvent, TelemetryView, VirtualDevice } from './types'

// jsdom has no canvas text metrics. VexFlow still draws the actual SVG engraving.
beforeAll(() => Element.setTextMeasurementCanvas({ getContext: () => ({
  measureText: (text: string) => ({ width: text.length * 8, actualBoundingBoxAscent: 16, actualBoundingBoxDescent: 4 }),
}) } as unknown as HTMLCanvasElement))

const event: TelemetryEvent = { id: 'tone', deviceId: 'fdd', start: 1, duration: 2, kind: 'tone', note: 55, sourceNote: 55, hz: 196, track: 'Guitar 1', velocity: 92, role: 'lead', reinforcement: false, profile: 'PLUCKED', articulation: null, direction: 1, frequencyCurve: { times: [0, 1, 2], values: [196, 208, 196] } }
const devices: VirtualDevice[] = ['FDD', 'DVD_SLED', 'HDD_VCM', 'DVD_TRAY', 'VHS'].map((type, i) => ({ id: ['fdd', 'dvd', 'hdd', 'tray', 'vhs'][i], type, name: ['FDD 1', 'DVD 1', 'HDD 1', 'TRAY 1', 'VHS'][i], track: 1, role: '', volume: .6, pan: 0, mute: false, solo: false, transpose: 0, gate: 1, profile: '', mode: 'virtual', overrides: {} }))
const hit: TelemetryEvent = { ...event, id: 'hit', deviceId: 'hdd', kind: 'hit', hz: 0, sourceNote: 36, articulation: 'HARD_HIT', duration: .22, frequencyCurve: null }
const tray: TelemetryEvent = { ...hit, id: 'tray', deviceId: 'tray', kind: 'tray', sourceNote: 57, duration: .3, reinforcement: true }
const view: TelemetryView = { file: 'song.mid', revision: 1, events: [event, hit, tray], activity: {}, report: null }
const state = { state: 'playing', position: 1.1, duration: 10, file: 'song.mid', hardware: { connected: false, port: null }, virtual: { enabled: true, config: { name: 'Test', devices: [] }, report: {}, trayStatus: { tray: { phase: 'opening', note: 57 } } } } as unknown as PlayerState
const playing: PlayerState = { ...state, virtual: { ...state.virtual!, config: { name: 'Test', devices } } }
afterEach(cleanup)
describe('renderer telemetry', () => {
  it('interpolates the real pitch curve and clamps outside it', () => {
    expect(frequencyAt(event, 1.5)).toBe(202)
    expect(frequencyAt(event, 0)).toBe(196)
    expect(frequencyAt(event, 10)).toBe(196)
  })
  it('prioritizes primary lead over HDD, reinforcement and tray', () => {
    expect(chooseFocus([tray, hit, { ...event, id: 'rf', reinforcement: true }, event], 1.1)).toBe(event)
    expect(chooseFocus([tray, hit, { ...event, role: 'harmony', velocity: 50 }], 1.1)).toBe(hit)
    expect(chooseFocus([tray, { ...event, id: 'rf', reinforcement: true }], 1.1)?.id).toBe('rf')
  })
  it('finds a lane by binary search and stops activity at its exact end', () => {
    const index = indexTelemetry(view)
    expect(eventAt(index.lanes.get('fdd')!, 1.5)).toBe(event)
    expect(eventAt(index.lanes.get('fdd')!, 3)).toBeNull()
    expect(eventAt(index.lanes.get('fdd')!, .9)).toBeNull()
  })
  it('streams only real onsets, latest first, rewinds and caps at 16', () => {
    const events = Array.from({ length: 100 }, (_, i) => ({ ...event, id: String(i), start: i }))
    expect(streamAt(events, 50)).toHaveLength(16)
    expect(streamAt(events, 50)[0].start).toBe(50)
    expect(streamAt(events, 3)[0].start).toBe(3)
    expect(streamAt(events, -1)).toEqual([])
  })
  const tile = (name: string) => screen.getByRole('article', { name })
  const lit = (name: string) => tile(name).classList.contains('is-active')
  it('renders the actual note and bent Hz, percussion velocity and source in independent tiles', () => {
    render(<TelemetryMonitor state={playing} view={view} error={null} />)
    expect(within(tile('FDD 1')).getByText('G3')).toBeDefined()
    expect(within(tile('FDD 1')).getByText('197.20 Hz')).toBeDefined()
    expect(within(tile('FDD 1')).getByText('G3').parentElement).toBe(within(tile('FDD 1')).getByText('197.20 Hz').parentElement)
    expect(within(tile('FDD 1')).getByRole('img', { name: /G3/ })).toBeDefined()
    expect(within(tile('FDD 1')).getByText('Guitar 1')).toBeDefined()
    expect(lit('FDD 1')).toBe(true)
    expect(within(tile('HDD 1')).getByText('HARD HIT')).toBeDefined()
    expect(within(tile('HDD 1')).getByText('VEL 92')).toBeDefined()
    expect(within(tile('HDD 1')).queryByText(/Hz/)).toBeNull()
    expect(within(tile('HDD 1')).queryByRole('img')).toBeNull()
    expect(lit('VHS')).toBe(false)
    expect(within(tile('VHS')).getByText('—')).toBeDefined()
    expect(screen.queryByText('IDLE')).toBeNull()
    const stream = within(screen.getByRole('region', { name: 'Event Stream' }))
    expect(stream.getAllByRole('listitem')).toHaveLength(3)
    expect(stream.getByText('CRASH')).toBeDefined()
    expect(screen.queryByRole('meter')).toBeNull()
    expect(screen.queryByText(/coverage|ORCHESTRA LOAD|CURRENT MUSICAL EVENT/)).toBeNull()
  })
  it.each(['SOFT_TAP', 'MEDIUM_HIT', 'HARD_HIT', 'DOUBLE_TAP', 'BUZZ_ROLL'])('uses the real HDD category %s', kind => {
    render(<TelemetryMonitor state={playing} view={{ ...view, events: [{ ...hit, articulation: kind }] }} error={null} />)
    expect(within(tile('HDD 1')).getByText(kind.replaceAll('_', ' '))).toBeDefined()
  })
  it('uses the output clock and audible release, even after the physical gate', () => {
    render(<TelemetryMonitor state={{ ...playing, position: 8, virtual: { ...playing.virtual!, audioPosition: 3.5 } }} view={{ ...view, audioEvents: [{ ...event, duration: 4 }] }} error={null} />)
    expect(lit('FDD 1')).toBe(true)
    expect(within(tile('FDD 1')).getByText('196.00 Hz')).toBeDefined()
    expect(within(screen.getByRole('region', { name: 'Event Stream' })).getAllByRole('listitem')).toHaveLength(1)
  })
  it('does not light tiles before the audio output starts', () => {
    render(<TelemetryMonitor state={{ ...playing, virtual: { ...playing.virtual!, audioClockRunning: false } }} view={{ ...view, audioEvents: [event] }} error={null} />)
    expect(lit('FDD 1')).toBe(false)
  })
  it('omits reinforcement suppressed by the final renderer', () => {
    render(<TelemetryMonitor state={playing} view={{ ...view, audioEvents: [] }} error={null} />)
    expect(lit('FDD 1')).toBe(false)
    expect(within(screen.getByRole('region', { name: 'Event Stream' })).queryByRole('listitem')).toBeNull()
  })
  it('does not light a tray during recovery', () => {
    render(<TelemetryMonitor state={{ ...playing, position: 2, virtual: { ...playing.virtual!, trayStatus: { tray: { phase: 'recovery', note: 57 } } } }} view={view} error={null} />)
    expect(lit('TRAY 1')).toBe(false)
  })
  it.each(['paused', 'stopped'] as const)('clears all lit tiles after %s', transport => {
    render(<TelemetryMonitor state={{ ...playing, state: transport }} view={view} error={null} />)
    expect(document.querySelectorAll('.instrument-tile.is-active')).toHaveLength(0)
    expect(screen.queryByText('IDLE')).toBeNull()
  })
  it('freezes the audible note and Hz on Stop, then follows playback again', () => {
    const hook = render(<TelemetryMonitor state={playing} view={view} error={null} />)
    hook.rerender(<TelemetryMonitor state={{ ...playing, state: 'stopped', position: 0 }} view={view} error={null} />)
    expect(within(tile('FDD 1')).getByText('G3')).toBeDefined()
    expect(within(tile('FDD 1')).getByText('197.20 Hz')).toBeDefined()
    expect(within(tile('FDD 1')).getByRole('img', { name: /G3/ })).toBeDefined()
    expect(lit('FDD 1')).toBe(false)
    hook.rerender(<TelemetryMonitor state={{ ...playing, position: 0 }} view={view} error={null} />)
    expect(within(tile('FDD 1')).queryByText('G3')).toBeNull()
    expect(within(tile('FDD 1')).getByText('—')).toBeDefined()
  })
  it('does not retain frozen notes when a different MIDI is loaded', () => {
    const hook = render(<TelemetryMonitor state={playing} view={view} error={null} />)
    hook.rerender(<TelemetryMonitor state={{ ...playing, state: 'stopped', file: 'other.mid', position: 0 }} view={null} error={null} />)
    expect(within(tile('FDD 1')).queryByText('G3')).toBeNull()
  })
  it('does not fabricate activity with output off and hardware unbound', () => {
    render(<TelemetryMonitor state={{ ...playing, virtual: { ...playing.virtual!, enabled: false } }} view={view} error={null} />)
    expect(document.querySelectorAll('.instrument-tile.is-active')).toHaveLength(0)
  })
  it('respects mute and solo without changing the plan', () => {
    const before = JSON.stringify(view)
    render(<TelemetryMonitor state={{ ...playing, virtual: { ...playing.virtual!, config: { name: 'Test', devices: devices.map(d => ({ ...d, solo: d.id === 'hdd' })) } } }} view={view} error={null} />)
    expect(lit('FDD 1')).toBe(false)
    expect(lit('HDD 1')).toBe(true)
    expect(JSON.stringify(view)).toBe(before)
  })
  it('hides disabled devices even if telemetry still contains their notes', () => {
    const hook = render(<TelemetryMonitor state={{ ...playing, virtual: { ...playing.virtual!, config: {
      name: 'Test', devices: devices.map(d => ({ ...d, enabled: d.id !== 'fdd' })) } } }} view={view} error={null} />)
    expect(screen.queryByRole('article', { name: 'FDD 1' })).toBeNull()
    hook.rerender(<TelemetryMonitor state={playing} view={view} error={null} />)
    expect(lit('FDD 1')).toBe(true)
  })
  it('keeps an idle device role without inventing a note or frequency', () => {
    render(<TelemetryMonitor state={{ ...playing, state: 'stopped', virtual: { ...playing.virtual!, config: { name: 'Test', devices: [{ ...devices[0], role: 'Bass' }] } } }} view={view} error={null} />)
    expect(within(tile('FDD 1')).getByText('Bass')).toBeDefined()
    expect(within(tile('FDD 1')).getByText('—')).toBeDefined()
    expect(within(tile('FDD 1')).queryByText(/Hz/)).toBeNull()
  })
  it('shows a real telemetry error without fabricated measurements', () => {
    render(<TelemetryMonitor state={playing} view={null} error="Telemetry unavailable" />)
    expect(screen.getByRole('alert').textContent).toBe('Telemetry unavailable')
    expect(lit('FDD 1')).toBe(false)
  })
  it('uses only the actual Arduino connection state', () => {
    expect(arduinoStatus(state)).toBe('Arduino disconnected')
    expect(arduinoStatus({ ...state, hardware: { ...state.hardware, connected: true } })).toBe('Arduino connected')
    expect(arduinoStatus({ ...state, hardware: { ...state.hardware, connecting: true } })).toBe('Arduino disconnected')
    expect(arduinoStatus({ ...state, hardware: { ...state.hardware, pendingPlay: true } })).toBe('Arduino disconnected')
  })
})
