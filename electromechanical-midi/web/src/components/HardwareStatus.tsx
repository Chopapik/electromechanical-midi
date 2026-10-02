/** Status sprzetu: polaczenie, port, reconnect, wybor portu. */

import type { HardwareState, PortInfo } from '../types'

interface Props {
  hardware: HardwareState | null
  ports: PortInfo[]
  onReconnect: (port?: string) => void
}

export function HardwareStatus({ hardware, ports, onReconnect }: Props) {
  const connected = hardware?.connected ?? false
  const current = hardware?.port ?? null

  return (
    <div className="hardware">
      <div className={`hardware-status ${connected ? 'ok' : 'off'}`}>
        <span className="dot" />
        <span className="hardware-text">
          <strong>{connected ? 'Arduino connected' : 'Arduino disconnected'}</strong>
          <small>{current ?? 'brak portu'}</small>
        </span>
      </div>

      {hardware?.error && <p className="hardware-error">⚠ {hardware.error}</p>}

      <div className="hardware-actions">
        {ports.length > 1 && (
          <select
            className="port-select"
            defaultValue={current ?? ports[0]?.device ?? ''}
            onChange={(event) => onReconnect(event.target.value)}
            aria-label="Port szeregowy"
          >
            {ports.map((port) => (
              <option key={port.device} value={port.device}>
                {port.device} ({port.label})
              </option>
            ))}
          </select>
        )}

        <button type="button" className="button" onClick={() => onReconnect()}>
          Reconnect
        </button>
      </div>
    </div>
  )
}
