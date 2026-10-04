import type { PlaybackStateValue, VirtualDevice } from './types'

export interface MechanicalDevice extends VirtualDevice { parameters: Record<string, number | null> }
export interface PlanNote {
  id: string; deviceId: string; actualStart: number; performedDuration: number
  note: number; playedNote: number | null; playedHz: number | null; name: string | null
  trackName: string; role: string; velocity: number; outcome: string
}
export interface PlanExtra {
  sourceId: string; deviceId: string; start: number; duration: number; hz: number
  velocity: number; kind: string; reason: string; role: string; gmFamily?: string; gmProgram?: number
}
export interface PlanTray {
  sourceId: string; deviceId: string; start: number; duration: number; cooldown: number
  note: number; velocity: number; direction: number; sourceTrackName: string; reason: string
}
export interface MechanicalPlan {
  file: string | null; revision: number; hasPlan: boolean; devices: MechanicalDevice[]
  events: PlanNote[]; reinforcements: PlanExtra[]; trays: PlanTray[]
}
export interface MotionEvent {
  id: string; start: number; end: number; busyUntil: number; kind: 'PRIMARY' | 'REINFORCEMENT'
  note: number | null; hz: number; label: string; track: string; role: string; velocity: number
  sourceId: string; reason: string; direction: number
}
export interface DeviceIndex { device: MechanicalDevice; events: MotionEvent[]; prefixEnd: number[] }
export interface MotionState {
  phase: 'IDLE' | 'ACTIVE' | 'COOLDOWN'; event: MotionEvent | null; progress: number
  linear: number; angle: number; tray: number; attack: boolean
}
const clamp = (value: number) => Math.min(1, Math.max(0, value))

/** Cached on plan revision, not on every animation frame. */
export function indexMechanicalPlan(plan: MechanicalPlan): DeviceIndex[] {
  const source = new Map(plan.events.map(e => [e.id, e]))
  const byDevice = new Map<string, MotionEvent[]>()
  const add = (device: string, event: MotionEvent) => {
    if (event.end <= event.start) return
    const list = byDevice.get(device) ?? []; list.push(event); byDevice.set(device, list)
  }
  for (const e of plan.events) {
    if (e.outcome === 'DROPPED') continue
    add(e.deviceId, { id: e.id, start: e.actualStart, end: e.actualStart + e.performedDuration,
      busyUntil: e.actualStart + e.performedDuration, kind: 'PRIMARY', note: e.playedNote ?? e.note,
      hz: e.playedHz ?? 0, label: e.name ?? `MIDI ${e.playedNote ?? e.note}`, track: e.trackName,
      role: e.role, velocity: e.velocity, sourceId: e.id, reason: e.outcome, direction: 1 })
  }
  plan.reinforcements.forEach((e, i) => {
    const parent = source.get(e.sourceId)
    add(e.deviceId, { id: `reinforcement:${i}`, start: e.start, end: e.start + e.duration,
      busyUntil: e.start + e.duration, kind: 'REINFORCEMENT', note: parent?.playedNote ?? parent?.note ?? null,
      hz: e.hz, label: parent?.name ?? e.gmFamily ?? 'Doubling', track: parent?.trackName ?? '—',
      role: e.role || parent?.role || '—', velocity: e.velocity, sourceId: e.sourceId, reason: e.reason, direction: 1 })
  })
  plan.trays.forEach((e, i) => add(e.deviceId, { id: `tray:${i}`, start: e.start,
    end: e.start + e.duration, busyUntil: e.start + e.duration + e.cooldown,
    kind: 'REINFORCEMENT', note: e.note, hz: 0, label: `GM ${e.note}`, track: e.sourceTrackName,
    role: 'percussion', velocity: e.velocity, sourceId: e.sourceId, reason: e.reason, direction: e.direction }))
  return plan.devices.map(device => {
    const events = (byDevice.get(device.id) ?? []).sort((a, b) => a.start - b.start)
    let end = -Infinity
    const prefixEnd = events.map(e => (end = Math.max(end, e.busyUntil)))
    return { device, events, prefixEnd }
  })
}

/** Binary search + local overlapping candidates; seeking does not replay history. */
export function mechanicalState(index: DeviceIndex, time: number, playback: PlaybackStateValue): MotionState {
  const idle: MotionState = { phase: 'IDLE', event: null, progress: 0, linear: .5, angle: 0, tray: 0, attack: false }
  if (playback === 'stopped') return idle
  const { events, prefixEnd, device } = index
  let lo = 0, hi = events.length
  while (lo < hi) { const mid = (lo + hi) >>> 1; if (events[mid].start <= time) lo = mid + 1; else hi = mid }
  let event: MotionEvent | null = null
  for (let i = lo - 1; i >= 0 && prefixEnd[i] > time + 1e-9; i--) {
    const candidate = events[i]
    if (candidate.busyUntil <= time + 1e-9) continue
    if (!event || (candidate.kind === 'PRIMARY' && time < candidate.end)) event = candidate
    if (event.kind === 'PRIMARY' && time < event.end) break
  }
  if (!event) return device.type === 'DVD_TRAY' && lo > 0
    ? { ...idle, tray: events[lo - 1].direction > 0 ? 1 : 0 } : idle
  const elapsed = time - event.start
  const progress = clamp(elapsed / (event.end - event.start))
  let phase: MotionState['phase'] = time < event.end ? 'ACTIVE' : 'COOLDOWN'
  // Rate bounded for legibility. Geometry is schematic, timing is exact.
  const rate = Math.min(8, Math.max(2, event.hz / 70))
  const linear = .5 + .38 * Math.sin(elapsed * rate * Math.PI * 2)
  let angle = elapsed * Math.min(3, Math.max(.5, event.hz / 200)) * 360
  if (device.type === 'HDD_VCM') {
    const p = device.parameters
    const park = (p.parkMs ?? 40) / 1000, settle = (p.settleMs ?? 40) / 1000, strike = (p.strikeMs ?? 25) / 1000
    if (elapsed >= park + settle + strike) phase = 'COOLDOWN'
    angle = elapsed < park ? -25 * clamp(elapsed / Math.max(park, .001))
      : elapsed < park + settle ? -25
      : elapsed < park + settle + strike ? -25 + 65 * Math.sin(clamp((elapsed - park - settle) / Math.max(strike, .001)) * Math.PI) : 0
  }
  const tray = event.direction > 0 ? progress : 1 - progress
  return { phase, event, progress, linear, angle, tray, attack: elapsed < .06 }
}
