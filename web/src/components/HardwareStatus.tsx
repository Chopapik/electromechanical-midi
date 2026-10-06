/** Status sprzetu: polaczenie, port, reconnect, wybor portu. */

import { useState } from 'react'
import type { HardwareState, PortInfo } from '../types'

interface Props {
  hardware: HardwareState | null
  ports: PortInfo[]
  onReconnect: (port?: string) => void
  onHome: () => void
  onRefreshPorts?: () => void
}

export function HardwareStatus({ hardware, ports, onReconnect, onHome, onRefreshPorts }: Props) {
  const connected = hardware?.connected ?? false
  const connecting = hardware?.connecting ?? false
  const pendingPlay = hardware?.pendingPlay ?? false
  const current = hardware?.port ?? null
  const [chosenPort, setChosenPort] = useState<string | null>(null)
  const preferred = chosenPort ?? current ?? ''
  const selectedPort = ports.some(port => port.device === preferred) ? preferred : ''
  const warning = hardware?.warning ?? null

  const title = connected
    ? 'Arduino connected'
    : connecting
      ? 'Arduino: homing…'
      : 'Arduino disconnected'

  return (
    <div className="hardware">
      <div className={`hardware-status ${connected ? 'ok' : connecting ? 'busy' : 'off'}`}>
        <span className="dot" />
        <span className="hardware-text">
          <strong>{title}</strong>
          <small>{current ?? (connecting ? 'czekam na READY…' : 'brak portu')}</small>
        </span>
      </div>

      {connected && <p role="status">FDD: {hardware?.fddStatus === 'homing' ? 'Homing…' : hardware?.fddStatus === 'error' ? 'Error — Retry Home' : hardware?.homed ? 'Ready' : 'Not homed'}</p>}

      {connecting && (
        <p className="hardware-notice" role="status">
          Stacja dojeżdża do track 0. {pendingPlay
            ? 'Play jest w kolejce — utwór ruszy sam po READY.'
            : 'Play wciśnięty teraz wystartuje automatycznie po READY.'}
        </p>
      )}
      {pendingPlay && !connecting && (
        <p className="hardware-notice" role="status">Czekam na Arduino — utwór ruszy po READY.</p>
      )}

      {hardware?.error && <p className="hardware-error">⚠ {hardware.error}</p>}

      <div className="hardware-actions">
        <label className="field">
          <span className="field-label">Urządzenie / port szeregowy</span>
          <select
            className="port-select"
            value={selectedPort}
            onChange={(event) => setChosenPort(event.target.value)}
            disabled={connecting || ports.length === 0}
            aria-label="Port szeregowy"
          >
            <option value="">{ports.length ? 'Wybierz urządzenie…' : 'Brak wykrytych portów'}</option>
            {ports.map((port) => (
              <option key={port.device} value={port.device}>
                {port.label} — {port.device}{port.usbId ? ` [${port.usbId}]` : ''}
              </option>
            ))}
          </select>
        </label>
        {onRefreshPorts && <button type="button" className="button" onClick={onRefreshPorts}>
          Odśwież porty
        </button>}

        <button
          type="button"
          className="button"
          onClick={onHome}
          disabled={!connected}
          title="Ponów homing FDD bez rozłączania Arduino"
        >
          {hardware?.fddStatus === 'error' ? 'Retry Home' : 'Home'}
        </button>

        <button type="button" className="button" onClick={() => onReconnect(selectedPort || undefined)} disabled={connecting || (!connected && ports.length > 1 && !selectedPort)}>
          {connected ? 'Reconnect' : 'Połącz'}
        </button>
      </div>

      {warning && <p className="hardware-warning">⚠ {warning}</p>}
    </div>
  )
}
