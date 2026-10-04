import { useEffect, useMemo, useState } from 'react'
import type { PlayerState } from '../types'
import { indexMechanicalPlan, mechanicalState, type MechanicalPlan, type MotionState } from '../mechanical'
import { usePlaybackClock } from '../usePlaybackClock'
import './MechanicalView.css'

const GROUPS = [['FDD', 'Floppy drives'], ['DVD_SLED', 'DVD sleds'], ['HDD_VCM', 'HDD percussion'], ['VHS', 'VHS lead / vocal'], ['DVD_TRAY', 'DVD trays']] as const

function Mechanism({ type, motion }: { type: string; motion: MotionState }) {
  const x = 35 + motion.linear * 160
  return <svg viewBox="0 0 240 100" role="img" aria-label={`${type} mechanism`} data-mechanism={type}>
    {type === 'FDD' ? <>
      <rect className="housing" x="8" y="8" width="224" height="84" rx="6" />
      <rect className="slot" x="23" y="20" width="194" height="13" rx="2" />
      <path className="rail" d="M30 58 H210 M30 75 H210" />
      <g transform={`translate(${x}, 0)`}><rect className="moving" x="-12" y="47" width="24" height="37" rx="3" /><path className="ink" d="M-6 57 H6" /></g>
    </> : type === 'DVD_SLED' ? <>
      <rect className="housing" x="8" y="8" width="224" height="84" rx="16" />
      <path className="rail" d="M27 29 H213 M27 75 H213" />
      <path className="screw" d="M27 52 H213" />
      <g transform={`translate(${x}, 0)`}><rect className="moving" x="-17" y="35" width="34" height="35" rx="5" /><circle className="lens" cx="0" cy="52" r="8" /></g>
    </> : type === 'HDD_VCM' ? <>
      <rect className="housing" x="8" y="8" width="224" height="84" rx="8" />
      <circle className="platter" cx="100" cy="50" r="34" /><circle className="rail" cx="100" cy="50" r="9" />
      <g transform={`rotate(${motion.angle}, 175, 72)`}><path className="arm moving" d="M175 72 L111 38 L105 48 Z" /><circle className="lens" cx="109" cy="43" r="4" /></g>
      <circle className="rail" cx="175" cy="72" r="9" />
    </> : type === 'VHS' ? <>
      <rect className="housing" x="8" y="8" width="224" height="84" rx="6" />
      <path className="rail" d="M25 30 L75 70 H165 L215 30" />
      <g transform={`rotate(${motion.angle}, 120, 50)`}><circle className="moving" cx="120" cy="50" r="33" /><path className="ink" d="M120 17 V83 M87 50 H153" /><circle className="lens" cx="120" cy="50" r="8" /></g>
    </> : type === 'DVD_TRAY' ? <>
      <rect className="housing" x="15" y="8" width="210" height="51" rx="5" />
      <g transform={`translate(0, ${motion.tray * 30})`}><rect className="moving" x="35" y="26" width="170" height="40" rx="5" /><ellipse className="platter" cx="120" cy="44" rx="40" ry="13" /><ellipse className="lens" cx="120" cy="44" rx="8" ry="3" /></g>
      <path className="rail" d="M24 23 H216" />
    </> : <rect className="housing" x="8" y="8" width="224" height="84" rx="6" />}
  </svg>
}

