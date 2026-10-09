/**
 * Test integracyjny UI: mockujemy WebSocket i fetch, a potem sprawdzamy,
 * czy stan z backendu trafia na ekran i czy przyciski wysylaja dobre akcje.
 */

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type { PlayerState } from './types'

class MockWebSocket {
  static instances: MockWebSocket[] = []
  static readonly OPEN = 1
  static readonly CLOSED = 3

  readyState = MockWebSocket.OPEN
  url: string
  sent: string[] = []

  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
  }

  send(data: string): void {
    this.sent.push(data)
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED
  }

  emit(payload: unknown): void {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent)
  }

  actions(): Array<Record<string, unknown>> {
    return this.sent.map((raw) => JSON.parse(raw) as Record<string, unknown>)
  }
}

const STATE: PlayerState = {
  state: 'playing',
  position: 12.5,
  duration: 60,
  file: 'song.mid',
  track: 1,
  trackName: 'Thom Vox',
  midiNote: 52,
  noteName: 'E3',
  sourceNote: 64,
  frequency: 164.81,
  transpose: 'low',
  strategy: 'highest',
  range: { minHz: 130, maxHz: 410 },
  stats: { notes: 84, skipped: 0, folded: 80, out_of_range: 0 },
  hardware: {
    connected: true,
    port: '/dev/cu.usbmodem14101',
    label: 'Arduino',
    error: null,
    warning: null,
    log: [],
  },
  drum: {
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
  },
  hdd: {
    connected: true,
    busy: false,
    count: 0,
    controlledBy: 'off',
    midiTrack: null,
    midiTrackName: null,
    note: null,
    rate: null,
    notes: [],
    lastNote: null,
    lastNoteName: null,
  },
}

const FILES = [{ name: 'song.mid', size: 1234, modified: 0 }]

const METADATA = {
  name: 'song.mid',
  duration: 60,
  tempoChanges: 0,
  type: 1,
  ticksPerBeat: 480,
  tracks: [
    {
      index: 1,
      name: 'Thom Vox',
      label: 'Thom Vox - 84 nut',
      noteCount: 84,
      channels: [3],
      isDrums: false,
      polyphonic: false,
    },
  ],
}

function mockFetch(url: string, init?: RequestInit): Promise<Response> {
  let body: unknown = { files: FILES }

  if (url === '/api/files' && init?.method === 'POST') {
    body = { name: 'nowy.mid', size: 999, files: [...FILES, { name: 'nowy.mid', size: 999, modified: 0 }] }
  } else if (url.startsWith('/api/files/')) body = METADATA
  else if (url === '/api/ports') {
    body = { ports: [{ device: '/dev/cu.usbmodem14101', label: 'Arduino', usbId: '2341:0043', score: 195 }], current: '/dev/cu.usbmodem14101', connected: true }
  }

  return Promise.resolve({ ok: true, json: () => Promise.resolve(body) } as Response)
}

async function renderApp(overrides: Partial<PlayerState> = {}, manual = true): Promise<MockWebSocket> {
  render(<App />)

  await waitFor(() => expect(MockWebSocket.instances.length).toBe(1))

  const socket = MockWebSocket.instances[0]

  await act(async () => {
    socket.onopen?.(new Event('open'))
    socket.emit({ type: 'state', state: { ...STATE, ...overrides } })
  })

  if (manual) {
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Settings' }))
    })
    fireEvent.click(screen.getByText('ADVANCED / MANUAL HARDWARE'))
  }
  return socket
}

