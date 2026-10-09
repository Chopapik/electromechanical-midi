import { X } from '@phosphor-icons/react'
import { useEffect, useRef } from 'react'
import type { PlayerApi } from '../usePlayer'
import { VirtualOrchestra } from './VirtualOrchestra'
import { LegacyControls } from './LegacyControls'
import { MidiFileSelector } from './MidiFileSelector'
import { ArrangementImport } from './ArrangementImport'
import { FirmwarePanel } from './FirmwarePanel'
import { HardwareStatus } from './HardwareStatus'
import { StrictTracksPanel } from './StrictTracksPanel'

export function SettingsDrawer({ player, onClose }: { player: PlayerApi; onClose: () => void }) {
  const hardwareMode = player.state?.virtual?.runtimeMode
    ? player.state.virtual.runtimeMode === 'hardware'
    : !player.state?.virtual?.enabled
  useEffect(() => {
    if (!hardwareMode) return
    player.refreshPorts()
    const timer = window.setInterval(player.refreshPorts, 5000)
    return () => window.clearInterval(timer)
  }, [hardwareMode, player.refreshPorts])
  const panel = useRef<HTMLElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    panel.current?.querySelector<HTMLButtonElement>('button')?.focus()
    return () => previous?.focus()
  }, [])
  return <aside ref={panel} className="settings-drawer" role="dialog" aria-label="Settings" onKeyDown={e => {
    if (e.key === 'Escape') { e.preventDefault(); onClose() }
  }}>
    <header><h2>Settings</h2><button type="button" aria-label="Close Settings" onClick={onClose}><X size={18} weight="fill" aria-hidden="true" /></button></header>
    <div className="settings-body">
      {(hardwareMode || player.state?.hardware.controllerTarget === 'esp32') && <section aria-label="Połączenie Arduino">
        <h3>Połączenie kontrolera</h3>
        <HardwareStatus hardware={player.state?.hardware ?? null} ports={player.ports}
          onReconnect={player.reconnect} onHome={player.home} onRefreshPorts={player.refreshPorts} />
      </section>}
      <FirmwarePanel selectedTarget={player.state?.hardware.controllerTarget ?? 'uno'} onTargetChange={player.setController} />
      <StrictTracksPanel player={player} />
      <VirtualOrchestra virtual={player.state?.virtual} metadata={player.metadata} configure={player.configureVirtual} arrangementActive={player.state?.arrangementActive} hardware={player.state?.arrangementHardware} />
      <details className="manual-disclosure"><summary>ADVANCED / MANUAL HARDWARE</summary><MidiFileSelector files={player.files} selected={player.state?.file ?? null} onSelect={player.selectFile} onUpload={player.uploadFile} uploading={player.uploading} /><LegacyControls player={player} /><ArrangementImport /></details>
    </div>
  </aside>
}
