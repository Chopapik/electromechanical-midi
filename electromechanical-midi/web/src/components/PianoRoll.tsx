import { useEffect, useMemo, useRef, useState } from 'react'
import type { ArrangementNote } from '../types'

export type ViewMode = 'source' | 'device' | 'simulation'
const ROW = 19
const RULER = 30
const KEYS = 76
const HEIGHT = 480
const SOURCE_COLORS = ['#58a6ff', '#e9967a', '#c084fc', '#f6c453', '#59c9a5', '#ef7fa8', '#83bdf5', '#a4d65e']
const DEVICE_COLORS = ['#4ade80', '#22d3ee', '#f9a86c', '#d494ff', '#f5d061', '#f3789a', '#76b9ff']
export const sourceColor = (index: number) => SOURCE_COLORS[index % SOURCE_COLORS.length]
export const deviceColor = (index: number) => DEVICE_COLORS[index % DEVICE_COLORS.length]
const STATUS_COLORS: Record<string, string> = {
  ACCEPTED: '#4ade80', FOLDED: '#39c3e8', DELAYED: '#f4bf4f', DROPPED: '#d65762', UNASSIGNED: '#5c6876',
}
const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
const noteLabel = (note: number) => `${NOTE_NAMES[note % 12]}${Math.floor(note / 12) - 1}`

interface Props {
  notes: ArrangementNote[]
  devices: Array<{ id: string; name: string }>
  position: number
  playing: boolean
  mode: ViewMode
  selectedId: string | null
  hiddenTracks: Set<number>
  hiddenDevices: Set<string>
  onSelect: (id: string) => void
  onSeek: (time: number) => void
}

