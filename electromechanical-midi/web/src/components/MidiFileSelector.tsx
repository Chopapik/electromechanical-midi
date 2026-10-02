/** Wybor pliku MIDI z katalogu midi/. */

import { formatBytes } from '../format'
import type { MidiFileEntry } from '../types'

interface Props {
  files: MidiFileEntry[]
  selected: string | null
  onSelect: (name: string) => void
}

export function MidiFileSelector({ files, selected, onSelect }: Props) {
  return (
    <label className="field">
      <span className="field-label">MIDI</span>

      <select
        value={selected ?? ''}
        onChange={(event) => onSelect(event.target.value)}
        disabled={files.length === 0}
      >
        {files.length === 0 && <option value="">(brak plików w midi/)</option>}

        {files.map((file) => (
          <option key={file.name} value={file.name}>
            {file.name} · {formatBytes(file.size)}
          </option>
        ))}
      </select>
    </label>
  )
}
