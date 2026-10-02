/** Typy wspolne dla frontendu (odpowiadaja JSON-owi z backendu). */

export type PlaybackStateValue = 'stopped' | 'playing' | 'paused'

export interface HardwareState {
  connected: boolean
  port: string | null
  label: string | null
  error: string | null
  log: string[]
}

export interface DrumState {
  value: number
  output: number | null
  toneHz: number
  lastValue: number
  running: boolean
  connected: boolean
  minHz: number
  maxHz: number
}

export interface PlayerState {
  state: PlaybackStateValue
  position: number
  duration: number
  file: string | null
  track: number | null
  trackName: string | null
  midiNote: number | null
  noteName: string | null
  sourceNote: number | null
  frequency: number | null
  transpose: string
  strategy: string
  range: { minHz: number; maxHz: number }
  stats: Record<string, number> | null
  hardware: HardwareState
  drum: DrumState
}

export interface MidiFileEntry {
  name: string
  size: number
  modified: number
}

export interface TrackInfo {
  index: number
  name: string
  label: string
  noteCount: number
  channels: number[]
  isDrums: boolean
  polyphonic: boolean
}

export interface FileMetadata {
  name: string
  duration: number
  tempoChanges: number
  type: number
  ticksPerBeat: number
  tracks: TrackInfo[]
}

export interface PortInfo {
  device: string
  label: string
  usbId: string
  score: number
}

export interface PortsResponse {
  ports: PortInfo[]
  current: string | null
  connected: boolean
}

export interface ServerMessage {
  type: 'state' | 'error'
  state?: PlayerState
  message?: string
}