export function PianoRoll({ notes, devices, position, playing, mode, selectedId, hiddenTracks, hiddenDevices, onSelect, onSeek }: Props) {
  const scroller = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const hits = useRef<Array<{ x: number; y: number; w: number; h: number; id: string }>>([])
  const [zoom, setZoom] = useState(80)
  const [viewport, setViewport] = useState({ left: 0, top: 0, width: 900 })
  const sorted = useMemo(() => [...notes].sort((a, b) => a.start - b.start), [notes])
  const maxDuration = useMemo(() => notes.reduce((max, note) => Math.max(max, note.duration), 0), [notes])
  const deviceIndex = useMemo(() => new Map(devices.map((d, i) => [d.id, i])), [devices])
  const totalDuration = notes.reduce((max, note) => Math.max(max, note.start + note.duration), 1)
  const fullWidth = Math.max(viewport.width, KEYS + totalDuration * zoom + 80)
  const fullHeight = RULER + 128 * ROW

  useEffect(() => {
    const element = scroller.current
    if (!element) return
    const update = () => setViewport(v => ({ ...v, width: element.clientWidth || 900 }))
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])
  useEffect(() => {
    const element = scroller.current
    if (!element || notes.length === 0) return
    const highest = Math.min(127, notes.reduce((max, note) => Math.max(max, note.note), 0) + 4)
    element.scrollTop = Math.max(0, RULER + (127 - highest) * ROW)
    setViewport(v => ({ ...v, top: element.scrollTop }))
  }, [notes.length])
  useEffect(() => {
    const element = scroller.current
    if (!element || !playing) return
    const width = element.clientWidth || viewport.width
    const marker = KEYS + position * zoom
    const left = element.scrollLeft
    if (marker < left + KEYS || marker > left + width * .7) {
      element.scrollLeft = Math.max(0, marker - width * .35)
      setViewport(previous => ({ ...previous, left: element.scrollLeft }))
    }
  }, [position, playing, zoom, viewport.width])

  useEffect(() => {
    const target = canvas.current
    const ctx = target?.getContext('2d')
    if (!target || !ctx) return
    const width = viewport.width
    const ratio = window.devicePixelRatio || 1
    target.width = Math.round(width * ratio)
    target.height = Math.round(HEIGHT * ratio)
    target.style.width = `${width}px`
    target.style.height = `${HEIGHT}px`
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
    ctx.clearRect(0, 0, width, HEIGHT)
    ctx.fillStyle = '#111923'
    ctx.fillRect(0, 0, width, HEIGHT)
    const viewStart = Math.max(0, viewport.left / zoom)
    const viewEnd = Math.max(0, (viewport.left + width - KEYS) / zoom)
    const maxPitch = 127 - Math.floor(viewport.top / ROW)
    const minPitch = 127 - Math.ceil((viewport.top + HEIGHT - RULER) / ROW)
    for (let pitch = Math.max(0, minPitch); pitch <= Math.min(127, maxPitch); pitch++) {
      const y = RULER + (127 - pitch) * ROW - viewport.top
      const black = [1, 3, 6, 8, 10].includes(pitch % 12)
      ctx.fillStyle = black ? '#17212d' : '#202b38'
      ctx.fillRect(KEYS, y, width - KEYS, ROW - 1)
      ctx.fillStyle = black ? '#26313d' : '#d8dfe8'
      ctx.fillRect(0, y, KEYS - 2, ROW - 1)
      ctx.fillStyle = black ? '#d2dbe5' : '#101820'
      ctx.font = '11px system-ui'
      ctx.fillText(noteLabel(pitch), 8, y + 13)
    }
    const step = zoom < 55 ? 5 : zoom < 120 ? 2 : 1
    for (let second = Math.floor(viewStart / step) * step; second <= viewEnd; second += step) {
      const x = KEYS + second * zoom - viewport.left
      ctx.fillStyle = '#314152'; ctx.fillRect(x, RULER, 1, HEIGHT - RULER)
      ctx.fillStyle = '#b9c9d8'; ctx.font = '11px system-ui'
      ctx.fillText(`${Math.floor(second / 60)}:${String(second % 60).padStart(2, '0')}`, x + 3, 20)
    }
    // First visible start, including notes that began before the viewport.
    const from = Math.max(0, viewStart - maxDuration)
    let lo = 0, hi = sorted.length
    while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid].start < from) lo = mid + 1; else hi = mid }
    const drawn: typeof hits.current = []
    for (let i = lo; i < sorted.length && sorted[i].start <= viewEnd; i++) {
      const n = sorted[i]
      if (hiddenTracks.has(n.track) || n.start + n.duration < viewStart) continue
      const visibleRoutes = n.routes.filter(r => r.deviceId && !hiddenDevices.has(r.deviceId))
      if (n.routes.some(r => r.deviceId) && visibleRoutes.length === 0) continue
      const x = KEYS + n.start * zoom - viewport.left
      const y = RULER + (127 - n.note) * ROW - viewport.top + 2
      if (y < RULER || y > HEIGHT) continue
      const w = Math.max(5, n.duration * zoom)
      const trackColor = sourceColor(n.track)
      const deviceId = visibleRoutes[0]?.deviceId
      const destinationColor = deviceId ? deviceColor(deviceIndex.get(deviceId) ?? 0) : '#8a97a7'
      ctx.fillStyle = mode === 'source' ? trackColor : mode === 'device' ? (deviceId ? destinationColor : '#5c6876') : STATUS_COLORS[n.status]
      ctx.fillRect(x, y, w, ROW - 4)
      ctx.strokeStyle = destinationColor
      ctx.lineWidth = selectedId === n.id ? 3 : 2
      if (n.reinforcement) ctx.setLineDash([4, 2])
      ctx.strokeRect(x + 1, y + 1, w - 2, ROW - 6)
      ctx.setLineDash([])
      ctx.fillStyle = trackColor
      ctx.fillRect(x, y, Math.min(w, 4), ROW - 4)
      if (n.status === 'DROPPED') {
        ctx.strokeStyle = '#2e0d12'; ctx.lineWidth = 2
        ctx.beginPath(); ctx.moveTo(x + 1, y + ROW - 5); ctx.lineTo(x + w - 1, y + 2); ctx.stroke()
      }
      if (n.status === 'UNASSIGNED') { ctx.setLineDash([3, 2]); ctx.strokeStyle = '#d1d8e0'; ctx.strokeRect(x + 1, y + 1, w - 2, ROW - 6); ctx.setLineDash([]) }
      if (w > 25) {
        ctx.fillStyle = '#101820'; ctx.font = 'bold 11px system-ui'
        const marker = { ACCEPTED: '✓', FOLDED: '↕', DELAYED: '⏱', DROPPED: '×', UNASSIGNED: '·' }[n.status]
        ctx.fillText(`${marker} ${n.name ?? noteLabel(n.note)}`, x + 6, y + 12, w - 8)
      }
      drawn.push({ x, y, w, h: ROW - 4, id: n.id })
    }
    hits.current = drawn
    const playX = KEYS + position * zoom - viewport.left
    if (playX >= KEYS && playX <= width) {
      ctx.fillStyle = '#ffdf75'; ctx.fillRect(playX - 1, 0, 2, HEIGHT)
      ctx.beginPath(); ctx.moveTo(playX - 5, 0); ctx.lineTo(playX + 5, 0); ctx.lineTo(playX, 8); ctx.fill()
    }
    ctx.fillStyle = '#18232e'; ctx.fillRect(0, 0, KEYS, RULER)
    ctx.fillStyle = '#cbd5e1'; ctx.font = 'bold 11px system-ui'; ctx.fillText('PITCH', 8, 20)
  }, [sorted, maxDuration, viewport, zoom, mode, selectedId, hiddenTracks, hiddenDevices, deviceIndex, position])

  const click = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const x = event.clientX - rect.left, y = event.clientY - rect.top
    if (y < RULER && x >= KEYS) { onSeek(Math.max(0, (viewport.left + x - KEYS) / zoom)); return }
    const hit = [...hits.current].reverse().find(item => x >= item.x && x <= item.x + item.w && y >= item.y && y <= item.y + item.h)
    if (hit) onSelect(hit.id)
  }

  return <div className="piano-roll">
    <div className="piano-toolbar">
      <label>Horizontal zoom <input aria-label="Horizontal zoom" type="range" min="25" max="240" value={zoom} onChange={e => setZoom(Number(e.target.value))} /></label>
      <span>{zoom} px/s · scroll time and pitch · click ruler to seek · follows playhead during Play</span>
    </div>
    <div ref={scroller} className="piano-scroller" onScroll={e => setViewport({ left: e.currentTarget.scrollLeft, top: e.currentTarget.scrollTop, width: e.currentTarget.clientWidth || 900 })}>
      <div style={{ width: fullWidth, height: fullHeight }}>
        <canvas ref={canvas} onClick={click} aria-label="MIDI piano roll" role="img" style={{ position: 'sticky', top: 0, left: 0, display: 'block' }} />
      </div>
    </div>
  </div>
}
