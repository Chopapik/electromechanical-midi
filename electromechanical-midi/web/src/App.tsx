/** Glowny widok lokalnego playera. */

import { DrumPanel } from './components/DrumPanel'
import { HardwareStatus } from './components/HardwareStatus'
import { MidiFileSelector } from './components/MidiFileSelector'
import { NoteDisplay } from './components/NoteDisplay'
import { PlayerControls } from './components/PlayerControls'
import { ProgressBar } from './components/ProgressBar'
import { TrackSelector } from './components/TrackSelector'
import { TransposeSelector } from './components/TransposeSelector'
import { usePlayer } from './usePlayer'

export default function App() {
  const player = usePlayer()
  const { state } = player

  const duration = state?.duration ?? 0
  const playing = state?.state === 'playing'
  const hasTrack = Boolean(state?.file && state?.track !== null)
  const stats = state?.stats

  return (
    <div className="app">
      <header className="header">
        <h1>Electromechanical MIDI</h1>
        <p className="subtitle">
          MIDI → Python → Serial → Arduino Uno → stacja dyskietek 3.5″
        </p>
      </header>

      {player.error && (
        <div className="banner error">
          <span>{player.error}</span>
          <button type="button" className="button small" onClick={player.dismissError}>
            Zamknij
          </button>
        </div>
      )}

      {!player.socketConnected && (
        <div className="banner warning">Brak połączenia z backendem — próbuję ponownie…</div>
      )}

      <section className="now-playing">
        <div className="title">{state?.file ?? 'wybierz plik MIDI'}</div>
        <div className="subtitle-track">{state?.trackName ?? '—'}</div>

        <NoteDisplay state={state} />
      </section>

      <section className="transport">
        <PlayerControls
          state={state?.state ?? 'stopped'}
          disabled={!hasTrack}
          onRestart={() => player.seek(0)}
          onToggle={player.toggle}
          onStop={player.stop}
        />

        <ProgressBar
          position={state?.position ?? 0}
          duration={duration}
          playing={playing}
          onSeek={player.seek}
        />

        <div className="status-line">
          <span className={`pill ${state?.state ?? 'stopped'}`}>{state?.state ?? 'stopped'}</span>
          {stats && (
            <span className="muted">
              {stats.notes} nut · złożone oktawowo: {stats.folded}
              {stats.skipped ? ` · pominięte: ${stats.skipped}` : ''}
            </span>
          )}
        </div>
      </section>

      <section className="selectors">
        <MidiFileSelector
          files={player.files}
          selected={state?.file ?? null}
          onSelect={player.selectFile}
          onUpload={player.uploadFile}
          uploading={player.uploading}
        />

        <TrackSelector
          metadata={player.metadata}
          selected={state?.track ?? null}
          onSelect={player.selectTrack}
          label="FDD Track"
        />

        <TrackSelector
          metadata={player.metadata}
          selected={state?.drum.midiTrack ?? null}
          onSelect={(index) => player.selectDrumTrack(index < 0 ? null : index)}
          label="VHS Drum Track"
          allowNone
          noneLabel="None (bęben ręcznie)"
        />

        <TransposeSelector
          value={state?.transpose ?? 'auto'}
          range={state?.range ?? null}
          onSelect={player.selectTranspose}
          label="FDD transpose"
        />

        <TransposeSelector
          value={state?.drum.transpose ?? 'auto'}
          range={state?.drum.range ?? null}
          onSelect={player.selectDrumTranspose}
          label="VHS Drum transpose"
        />

        <label className="field">
          <span className="field-label">VHS Drum strategy</span>

          <select
            value={state?.drum.strategy ?? 'highest'}
            onChange={(event) => player.selectDrumStrategy(event.target.value)}
          >
            <option value="highest">highest — najwyższa nuta (melodia)</option>
            <option value="lowest">lowest — najniższa nuta (bas)</option>
            <option value="last">last — ostatni NOTE_ON</option>
          </select>
        </label>
      </section>

      <HardwareStatus
        hardware={state?.hardware ?? null}
        ports={player.ports}
        onReconnect={player.reconnect}
      />

      <DrumPanel
        drum={state?.drum ?? null}
        onStart={player.startDrum}
        onStop={player.stopDrum}
        onPwm={player.setDrum}
        onTone={player.setDrumTone}
      />

      <footer className="footer">
        <span>
          Kliknij lub przeciągnij pasek, żeby przewinąć (seek). Strzałki ← → przewijają o 5 s,
          Shift+strzałka o 30 s.
        </span>
        <span className="muted">
          Zakres stacji: {state?.range.minHz ?? 130}–{state?.range.maxHz ?? 330} Hz · jedna nuta
          naraz
        </span>
      </footer>
    </div>
  )
}
