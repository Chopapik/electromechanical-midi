/** Wybor tracku z pliku MIDI. */

import type { FileMetadata } from '../types'

interface Props {
  metadata: FileMetadata | null
  selected: number | null
  onSelect: (index: number) => void
  label?: string
  allowNone?: boolean
  noneLabel?: string
}

export function TrackSelector({
  metadata,
  selected,
  onSelect,
  label = 'Track',
  allowNone = false,
  noneLabel = '— brak —',
}: Props) {
  const tracks = metadata?.tracks ?? []
  const playable = tracks.filter((track) => track.noteCount > 0)

  return (
    <label className="field">
      <span className="field-label">{label}</span>

      <select
        value={selected ?? ''}
        onChange={(event) =>
          onSelect(event.target.value === '' ? -1 : Number(event.target.value))
        }
        disabled={playable.length === 0 && !allowNone}
      >
        {allowNone && <option value="">{noneLabel}</option>}
        {playable.length === 0 && !allowNone && <option value="">(brak tracków z nutami)</option>}

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
