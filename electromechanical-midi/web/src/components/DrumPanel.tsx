/** Ręczne sterowanie bębnem VHS (niezależne od MIDI). */

import type { DrumState } from '../types'
import { ThrottledSlider } from './ThrottledSlider'

interface Props {
  drum: DrumState | null
  onStart: () => void
  onStop: () => void
  onPwm: (value: number) => void
  onTone: (hz: number) => void
}

function statusLabel(drum: DrumState | null): { text: string; kind: string } {
  if (!drum || !drum.connected) {
    return { text: 'Disconnected', kind: 'off' }
  }

  return drum.running
    ? { text: 'Running', kind: 'ok' }
    : { text: 'Stopped', kind: 'idle' }
}

export function DrumPanel({ drum, onStart, onStop, onPwm, onTone }: Props) {
  const connected = Boolean(drum?.connected)
  const status = statusLabel(drum)

  const value = drum?.value ?? 0
  const toneHz = drum?.toneHz ?? 0
  const output = drum?.output ?? null
  const percent = Math.round((value / 255) * 100)

  return (
    <section className="drum">
      <header className="drum-head">
        <h2>VHS Drum</h2>

        <span className={`hardware-status ${status.kind}`}>
          <span className="dot" />
          <strong>{status.text}</strong>
        </span>
      </header>

      <div className="drum-buttons">
        <button
          type="button"
          className="button primary"
          onClick={onStart}
          disabled={!connected}
          title="Start bębna"
        >
          Start
        </button>

        <button
          type="button"
          className="button"
          onClick={onStop}
          disabled={!connected}
          title="Stop bębna"
        >
          Stop
        </button>
      </div>

      <ThrottledSlider
        label="PWM (głośność)"
        min={0}
        max={255}
        value={value}
        disabled={!connected}
        format={(v) => `${v} · ${Math.round((v / 255) * 100)}%`}
        onCommit={onPwm}
      />

      <ThrottledSlider
        label="Ton (wysokość)"
        min={0}
        max={drum?.maxHz ?? 2000}
        value={toneHz}
        disabled={!connected}
        format={(v) => (v === 0 ? 'DC — bez tonu' : `${v} Hz`)}
        onCommit={onTone}
      />

      <dl className="drum-readout">
        <div>
          <dt>PWM</dt>
          <dd>{output === null ? '—' : output}</dd>
        </div>
        <div>
          <dt>Zadane</dt>
          <dd>
            {value} / 255 ({percent}%)
          </dd>
        </div>
        <div>
          <dt>Ton</dt>
          <dd>{toneHz === 0 ? 'DC' : `${toneHz} Hz`}</dd>
        </div>
      </dl>

      {!connected && (
        <p className="drum-note">
          Brak połączenia z Arduino — sterowanie bębnem niedostępne.
        </p>
      )}
    </section>
  )
}
