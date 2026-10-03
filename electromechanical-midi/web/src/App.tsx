/** Glowny widok lokalnego playera. */

import { useState } from 'react'
import { ArrangementEditor } from './components/ArrangementEditor'
import { ArrangementImport } from './components/ArrangementImport'
import { DrumPanel } from './components/DrumPanel'
import { HardwareStatus } from './components/HardwareStatus'
import { MidiFileSelector } from './components/MidiFileSelector'
import { NoteDisplay } from './components/NoteDisplay'
import { PlayerControls } from './components/PlayerControls'
import { ProgressBar } from './components/ProgressBar'
import { TrackSelector } from './components/TrackSelector'
import { TransposeSelector } from './components/TransposeSelector'
import { VirtualOrchestra } from './components/VirtualOrchestra'
import { usePlayer } from './usePlayer'

export default function App() {
  const player = usePlayer()
  const [tab, setTab] = useState<'player' | 'orchestra' | 'arrangement'>('player')
  const { state } = player

  const duration = state?.duration ?? 0
  const playing = state?.state === 'playing'
  const hasTrack = Boolean(state?.file && state?.track !== null)
  const stats = state?.stats

  return (
    <div className={`app ${tab === 'arrangement' ? 'arrangement-open' : ''}`}>
      <header className="header">
        <h1>Electromechanical MIDI</h1>
        <p className="subtitle">
          MIDI → Python → Serial → Arduino Uno → stacja dyskietek 3.5″
        </p>
      </header>

      <nav className="main-tabs" aria-label="Main sections">
        {(['player', 'orchestra', 'arrangement'] as const).map(value =>
          <button key={value} type="button" aria-current={tab === value ? 'page' : undefined}
            onClick={() => setTab(value)}>{value.toUpperCase()}</button>)}

        {/* Jeden import dla wszystkich zakladek: ten sam JSON opisuje
            instancje wirtualne i sprzetowe (pole "mode" kazdego urzadzenia). */}
        <ArrangementImport className="global-import" />
      </nav>

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
          {state?.hardware?.pendingPlay && (
            <span className="pill waiting" role="status">
              czekam na Arduino (homing) — ruszy po READY
            </span>
          )}
          {stats && (
            <span className="muted">
              {stats.notes} nut · złożone oktawowo: {stats.folded}
              {stats.skipped ? ` · pominięte: ${stats.skipped}` : ''}
            </span>
          )}
        </div>
      </section>

      {tab === 'player' && <section className="selectors">
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

        <TrackSelector
          metadata={player.metadata}
          selected={state?.hdd.midiTrack ?? null}
          onSelect={(index) => player.selectHddTrack(index < 0 ? null : index)}
          label="HDD Track (perkusja)"
          allowNone
          noneLabel="None (HDD wyłączony)"
        />

        {state?.hdd.midiTrack != null && (
          <>
            <label className="field">
              <span className="field-label">HDD Note (co ma uderzać)</span>

              <select
                value={state.hdd.note ?? ''}
                onChange={(event) =>
                  player.selectHddNote(
                    event.target.value === '' ? null : Number(event.target.value),
                  )
                }
              >
                <option value="">
                  wszystkie nuty ({state.hdd.notes.reduce((sum, o) => sum + o.count, 0)})
                </option>

                {state.hdd.notes.map((option) => (
                  <option key={option.note} value={option.note}>
                    {option.name} ({option.note}) · {option.count}×
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span className="field-label">HDD Gęstość</span>

              <select
                value={state.hdd.rate ?? ''}
                onChange={(event) =>
                  player.selectHddRate(
                    event.target.value === '' ? null : Number(event.target.value),
                  )
                }
              >
                <option value="">bez limitu (tylko mechanika ~9/s)</option>
                <option value="4">max 4 uderzenia/s</option>
                <option value="3">max 3 uderzenia/s</option>
                <option value="2">max 2 uderzenia/s</option>
                <option value="1">max 1 uderzenie/s (half-time)</option>
                <option value="0.5">max 1 na 2 s</option>
              </select>
            </label>

            <p className="hdd-status">
              HDD: {state.hdd.midiTrackName} ·{' '}
              {state.hdd.note == null
                ? 'wszystkie nuty'
                : state.hdd.notes.find((o) => o.note === state.hdd.note)?.name ??
                  `nuta ${state.hdd.note}`}{' '}
              · {state.hdd.count} uderzeń
              {state.hdd.busy ? ' · ⏵ uderzenie' : ''}
            </p>
          </>
        )}
      </section>}

      {tab === 'orchestra' && <VirtualOrchestra virtual={state?.virtual} metadata={player.metadata} configure={player.configureVirtual} arrangementActive={state?.arrangementActive} hardware={state?.arrangementHardware} />}

      {tab === 'arrangement' && <ArrangementEditor file={state?.file ?? null} state={state} seek={player.seek} />}

      {tab === 'player' && <><HardwareStatus
        hardware={state?.hardware ?? null}
        ports={player.ports}
        onReconnect={player.reconnect}
        onHome={player.home}
      />

      <DrumPanel
        drum={state?.drum ?? null}
        onStart={player.startDrum}
        onStop={player.stopDrum}
        onPwm={player.setDrum}
        onTone={player.setDrumTone}
      /></>}

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
