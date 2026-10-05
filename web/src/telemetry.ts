import type { TelemetryEvent, TelemetryView } from './types'

/** Upper bound, shared by lane lookups, curve interpolation and stream seek. */
export function upperBound<T>(items: readonly T[], value: number, key: (item: T) => number): number {
  let lo = 0, hi = items.length
  while (lo < hi) {
    const mid = (lo + hi) >>> 1
    if (key(items[mid]) <= value) lo = mid + 1
    else hi = mid
  }
  return lo
}
export function indexTelemetry(view: TelemetryView, audible = false) {
  const events = audible && view.audioEvents !== undefined ? view.audioEvents : view.events
  const lanes = new Map<string, TelemetryEvent[]>()
  for (const event of events) {
    const lane = lanes.get(event.deviceId) ?? []
    lane.push(event); lanes.set(event.deviceId, lane)
  }
  for (const lane of lanes.values()) lane.sort((a, b) => a.start - b.start)
  return { lanes, reinforcementCount: events.filter(e => e.reinforcement).length, events: [...events].sort((a, b) => a.start - b.start) }
}
export function eventAt(lane: TelemetryEvent[], position: number) {
  const index = upperBound(lane, position, e => e.start) - 1
  const event = lane[index]
  // HDD visual activity uses the renderer's real busy interval separately.
  return event && position < event.start + (event.kind === 'hit' ? event.duration : event.duration) ? event : null
}
export function frequencyAt(event: TelemetryEvent, position: number): number {
  const curve = event.frequencyCurve
  if (!curve?.times.length) return event.hz
  const t = Math.max(0, position - event.start)
  const i = upperBound(curve.times, t, v => v) - 1
  if (i < 0) return curve.values[0]
  if (i + 1 === curve.times.length) return curve.values[i]
  const f = (t - curve.times[i]) / (curve.times[i + 1] - curve.times[i])
  return curve.values[i] * (1 - f) + curve.values[i + 1] * f
}
export function noteName(note: number | null) {
  return note == null ? '—' : `${['C', 'C♯', 'D', 'D♯', 'E', 'F', 'F♯', 'G', 'G♯', 'A', 'A♯', 'B'][((note % 12) + 12) % 12]}${Math.floor(note / 12) - 1}`
}
export function chooseFocus(events: TelemetryEvent[], position: number) {
  const score = (e: TelemetryEvent) => {
    if (e.kind === 'tone' && !e.reinforcement && e.role === 'lead') return 600
    if (e.kind === 'tone' && !e.reinforcement && e.profile === 'PLUCKED' && e.role !== 'bass' && e.velocity >= 80 && e.duration >= .25) return 550
    if (e.kind === 'hit' && !e.reinforcement) return 500
    if (e.kind === 'tone' && Math.abs(frequencyAt(e, position) - e.hz) > .05) return 400
    if (e.reinforcement && e.kind !== 'tray') return 300
    if (e.kind === 'tray') return 200
    return 100
  }
  return [...events].sort((a, b) => score(b) - score(a) || b.velocity - a.velocity || b.duration - a.duration || a.id.localeCompare(b.id))[0] ?? null
}
export function streamAt(events: TelemetryEvent[], position: number) {
  const end = upperBound(events, position, e => e.start)
  return events.slice(Math.max(0, end - 16), end).reverse()
}
export function eventTime(time: number) {
  const ms = Math.floor(Math.max(0, time) * 1000)
  return `${String(Math.floor(ms / 60000)).padStart(2, '0')}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}.${String(ms % 1000).padStart(3, '0')}`
}
