import { CircleNotch, UploadSimple } from '@phosphor-icons/react'
import { useState } from 'react'

export function FirmwarePanel({ selectedTarget, onTargetChange }: { selectedTarget?: string; onTargetChange?: (target: string) => void } = {}) {
  const [localTarget, setLocalTarget] = useState('uno')
  const target = selectedTarget ?? localTarget
  function setTarget(value: string) { setLocalTarget(value); onTargetChange?.(value) }
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [log, setLog] = useState('')
  const [failed, setFailed] = useState(false)
  async function upload() {
    setBusy(true); setFailed(false); setLog('')
    setMessage('Kompilacja, wgrywanie i ponowne łączenie Arduino…')
    try {
      const response = await fetch(target === 'uno' ? '/api/firmware/upload' : '/api/firmware/upload?target=esp32', { method: 'POST' })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || 'Nie udało się wgrać firmware.')
      setLog(result.log)
      setFailed(!result.ready)
      setMessage(result.ready
        ? `Firmware wgrany. Arduino READY · ${result.port}`
        : 'Firmware wgrany, ale Arduino nie odpowiedziało READY. Sprawdź połączenie FDD i komunikaty sprzętu.')
    } catch (error) {
      setFailed(true)
      setMessage(error instanceof Error ? error.message : String(error))
    } finally { setBusy(false) }
  }
  return <section className="firmware-panel" aria-label="Arduino firmware">
    <h3>Arduino firmware</h3>
    <p>Wgrywa aktualny firmware dla wybranego kontrolera. Wybierz zgodnie z podłączoną płytką. Zatrzymuje odtwarzanie; po uploadzie ponownie łączy Arduino. Zamknij Serial Monitor.</p>
    <label>Kontroler <select aria-label="Firmware target" value={target} disabled={busy} onChange={e => setTarget(e.target.value)}><option value="uno">Arduino Uno · Serial</option><option value="esp32">ESP32-WROOM-32 · BLE</option></select></label>
    <button type="button" disabled={busy} onClick={upload}>
      {busy ? <CircleNotch size={18} className="playback-spinner" aria-hidden="true" /> : <UploadSimple size={18} aria-hidden="true" />}
      {busy ? 'Wgrywanie firmware…' : 'Wgraj ponownie firmware'}
    </button>
    {message && <p role={failed ? 'alert' : 'status'}>{message}</p>}
    {log && <details><summary>Log wgrywania</summary><pre>{log}</pre></details>}
  </section>
}
