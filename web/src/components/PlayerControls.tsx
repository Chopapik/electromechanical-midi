/** Przyciski: od poczatku, play/pause, stop. */

import { Rewind, Play, Pause, Stop, CircleNotch } from '@phosphor-icons/react'
type PlaybackStateValue = 'playing' | 'paused' | 'stopped'

interface Props {
  state: PlaybackStateValue
  disabled: boolean
  loading?: boolean
  loadingFrom?: 'stopped' | 'paused'
  onRestart: () => void
  onToggle: () => void
  onStop: () => void
}

export function PlayerControls({ state, disabled, loading = false, onRestart, onToggle, onStop }: Props) {
  // Idle (szary + play): stopped oraz każdy nieznany stan. Orange tylko przy jawnej pauzie.
  const mode = state === 'playing' ? 'playing' : state === 'paused' ? 'paused' : 'idle'
  const showPause = mode === 'playing'

  return (
    <div className="controls">
      <button
        type="button"
        className="button icon"
        title="Od początku"
        aria-label="Od początku"
        onClick={onRestart}
        disabled={disabled}
      >
        <Rewind size={18} weight="fill" aria-hidden="true" />
      </button>

      <button
        type="button"
        className={`button icon playback-toggle is-${loading ? 'idle' : mode}${loading ? ' loading' : ''}`}
        aria-label={loading ? 'Ładowanie odtwarzania' : showPause ? 'Pauza' : 'Play'}
        aria-busy={loading}
        aria-description={loading ? 'loading' : state}
        title={loading ? 'Ładowanie odtwarzania' : showPause ? 'Pauza' : 'Play'}
        onClick={onToggle}
        disabled={disabled || loading}
      >
        {loading ? <CircleNotch className="playback-spinner" size={18} weight="bold" aria-hidden="true" /> : showPause ? <Pause size={18} weight="fill" aria-hidden="true" /> : <Play size={18} weight="fill" aria-hidden="true" />}
      </button>

      <button
        type="button"
        className="button icon"
        title="Stop"
        aria-label="Stop"
        onClick={onStop}
      >
        <Stop size={18} weight="fill" aria-hidden="true" />
      </button>
    </div>
  )
}
