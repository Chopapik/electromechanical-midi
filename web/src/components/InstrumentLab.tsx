import { useEffect, useState } from 'react'
import { Play, Square, Zap, Download, FlaskConical } from 'lucide-react'
import type { PlayerApi } from '../usePlayer'

export interface LabDevice { id: string; name: string; kind: string; available: boolean; bands: number[][]; reason: string | null; pulseMaxMs?: number }
export interface LabState { enabled: boolean; state: string; device: string | null; hz: number | null; duration: number; remaining: number; error: string | null; confirmed: boolean; catalog: LabDevice[] }
type Rating = { device: string; hz: number | null; duration: number; rating: string; date: string }
const HISTORY_KEY = 'instrument-lab-ratings-v1'

export function InstrumentLab({ player }: { player: PlayerApi }) {
  const [device, setDevice] = useState('sled:1')
  const [hz, setHz] = useState(392)
  const [duration, setDuration] = useState(3)
  const [amp, setAmp] = useState(64)
  const [direction, setDirection] = useState('FWD')
  const [pulseMs, setPulseMs] = useState(100)
  const [history, setHistory] = useState<Rating[]>(() => { try { const saved = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '[]'); return Array.isArray(saved) ? saved : [] } catch { return [] } })
  const lab = player.state?.lab
  const item = lab?.catalog.find(d => d.id === device)
  const tonal = item && ['fdd','sled','drum'].includes(item.kind)
  const connected = Boolean(player.socketConnected && player.state?.hardware.connected && player.state?.hardware.controllerTarget === 'esp32')
  const busy = ['starting','playing'].includes(lab?.state ?? '')
  const allowed = (value: number) => Boolean(item?.bands.some(([lo,hi]) => value >= lo && value <= hi))
  useEffect(() => {
    if (!player.socketConnected) return
    player.labCommand('lab_enter')
    const heartbeat = window.setInterval(() => player.labCommand('lab_heartbeat'), 2000)
    const leave = () => player.labCommand('lab_leave')
    window.addEventListener('pagehide', leave)
    return () => { clearInterval(heartbeat); window.removeEventListener('pagehide', leave); leave() }
  }, [player.socketConnected, player.labCommand])
  function rate(rating: string) {
    if (!lab?.device || !lab.confirmed) return
    const next = [{ device: lab.device, hz: lab.hz, duration: lab.duration, rating, date: new Date().toISOString() }, ...history].slice(0,1000)
    setHistory(next); localStorage.setItem(HISTORY_KEY, JSON.stringify(next))
  }
  function exportHistory() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(history,null,2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href=url; link.download='instrument-lab-ratings.json'; link.click(); URL.revokeObjectURL(url)
  }
  return <main className="instrument-lab">
    <h1><FlaskConical size={22} /> Instrument Lab</h1>
    <p>Ręczny test fizycznego urządzenia · ESP32: {player.state?.hardware.connected ? 'connected' : 'disconnected'} · backend: {player.socketConnected ? 'connected' : 'disconnected'}</p>
    <section className="lab-panel">
      <label>Instrument<select aria-label="Instrument" value={device} disabled={busy} onChange={e => setDevice(e.target.value)}>{lab?.catalog.map(d => <option key={d.id} value={d.id}>{d.name}{d.available ? '' : ' — niedostępny'}</option>)}</select></label>
      {tonal && <>
        <label>{item.kind === 'drum' ? 'Częstotliwość sterowania (Hz)' : 'Częstotliwość (Hz)'}<input aria-label="Częstotliwość" type="number" min="0.01" step="0.01" value={hz} disabled={busy} onChange={e => setHz(Number(e.target.value))} /></label>
        <label>Czas (s)<input aria-label="Czas" type="number" min="0.1" max="30" step="0.1" value={duration} disabled={busy} onChange={e => setDuration(Number(e.target.value))} /></label>
        <p>Dozwolone: {item.bands.map(([lo,hi]) => `${lo}–${hi} Hz`).join(' · ') || 'wg profilu urządzenia'}</p>
        <div className="lab-actions">{[110,220,392,440].filter(allowed).map(value => <button key={value} disabled={busy} onClick={() => setHz(value)}>{value} Hz</button>)}</div>
      </>}
      {item?.kind === 'drum' && <><label>AMP (0–255)<input aria-label="AMP" type="number" min="0" max="255" value={amp} disabled={busy} onChange={e => setAmp(Number(e.target.value))} /></label><p>Hz to częstotliwość sterowania, nie zmierzona wysokość dźwięku.</p></>}
      {item?.kind === 'sled' && <p>Limit ruchu: 140 kroków. Przed testem ustaw mechanizm ręcznie w pozycji początkowej; licznik nie jest pomiarem fizycznym.</p>}
      {item?.kind === 'fdd' && <p>FDD musi być zahomowane. HOME jest dostępne w ustawieniach orkiestry.</p>}
      {item?.kind === 'hdd' && <p>Pojedynczy HIT. Impuls i regenerację kontroluje istniejący profil firmware.</p>}
      {item?.kind === 'tray' && <><label>Kierunek<select value={direction} onChange={e => setDirection(e.target.value)}><option>FWD</option><option>REV</option></select></label><label>PULSE (1–{item.pulseMaxMs} ms)<input type="number" min="1" max={item.pulseMaxMs ?? 1} value={pulseMs} onChange={e => setPulseMs(Number(e.target.value))} /></label></>}
      {!item?.available && <p role="status">{item?.reason ?? 'Oczekiwanie na konfigurację…'}</p>}
      <div className="lab-actions">
        <button disabled={busy || !lab?.enabled || !item?.available || !connected} onClick={() => player.labCommand('lab_start',{device,hz,duration,amp,direction,pulseMs})}>{tonal ? <Play size={18} /> : <Zap size={18} />}{item?.kind === 'hdd' ? 'HIT' : item?.kind === 'tray' ? 'PULSE' : 'PLAY'}</button>
        <button onClick={() => player.labCommand('lab_stop')}><Square size={18} /> STOP</button>
      </div>
      <p aria-live="polite">{lab?.state ?? 'idle'} · {lab?.device ?? '—'} · {lab?.hz ?? '—'} Hz · pozostało {(lab?.remaining ?? 0).toFixed(1)} s</p>
      {lab?.error && <p role="alert">{lab.error}</p>}
    </section>
    <section className="lab-panel"><h2>Ocena i historia</h2><div className="lab-actions">{['NORMAL','RESONANCE','STRONG_RESONANCE'].map(r => <button key={r} disabled={busy || !lab?.confirmed} onClick={() => rate(r)}>{r}</button>)}<button onClick={exportHistory}><Download size={18} /> JSON</button></div>
      <ul>{history.map((r,i) => <li key={i}>{r.date} · {r.device} · {r.hz ?? 'HIT'} Hz · {r.rating}</li>)}</ul>
    </section>
  </main>
}
