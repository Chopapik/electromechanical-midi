/** Przyciski: od poczatku, play/pause, stop. */

import type { PlaybackStateValue } from '../types'

interface Props {
  state: PlaybackStateValue
  disabled: boolean
  onRestart: () => void
  onToggle: () => void
  onStop: () => void
}

export function PlayerControls({ state, disabled, onRestart, onToggle, onStop }: Props) {
  const playing = state === 'playing'

  return (
    <div className="controls">
      <button
        type="button"
        className="button icon"
        title="Od początku"
        onClick={onRestart}
        disabled={disabled}
      >
        ⏮
      </button>

      <button
        type="button"
        className={`button icon playback-toggle ${state}`}
        aria-label={playing ? 'Pauza' : 'Play'}
        aria-description={state}
        title={playing ? 'Pauza' : 'Play'}
        onClick={onToggle}
        disabled={disabled}
      >
        {state === 'paused' ? 'Ⅱ' : '▶'}
      </button>

      <button
        type="button"
        className="button icon"
        title="Stop"
        onClick={onStop}
        disabled={disabled}
      >
        ■
      </button>
    </div>
  )
}
