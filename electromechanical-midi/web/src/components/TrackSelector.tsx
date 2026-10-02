/** Wybor tracku z pliku MIDI. */

import type { FileMetadata } from '../types'

interface Props {
  metadata: FileMetadata | null
  selected: number | null
  onSelect: (index: number) => void
}

export function TrackSelector({ metadata, selected, onSelect }: Props) {
  const tracks = metadata?.tracks ?? []
  const playable = tracks.filter((track) => track.noteCount > 0)

  return (
    <label className="field">
      <span className="field-label">Track</span>

      <select
        value={selected ?? ''}
        onChange={(event) => onSelect(Number(event.target.value))}
        disabled={playable.length === 0}
      >
        {playable.length === 0 && <option value="">(brak tracków z nutami)</option>}

        {playable.map((track) => (
          <option key={track.index} value={track.index}>
            [{track.index}] {track.name} · {track.noteCount} nut
            {track.polyphonic ? ' · polifonia' : ' · monofonia'}
            {track.isDrums ? ' · perkusja' : ''}
          </option>
        ))}
      </select>
    </label>
  )
}
