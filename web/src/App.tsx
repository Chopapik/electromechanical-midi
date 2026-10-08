import { useState } from 'react'
import { InstrumentLab } from './components/InstrumentLab'
import { MidiFileSelector } from './components/MidiFileSelector'
import { PlayerControls } from './components/PlayerControls'
import { ProgressBar } from './components/ProgressBar'
import { SettingsDrawer } from './components/SettingsDrawer'
import { TelemetryMonitor } from './components/TelemetryMonitor'
import { usePlayer } from './usePlayer'
import { useTelemetry } from './useTelemetry'

export default function App() {
  const player = usePlayer()
  const [lab, setLab] = useState(false)
  const [settings, setSettings] = useState(false)
  const { state } = player
  const telemetry = useTelemetry(state?.file ?? null, state?.arrangementRevision ?? 0, state?.virtual?.config.tonalMode, state?.virtual?.config.hddMode, state?.virtual?.audioRevision)
  return <div className="workstation">
    <header className="top-bar">
      <div className="top-bar-content">
        <nav className="lab-actions"><button onClick={() => setLab(false)} aria-pressed={!lab}>ORKIESTRA</button><button onClick={() => { setSettings(false); setLab(true) }} aria-pressed={lab}>INSTRUMENT LAB</button></nav>
        {!lab && <>
        <MidiFileSelector compact files={player.files} selected={state?.file ?? null} onSelect={player.selectFile} onUpload={player.uploadFile} uploading={player.uploading} />
        <PlayerControls loadingFrom={player.startingFrom} loading={player.starting} state={state?.state ?? 'stopped'} disabled={!state?.file} onRestart={() => player.seek(0)} onToggle={player.toggle} onStop={player.stop} />
        <ProgressBar position={state?.position ?? 0} duration={state?.duration ?? 0} playing={state?.state === 'playing' && state?.virtual?.audioClockRunning !== false} onSeek={player.seek} />
        </>}
      </div>
    </header>
    {player.error && <div className="banner error" role="alert">{player.error}<button onClick={player.dismissError}>Zamknij</button></div>}
    {!player.socketConnected && <div className="banner warning" role="alert">Brak połączenia z backendem — próbuję ponownie…</div>}
    {state?.hardware.error && <div className="banner warning" role="alert">{state.hardware.error}</div>}
    {lab ? <InstrumentLab player={player} /> : <TelemetryMonitor state={state} view={telemetry.view} error={telemetry.error} metadata={player.metadata} onSettings={() => setSettings(v => !v)} settingsOpen={settings} />}
    {settings && <SettingsDrawer player={player} onClose={() => setSettings(false)} />}
  </div>
}