export function MechanicalView({ state }: { state: PlayerState | null }) {
  const [plan, setPlan] = useState<MechanicalPlan | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [selected, setSelected] = useState<string | null>(null)
  const [labels, setLabels] = useState(true)
  const file = state?.file ?? null
  const revision = state?.arrangementRevision
  const playback = state?.state ?? 'stopped'
  const time = usePlaybackClock(state?.position ?? 0, playback === 'playing', state?.duration ?? 0)
  useEffect(() => {
    const controller = new AbortController()
    setPlan(null); setError('')
    fetch('/api/mechanical', { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error(`Mechanical View: HTTP ${response.status}. Uruchom ponownie backend.`)
      const data = await response.json() as MechanicalPlan
      if (!controller.signal.aborted) setPlan(data)
    }).catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Could not load plan') })
    return () => controller.abort()
  }, [file, revision, retry])
  const indexes = useMemo(() => plan ? indexMechanicalPlan(plan) : [], [plan])
  const motions = indexes.map(index => mechanicalState(index, time, playback))
  const selectedIndex = indexes.findIndex(index => index.device.id === selected)
  const inspected = motions[selectedIndex]
  const event = inspected?.event
  const known = new Set<string>(GROUPS.map(([type]) => type))
  const groups: Array<readonly [string, string]> = [...GROUPS, ...indexes.filter(i => !known.has(i.device.type)).map(i => [i.device.type, i.device.type] as const)]
  return <section className="mechanical-view" aria-label="Mechanical Debug View">
    <header className="mechanical-heading"><div><h2>Mechanical View</h2><p>PerformancePlan · schematic motion · {playback} · {time.toFixed(2)} s</p></div>
      <label><input type="checkbox" checked={labels} onChange={e => setLabels(e.target.checked)} /> Show debug labels</label></header>
    <div className="mechanical-legend"><span className="primary">● PRIMARY</span><span className="reinforcement">● REINFORCEMENT</span><span>● IDLE</span><span>◷ COOLDOWN</span><span>Pause freezes motion · seek uses the player transport above</span></div>
    {error && <p role="alert">{error} <button onClick={() => setRetry(n => n + 1)}>Retry</button></p>}
    {!error && !plan && <p role="status">Loading mechanical plan…</p>}
    {plan && !plan.hasPlan && <p>No PerformancePlan loaded. Load MIDI and enable Virtual Orchestra / Auto Arranger.</p>}
    {plan?.hasPlan && !plan.events.length && !plan.reinforcements.length && !plan.trays.length && <p>The plan has no played events.</p>}
    {groups.filter(([type], i, all) => all.findIndex(g => g[0] === type) === i).map(([type, title]) => {
      const members = indexes.map((index, i) => ({ index, motion: motions[i] })).filter(item => item.index.device.type === type)
      if (!members.length) return null
      return <section className="mechanical-group" key={type}><h3>{title} <small>{members.length} devices</small></h3><div className="mechanical-grid">
        {members.map(({ index, motion }) => {
          const d = index.device, e = motion.event
          const status = motion.phase === 'IDLE' ? 'IDLE' : `${motion.phase} ${e?.kind}`
          const color = e ? e.kind.toLowerCase() : 'idle'
          return <button type="button" key={d.id} aria-label={`Inspect ${d.name}`} aria-pressed={selected === d.id}
            className={`mechanical-device ${color} ${motion.attack ? 'attack' : ''}`} data-state={status} data-device={d.id}
            onClick={() => setSelected(d.id)} title={`${d.name} · ${status}${e ? ` · ${e.label} · ${e.track} · ${e.role}` : ''}`}>
            <div className="mechanical-card-heading"><strong>{d.name}</strong><span>{motion.phase}</span></div>
            <Mechanism type={type} motion={motion} />
            <div className="mechanical-badge">{e?.kind ?? 'IDLE'}</div>
            {labels && <div className="mechanical-labels">{e ? <>{e.label} · MIDI {e.note ?? '—'}<br />{e.role} · {e.hz.toFixed(1)} Hz<br /><span>{e.track}</span></> : <><span>{d.type}</span><br />No active event<br />{d.id}</>}</div>}
          </button>
        })}
      </div></section>
    })}
    <aside className="mechanical-inspector" aria-label="Mechanical inspector"><h3>{selectedIndex >= 0 ? indexes[selectedIndex].device.name : 'Device inspector'}</h3>
      {selectedIndex >= 0 ? <><p>{indexes[selectedIndex].device.type} · {inspected.phase} · {event?.kind ?? 'IDLE'}</p>
        {event ? <><p>{event.label} · MIDI {event.note ?? '—'} · {event.hz.toFixed(2)} Hz · velocity {event.velocity}</p>
          <p>Track: {event.track} · role: {event.role}</p><p>Event: {event.id} · source: {event.sourceId}</p>
          <p>{event.start.toFixed(3)}–{event.end.toFixed(3)} s · busy until {event.busyUntil.toFixed(3)} s</p><p>{event.reason}</p></> : <p>No active event at the current playhead.</p>}</> : <p>Click a device to inspect the current event. Hover for a quick summary.</p>}
    </aside>
  </section>
}
