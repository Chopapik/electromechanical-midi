import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ArrangementImport, remapDocument } from './ArrangementImport'
import type { ArrangementDocument } from '../types'

const document: ArrangementDocument = {
  schemaVersion: 1, name: 'Song', midi: { file: 'song.mid', sha256: 'abc', tracks: [{ index: 0, name: 'Melody' }] },
  devices: [{ id: 'fdd', type: 'FDD', name: 'FDD #1', track: 0, role: '', volume: 1, pan: 0,
    mute: false, solo: false, transpose: 0, gate: 1, profile: 'FDD_CURRENT', mode: 'real', overrides: {} }],
  rules: [{ id: 'melody', source: { track: 0 }, destination: { deviceId: 'fdd' },
    transform: { gate: 1, transpose: 0, octaveFold: true, strategy: 'first' } }],
}

let calls: Array<{ url: string; init?: RequestInit }> = []
const respond = (status: number, body: unknown) =>
  ({ ok: status >= 200 && status < 300, status, json: async () => body }) as Response

beforeEach(() => {
  calls = []
  Object.defineProperty(File.prototype, 'text', { configurable: true, value: vi.fn(async () => JSON.stringify(document)) })
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

const chooseFile = () =>
  fireEvent.change(screen.getByLabelText('Arrangement JSON file'), { target: { files: [new File(['{}'], 'song.orchestra.json')] } })

describe('ArrangementImport', () => {
  it('wysyla dokument na backend i pokazuje podsumowanie', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init })
      return respond(200, { arrangement: document, notes: [], midiIdentity: document.midi, tracks: [], revision: 2 })
    }))
    render(<ArrangementImport />)
    chooseFile()
    await waitFor(() => expect(screen.getByText(/Imported .Song./)).toBeDefined())
    const put = calls.find(call => call.init?.method === 'PUT')
    expect(put?.url).toBe('/api/arrangement')
    expect((JSON.parse(String(put?.init?.body)) as ArrangementDocument).devices[0].mode).toBe('real')
  })

  it('rozroznia niezgodnosc MIDI od braku wczytanego pliku', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => respond(409, { detail: 'load MIDI first' })))
    render(<ArrangementImport />)
    chooseFile()
    await waitFor(() => expect(screen.getByText('load MIDI first')).toBeDefined())
    expect(screen.queryByText('Arrangement MIDI mismatch')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Apply remapping' })).toBeNull()
  })

  it('przy niezgodnosci pokazuje mapowanie i nie wysyla nic bez potwierdzenia', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init })
      if (init?.method === 'PUT') {
        return respond(409, { detail: { mismatches: [{ kind: 'track', index: 0, expected: 'Old', actual: 'Melody' }] } })
      }
      return respond(200, { arrangement: document, notes: [], midiIdentity: { file: 'other.mid', sha256: 'z', tracks: [] },
        tracks: [{ index: 3, name: 'Melody', isDrums: false, noteCount: 5 }], revision: 1 })
    }))
    render(<ArrangementImport />)
    chooseFile()
    await waitFor(() => expect(screen.getByText('Arrangement MIDI mismatch')).toBeDefined())
    expect(calls.filter(call => call.init?.method === 'PUT')).toHaveLength(1)

    fireEvent.click(screen.getByRole('button', { name: 'Apply remapping' }))
    await waitFor(() => expect(calls.filter(call => call.init?.method === 'PUT')).toHaveLength(2))
    const remapped = JSON.parse(String(calls.filter(call => call.init?.method === 'PUT')[1].init?.body)) as ArrangementDocument
    expect(remapped.rules[0].source.track).toBe(3)
    expect(remapped.midi.file).toBe('other.mid')
  })

  it('odrzuca niepoprawny JSON bez wolania backendu', async () => {
    Object.defineProperty(File.prototype, 'text', { configurable: true, value: vi.fn(async () => 'not json') })
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    render(<ArrangementImport />)
    chooseFile()
    await waitFor(() => expect(screen.getByText('Invalid arrangement JSON')).toBeDefined())
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe('remapDocument', () => {
  it('przepisuje indeksy trackow i tozsamosc MIDI', () => {
    const withTracks: ArrangementDocument = {
      ...document,
      rules: [{ ...document.rules[0], source: { track: 0, tracks: [0, 1] } }],
    }
    const next = remapDocument(withTracks, { 0: 3, 1: 4 }, { file: 'other.mid', sha256: 'z', tracks: [] })
    expect(next.rules[0].source.track).toBe(3)
    expect(next.rules[0].source.tracks).toEqual([3, 4])
    expect(next.midi.file).toBe('other.mid')
    // Oryginal nie moze byc zmutowany - import bywa powtarzany.
    expect(withTracks.rules[0].source.track).toBe(0)
    expect(withTracks.midi.file).toBe('song.mid')
  })
})
