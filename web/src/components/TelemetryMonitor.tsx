import { useMemo } from 'react'
import type { FileMetadata, PlayerState, TelemetryEvent, TelemetryView, VirtualDevice } from '../types'
import { usePlaybackPosition } from '../usePlaybackPosition'
import { eventAt, eventTime, frequencyAt, indexTelemetry, noteName, streamAt } from '../telemetry'

export function arduinoStatus(state: PlayerState | null) {
  return state?.hardware.connected ? 'Arduino connected' : 'Arduino disconnected'
}
function label(event: TelemetryEvent) {
  if (event.kind === 'hit') return (event.articulation ?? 'HIT').replaceAll('_', ' ')
  if (event.kind === 'tray') return [49, 57].includes(event.sourceNote ?? -1) ? 'CRASH' : 'MECHANICAL ACCENT'
  return noteName(event.note ?? (event.hz > 0 ? Math.round(69 + 12 * Math.log2(event.hz / 440)) : null))
}
function deviceName(name: string) {
  return name.replace(/^DVD Stepper /, 'DVD ').replace(/^HDD_VCM #/, 'HDD ').replace(/^FDD #/, 'FDD ').replace(/^DVD Tray /, 'TRAY ')
}
export function TelemetryMonitor({ state, view, error, metadata, onSettings, settingsOpen }: { state: PlayerState | null; view: TelemetryView | null; error: string | null; metadata?: FileMetadata | null; onSettings?: () => void; settingsOpen?: boolean }) {
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
  const recent = index && state?.state !== 'stopped' ? streamAt(index.events, position) : []
  const connected = Boolean(state?.hardware.connected)
  return <>
    <main className="monitor-layout">
      <section className="instrument-grid" aria-label="Virtual Instrument Grid">
        {devices.map(device => {
          const event = active.get(device.id)
          const tray = device.type === 'DVD_TRAY' && enabledFor(device) ? state?.virtual?.trayStatus?.[device.id] : null
          const moving = tray && !['idle', 'cooldown', 'recovery'].includes(tray.phase)
          const lit = Boolean(event || moving)
          const source = event?.track || metadata?.tracks.find(t => t.index === device.track)?.name || device.role || ''
          return <article key={device.id} aria-label={device.name} className={`instrument-tile${lit ? ' is-active' : ''}`}>
            <h2>{deviceName(device.name)}</h2>
            <div className={`instrument-event${event?.kind !== 'tone' ? ' instrument-action' : ''}`}>{event ? label(event) : moving ? tray.phase.replaceAll('_', ' ').toUpperCase() : '—'}</div>
            <div className="instrument-detail">{event?.kind === 'tone' && event.hz > 0 ? `${frequencyAt(event, position).toFixed(2)} Hz` : event ? `VEL ${event.velocity}` : ' '}</div>
            <div className="instrument-source" title={source}>{source}</div>
          </article>
        })}
      </section>
      <section className="event-stream" aria-label="Event Stream">
        <h2>EVENT STREAM</h2>
        {error && <p className="muted" role="alert">{error}</p>}
        <ol>{recent.map((event, i) => <li key={event.id} style={{ opacity: Math.max(.4, 1 - i * .04) }}>
          <time>{eventTime(event.start)}</time>
          <span title={event.track}>{deviceName(devices.find(d => d.id === event.deviceId)?.name ?? event.deviceId)}</span>
          <span>{label(event)}</span>
        </li>)}</ol>
      </section>
    </main>
    <footer className="workstation-status">
      <span className={connected ? 'arduino-connected' : ''}><span aria-hidden="true">{connected ? '●' : '○'}</span> {arduinoStatus(state)}</span>
      {onSettings && <button className="settings-trigger" type="button" aria-label="Settings" aria-expanded={settingsOpen} onClick={onSettings}>Settings</button>}
    </footer>
  </>
}