describe('App', () => {
  beforeEach(() => {
    MockWebSocket.instances = []
    vi.stubGlobal('WebSocket', MockWebSocket)
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => mockFetch(url, init)))
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('opens one monitor with no main navigation or legacy forms', async () => {
    await renderApp({}, false)
    for (const name of ['PLAYER', 'ORCHESTRA', 'ARRANGEMENT']) expect(screen.queryByRole('button', { name })).toBeNull()
    expect(screen.getByRole('region', { name: 'Virtual Instrument Grid' })).toBeDefined()
    expect(screen.queryByText('LIVE')).toBeNull()
    expect(screen.queryByText(/backend connected/i)).toBeNull()
    expect(screen.queryByLabelText('FDD Track')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Import Arrangement JSON' })).toBeNull()
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(fetch).not.toHaveBeenCalledWith('/api/arrangement/initialize', expect.anything())
  })

  it('opens and closes Settings without sending playback commands', async () => {
    const socket = await renderApp({}, false)
    socket.sent = []
    const button = screen.getByRole('button', { name: 'Settings' })
    button.focus()
    fireEvent.click(button)
    expect(screen.getByRole('dialog', { name: 'Settings' })).toBeDefined()
    expect(screen.getByText('SOUND')).toBeDefined()
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(button)
    expect(socket.actions()).toEqual([])
    expect(screen.getByRole('slider', { name: 'Pozycja utworu' }).getAttribute('aria-valuenow')).toBe('13')
  })

  it.each([['playing', 'Pauza'], ['paused', 'Play'], ['stopped', 'Play']] as const)('reflects %s with the state icon while keeping toggle actions', async (state, action) => {
    const socket = await renderApp({ state }, false)
    const button = screen.getByRole('button', { name: action })
    expect(button.textContent?.trim()).toBe('')
    expect(button.querySelector('svg')?.getAttribute('width')).toBe('18')
    expect(button.querySelector('svg')?.getAttribute('height')).toBe('18')
    expect(button.classList.contains(state)).toBe(true)
    expect(screen.queryByText(/PLAYING|PAUSED|STOPPED/)).toBeNull()
    fireEvent.click(button)
    expect(socket.actions().at(-1)).toEqual({ action: state === 'playing' ? 'pause' : state === 'paused' ? 'resume' : 'play' })
    fireEvent.click(screen.getByTitle('Stop'))
    expect(socket.actions().at(-1)).toEqual({ action: 'stop' })
  })

  it('keeps runtime output outside Settings and retains every sound option', async () => {
    const socket = await renderApp({ virtual: { enabled: true, config: { name: 'Test', devices: [], masterVolume: 19.5 }, report: {}, activity: {}, profiles: [] } })
    expect(screen.queryByLabelText('Virtual instruments mode')).toBeNull()
    fireEvent.change(screen.getByLabelText('Master Volume'), { target: { value: '10' } })
    expect(socket.actions().at(-1)).toMatchObject({ action: 'set_virtual', config: { masterVolume: 10 } })
    const modes = screen.getByLabelText('Tonal sound') as HTMLSelectElement
    expect([...modes.options].map(o => o.value)).toEqual(['raw', 'articulated', 'extreme', 'extreme_v15', 'extreme_v2'])
    fireEvent.change(modes, { target: { value: 'raw' } })
    expect(socket.actions().at(-1)).toMatchObject({ action: 'set_virtual', config: { tonalMode: 'raw' } })
    fireEvent.change(screen.getByLabelText('HDD sound'), { target: { value: 'raw' } })
    expect(socket.actions().at(-1)).toMatchObject({ action: 'set_virtual', config: { hddMode: 'raw' } })
    fireEvent.change(screen.getByLabelText('Note length'), { target: { value: 'source_v15' } })
    expect(socket.actions().at(-1)).toMatchObject({ action: 'set_virtual', config: { sourceContinuity: true, sourceContinuityAmount: .5 } })
    expect(socket.actions().some(a => ['stop', 'seek', 'play'].includes(String(a.action)))).toBe(false)
  })

  it('loads and saves presets with the complete config', async () => {
    const config = { name: 'Test', devices: [], masterVolume: 10 }
    vi.spyOn(window, 'prompt').mockReturnValue('Test')
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => url.startsWith('/api/virtual/presets')
      ? Promise.resolve({ ok: true, json: async () => ({ presets: { Test: config } }) } as Response) : mockFetch(url, init)))
    const socket = await renderApp({ virtual: { enabled: true, config, report: {}, activity: {}, profiles: [] } })
    await waitFor(() => expect(screen.getByRole('option', { name: 'Test' })).toBeDefined())
    fireEvent.change(screen.getByLabelText('Load preset'), { target: { value: 'Test' } })
    expect(socket.actions().at(-1)).toMatchObject({ action: 'set_virtual', config })
    fireEvent.click(screen.getByText('Save preset'))
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/virtual/presets/Test', expect.objectContaining({ method: 'PUT', body: JSON.stringify(config) })))
    vi.restoreAllMocks()
  })

  it('duplicates a device and retains reinforcement controls', async () => {
    const device = { id: 'fdd', type: 'FDD', name: 'FDD 1', track: 1, role: '', volume: .6, pan: 0, mute: false, solo: false, transpose: 0, gate: 1, profile: 'FDD_CURRENT', mode: 'virtual' as const, overrides: {} }
    const socket = await renderApp({ virtual: { enabled: true, config: { name: 'Test', devices: [device], idleReinforcement: { enabled: true } }, report: {}, activity: {}, profiles: [] } })
    fireEvent.click(screen.getByText('Ustawienia FDD 1'))
    fireEvent.click(screen.getByText('Duplicate'))
    expect(socket.actions().at(-1)).toMatchObject({ action: 'set_virtual', config: { devices: [device, { name: 'FDD 1 copy', mode: 'virtual' }] } })
    fireEvent.change(screen.getByLabelText('Reinforcement max copies'), { target: { value: '2' } })
    expect(socket.actions().at(-1)).toMatchObject({ config: { idleReinforcement: { maxCopiesPerEvent: 2 } } })
    fireEvent.change(screen.getByLabelText('Reinforcement reservation'), { target: { value: '120' } })
    expect(socket.actions().at(-1)).toMatchObject({ config: { idleReinforcement: { lookAheadMs: 120 } } })
    fireEvent.change(screen.getByLabelText('Reinforcement minimum score'), { target: { value: '90' } })
    expect(socket.actions().at(-1)).toMatchObject({ config: { idleReinforcement: { minScore: 90 } } })
  })

  it('adds a virtual device without Arduino and sends its track to the backend', async () => {
    const socket = await renderApp({
      virtual: {
        enabled: false,
        config: { name: 'Test', devices: [] },
        report: {},
        activity: {},
        profiles: [{ id: 'FDD_CURRENT', kind: 'FDD', parameters: {} }],
      },
    })

    await waitFor(() => expect(screen.getByText('ORCHESTRA')).toBeDefined())
    fireEvent.change(screen.getByLabelText('Add device'), { target: { value: 'FDD' } })
    expect(socket.actions().at(-1)).toMatchObject({
      action: 'set_virtual',
      config: { enabled: false, devices: [{ type: 'FDD', track: 1, enabled: true, mode: 'real' }] },
    })
  })

  it('adds a quiet DVD and removes a specific instance from OrchestraConfig', async () => {
    const fdd = { id: 'fdd-1', type: 'FDD', name: 'FDD #1', track: null, role: '', volume: .6,
      pan: 0, mute: false, solo: false, transpose: 0, gate: 1,
      profile: 'FDD_CURRENT', mode: 'virtual' as const, overrides: {} }
    const dvd = { ...fdd, id: 'dvd-1', type: 'DVD_SLED', name: 'DVD sled #1',
      volume: .2, profile: 'DVD_REFERENCE' }
    const socket = await renderApp({ virtual: {
      enabled: true, config: { name: 'Eleven voices', devices: [fdd, dvd] },
      report: {}, activity: {}, profiles: [
        { id: 'FDD_CURRENT', kind: 'FDD', parameters: {} },
        { id: 'DVD_REFERENCE', kind: 'DVD_SLED', parameters: {} },
      ],
    } })

    fireEvent.change(screen.getByLabelText('Add device'), { target: { value: 'DVD_SLED' } })
    expect(socket.actions().at(-1)).toMatchObject({
      action: 'set_virtual', config: { devices: [fdd, dvd, { type: 'DVD_SLED', volume: .2,
        profile: 'DVD_REFERENCE', mode: 'virtual' }] },
    })
    const row = screen.getByText('Ustawienia DVD sled #1').closest('details')!
    fireEvent.click(row.querySelector('summary')!)
    fireEvent.click(row.querySelector('button:last-of-type')!)
    expect(socket.actions().at(-1)).toMatchObject({
      action: 'set_virtual', config: { devices: [fdd] },
    })
  })

  it('switches four physical DVD to dynamic reinforcement', async () => {
    const dvd = Array.from({ length: 4 }, (_, index) => ({
      id: `dvd_sled-${index + 1}`, type: 'DVD_SLED', name: `DVD #${index + 1}`,
      track: null, role: '', volume: .2, pan: 0, mute: false, solo: false,
      transpose: 0, gate: 1, profile: 'DVD_REFERENCE', mode: 'virtual' as const,
      overrides: {},
    }))
    const socket = await renderApp({ virtual: {
      enabled: true, config: { name: 'Four DVD', devices: dvd, dvdMode: 'independent' },
      report: {}, activity: {}, profiles: [{ id: 'DVD_REFERENCE', kind: 'DVD_SLED', parameters: {} }],
    } })

    fireEvent.change(screen.getByLabelText('DVD mode'), { target: { value: 'reinforcement' } })
    expect(socket.actions().at(-1)).toMatchObject({ action: 'set_virtual',
      config: { dvdMode: 'reinforcement', devices: dvd } })
  })

  it('shows tray movement and toggles acoustic accents', async () => {
    const tray = { id: 'DVD_TRAY_1', type: 'DVD_TRAY', name: 'DVD Tray 1', track: null,
      role: '', volume: .35, pan: 0, mute: false, solo: false, transpose: 0, gate: 1,
      profile: 'DVD_TRAY_REFERENCE', mode: 'virtual' as const, overrides: {} }
    const socket = await renderApp({ virtual: {
      enabled: true, config: { name: 'Trays', devices: [tray], trayEnabled: true },
      report: {}, activity: { DVD_TRAY_1: true },
      trayStatus: { DVD_TRAY_1: { phase: 'moving', note: 57, velocity: 110, duration: .245, strength: 'STRONG' } },
      profiles: [{ id: 'DVD_TRAY_REFERENCE', kind: 'DVD_TRAY', parameters: {} }],
    } })

    fireEvent.click(screen.getByText('Ustawienia DVD Tray 1'))
    expect(screen.getByText(/GM 57 · velocity 110 · STRONG · 245 ms/)).toBeTruthy()
    expect(screen.queryByLabelText('DVD Tray 1 mode')).toBeNull()
    fireEvent.click(screen.getByLabelText('DVD tray mechanical accents'))
    expect(socket.actions().at(-1)).toMatchObject({ action: 'set_virtual', config: { trayEnabled: false, devices: [tray] } })
  })

  it('enables idle reinforcement without changing normal devices', async () => {
    const device = { id: 'DVD_STEPPER_1', type: 'DVD_SLED', name: 'DVD Stepper 1', track: null,
      role: '', volume: .2, pan: 0, mute: false, solo: false, transpose: 0, gate: 1,
      profile: 'DVD_REFERENCE', mode: 'virtual' as const, overrides: {} }
    const socket = await renderApp({ virtual: { enabled: true,
      config: { name: 'Test', devices: [device], idleReinforcement: { enabled: false } },
      report: {}, activity: {}, profiles: [{ id: 'DVD_REFERENCE', kind: 'DVD_SLED', parameters: {} }] } })

    fireEvent.click(screen.getByLabelText('Idle device reinforcement'))
    expect(socket.actions().at(-1)).toMatchObject({ action: 'set_virtual',
      config: { devices: [device], idleReinforcement: { enabled: true } } })
  })

  it('shows each device LED from backend activity state', async () => {
    const socket = await renderApp({
      virtual: {
        enabled: true,
        config: { name: 'Test', devices: [{ id: 'a', type: 'FDD', name: 'FDD #1', track: 1,
          role: '', volume: .6, pan: 0, mute: false, solo: false, transpose: 0, gate: 1,
          profile: 'FDD_CURRENT', mode: 'virtual', overrides: {} }] },
        report: {}, activity: { a: false },
        profiles: [{ id: 'FDD_CURRENT', kind: 'FDD', parameters: {} }],
      },
    })

    expect(screen.getByLabelText('FDD #1: idle').classList.contains('is-active')).toBe(false)
    await act(async () => {
      socket.emit({ type: 'state', state: { ...STATE, virtual: {
        enabled: true, config: { name: 'Test', devices: [{ id: 'a', type: 'FDD', name: 'FDD #1', track: 1,
          role: '', volume: .6, pan: 0, mute: false, solo: false, transpose: 0, gate: 1,
          profile: 'FDD_CURRENT', mode: 'virtual', overrides: {} }] }, report: {}, activity: { a: true },
        profiles: [{ id: 'FDD_CURRENT', kind: 'FDD', parameters: {} }],
      } } })
    })
    expect(screen.getByLabelText('FDD #1: active').classList.contains('is-active')).toBe(true)
  })

  it('pokazuje plik, track i status sprzetu', async () => {
    await renderApp()

    expect(screen.getAllByLabelText('MIDI').length).toBeGreaterThan(0)
    expect((screen.getByLabelText('FDD Track') as HTMLSelectElement).value).toBe('1')
    expect(screen.getAllByText('/dev/cu.usbmodem14101').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Arduino connected').length).toBeGreaterThan(0)
  })

  it('nie tworzy fikcyjnego kafla przy odtwarzaniu manualnym', async () => {
    await renderApp()

    expect(screen.queryByRole('article')).toBeNull()
    expect(screen.getByRole('region', { name: 'Virtual Instrument Grid' })).toBeDefined()
  })

  it('przycisk play (stan stopped) wysyla akcje play', async () => {
    const socket = await renderApp({ state: 'stopped', noteName: null, frequency: null })

    fireEvent.click(screen.getByTitle('Play'))

    expect(socket.actions()).toContainEqual({ action: 'play' })
  })

  it('przycisk pauzy (stan playing) wysyla akcje pause', async () => {
    const socket = await renderApp()

    fireEvent.click(screen.getByTitle('Pauza'))

    expect(socket.actions()).toContainEqual({ action: 'pause' })
  })

  it('przycisk play (stan paused) wysyla akcje resume', async () => {
    const socket = await renderApp({ state: 'paused', noteName: null, frequency: null })

    fireEvent.click(screen.getByTitle('Play'))

    expect(socket.actions()).toContainEqual({ action: 'resume' })
  })

  it('przycisk stop wysyla akcje stop', async () => {
    const socket = await renderApp()

    fireEvent.click(screen.getByTitle('Stop'))

    expect(socket.actions()).toContainEqual({ action: 'stop' })
  })

  it('klikniecie paska wysyla dokladnie jeden seek', async () => {
    const socket = await renderApp()

    const slider = screen.getByRole('slider', { name: /Pozycja utworu/i })
    slider.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 200, height: 10, right: 200, bottom: 10, x: 0, y: 0 }) as DOMRect
    slider.setPointerCapture = () => {}
    slider.releasePointerCapture = () => {}

    fireEvent.pointerDown(slider, { clientX: 100, pointerId: 1 })
    fireEvent.pointerUp(slider, { clientX: 100, pointerId: 1 })

    const seeks = socket.actions().filter((action) => action.action === 'seek')

    expect(seeks).toHaveLength(1)
    expect(seeks[0].position).toBeCloseTo(30, 0)
  })

  it('przeciaganie paska nie spamuje backendu', async () => {
    const socket = await renderApp()

    const slider = screen.getByRole('slider', { name: /Pozycja utworu/i })
    slider.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 200, height: 10, right: 200, bottom: 10, x: 0, y: 0 }) as DOMRect
    slider.setPointerCapture = () => {}
    slider.releasePointerCapture = () => {}

    fireEvent.pointerDown(slider, { clientX: 10, pointerId: 1 })

    for (const x of [20, 40, 60, 80, 100, 120]) {
      fireEvent.pointerMove(slider, { clientX: x, pointerId: 1 })
    }

    expect(socket.actions().filter((action) => action.action === 'seek')).toHaveLength(0)

    fireEvent.pointerUp(slider, { clientX: 120, pointerId: 1 })

    expect(socket.actions().filter((action) => action.action === 'seek')).toHaveLength(1)
  })

  it('wybor tracku i transpozycji idzie do backendu', async () => {
    const socket = await renderApp()

    await waitFor(() => expect(screen.getByLabelText(/FDD Track/i)).toBeDefined())

    fireEvent.change(screen.getByLabelText(/FDD Track/i), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText(/FDD transpose/i), { target: { value: 'high' } })

    expect(socket.actions()).toContainEqual({ action: 'set_track', track: 1 })
    expect(socket.actions()).toContainEqual({ action: 'set_transpose', mode: 'high' })
  })

  it('wgranie pliku MIDI wysyla POST i przelacza na nowy plik', async () => {
    const socket = await renderApp()

    // Import aranzacji tez ma ukryty input - wybieramy ten od plikow MIDI.
    const input = document.querySelector('input[type="file"][accept*=".mid"]') as HTMLInputElement
    expect(input).not.toBeNull()

    const file = new File([new Uint8Array([77, 84, 104, 100])], 'nowy.mid', {
      type: 'audio/midi',
    })

    fireEvent.change(input, { target: { files: [file] } })

    await waitFor(() =>
      expect(socket.actions()).toContainEqual({ action: 'set_file', file: 'nowy.mid' }),
    )

    expect(fetch).toHaveBeenCalledWith(
      '/api/files',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('selektor MIDI ma przycisk wgrywania', async () => {
    await renderApp()

    expect(screen.getByText('Wgraj plik MIDI')).toBeDefined()
    expect(document.querySelector('input[accept*=".mid"]')).not.toBeNull()
  })

  it('hardware settings expose port selection without opening Advanced', async () => {
    await renderApp({ hardware: { ...STATE.hardware, connected: false, port: null, error: 'wykrylem kilka rownorzędnych portow' } }, false)
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }))
    expect(await screen.findByRole('combobox', { name: 'Port szeregowy' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Odśwież porty' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Połącz' })).toBeTruthy()
  })

  it('virtual settings omit serial port controls', async () => {
    await renderApp({ virtual: { enabled: true, runtimeMode: 'virtual', config: { name: 'Test', devices: [] }, report: {}, activity: {}, profiles: [] } }, false)
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }))
    expect(screen.queryByRole('combobox', { name: 'Port szeregowy' })).toBeNull()
  })

  it('switches output to virtual instruments only while stopped', async () => {
    const virtual = { enabled: false, runtimeMode: 'hardware' as const,
      config: { name: 'Test', devices: [] }, report: {}, activity: {}, profiles: [] }
    const socket = await renderApp({ state: 'stopped', virtual }, false)
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }))
    const checkbox = screen.getByRole('checkbox', { name: 'Graj na instrumentach wirtualnych' }) as HTMLInputElement
    expect(checkbox.checked).toBe(false)
    fireEvent.click(checkbox)
    expect(socket.actions().at(-1)).toEqual({ action: 'set_output_mode', virtual: true })
  })

  it('reconnect wysyla wybrany aktualny port', async () => {
    const socket = await renderApp()

    fireEvent.click(screen.getByText('Reconnect'))

    expect(socket.actions()).toContainEqual({ action: 'reconnect', port: '/dev/cu.usbmodem14101' })
  })

  it('Start i Stop bebna wysylaja akcje', async () => {
    const socket = await renderApp()

    fireEvent.click(screen.getByTitle('Start bębna'))
    fireEvent.click(screen.getByTitle('Stop bębna'))

    expect(socket.actions()).toContainEqual({ action: 'start_drum' })
    expect(socket.actions()).toContainEqual({ action: 'stop_drum' })
  })

  it('suwak PWM wysyla set_drum z finalna wartoscia', async () => {
    const socket = await renderApp()

    const slider = screen.getByLabelText('PWM (głośność)')

    fireEvent.pointerDown(slider)
    fireEvent.change(slider, { target: { value: '120' } })
    fireEvent.pointerUp(slider)

    const sent = socket.actions().filter((action) => action.action === 'set_drum')

    expect(sent.length).toBeGreaterThanOrEqual(1)
    expect(sent[sent.length - 1]).toEqual({ action: 'set_drum', value: 120 })
  })

  it('suwak tonu wysyla set_drum_tone', async () => {
    const socket = await renderApp()

    const slider = screen.getByLabelText('Ton (wysokość)')

    fireEvent.pointerDown(slider)
    fireEvent.change(slider, { target: { value: '440' } })
    fireEvent.pointerUp(slider)

    const sent = socket.actions().filter((action) => action.action === 'set_drum_tone')

    expect(sent[sent.length - 1]).toEqual({ action: 'set_drum_tone', hz: 440 })
  })

  it('pokazuje stan bebna z WebSocketa', async () => {
    await renderApp({
      drum: {
        value: 128,
        output: 128,
        toneHz: 300,
        lastValue: 128,
        running: true,
        connected: true,
        minHz: 20,
        maxHz: 2000,
        controlledBy: 'midi',
        drive: 74,
        range: { minHz: 110, maxHz: 880 },
        transpose: 'high',
        strategy: 'highest',
        midiTrack: 2,
        midiTrackName: 'Thom Piano',
        midiNote: 64,
        midiNoteName: 'E4',
        midiFrequency: 329.63,
      },
    })

    expect(screen.getByText('Running')).toBeDefined()
    // W trybie MIDI panel pokazuje, kto steruje, jaka nuta i jakim tonem.
    expect(screen.getByText('MIDI CONTROLLED')).toBeDefined()
    expect(screen.getByText('Thom Piano')).toBeDefined()
    expect(screen.getByText('E4')).toBeDefined()
    expect(screen.getAllByText('300.00 Hz').length).toBeGreaterThanOrEqual(1)
  })

  it('wybor tracku bebna idzie do backendu', async () => {
    const socket = await renderApp()

    await waitFor(() => expect(screen.getByLabelText(/VHS Drum Track/i)).toBeDefined())

    fireEvent.change(screen.getByLabelText(/VHS Drum Track/i), { target: { value: '1' } })
    expect(socket.actions()).toContainEqual({ action: 'set_drum_track', track: 1 })

    fireEvent.change(screen.getByLabelText(/VHS Drum Track/i), { target: { value: '' } })
    expect(socket.actions()).toContainEqual({ action: 'set_drum_track', track: null })
  })

  it('tryb transpozycji bebna idzie do backendu', async () => {
    const socket = await renderApp()

    fireEvent.change(screen.getByLabelText(/VHS Drum transpose/i), { target: { value: 'high' } })

    expect(socket.actions()).toContainEqual({ action: 'set_drum_transpose', mode: 'high' })
  })

  it('wybor tracku HDD idzie do backendu', async () => {
    const socket = await renderApp()

    await waitFor(() => expect(screen.getByLabelText(/HDD Track/i)).toBeDefined())

    fireEvent.change(screen.getByLabelText(/HDD Track/i), { target: { value: '1' } })
    expect(socket.actions()).toContainEqual({ action: 'set_hdd_track', track: 1 })

    fireEvent.change(screen.getByLabelText(/HDD Track/i), { target: { value: '' } })
    expect(socket.actions()).toContainEqual({ action: 'set_hdd_track', track: null })
  })

  it('wybor nuty HDD idzie do backendu', async () => {
    const socket = await renderApp({
      hdd: {
        connected: true,
        busy: false,
        count: 0,
        controlledBy: 'midi',
        midiTrack: 1,
        midiTrackName: 'Bębny',
        note: null,
        rate: null,
        notes: [
          { note: 40, name: 'Werbel', count: 339 },
          { note: 36, name: 'Stopa', count: 421 },
        ],
        lastNote: null,
        lastNoteName: null,
      },
    })

    fireEvent.change(screen.getByLabelText(/HDD Note/i), { target: { value: '40' } })
    expect(socket.actions()).toContainEqual({ action: 'set_hdd_note', note: 40 })

    fireEvent.change(screen.getByLabelText(/HDD Note/i), { target: { value: '' } })
    expect(socket.actions()).toContainEqual({ action: 'set_hdd_note', note: null })
  })

  it('gestosc HDD idzie do backendu', async () => {
    const socket = await renderApp({
      hdd: {
        connected: true,
        busy: false,
        count: 0,
        controlledBy: 'midi',
        midiTrack: 1,
        midiTrackName: 'Selway',
        note: 40,
        rate: null,
        notes: [{ note: 40, name: 'Werbel', count: 339 }],
        lastNote: null,
        lastNoteName: null,
      },
    })

    fireEvent.change(screen.getByLabelText(/HDD Gęstość/i), { target: { value: '1' } })
    expect(socket.actions()).toContainEqual({ action: 'set_hdd_rate', rate: 1 })

    fireEvent.change(screen.getByLabelText(/HDD Gęstość/i), { target: { value: '' } })
    expect(socket.actions()).toContainEqual({ action: 'set_hdd_rate', rate: null })
  })

  it('status HDD widoczny gdy track wybrany', async () => {
    await renderApp({
      hdd: {
        connected: true,
        busy: false,
        count: 12,
        controlledBy: 'midi',
        midiTrack: 1,
        midiTrackName: 'Bębny',
        note: 40,
        rate: null,
        notes: [
          { note: 42, name: 'Hi-hat zamk.', count: 839 },
          { note: 40, name: 'Werbel', count: 339 },
        ],
        lastNote: 36,
        lastNoteName: 'C2',
      },
    })

    expect(screen.getByText(/HDD: Bębny · Werbel · 12 uderzeń/i)).toBeDefined()
  })

  it('podczas MIDI panel bebna nie pokazuje suwakow recznych', async () => {
    await renderApp({
      drum: {
        value: 74,
        output: 74,
        toneHz: 523,
        lastValue: 64,
        running: true,
        connected: true,
        minHz: 20,
        maxHz: 2000,
        controlledBy: 'midi',
        drive: 74,
        range: { minHz: 110, maxHz: 880 },
        transpose: 'high',
        strategy: 'highest',
        midiTrack: 2,
        midiTrackName: 'Thom Piano',
        midiNote: 72,
        midiNoteName: 'C5',
        midiFrequency: 523.25,
      },
    })

    expect(screen.queryByTitle('Start bębna')).toBeNull()
    expect(screen.queryByLabelText('PWM (głośność)')).toBeNull()
  })

  it('przy rozlaczonym Arduino beben pokazuje Disconnected i jest zablokowany', async () => {
    await renderApp({
      hardware: {
        connected: false,
        port: null,
        label: null,
        error: 'brak',
        warning: null,
        log: [],
      },
      drum: {
        value: 0,
        output: null,
        toneHz: 0,
        lastValue: 64,
        running: false,
        connected: false,
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
      },
    })

    expect(screen.getByText('Disconnected')).toBeDefined()
    expect((screen.getByTitle('Start bębna') as HTMLButtonElement).disabled).toBe(true)
  })

  it('import aranzacji pozostaje w Advanced / Manual hardware', async () => {
    const documents: Array<Record<string, unknown>> = []
    const arrangement = {
      schemaVersion: 1, name: 'Imported song', midi: { file: 'song.mid', sha256: 'abc', tracks: [] },
      devices: [{ id: 'fdd', type: 'FDD', name: 'FDD', track: 1, role: '', volume: 1, pan: 0,
        mute: false, solo: false, transpose: 0, gate: 1, profile: 'FDD_CURRENT', mode: 'real', overrides: {} }],
      rules: [],
    }
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
      if (url === '/api/arrangement' && init?.method === 'PUT') {
        documents.push(JSON.parse(String(init.body)) as Record<string, unknown>)
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ arrangement, notes: [], midiIdentity: arrangement.midi, tracks: [], revision: 2 }) } as Response)
      }
      return mockFetch(url, init)
    }))

    await renderApp()

    expect(screen.getAllByRole('button', { name: 'Import Arrangement JSON' })).toHaveLength(1)

    const input = screen.getAllByLabelText('Arrangement JSON file').at(-1) as HTMLInputElement
    Object.defineProperty(File.prototype, 'text', { configurable: true, value: vi.fn(async () => JSON.stringify(arrangement)) })
    fireEvent.change(input, { target: { files: [new File(['{}'], 'song.orchestra.json')] } })

    await waitFor(() => expect(documents).toHaveLength(1))
    expect(documents[0].name).toBe('Imported song')
    await waitFor(() => expect(screen.getByText(/Imported .Imported song./)).toBeDefined())
  })

  it('toggles device Enabled without exposing runtime mode', async () => {
    const device = { id: 'a', type: 'FDD', name: 'FDD #1', track: 1, role: '', volume: .6, pan: 0,
      mute: false, solo: false, transpose: 0, gate: 1, profile: 'FDD_CURRENT', mode: 'virtual' as const, overrides: {} }
    const socket = await renderApp({
      virtual: { enabled: true, config: { name: 'Test', devices: [device] }, report: {}, activity: {},
        profiles: [{ id: 'FDD_CURRENT', kind: 'FDD', parameters: {} }] },
    })


    expect(screen.queryByLabelText('FDD #1 mode')).toBeNull()
    const toggle = screen.getByRole('switch', { name: 'FDD #1 Enabled' })
    expect(toggle.getAttribute('aria-checked')).toBe('true')
    fireEvent.click(toggle)
    expect(socket.actions().at(-1)).toMatchObject({
      action: 'set_virtual', config: { devices: [{ id: 'a', enabled: false }] },
    })
    expect(toggle.getAttribute('aria-checked')).toBe('false')
    await act(async () => socket.emit({ type: 'state', state: { ...STATE, virtual: {
      enabled: true, config: { name: 'Test', devices: [device] }, report: {}, activity: {}, profiles: [] } } }))
    expect(toggle.getAttribute('aria-checked')).toBe('false')
    await act(async () => socket.emit({ type: 'state', state: { ...STATE, virtual: {
      enabled: true, config: { name: 'Test', devices: [{ ...device, enabled: false }] },
      report: {}, activity: {}, profiles: [] } } }))
    expect(screen.getByRole('switch', { name: 'FDD #1 Enabled' }).getAttribute('aria-checked')).toBe('false')
    expect(screen.queryByRole('article', { name: 'FDD #1' })).toBeNull()
    fireEvent.click(screen.getByRole('switch', { name: 'FDD #1 Enabled' }))
    expect(socket.actions().at(-1)).toMatchObject({ config: { devices: [{ enabled: true }] } })
  })

  it('pokazuje ktore instancje trafily na fizyczne linie Serial', async () => {
    await renderApp({
      arrangementHardware: {
        active: true, connected: true,
        lanes: { fdd: { deviceId: 'fdd', name: 'FDD · Yorke', type: 'FDD' } },
        unmapped: [{ deviceId: 'fdd-2', name: 'FDD · extra', type: 'FDD', reason: 'LANE_TAKEN', lane: 'fdd', boundTo: 'fdd' }],
      },
    })


    expect(screen.getByText('Hardware lanes')).toBeDefined()
    expect(screen.getByText(/FDD · Yorke/)).toBeDefined()
    expect(screen.getByText(/lane fdd already used by fdd/)).toBeDefined()
  })

  it('w trakcie homingu pokazuje ze Play czeka w kolejce', async () => {
    await renderApp({
      hardware: { connected: false, port: null, label: null, error: null, warning: null, log: [],
        connecting: true, pendingPlay: true },
    })

    expect(screen.getByText('Arduino: homing…')).toBeDefined()
    expect(screen.getByText(/Play jest w kolejce/)).toBeDefined()
    expect(screen.getByText('Arduino disconnected')).toBeDefined()
    // Główny monitor pokazuje wyłącznie rzeczywisty stan połączenia.
    expect(screen.queryByText('Arduino connected')).toBeNull()
  })

  it('bez homingu pokazuje zwykle rozlaczenie i blad', async () => {
    await renderApp({
      hardware: { connected: false, port: null, label: null, error: 'brak polaczenia z Arduino',
        warning: null, log: [], connecting: false, pendingPlay: false },
    })

    expect(screen.getAllByText('Arduino disconnected').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/brak polaczenia z Arduino/).length).toBeGreaterThan(0)
    expect(screen.queryByText('Arduino: homing…')).toBeNull()
  })
  it('shows loading immediately, waits for the audio clock and prevents duplicate Play', async () => {
    const virtual = { enabled: true, config: { name: 'Test', devices: [] }, report: {}, activity: {}, profiles: [], audioClockRunning: false }
    const socket = await renderApp({ state: 'stopped', virtual }, false)
    fireEvent.click(screen.getByTitle('Play'))
    expect((screen.getByRole('button', { name: 'Ładowanie odtwarzania' }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByRole('button', { name: 'Ładowanie odtwarzania' }).classList.contains('stopped')).toBe(true)
    await act(async () => socket.emit({ type: 'state', state: { ...STATE, state: 'stopped', virtual } }))
    expect(screen.getByRole('button', { name: 'Ładowanie odtwarzania' })).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: 'Ładowanie odtwarzania' }))
    expect(socket.actions().filter(a => a.action === 'play')).toHaveLength(1)
    await act(async () => socket.emit({ type: 'state', completedAction: 'play', state: { ...STATE, virtual } }))
    expect(screen.getByRole('button', { name: 'Ładowanie odtwarzania' })).toBeDefined()
    await act(async () => socket.emit({ type: 'state', state: { ...STATE, virtual: { ...virtual, audioClockRunning: true } } }))
    expect(screen.getByRole('button', { name: 'Pauza' }).getAttribute('aria-busy')).toBe('false')
  })
  it('retains the orange pause style throughout resume, including waiting for audio after acknowledgment', async () => {
    const virtual = { enabled: true, config: { name: 'Test', devices: [] }, report: {}, activity: {}, profiles: [], audioClockRunning: false }
    const socket = await renderApp({ state: 'paused', virtual }, false)
    fireEvent.click(screen.getByTitle('Play'))
    const loading = () => screen.getByRole('button', { name: 'Ładowanie odtwarzania' })
    expect(loading().classList.contains('paused')).toBe(true)
    await act(async () => socket.emit({ type: 'state', completedAction: 'resume', state: { ...STATE, virtual } }))
    expect(loading().classList.contains('paused')).toBe(true)
    expect(loading().classList.contains('playing')).toBe(false)
    await act(async () => socket.emit({ type: 'state', state: { ...STATE, virtual: { ...virtual, audioClockRunning: true } } }))
    expect(screen.getByRole('button', { name: 'Pauza' }).classList.contains('playing')).toBe(true)
  })
  it('waits for Arduino READY, then shows playback, and clears rejected starts', async () => {
    const socket = await renderApp({ state: 'stopped' }, false)
    fireEvent.click(screen.getByTitle('Play'))
    await act(async () => socket.emit({ type: 'state', completedAction: 'play', state: { ...STATE, state: 'stopped', hardware: { ...STATE.hardware, connected: false, connecting: true, pendingPlay: true } } }))
    expect(screen.getByRole('button', { name: 'Ładowanie odtwarzania' })).toBeDefined()
    await act(async () => socket.emit({ type: 'state', state: STATE }))
    expect(screen.getByRole('button', { name: 'Pauza' })).toBeDefined()
    await act(async () => socket.emit({ type: 'state', state: { ...STATE, state: 'stopped' } }))
    fireEvent.click(screen.getByTitle('Play'))
    await act(async () => socket.emit({ type: 'state', completedAction: 'play', state: { ...STATE, state: 'stopped' } }))
    expect(screen.getByRole('button', { name: 'Play' })).toBeDefined()
    fireEvent.click(screen.getByTitle('Play'))
    await act(async () => socket.emit({ type: 'error', message: 'Start failed' }))
    expect(screen.getByRole('button', { name: 'Play' })).toBeDefined()
    fireEvent.click(screen.getByTitle('Play'))
    await act(async () => socket.onclose?.(new CloseEvent('close')))
    expect(screen.queryByRole('button', { name: 'Ładowanie odtwarzania' })).toBeNull()
  })

})
