import { useEffect, useRef, useState } from 'react'
import type { ArrangementDocument, ArrangementRule, ArrangementView, PlayerState } from '../types'
import { ArrangementImport } from './ArrangementImport'
import { AutoArrangerReport } from './AutoArrangerReport'
import { PianoRoll, deviceColor, sourceColor, type ViewMode } from './PianoRoll'

const STATUS = ['ACCEPTED', 'FOLDED', 'DELAYED', 'DROPPED', 'UNASSIGNED']
const formatTime = (seconds: number) => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${(seconds % 60).toFixed(3).padStart(6, '0')}`
const clone = (value: ArrangementDocument): ArrangementDocument => JSON.parse(JSON.stringify(value)) as ArrangementDocument
const exactRule = (rule: ArrangementRule, track: number, note: number) => rule.source.track === track && rule.source.includeNotes?.length === 1 && rule.source.includeNotes[0] === note
const newRule = (id: string, track: number, deviceId: string | null, note?: number): ArrangementRule => ({
  id, source: { track, ...(note === undefined ? {} : { includeNotes: [note] }) },
  destination: { deviceId }, transform: { gate: 1, transpose: 0, octaveFold: true, strategy: 'first' },
})

interface Props { file: string | null; state: PlayerState | null; seek: (seconds: number) => void }
export function ArrangementEditor({ file, state, seek }: Props) {
  const [view, setView] = useState<ArrangementView | null>(null)
  const [mode, setMode] = useState<ViewMode>('source')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [drumTrack, setDrumTrack] = useState<number | null>(null)
  const [hiddenTracks, setHiddenTracks] = useState<Set<number>>(new Set())
  const [hiddenDevices, setHiddenDevices] = useState<Set<string>>(new Set())
  const [message, setMessage] = useState('')
  const [loadError, setLoadError] = useState('')
  const [retry, setRetry] = useState(0)
  const [imported, setImported] = useState<ArrangementDocument | null>(null)
  const [mismatches, setMismatches] = useState<Array<{ kind: string; index?: number; expected: string; actual: string | null }>>([])
  const [remap, setRemap] = useState<Record<number, number>>({})
  const latest = useRef<ArrangementDocument | null>(null)
  const confirmed = useRef<ArrangementDocument | null>(null)
  const pending = useRef<Promise<void>>(Promise.resolve())
  const editVersion = useRef(0)
  const revision = state?.arrangementRevision

  useEffect(() => {
    if (!file) { setView(null); setLoadError(''); return }
    let cancelled = false
    const version = editVersion.current
    setLoadError('')
    setView(previous => previous?.midiIdentity?.file === file ? previous : null)
    const failure = async (response: Response) => {
      if (response.status === 404) return 'Backend nie obsługuje jeszcze Arrangement. Uruchom ponownie ./scripts/dev.sh i odśwież stronę.'
      const body = await response.json().catch(() => ({})) as { detail?: string }
      return typeof body.detail === 'string' ? body.detail : `Nie udało się wczytać aranżacji (HTTP ${response.status}).`
    }
    const load = async () => {
      const response = await fetch('/api/arrangement')
      if (!response.ok) throw new Error(await failure(response))
      let data = await response.json() as ArrangementView
      if (!data.arrangement) {
        const initialized = await fetch('/api/arrangement/initialize', { method: 'POST' })
        if (!initialized.ok) throw new Error(await failure(initialized))
        data = await initialized.json() as ArrangementView
      }
      if (!cancelled && version === editVersion.current) {
        setView(data); latest.current = data.arrangement; confirmed.current = data.arrangement
      }
    }
    load().catch((error: unknown) => { if (!cancelled) setLoadError(error instanceof Error ? error.message : 'Nie udało się wczytać aranżacji.') })
    return () => { cancelled = true }
  }, [file, revision, retry])

  const send = async (document: ArrangementDocument, isImport: boolean, version: number) => {
    const response = await fetch('/api/arrangement', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(document) })
    if (response.status === 409 && isImport) {
      const body = await response.json() as { detail?: { mismatches?: typeof mismatches } }
      setImported(document); setMismatches(body.detail?.mismatches ?? [])
      const suggested: Record<number, number> = {}
      for (const track of document.midi.tracks) {
        const byName = view?.tracks.find(t => t.name === track.name)
        suggested[track.index] = byName?.index ?? (view?.tracks.some(t => t.index === track.index) ? track.index : 0)
      }
      setRemap(suggested)
      setMessage('MIDI mismatch. Review the track mapping below or cancel import.')
      return
    }
    if (!response.ok) {
      const body = await response.json() as { detail?: string }
      setMessage(typeof body.detail === 'string' ? body.detail : `Update failed (${response.status})`)
      if (version === editVersion.current) {
        latest.current = confirmed.current
        setView(v => v ? { ...v, arrangement: confirmed.current } : v)
      }
      return
    }
    const next = await response.json() as ArrangementView
    confirmed.current = next.arrangement
    if (version === editVersion.current) { setView(next); latest.current = next.arrangement }
    setImported(null); setMismatches([]); setMessage('Arrangement updated')
  }
  const put = (document: ArrangementDocument, isImport = false): Promise<void> => {
    const version = ++editVersion.current
    if (!isImport) {
      latest.current = document
      setView(v => v ? { ...v, arrangement: document } : v)
    }
    const operation = pending.current.then(() => send(document, isImport, version))
    pending.current = operation.catch(() => {
      setMessage('Could not update arrangement')
      if (version === editVersion.current) {
        latest.current = confirmed.current
        setView(v => v ? { ...v, arrangement: confirmed.current } : v)
      }
    })
    return pending.current
  }
  const change = (edit: (document: ArrangementDocument) => void) => {
    const current = latest.current
    if (!current) return
    const next = clone(current)
    edit(next)
    void put(next)
  }
  const setNoteRoute = (track: number, note: number, deviceId: string | null, articulation?: string | null) => change(doc => {
    doc.rules = doc.rules.filter(rule => !exactRule(rule, track, note))
    const rule = newRule(`note-${track}-${note}`, track, deviceId, note)
    rule.articulation = articulation ?? null
    doc.rules.push(rule)
  })
  const save = async () => {
    const response = await fetch('/api/arrangement/save', { method: 'POST' })
    const data = await response.json() as { file?: string; detail?: string }
    setMessage(response.ok ? `Saved ${data.file}` : (data.detail ?? 'Save failed'))
  }
  const loadSaved = async () => {
    const response = await fetch('/api/arrangement/saved')
    const data = await response.json() as { arrangement?: ArrangementDocument; detail?: string }
    if (!response.ok || !data.arrangement) { setMessage(data.detail ?? 'No saved arrangement'); return }
    await put(data.arrangement, true)
  }
  const exportJson = () => {
    const doc = latest.current
    if (!doc) return
    const blob = new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url; link.download = `${file?.replace(/\.[^.]+$/, '') ?? 'song'}.orchestra.json`
    link.click(); URL.revokeObjectURL(url)
  }
  const applyRemap = async () => {
    if (!imported || !view?.midiIdentity) return
    const doc = clone(imported)
    for (const rule of doc.rules) {
      if (rule.source.track !== undefined) rule.source.track = remap[rule.source.track] ?? rule.source.track
      if (rule.source.tracks) rule.source.tracks = rule.source.tracks.map(index => remap[index] ?? index)
    }
    doc.midi = view.midiIdentity
    await put(doc, true)
  }
  const toggle = <T,>(values: Set<T>, setter: (next: Set<T>) => void, value: T) => {
    const next = new Set(values)
    if (next.has(value)) next.delete(value); else next.add(value)
    setter(next)
  }

  if (!file) return <section className="arrangement"><h2>Arrangement</h2><p>Load MIDI to begin.</p></section>
  if (loadError) return <section className="arrangement"><h2>Arrangement</h2><p role="alert">{loadError}</p>
    <button type="button" onClick={() => setRetry(value => value + 1)}>Spróbuj ponownie</button></section>
  if (!view?.arrangement) return <section className="arrangement"><h2>Arrangement</h2><p>Loading arrangement…</p></section>
  const doc = view.arrangement
  const displayNotes = mode === 'source' ? view.notes : [...view.notes, ...(view.trayNotes ?? []), ...(view.reinforcementNotes ?? [])]
  const selected = displayNotes.find(n => n.id === selectedId) ?? null
  const selectedClassification = view.report?.trackClassification?.find(item => item.index === selected?.track)
  const drumTracks = view.tracks.filter(t => t.isDrums)
  const drumIndex = drumTrack ?? drumTracks[0]?.index ?? null
  const drumNotes = [...new Map(view.notes.filter(n => n.track === drumIndex).map(n => [n.note, n])).values()].sort((a, b) => a.note - b.note)
  const countByNote = new Map<number, number>()
  for (const note of view.notes) if (note.track === drumIndex) countByNote.set(note.note, (countByNote.get(note.note) ?? 0) + 1)

  return <section className="arrangement">
    <header className="arrangement-header"><h2>Arrangement</h2><span>{doc.name} · {view.notes.length} MIDI notes</span></header>
    <AutoArrangerReport report={view.report} origin={doc.origin} />

    <div className="arrangement-actions">
      <button type="button" onClick={save}>Save Arrangement</button>
      <button type="button" onClick={loadSaved}>Load Arrangement</button>
      <button type="button" onClick={exportJson}>Export Arrangement JSON</button>
      {/* Ten sam komponent co w naglowku - import jest wspolny dla zakladek. */}
      <ArrangementImport />
    </div>
    {message && <p role="status" className="muted">{message}</p>}
    {imported && <div className="arrangement-mismatch" role="alert">
      <strong>Arrangement MIDI mismatch</strong>
      {mismatches.map((item, i) => <p key={i}>{item.kind === 'midi' ? 'Filename or fingerprint differs.' : `Track ${item.index}: expected “${item.expected}”, loaded “${item.actual ?? 'missing'}”.`}</p>)}
      {imported.midi.tracks.filter(t => imported.rules.some(r => r.source.track === t.index || r.source.tracks?.includes(t.index))).map(t =>
        <label key={t.index}>Expected {t.index} — {t.name} → <select value={remap[t.index] ?? 0} onChange={e => setRemap(v => ({ ...v, [t.index]: Number(e.target.value) }))}>
          {view.tracks.map(actual => <option key={actual.index} value={actual.index}>{actual.index} — {actual.name}</option>)}
        </select></label>)}
      <button type="button" onClick={() => void applyRemap()}>Apply remapping</button>
      <button type="button" onClick={() => { setImported(null); setMismatches([]); setMessage('Import cancelled') }}>Cancel import</button>
    </div>}
    <div className="arrangement-toolbar"><label>View <select aria-label="Piano roll view mode" value={mode} onChange={e => setMode(e.target.value as ViewMode)}>
      <option value="source">SOURCE VIEW</option><option value="device">DEVICE VIEW</option><option value="simulation">SIMULATION VIEW</option>
    </select></label><span>Playhead follows the existing player · MIDI is read-only</span></div>
    <PianoRoll notes={displayNotes} devices={doc.devices} position={state?.position ?? 0} playing={state?.state === 'playing'} mode={mode} selectedId={selectedId}
      hiddenTracks={hiddenTracks} hiddenDevices={hiddenDevices} onSelect={setSelectedId} onSeek={seek} />
    <div className="arrangement-bottom">
      <aside className="arrangement-legend"><h3>Legend</h3><p>Fill: current view · left stripe: source track · border: destination device · dashed: reinforcement</p>
        <h4>MIDI Sources</h4>{view.tracks.filter(t => t.noteCount > 0).map(t => <label key={t.index}>
          <input type="checkbox" checked={!hiddenTracks.has(t.index)} onChange={() => toggle(hiddenTracks, setHiddenTracks, t.index)} />
          <span className="legend-swatch" style={{ background: sourceColor(t.index) }} /> {t.index} — {t.name}
        </label>)}
        <h4>Devices</h4>{doc.devices.map((d, index) => <label key={d.id}>
          <input type="checkbox" checked={!hiddenDevices.has(d.id)} onChange={() => toggle(hiddenDevices, setHiddenDevices, d.id)} />
          <span className="legend-swatch" style={{ background: deviceColor(index) }} /> {d.name}
        </label>)}
        <h4>Simulation</h4>{STATUS.map(s => <div key={s} className={`status-key status-${s.toLowerCase()}`}>{s === 'ACCEPTED' ? '✓' : s === 'FOLDED' ? '↕' : s === 'DELAYED' ? '⏱' : s === 'DROPPED' ? '×' : '·'} {s}</div>)}
      </aside>
      <div className="arrangement-inspector"><h3>Note Inspector</h3>
        {selected ? <><p><strong>{selected.name ?? `MIDI ${selected.note}`}</strong> · MIDI {selected.note} · {selected.isDrum ? 'drum' : 'tonal'}</p>
          <p><strong>{selected.reinforcement ? 'REINFORCEMENT' : 'PRIMARY'}</strong></p>
          <p>SOURCE: track {selected.track} — {selected.trackName} · channel {selected.channel} · velocity {selected.velocity}{selected.role ? ` · rola ${selected.role}` : ''}</p>
          {selectedClassification && <p>SEMANTIC: {selectedClassification.finalRole} · {(selectedClassification.confidence * 100).toFixed(0)}%
            {' · '}{selectedClassification.evidence.slice(0, 3).join('; ')}</p>}
          {(selected.sourceTracks?.length ?? 0) > 1 && <p className="muted">
            partia logiczna z tracków {selected.sourceTracks!.join(' + ')}
            {selected.duplicateGroupId ? ` · grupa ${selected.duplicateGroupId}` : ''}
          </p>}
          {selected.reinforcement && <p><strong>REINFORCEMENT</strong> · source {selected.sourceEventId ?? selected.id} · source device {selected.sourceDevice ?? '—'} · score {selected.score?.toFixed(1) ?? '—'} · {selected.semanticCompatibility ?? 'mechanical accent'}</p>}
          <p>AUTO ARRANGER: <strong>{selected.deviceId ?? 'DROP'}</strong>
            {selected.reassigned ? ' (reassigned)' : ''}{selected.folded ? ' (folded)' : ''}</p>
          <p>OUTCOME: <strong className={selected.outcome === 'DROPPED' ? 'report-bad' : ''}>{selected.outcome ?? selected.status}</strong>{selected.reason ? ` · ${selected.reason}` : ''}</p>
          <p>TIMING: start {formatTime(selected.start)} → {formatTime(selected.actualStart ?? selected.start)}
            {(selected.delayMs ?? 0) > 0.01 ? ` · +${(selected.delayMs ?? 0).toFixed(1)} ms` : ' · on time'}</p>
          <p>Source duration: {(selected.sourceDuration ?? selected.duration) * 1000 >= 1 ? `${((selected.sourceDuration ?? selected.duration) * 1000).toFixed(0)} ms` : `${(selected.sourceDuration ?? selected.duration).toFixed(3)} s`}
            {' · '}Performed duration: {((selected.performedDuration ?? selected.actualDuration ?? selected.duration) * 1000 >= 1)
              ? `${((selected.performedDuration ?? selected.actualDuration ?? selected.duration) * 1000).toFixed(0)} ms`
              : `${(selected.performedDuration ?? selected.actualDuration ?? selected.duration).toFixed(3)} s`}</p>
          {(selected.sustainExtendedMs ?? 0) > 0.5 && <p className="mechanical-sustain">
            Mechanical sustain: +{(selected.sustainExtendedMs ?? 0).toFixed(0)} ms
          </p>}
          {(selected.actualDuration ?? selected.duration) < (selected.sourceDuration ?? selected.duration) - 1e-3
            && (selected.sustainExtendedMs ?? 0) <= 0.5 && <p className="muted">skrócone przez scheduler</p>}
          {selected.routes.length ? selected.routes.map((r, i) => <p key={`${r.ruleId}-${i}`} className="inspector-route">
            Rule {r.ruleId} → {doc.devices.find(d => d.id === r.deviceId)?.name ?? 'DROP'} · {r.status}
            {r.reason ? ` · ${r.reason}` : ''}{r.articulation ? ` · ${r.articulation}` : ''}
            {r.playedNote !== null && r.playedNote !== undefined && r.playedNote !== selected.note ? ` · played MIDI ${r.playedNote}` : ''}
            {r.deviceAvailableAt !== null && r.deviceAvailableAt !== undefined ? ` · available ${formatTime(r.deviceAvailableAt)}` : ''}
          </p>) : <p>No routing rule matched this note.</p>}
          <label>Route this pitch <select disabled={selected.reinforcement} aria-label="Selected note destination" value={selected.routes.find(r => r.deviceId)?.deviceId ?? ''}
            onChange={e => setNoteRoute(selected.track, selected.note, e.target.value || null)}>
            <option value="">DROP / unused</option>{doc.devices.filter(d => d.type !== 'DVD_TRAY').map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select></label>
        </> : <p>Click a note in the piano roll to inspect its MIDI source, routing and mechanical result.</p>}
        <div className="note-access-list"><strong>Quick select</strong>{view.notes.slice(0, 12).map(n => <button type="button" key={n.id} onClick={() => setSelectedId(n.id)}>{n.name ?? n.note} · {formatTime(n.start)} · {n.status}</button>)}</div>
      </div>
    </div>
    <details className="routing-editor" open><summary>Routing Rules</summary>
      <button type="button" onClick={() => change(d => d.rules.push(newRule(`rule-${Date.now()}`, view.tracks.find(t => t.noteCount)?.index ?? 0, d.devices[0]?.id ?? null)))}>Add routing rule</button>
      {doc.rules.map(rule => <article key={rule.id}><div><strong>{rule.id}</strong> <button type="button" onClick={() => change(d => { d.rules = d.rules.filter(r => r.id !== rule.id) })}>Remove rule</button></div>
        <div className="rule-fields">
          <label>Track <select value={rule.source.track ?? ''} onChange={e => change(d => { const r = d.rules.find(r => r.id === rule.id)!; r.source.track = e.target.value === '' ? undefined : Number(e.target.value); delete r.source.tracks })}>
            <option value="">All tracks</option>{view.tracks.map(t => <option key={t.index} value={t.index}>{t.index} — {t.name}</option>)}
          </select></label>
          <label>Device <select value={rule.destination.deviceId ?? ''} onChange={e => change(d => { d.rules.find(r => r.id === rule.id)!.destination.deviceId = e.target.value || null })}>
            <option value="">DROP</option>{doc.devices.filter(d => d.type !== 'DVD_TRAY').map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select></label>
          <label>Include notes <input aria-label={`${rule.id} include notes`} defaultValue={rule.source.includeNotes?.join(', ') ?? ''} placeholder="36, 38, 49" onBlur={e => change(d => { const r = d.rules.find(r => r.id === rule.id)!; const values = e.target.value.split(',').map(v => Number(v.trim())).filter(v => Number.isInteger(v) && v >= 0 && v <= 127); if (e.target.value.trim()) r.source.includeNotes = values; else delete r.source.includeNotes })} /></label>
          <label>Exclude notes <input aria-label={`${rule.id} exclude notes`} defaultValue={rule.source.excludeNotes?.join(', ') ?? ''} onBlur={e => change(d => { const r = d.rules.find(r => r.id === rule.id)!; r.source.excludeNotes = e.target.value.split(',').map(v => Number(v.trim())).filter(v => Number.isInteger(v) && v >= 0 && v <= 127) })} /></label>
          {(['noteRange', 'velocityRange'] as const).map(key => <span key={key} className="rule-range">
            <label>{key} min <input type="number" min="0" max="127" defaultValue={rule.source[key]?.min ?? ''} onBlur={e => change(d => { const r = d.rules.find(r => r.id === rule.id)!; r.source[key] = { ...r.source[key], min: e.target.value ? Number(e.target.value) : undefined } })} /></label>
            <label>max <input type="number" min="0" max="127" defaultValue={rule.source[key]?.max ?? ''} onBlur={e => change(d => { const r = d.rules.find(r => r.id === rule.id)!; r.source[key] = { ...r.source[key], max: e.target.value ? Number(e.target.value) : undefined } })} /></label>
          </span>)}
          <label>Gate <input type="number" min="0.1" max="2" step="0.05" defaultValue={rule.transform.gate} onBlur={e => change(d => { d.rules.find(r => r.id === rule.id)!.transform.gate = Number(e.target.value) })} /></label>
          <label>Transpose <input type="number" min="-48" max="48" defaultValue={rule.transform.transpose} onBlur={e => change(d => { d.rules.find(r => r.id === rule.id)!.transform.transpose = Number(e.target.value) })} /></label>
          <label>Strategy <select value={rule.transform.strategy} onChange={e => change(d => { d.rules.find(r => r.id === rule.id)!.transform.strategy = e.target.value as ArrangementRule['transform']['strategy'] })}>
            {['first', 'highest', 'lowest', 'last'].map(s => <option key={s}>{s}</option>)}
          </select></label>
          <label><input type="checkbox" checked={rule.transform.octaveFold} onChange={e => change(d => { d.rules.find(r => r.id === rule.id)!.transform.octaveFold = e.target.checked })} /> Octave fold</label>
        </div>
      </article>)}
    </details>
    <details className="drum-routing" open><summary>Percussion note routing</summary>
      {drumTracks.length ? <><label>Drum track <select aria-label="Drum track" value={drumIndex ?? ''} onChange={e => setDrumTrack(Number(e.target.value))}>
        {drumTracks.map(t => <option key={t.index} value={t.index}>{t.index} — {t.name}</option>)}
      </select></label>
      <div className="drum-route-list">{drumNotes.map(n => {
        const routed = n.routes.find(r => r.deviceId)
        const precise = doc.rules.find(r => exactRule(r, n.track, n.note))
        return <div key={n.note} className="drum-route-row">
          <label><input type="checkbox" aria-label={`Use drum ${n.note}`} checked={Boolean(routed)} onChange={e => setNoteRoute(n.track, n.note, e.target.checked ? (doc.devices.find(d => d.type === 'HDD_VCM' || d.type === 'SOLENOID_RESONATOR')?.id ?? doc.devices[0]?.id ?? null) : null, precise?.articulation)} /> {n.note} {n.name} ({countByNote.get(n.note)})</label>
          <select aria-label={`Route drum ${n.note}`} value={routed?.deviceId ?? ''} onChange={e => setNoteRoute(n.track, n.note, e.target.value || null, precise?.articulation)}>
            <option value="">DROP</option>{doc.devices.filter(d => d.type !== 'DVD_TRAY').map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
          <select aria-label={`Articulation drum ${n.note}`} value={precise?.articulation ?? ''} onChange={e => setNoteRoute(n.track, n.note, routed?.deviceId ?? null, e.target.value || null)}>
            <option value="">Default articulation</option>{['LEFT_SOFT', 'LEFT_HARD', 'RIGHT_SOFT', 'RIGHT_HARD', 'DOUBLE_HIT'].map(a => <option key={a}>{a}</option>)}
          </select>
        </div>
      })}</div><p className="muted">Articulation is stored in the arrangement; the current audio renderer does not synthesize these variants yet.</p></> : <p>No General MIDI drum track in this file.</p>}
    </details>
  </section>
}
