/**
 * Wspolny import aranzacji (JSON z ustawieniami instrumentow).
 *
 * Ten sam dokument obsluguje wirtualizacje i realny sprzet: o tym, dokad
 * trafia instancja, decyduje jej pole `mode` ('virtual' | 'real' | 'hybrid').
 * Dlatego import jest jeden i widoczny w kazdej zakladce - nie ma osobnego
 * pliku "dla sprzetu" i "dla wirtualizacji".
 */

import { useRef, useState } from 'react'
import type { ArrangementDocument, ArrangementView } from '../types'

export interface ArrangementMismatch {
  kind: string
  index?: number
  expected: string | number | { file?: string; sha256?: string }
  actual: string | number | { file?: string; sha256?: string } | null
}

interface Props {
  label?: string
  className?: string
  onImported?: (document: ArrangementDocument) => void
}

/** Podmienia indeksy trackow w regulach na te z aktualnie wczytanego MIDI. */
export function remapDocument(
  document: ArrangementDocument,
  remap: Record<number, number>,
  midiIdentity: ArrangementDocument['midi'],
): ArrangementDocument {
  const next = JSON.parse(JSON.stringify(document)) as ArrangementDocument

  for (const rule of next.rules) {
    if (rule.source.track !== undefined) rule.source.track = remap[rule.source.track] ?? rule.source.track
    if (rule.source.tracks) rule.source.tracks = rule.source.tracks.map(index => remap[index] ?? index)
  }

  next.midi = midiIdentity

  return next
}

export function ArrangementImport({ label = 'Import Arrangement JSON', className = '', onImported }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [message, setMessage] = useState('')
  const [failed, setFailed] = useState(false)
  const [imported, setImported] = useState<ArrangementDocument | null>(null)
  const [mismatches, setMismatches] = useState<ArrangementMismatch[]>([])
  const [remap, setRemap] = useState<Record<number, number>>({})
  const [remapTracks, setRemapTracks] = useState<ArrangementView['tracks']>([])

  const currentView = async (): Promise<ArrangementView | null> => {
    const response = await fetch('/api/arrangement')

    return response.ok ? await response.json() as ArrangementView : null
  }

  const report = (text: string, isFailure = false) => {
    setMessage(text)
    setFailed(isFailure)
  }

  const submit = async (document: ArrangementDocument) => {
    const response = await fetch('/api/arrangement', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(document),
    })

    if (response.status === 409) {
      const body = await response.json().catch(() => ({})) as { detail?: string | { mismatches?: ArrangementMismatch[] } }

      // 409 to nie zawsze niezgodnosc MIDI: backend tak samo odpowiada na
      // "najpierw wczytaj MIDI" i na trwajace odtwarzanie bez sprzetu.
      if (typeof body.detail === 'string' || !body.detail?.mismatches) {
        report(typeof body.detail === 'string' ? body.detail : 'Import rejected', true)
        return
      }

      const mismatchList = body.detail.mismatches
      const view = await currentView()
      const suggested: Record<number, number> = {}

      for (const track of document.midi?.tracks ?? []) {
        const byName = view?.tracks.find(candidate => candidate.name === track.name)
        suggested[track.index] = byName?.index
          ?? (view?.tracks.some(candidate => candidate.index === track.index) ? track.index : 0)
      }

      setImported(document)
      setMismatches(mismatchList)
      setRemap(suggested)
      setRemapTracks(view?.tracks ?? [])
      report('Arrangement MIDI mismatch — review the track mapping below or cancel.', true)
      return
    }

    if (!response.ok) {
      const body = await response.json().catch(() => ({})) as { detail?: unknown }
      report(typeof body.detail === 'string' ? body.detail : `Import failed (HTTP ${response.status})`, true)
      return
    }

    const next = await response.json() as ArrangementView
    setImported(null)
    setMismatches([])
    report(`Imported “${next.arrangement?.name ?? document.name}” — ` +
      `${next.arrangement?.devices.length ?? document.devices.length} devices, ` +
      `${next.arrangement?.rules.length ?? document.rules.length} rules`)
    if (next.arrangement) onImported?.(next.arrangement)
  }

  const choose = async (file: File) => {
    setImported(null)
    setMismatches([])

    let document: ArrangementDocument

    try {
      document = JSON.parse(await file.text()) as ArrangementDocument
    } catch {
      report('Invalid arrangement JSON', true)
      return
    }

    try {
      await submit(document)
    } catch {
      report('Could not reach the backend', true)
    }
  }

  const applyRemap = async () => {
    if (!imported) return

    const view = await currentView()

    if (!view?.midiIdentity) {
      report('No MIDI is loaded — load a file first', true)
      return
    }

    try {
      await submit(remapDocument(imported, remap, view.midiIdentity))
    } catch {
      report('Could not reach the backend', true)
    }
  }

  const cancel = () => {
    setImported(null)
    setMismatches([])
    report('Import cancelled')
  }

  return <div className={`arrangement-import ${className}`.trim()}>
    <button type="button" onClick={() => inputRef.current?.click()}>{label}</button>
    <input ref={inputRef} type="file" accept=".json,application/json" hidden
      aria-label="Arrangement JSON file"
      onChange={event => {
        const chosen = event.target.files?.[0]
        if (chosen) void choose(chosen)
        event.target.value = ''
      }} />
    {message && <p role="status" className={failed ? 'import-error' : 'muted'}>{message}</p>}
    {imported && <div className="arrangement-mismatch" role="alert">
      <strong>Arrangement MIDI mismatch</strong>
      {mismatches.map((item, index) => <p key={index}>{item.kind === 'midi'
        ? 'Filename or fingerprint differs.'
        : `Track ${item.index}: expected “${String(item.expected)}”, loaded “${String(item.actual ?? 'missing')}”.`}</p>)}
      {imported.midi.tracks
        .filter(track => imported.rules.some(rule => rule.source.track === track.index || rule.source.tracks?.includes(track.index)))
        .map(track => <label key={track.index}>Expected {track.index} — {track.name} →{' '}
          <select value={remap[track.index] ?? 0}
            onChange={event => setRemap(values => ({ ...values, [track.index]: Number(event.target.value) }))}>
            {remapTracks.map(actual => <option key={actual.index} value={actual.index}>{actual.index} — {actual.name}</option>)}
          </select></label>)}
      <button type="button" onClick={() => void applyRemap()}>Apply remapping</button>
      <button type="button" onClick={cancel}>Cancel import</button>
    </div>}
  </div>
}
