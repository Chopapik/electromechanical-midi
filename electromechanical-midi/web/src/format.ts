/** Formatowanie czasu i liczb. */

export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00'

  const total = Math.floor(seconds)
  const minutes = Math.floor(total / 60)
  const rest = total % 60

  return `${minutes}:${rest.toString().padStart(2, '0')}`
}

export function formatHz(hz: number | null): string {
  return hz === null ? '—' : `${hz.toFixed(2)} Hz`
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`

  return `${(bytes / 1024).toFixed(1)} kB`
}

/** Zamiana nuty MIDI na nazwe (E3, C#4...) - do podgladu nuty zrodlowej. */
const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

export function midiNoteName(note: number | null): string | null {
  if (note === null || note < 0 || note > 127) return null

  return `${NOTE_NAMES[note % 12]}${Math.floor(note / 12) - 1}`
}
