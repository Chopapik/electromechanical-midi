/** Aktualnie grana nuta: nazwa + czestotliwosc (albo REST). */

import { formatHz, midiNoteName } from '../format'
import type { PlayerState } from '../types'

interface Props {
  state: PlayerState | null
}

export function NoteDisplay({ state }: Props) {
  const noteName = state?.noteName ?? null
  const sourceName = midiNoteName(state?.sourceNote ?? null)
  const transposed = noteName !== null && sourceName !== null && sourceName !== noteName

  return (
    <div className={`note${noteName ? '' : ' rest'}`}>
      <div className="note-name">{noteName ?? 'REST'}</div>
      <div className="note-hz">{formatHz(state?.frequency ?? null)}</div>

      {transposed && (
        <div className="note-source">
          z {sourceName} (transpozycja oktawowa)
        </div>
      )}
    </div>
  )
}
