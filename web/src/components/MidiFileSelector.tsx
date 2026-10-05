/** Wybor pliku MIDI z katalogu midi/ + wgranie nowego z przegladarki. */

import { useRef, useState } from 'react'
import type { DragEvent as ReactDragEvent } from 'react'

import { formatBytes } from '../format'
import type { MidiFileEntry } from '../types'

interface Props {
  files: MidiFileEntry[]
  selected: string | null
  onSelect: (name: string) => void
  onUpload: (file: File) => void
  uploading?: boolean
  compact?: boolean
}

const ACCEPTED = '.mid,.midi,audio/midi,audio/x-midi'

export function MidiFileSelector({
  files,
  selected,
  onSelect,
  onUpload,
  uploading = false,
  compact = false,
}: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [dragging, setDragging] = useState(false)

  const pick = () => inputRef.current?.click()

  const handleFiles = (list: FileList | null) => {
    const file = list?.[0]

    if (file) onUpload(file)
  }

  const handleDrop = (event: ReactDragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragging(false)

    if (!uploading) handleFiles(event.dataTransfer.files)
  }

  return (
    <div className={`field ${compact ? 'compact-midi' : ''}`}>
      <label className="field-label" htmlFor="midi-file">
        MIDI
      </label>

      <select
        id="midi-file"
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

      <div
        className={`upload${dragging ? ' dragging' : ''}${uploading ? ' busy' : ''}`}
        onDragOver={(event) => {
          event.preventDefault()
          if (!uploading) setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
      >
        <button
          type="button"
          className="button small"
          onClick={pick}
          disabled={uploading}
        >
          {uploading ? 'Wgrywam…' : compact ? 'Upload' : '＋ Wgraj plik MIDI'}
        </button>

        <span className="upload-hint">
          {dragging ? 'upuść plik tutaj' : 'albo przeciągnij .mid w to miejsce'}
        </span>

        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED}
          hidden
          onChange={(event) => {
            handleFiles(event.target.files)
            event.target.value = ''
          }}
        />
      </div>
    </div>
  )
}
