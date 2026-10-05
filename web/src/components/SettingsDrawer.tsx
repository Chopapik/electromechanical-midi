import { X } from '@phosphor-icons/react'
import { useEffect, useRef } from 'react'
import type { PlayerApi } from '../usePlayer'
import { VirtualOrchestra } from './VirtualOrchestra'
import { LegacyControls } from './LegacyControls'
import { MidiFileSelector } from './MidiFileSelector'
import { ArrangementImport } from './ArrangementImport'
import { FirmwarePanel } from './FirmwarePanel'

export function SettingsDrawer({ player, onClose }: { player: PlayerApi; onClose: () => void }) {
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
      <FirmwarePanel />
      <VirtualOrchestra virtual={player.state?.virtual} metadata={player.metadata} configure={player.configureVirtual} arrangementActive={player.state?.arrangementActive} hardware={player.state?.arrangementHardware} />
      <details className="manual-disclosure"><summary>ADVANCED / MANUAL HARDWARE</summary><MidiFileSelector files={player.files} selected={player.state?.file ?? null} onSelect={player.selectFile} onUpload={player.uploadFile} uploading={player.uploading} /><LegacyControls player={player} /><ArrangementImport /></details>
    </div>
  </aside>
}
