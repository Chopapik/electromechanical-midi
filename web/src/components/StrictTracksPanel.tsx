import { useEffect, useState } from 'react'
import type { PlayerApi } from '../usePlayer'

const GM: Record<number, string> = {
  28: 'Electric Guitar (muted)', 35: 'Fretless Bass',
  50: 'Synth Strings 1', 72: 'Piccolo',
}

export function StrictTracksPanel({ player }: { player: PlayerApi }) {
  const routing = player.state?.trackRouting
  const tracks = player.metadata?.tracks.filter(t => t.noteCount > 0 && !t.isDrums) ?? []
  const fdds = player.state?.virtual?.config.devices.filter(d => d.type === 'FDD').slice(0, 4) ?? []
  const police = /every breath you take/i.test(player.state?.file ?? '')
  const suggested = police ? [3, 1, 4, 8] : tracks.slice(0, 4).map(t => t.index)
  const [draft, setDraft] = useState<Array<number | null>>([null, null, null, null])
  useEffect(() => {
    setDraft(routing && (routing.mode === 'STRICT_TRACKS' || routing.fourFddOnly || routing.tracks.some(t => t !== null))
      ? routing.tracks : [...suggested, ...Array(4).fill(null)].slice(0, 4))
  }, [player.state?.file, routing?.mode, routing?.tracks.join(','), player.metadata])
  const stopped = player.state?.state === 'stopped'
  const send = (mode: 'AUTO' | 'STRICT_TRACKS', fourFddOnly: boolean, values = draft) =>
    player.setTrackRouting(mode, fourFddOnly, values)
  return <section className="strict-tracks-panel" aria-label="Test routingu czterech FDD">
    <h3>4 FDD · test routingu</h3>
    <p>Ten sam plik i tempo. Zmiana wariantu wymaga STOP.</p>
    <div className="virtual-toolbar">
      <button type="button" disabled={!stopped || fdds.length !== 4}
        aria-pressed={routing?.mode === 'AUTO' && routing.fourFddOnly === true}
        onClick={() => send('AUTO', true)}>AUTO · 4 FDD</button>
      <button type="button" disabled={!stopped || fdds.length !== 4}
        aria-pressed={routing?.mode === 'STRICT_TRACKS'}
        onClick={() => send('STRICT_TRACKS', true)}>STRICT TRACKS</button>
      <button type="button" disabled={!stopped} onClick={() => send('AUTO', false)}>Przywróć standardowe AUTO</button>
      {police && <button type="button" disabled={!stopped || fdds.length !== 4}
        onClick={() => { setDraft([3, 1, 4, 8]); send('STRICT_TRACKS', true, [3, 1, 4, 8]) }}>
        The Police · 3 / 1 / 4 / 8</button>}
    </div>
    {fdds.map((device, i) => <label key={device.id} className="strict-track-row">
      FDD{i + 1} · {device.name}{device.enabled === false ? ' (wyłączona w orkiestrze)' : ''}
      <select aria-label={`STRICT FDD${i + 1} track`} disabled={!stopped}
        value={draft[i] ?? ''} onChange={event => {
          const next = draft.slice(); next[i] = event.target.value === '' ? null : Number(event.target.value)
          setDraft(next)
          if (routing?.mode === 'STRICT_TRACKS') send('STRICT_TRACKS', true, next)
        }}>
        <option value="">Wyłącz tę FDD</option>
        {tracks.map(t => <option key={t.index} value={t.index}>
          {t.index} · {t.name !== '(bez nazwy)' ? t.name : GM[t.programs?.[0] ?? -1] ?? `GM ${t.programs?.[0] !== undefined ? t.programs[0] + 1 : '?'}`} · {t.noteCount} nut
        </option>)}
      </select>
    </label>)}
    {routing?.output && <p>Zaplanowane na włączonych wyjściach: {routing.output.enabledPlayed} nut
      {routing.output.disabledReservations > 0 && ` · ${routing.output.disabledReservations} rezerwacji na wyłączonych urządzeniach`}</p>}
    {routing?.mode === 'STRICT_TRACKS' && routing.report && <table className="strict-track-report"><thead><tr>
      <th>FDD / track</th><th>Wykonane</th><th>Pominięte</th><th>Zachowane</th><th>Akord</th><th>Zmiany wysokości</th><th>Fold</th>
    </tr></thead><tbody>{fdds.map(device => {
      const row = routing.report?.[device.id]
      return <tr key={device.id}><td>{device.name} / {row?.track ?? 'off'}</td><td>{row?.played ?? 0}</td>
        <td>{row?.dropped ?? 0}</td><td>{Math.round((row?.retention ?? 0) * 100)}%</td>
        <td>{row?.chordRejected ?? 0}</td><td>{row?.pitchChanges ?? 0}</td><td>{row?.folded ?? 0}</td></tr>
    })}</tbody></table>}
  </section>
}
