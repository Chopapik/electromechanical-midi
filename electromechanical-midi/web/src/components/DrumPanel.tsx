/** Ręczne sterowanie bębnem VHS + informacja, gdy gra drugi głos z MIDI. */

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
  const midiControlled = drum?.controlledBy === 'midi'
  const manualEnabled = connected && !midiControlled

  const status = statusLabel(drum)
  const value = drum?.value ?? 0
  const toneHz = drum?.toneHz ?? 0
  const output = drum?.output ?? null
  const percent = Math.round((value / 255) * 100)

  return (
    <section className={`drum${midiControlled ? ' midi' : ''}`}>
      <header className="drum-head">
        <h2>VHS Drum</h2>

        <span className={`hardware-status ${status.kind}`}>
          <span className="dot" />
          <strong>{status.text}</strong>
        </span>
      </header>

      {midiControlled ? (
        <div className="drum-midi">
          <div className="drum-midi-badge">MIDI CONTROLLED</div>
          <dl className="drum-readout">
            <div>
              <dt>Track</dt>
              <dd>{drum?.midiTrackName ?? '—'}</dd>
            </div>
            <div>
              <dt>Note</dt>
              <dd>{drum?.midiNoteName ?? 'REST'}</dd>
            </div>
            <div>
              <dt>Tone</dt>
              <dd>{toneHz > 0 ? `${toneHz.toFixed(2)} Hz` : '—'}</dd>
            </div>
            <div>
              <dt>Drive</dt>
              <dd>{drum?.drive ?? 0}</dd>
            </div>
          </dl>
        </div>
      ) : (
        <>
          <div className="drum-buttons">
            <button
              type="button"
              className="button primary"
              onClick={onStart}
              disabled={!manualEnabled}
              title="Start bębna"
            >
              Start
            </button>

            <button
              type="button"
              className="button"
              onClick={onStop}
              disabled={!manualEnabled}
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
            disabled={!manualEnabled}
            format={(v) => `${v} · ${Math.round((v / 255) * 100)}%`}
            onCommit={onPwm}
          />

          <ThrottledSlider
            label="Ton (wysokość)"
            min={0}
            max={drum?.maxHz ?? 2000}
            value={toneHz}
            disabled={!manualEnabled}
            format={(v) => (v === 0 ? 'DC — bez tonu' : `${v} Hz`)}
            onCommit={onTone}
          />
        </>
      )}

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
          <dd>{toneHz === 0 ? 'DC' : `${toneHz.toFixed(2)} Hz`}</dd>
        </div>
      </dl>

      {!connected && (
        <p className="drum-note">Brak połączenia z Arduino — sterowanie bębnem niedostępne.</p>
      )}

      {midiControlled && (
        <p className="drum-note">
          Bęben gra drugi głos z pliku MIDI — sterowanie ręczne wróci po pauzie/stopie.
        </p>
      )}
    </section>
  )
}
