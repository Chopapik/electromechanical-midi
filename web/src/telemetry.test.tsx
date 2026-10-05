import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { TelemetryMonitor, arduinoStatus } from './components/TelemetryMonitor'
import { chooseFocus, eventAt, frequencyAt, indexTelemetry, streamAt } from './telemetry'
import type { PlayerState, TelemetryEvent, TelemetryView, VirtualDevice } from './types'

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
  it('renders current folded note, real bend Hz, configured lanes, HDD and tray', () => {
    render(<TelemetryMonitor state={playing} view={view} error={null} />)
    const focus = within(screen.getByRole('region', { name: 'Current Musical Event' }))
    expect(focus.getByText('G3')).toBeDefined()
    expect(focus.getByText('197.20 Hz')).toBeDefined()
    expect(focus.getByText('PITCH BEND')).toBeDefined()
    const activity = within(screen.getByRole('region', { name: 'Device Activity' }))
    expect(activity.getByText('HARD_HIT')).toBeDefined()
    expect(activity.getByText('OPENING')).toBeDefined()
    expect(activity.getByText('VHS')).toBeDefined()
    expect(activity.getByText('GM36 · VEL 92')).toBeDefined()
    expect(within(screen.getByRole('region', { name: 'Event Stream' })).getAllByRole('listitem')).toHaveLength(3)
  })
  it.each(['SOFT_TAP', 'MEDIUM_HIT', 'HARD_HIT', 'DOUBLE_TAP', 'BUZZ_ROLL'])('uses existing HDD category %s', kind => {
    render(<TelemetryMonitor state={playing} view={{ ...view, events: [{ ...hit, articulation: kind }] }} error={null} />)
    expect(within(screen.getByRole('region', { name: 'Device Activity' })).getByText(kind)).toBeDefined()
  })
  it('uses the audible interval and output clock, including release after the gate', () => {
    const audible = { ...event, duration: 4 }
    render(<TelemetryMonitor state={{ ...playing, position: 8, virtual: { ...playing.virtual!, audioPosition: 3.5 } }} view={{ ...view, audioEvents: [audible] }} error={null} />)
    const activity = within(screen.getByRole('region', { name: 'Device Activity' }))
    expect(activity.getByText('ACTIVE')).toBeDefined()
    expect(activity.getByText('G3 · 196.00 Hz')).toBeDefined()
    expect(within(screen.getByRole('region', { name: 'Event Stream' })).getAllByRole('listitem')).toHaveLength(1)
  })
  it('does not advance or light notes before the audio device starts', () => {
    render(<TelemetryMonitor state={{ ...playing, virtual: { ...playing.virtual!, audioClockRunning: false } }} view={{ ...view, audioEvents: [event] }} error={null} />)
    expect(within(screen.getByRole('region', { name: 'Device Activity' })).queryByText('ACTIVE')).toBeNull()
  })
  it('omits extras suppressed by the final waveform renderer', () => {
    render(<TelemetryMonitor state={playing} view={{ ...view, audioEvents: [] }} error={null} />)
    expect(within(screen.getByRole('region', { name: 'Device Activity' })).queryByText('ACTIVE')).toBeNull()
    expect(within(screen.getByRole('region', { name: 'Event Stream' })).queryByRole('listitem')).toBeNull()
  })
  it('shows the actual tray recovery phase without claiming movement', () => {
    const recovering = { ...playing, position: 2, virtual: { ...playing.virtual!, trayStatus: { tray: { phase: 'recovery', note: 57 } } } }
    render(<TelemetryMonitor state={recovering} view={view} error={null} />)
    const activity = within(screen.getByRole('region', { name: 'Device Activity' }))
    expect(activity.getByText('RECOVERY')).toBeDefined()
    expect(activity.queryByText('MOVING')).toBeNull()
  })
  it.each(['paused', 'stopped'] as const)('never leaves devices ACTIVE after %s', transport => {
    render(<TelemetryMonitor state={{ ...playing, state: transport }} view={view} error={null} />)
    const activity = within(screen.getByRole('region', { name: 'Device Activity' }))
    expect(activity.queryByText('ACTIVE')).toBeNull()
    expect(activity.queryByText('HIT')).toBeNull()
    expect(activity.getAllByText('IDLE')).toHaveLength(devices.length)
  })
  it('does not fabricate activity when virtual output is off or hardware unbound', () => {
    render(<TelemetryMonitor state={{ ...playing, virtual: { ...playing.virtual!, enabled: false } }} view={view} error={null} />)
    expect(within(screen.getByRole('region', { name: 'Device Activity' })).getAllByText('IDLE')).toHaveLength(5)
  })
  it('shows missing telemetry as unavailable, not mock percentages', () => {
    render(<TelemetryMonitor state={playing} view={null} error="Telemetry unavailable" />)
    expect(screen.getByText('Telemetry unavailable')).toBeDefined()
    expect(screen.getByRole('meter', { name: 'FDD utilization' }).getAttribute('aria-valuenow')).toBeNull()
  })
  it('uses real report active time for load, and leaves the plan unchanged', () => {
    const before = JSON.stringify(view)
    const report = { activeTime: 6, busyTime: 3 } as unknown as NonNullable<PlayerState['virtual']>['report'][string]
    render(<TelemetryMonitor state={{ ...playing, virtual: { ...playing.virtual!, report: { fdd: report } } }} view={view} error={null} />)
    expect(screen.getByRole('meter', { name: 'FDD utilization' }).getAttribute('aria-valuenow')).toBe('60')
    expect(JSON.stringify(view)).toBe(before)
  })
  it('reports real Arduino connected/disconnected/homing/waiting states', () => {
    expect(arduinoStatus(state)).toBe('Arduino disconnected')
    expect(arduinoStatus({ ...state, hardware: { ...state.hardware, connected: true } })).toBe('Arduino connected')
    expect(arduinoStatus({ ...state, hardware: { ...state.hardware, connecting: true } })).toBe('Arduino homing')
    expect(arduinoStatus({ ...state, hardware: { ...state.hardware, pendingPlay: true } })).toBe('Arduino waiting')
  })
})
