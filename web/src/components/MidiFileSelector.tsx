/** Wybor pliku MIDI z katalogu midi/ + wgranie nowego z przegladarki. */

import { Plus } from '@phosphor-icons/react'
import { useId, useRef, useState } from 'react'
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
  showUpload?: boolean
}

const ACCEPTED = '.mid,.midi,audio/midi,audio/x-midi'

export function MidiFileSelector({
  files,
  selected,
  onSelect,
  onUpload,
  uploading = false,
  compact = false,
  showUpload = true,
}: Props) {
  const selectId = useId()
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
      <label className="field-label" htmlFor={selectId}>
        MIDI
      </label>

      <select
        id={selectId}
        value={selected ?? ''}
        onChange={(event) => onSelect(event.target.value)}
        disabled={files.length === 0}
      >
        <option value="">{files.length===0?'(brak plików w midi/)':'Wybierz MIDI'}</option>

        {files.map((file) => (
          <option key={file.name} value={file.name}>
            {compact ? file.name : `${file.name} · ${formatBytes(file.size)}`}
          </option>
        ))}
      </select>

      {showUpload && <div
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
          {!compact && !uploading && <Plus size={14} weight="fill" aria-hidden="true" />}
          {uploading ? 'Wgrywam…' : compact ? 'Wczytaj MIDI' : 'Wgraj plik MIDI'}
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
      </div>}
    </div>
  )
}
