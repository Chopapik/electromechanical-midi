/** Tytuł aktywnego MIDI + eject otwierający okno wyboru pliku. */

import { Eject } from '@phosphor-icons/react'
import { useRef, useState } from 'react'
import type { DragEvent as ReactDragEvent } from 'react'

interface Props {
  selected: string | null
  onUpload: (file: File) => void
  uploading?: boolean
}

const ACCEPTED = '.mid,.midi,audio/midi,audio/x-midi'

export function MidiFileSelector({ selected, onUpload, uploading = false }: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [dragging, setDragging] = useState(false)

  const pick = () => inputRef.current?.click()

  const handleFiles = (list: FileList | null) => {
    const file = list?.[0]
    if (file) onUpload(file)
  }

  return (
    <div
      className={`midi-now-playing${dragging ? ' dragging' : ''}${uploading ? ' busy' : ''}`}
      onDragOver={(event: ReactDragEvent<HTMLDivElement>) => {
        event.preventDefault()
        if (!uploading) setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault()
        setDragging(false)
        if (!uploading) handleFiles(event.dataTransfer.files)
      }}
    >
      <p className="midi-title" title={selected ?? undefined}>{selected ?? 'Brak pliku MIDI'}</p>
      <button
        type="button"
        className="midi-eject"
        aria-label="Wczytaj MIDI"
        title="Wczytaj MIDI"
        onClick={pick}
        disabled={uploading}
      >
        <Eject size={18} weight="fill" aria-hidden="true" />
      </button>
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
  )
}
