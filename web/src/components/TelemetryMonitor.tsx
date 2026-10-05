import { useMemo } from 'react'
import type { PlayerState, TelemetryEvent, TelemetryView, VirtualDevice } from '../types'
import { usePlaybackPosition } from '../usePlaybackPosition'
import { chooseFocus, eventAt, eventTime, frequencyAt, indexTelemetry, noteName, streamAt } from '../telemetry'

const GROUPS = [
  ['TONAL / FDD', ['FDD']], ['TONAL / DVD STEPPER', ['DVD_SLED', 'STEPPER_FREE']],
  ['TONAL / VHS', ['VHS']], ['PERCUSSION / HDD VCM', ['HDD_VCM', 'SOLENOID_RESONATOR']],
  ['MECHANICAL FX', ['DVD_TRAY']],
] as const
const modeNames: Record<string, string> = { raw: 'TONAL RAW', articulated: 'TONAL ARTICULATED', extreme: 'TONAL EXTREME v1', extreme_v15: 'TONAL EXTREME 1.5', extreme_v2: 'TONAL EXTREME v2' }
export function arduinoStatus(state: PlayerState | null) {
  const hw = state?.hardware
  return hw?.connecting ? 'Arduino homing' : hw?.pendingPlay ? 'Arduino waiting' : hw?.connected ? 'Arduino connected' : 'Arduino disconnected'
}
function label(event: TelemetryEvent) {
  return event.kind === 'hit' ? event.articulation ?? 'HIT' : event.kind === 'tray' ? 'MECHANICAL ACCENT' : noteName(event.note ?? (event.hz > 0 ? Math.round(69 + 12 * Math.log2(event.hz / 440)) : null))
}
export function TelemetryMonitor({ state, view, error }: { state: PlayerState | null; view: TelemetryView | null; error: string | null }) {
  const devices = state?.virtual?.config.devices ?? []
  const realDeviceKey = JSON.stringify(devices.filter(d => d.mode === 'real').map(d => d.id))
  const index = useMemo(() => {
    if (!view) return null
    if (!state?.virtual?.enabled || !view.audioEvents) return indexTelemetry(view)
    const realIds = new Set<string>(JSON.parse(realDeviceKey))
    return indexTelemetry({ ...view, audioEvents: [...view.audioEvents, ...view.events.filter(e => realIds.has(e.deviceId))] }, true)
  }, [view, state?.virtual?.enabled, realDeviceKey])
  const playing = state?.state === 'playing'
  const virtual = Boolean(state?.virtual?.enabled)
  const clockReady = state?.virtual?.audioClockRunning !== false
  const position = usePlaybackPosition(virtual ? state?.virtual?.audioPosition ?? state?.position ?? 0 : state?.position ?? 0,
    playing && (!virtual || clockReady))
  const enabledFor = (d: VirtualDevice) => {
    const mode = d.mode ?? 'virtual'
    const virtual = state?.virtual?.enabled && clockReady && mode !== 'real'
    const wired = state?.arrangementHardware?.connected && Object.values(state.arrangementHardware.lanes).some(l => l.deviceId === d.id) && mode !== 'virtual'
    return playing && !d.mute && (!devices.some(v => v.solo && !v.mute) || d.solo) && Boolean(virtual || wired)
  }
  const active = new Map<string, TelemetryEvent>()
  for (const device of devices) {
    const event = index && enabledFor(device) ? eventAt(index.lanes.get(device.id) ?? [], position) : null
    if (event) active.set(device.id, event)
  }
  const manual = !devices.length && playing && state?.frequency != null && state.hardware.connected
  const focus = chooseFocus([...active.values()], position)
  const frequency = focus?.kind === 'tone' ? frequencyAt(focus, position) : null
  const bend = focus && frequency && focus.hz ? 1200 * Math.log2(frequency / focus.hz) : 0
  const focusedDevice = devices.find(d => d.id === focus?.deviceId)
  const recent = index && state?.state !== 'stopped' ? streamAt(index.events, position) : []
  const report = view?.report
  const totals = state?.arrangementTotals ?? report?.totals
  const load = (types: string[]) => {
    const rows = devices.filter(d => types.includes(d.type))
    if (!rows.length || !view || !state?.duration || rows.some(d => !state.virtual?.report[d.id])) return null
    // Existing report: whole-plan utilization, not a fabricated live percentage.
    return rows.reduce((sum, d) => {
      const r = state?.virtual?.report[d.id]
      const time = d.type === 'HDD_VCM' ? r?.busyTime : r?.activeTime
      return sum + Math.min(1, Math.max(0, (time ?? 0) / Math.max(.001, state?.duration ?? 0)))
    }, 0) / rows.length
  }
  return <>
    <main className="monitor-layout">
      <div className="monitor-main">
        <section className="current-event" aria-label="Current Musical Event">
          <div className="monitor-section-heading"><h2>CURRENT MUSICAL EVENT</h2><span className={`transport-state ${state?.state ?? 'stopped'}`}>
            {playing ? '▶ PLAYING' : state?.state === 'paused' ? 'Ⅱ PAUSED' : '■ STOPPED'}</span></div>
          <div className="event-source">{focus ? Math.abs(bend) > 1 ? 'PITCH BEND' : focus.reinforcement && focus.kind !== 'tray' ? 'REINFORCEMENT' : focus.track || '—' : manual ? state?.trackName : state?.file ?? 'Select a MIDI file'}</div>
          <div className={`event-note ${focus?.kind !== 'tone' ? 'event-action' : ''}`}>{focus ? label(focus) : manual ? state?.noteName : '—'}</div>
          <div className="event-frequency">{manual ? `${state.frequency?.toFixed(2)} Hz` : frequency != null ? `${frequency.toFixed(2)} Hz` : focus?.kind === 'hit' ? `GM${focus.sourceNote ?? '—'} · ${focusedDevice?.name ?? '—'}` : focus?.kind === 'tray' ? `${state?.virtual?.trayStatus?.[focus.deviceId]?.phase.toUpperCase() ?? '—'} · GM${focus.sourceNote ?? '—'}` : '—'}</div>
          <div className="event-meta">{focus ? <>{focus.reinforcement ? 'REINFORCEMENT' : 'PRIMARY'} · {focus.profile ?? (focus.kind === 'hit' ? `HDD ${(state?.virtual?.config.hddMode ?? 'articulated').toUpperCase()}` : 'MECHANICAL')} · VEL {focus.velocity} · {focusedDevice?.name}
            {focus.reinforcement && ` · ${focus.track} → ${focusedDevice?.name}`}
            {Math.abs(bend) > 1 && ` · ${bend > 0 ? '+' : ''}${bend.toFixed(0)} cents · ${focus.track}`}</> : manual ? 'PRIMARY · Manual hardware' : error ?? (playing ? 'No active event' : 'Ready')}</div>
          <div className="event-intensity" aria-label="Event velocity"><div style={{ width: `${focus ? focus.velocity / 127 * 100 : 0}%` }} /></div>
        </section>
        <section className="device-activity" aria-label="Device Activity"><h2>DEVICE ACTIVITY</h2>
          {!devices.length && <p className="muted">No devices configured</p>}
          {GROUPS.map(([title, types]) => {
            const rows = devices.filter(d => (types as readonly string[]).includes(d.type))
            if (!rows.length) return null
            return <section className="device-group" key={title}><h3>{title}</h3><table><colgroup>{[20, 26, 25, 18, 11].map((width, i) => <col key={i} style={{ width: `${width}%` }} />)}</colgroup><thead><tr><th>DEVICE</th><th>EVENT</th><th>SOURCE</th><th>VOICE</th><th>STATE</th></tr></thead><tbody>{rows.map(d => {
              const event = active.get(d.id)
              const tray = d.type === 'DVD_TRAY' && playing ? state?.virtual?.trayStatus?.[d.id] : null
              const moving = enabledFor(d) && tray && !['idle', 'cooldown', 'recovery'].includes(tray.phase)
              return <tr key={d.id} className={event || moving ? 'active-row' : ''}><th scope="row">{d.name}</th>
                <td>{event ? event.kind === 'tone' ? `${label(event)} · ${frequencyAt(event, position).toFixed(2)} Hz` : event.kind === 'tray' ? tray?.phase.toUpperCase() ?? '—' : event.articulation ?? 'HIT' : enabledFor(d) && tray && tray.phase !== 'idle' ? tray.phase.toUpperCase() : '—'}</td>
                <td title={event?.track}>{event?.kind === 'hit' || event?.kind === 'tray' ? `GM${event.sourceNote ?? '—'} · VEL ${event.velocity}` : event?.track ?? '—'}</td>
                <td>{event ? event.reinforcement ? 'REINFORCEMENT' : 'PRIMARY' : '—'}</td>
                <td>{event?.kind === 'hit' ? 'HIT' : event?.kind === 'tray' || moving ? 'MOVING' : event ? 'ACTIVE' : 'IDLE'}</td></tr>
            })}</tbody></table></section>
          })}
        </section>
      </div>
      <aside className="monitor-sidebar">
        <section className="event-stream" aria-label="Event Stream"><h2>EVENT STREAM</h2><p className="monitor-caption">Scheduled onsets · newest first</p>
          {!recent.length && <p className="muted">—</p>}
          <ol>{recent.map(event => <li key={event.id}><time>{eventTime(event.start)}</time><span title={event.track}>{(devices.find(d => d.id === event.deviceId)?.name ?? event.deviceId).replace(/^DVD Stepper /, 'DVD ').replace(/^HDD_VCM #/, 'HDD ').replace(/^FDD #/, 'FDD ').replace(/^DVD Tray /, 'TRAY ')}</span><span>{label(event)} {event.kind === 'tone' ? event.reinforcement ? 'RF' : 'PRIMARY' : `GM${event.sourceNote ?? '—'}`}</span></li>)}</ol>
        </section>
        <section className="orchestra-load" aria-label="Orchestra Load"><h2>ORCHESTRA LOAD</h2><p className="monitor-caption">Full MIDI · mean device utilization</p>
          {([['TONAL', ['FDD', 'DVD_SLED', 'STEPPER_FREE', 'VHS']], ['PERC', ['HDD_VCM', 'SOLENOID_RESONATOR']], ['FDD', ['FDD']], ['DVD', ['DVD_SLED']], ['HDD', ['HDD_VCM']]] as [string, string[]][]).map(([name, types]) => {
            const amount = load(types)
            return <div className="load-row" key={name}><span>{name}</span><div role="meter" aria-label={`${name} utilization`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={amount == null ? undefined : Math.round(amount * 100)}><div style={{ width: `${(amount ?? 0) * 100}%` }} /></div><span>{amount == null ? '—' : `${(amount * 100).toFixed(0)}%`}</span></div>
          })}
          <dl className="performance-summary"><dt>coverage</dt><dd>{totals ? `${((1 - totals.dropRate) * 100).toFixed(1)}%` : '—'}</dd><dt>drop</dt><dd>{totals ? `${(totals.dropRate * 100).toFixed(1)}%` : '—'}</dd><dt>played</dt><dd>{totals?.played ?? '—'}</dd><dt>reinforcement</dt><dd>{view ? index?.reinforcementCount : '—'}</dd></dl>
        </section>
      </aside>
    </main>
    <footer className="workstation-status"><span>{arduinoStatus(state)}</span><span>active {active.size}/{devices.length}</span><span>{modeNames[state?.virtual?.config.tonalMode ?? 'extreme_v15']}</span><span>HDD {(state?.virtual?.config.hddMode ?? 'articulated').toUpperCase()}</span><span>{state?.arrangementActive ? 'PerformancePlan' : 'Manual playback'}</span>{state?.hardware.port && <span>{state.hardware.port}</span>}</footer>
  </>
}
