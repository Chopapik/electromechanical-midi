/** Status sprzetu: polaczenie, port, reconnect, wybor portu. */

import type { HardwareState, PortInfo } from '../types'

interface Props {
  hardware: HardwareState | null
  ports: PortInfo[]
  onReconnect: (port?: string) => void
  onHome: () => void
}

export function HardwareStatus({ hardware, ports, onReconnect, onHome }: Props) {
  const connected = hardware?.connected ?? false
  const connecting = hardware?.connecting ?? false
  const pendingPlay = hardware?.pendingPlay ?? false
  const current = hardware?.port ?? null
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

        <button
          type="button"
          className="button"
          onClick={onHome}
          disabled={!connected}
          title="Ponów homing FDD bez rozłączania Arduino"
        >
          {hardware?.fddStatus === 'error' ? 'Retry Home' : 'Home'}
        </button>

        <button type="button" className="button" onClick={() => onReconnect()}>
          Reconnect
        </button>
      </div>

      {warning && <p className="hardware-warning">⚠ {warning}</p>}
    </div>
  )
}
