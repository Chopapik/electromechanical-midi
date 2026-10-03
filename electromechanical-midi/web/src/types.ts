/** Typy wspolne dla frontendu (odpowiadaja JSON-owi z backendu). */

export type PlaybackStateValue = 'stopped' | 'playing' | 'paused'

export interface HardwareState {
  connected: boolean
  port: string | null
  label: string | null
  error: string | null
  warning: string | null
  log: string[]
  /** true w trakcie homingu/reconnectu — Play poczeka w kolejce */
  connecting?: boolean
  /** true gdy Play zostal klikniety przed READY i wystartuje sam */
  pendingPlay?: boolean
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
  /** "midi" gdy bęben gra drugi głos z pliku, "manual" gdy sterujesz ręcznie */
  controlledBy: 'midi' | 'manual'
  drive: number
  range: { minHz: number; maxHz: number }
  transpose: string
  strategy: string
  midiTrack: number | null
  midiTrackName: string | null
  midiNote: number | null
  midiNoteName: string | null
  midiFrequency: number | null
}

export interface HddNoteOption {
  note: number
  name: string
  count: number
}

export interface HddState {
  connected: boolean
  busy: boolean
  count: number
  /** "midi" gdy HDD gra z pliku, "off" gdy wyłączony */
  controlledBy: 'midi' | 'off'
  midiTrack: number | null
  midiTrackName: string | null
  /** wybrana nuta perkusyjna; null = wszystkie nuty tracku */
  note: number | null
  /** maks. uderzeń na sekundę; null = tylko limit mechaniki (~9/s) */
  rate: number | null
  /** nuty dostępne w wybranym tracku (do wyboru jednej) */
  notes: HddNoteOption[]
  lastNote: number | null
  lastNoteName: string | null
}

export interface PlayerState {
  virtual?: VirtualState
  arrangementRevision?: number
  arrangementActive?: boolean
  arrangementOrigin?: 'auto' | 'manual' | 'hybrid' | null
  arrangementTotals?: ArrangementReport['totals'] | null
  arrangementHardware?: ArrangementHardware
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
  hdd: HddState
}

/** Dokad trafia instancja: symulacja, fizyczny sprzet, albo oba naraz. */
export type DeviceMode = 'virtual' | 'real' | 'hybrid'

export interface VirtualDevice {
  id: string
  type: string
  name: string
  track: number | null
  role: string
  volume: number
  pan: number
  mute: boolean
  solo: boolean
  transpose: number
  gate: number
  profile: string
  mode: DeviceMode
  overrides: Record<string, { value: number | null; provenance: string; source: string }>
}

/** Ktore instancje aranzacji trafily na fizyczne linie Serial. */
export interface ArrangementHardware {
  active: boolean
  connected: boolean
  lanes: Record<string, { deviceId: string; name: string; type: string }>
  unmapped: Array<{ deviceId: string; name: string; type: string; reason: string; lane?: string; boundTo?: string }>
}

export interface VirtualConfig { name: string; devices: VirtualDevice[] }
export interface VirtualReport {
  name: string; type: string; accepted: number; played: number; dropped: number
  folded: number; delayed: number; busyConflicts: number; steps: number
  reversals: number; travel: number; activeTime: number; requestedHits: number
  acceptedHits: number; droppedWhileBusy: number; busyTime: number
  maxDensity: number
  reasons: Record<string, number>; state: Record<string, number | boolean>
}
export interface VirtualState {
  enabled: boolean
  config: VirtualConfig
  report: Record<string, VirtualReport>
  activity: Record<string, boolean>
  profiles: Array<{ id: string; kind: string; parameters: Record<string, { value: number | null; provenance: string; source: string }> }>
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

export interface ArrangementRule {
  id: string
  source: {
    track?: number; tracks?: number[]; channel?: number; channels?: number[]
    includeNotes?: number[]; excludeNotes?: number[]
    noteRange?: { min?: number; max?: number }
    velocityRange?: { min?: number; max?: number }
  }
  destination: { deviceId: string | null }
  transform: { gate: number; transpose: number; octaveFold: boolean; strategy: 'first' | 'highest' | 'lowest' | 'last' }
  articulation?: string | null
}
export interface ArrangementDocument {
  schemaVersion: number
  name: string
  midi: { file: string; sha256: string; tracks: Array<{ index: number; name: string }> }
  devices: VirtualDevice[]
  rules: ArrangementRule[]
  /** Auto Arranger: polityka wykonania; rules sa wtedy tylko recznym overridem */
  policy?: Record<string, number | string | boolean>
  origin?: 'auto' | 'manual' | 'hybrid'
}
export interface ArrangementRouteResult {
  ruleId: string; deviceId: string | null; status: 'PENDING' | 'ACCEPTED' | 'FOLDED' | 'DELAYED' | 'DROPPED' | 'UNASSIGNED'
  articulation?: string | null; reason?: string | null; originalNote?: number
  playedNote?: number | null; deviceAvailableAt?: number | null
}
/** Wynik Auto Arrangera dla jednej nuty - patrz host/playback/performance.py */
export type PerformanceOutcome =
  | 'ACCEPTED' | 'REASSIGNED' | 'DELAYED' | 'ARPEGGIATED'
  | 'SHORTENED' | 'STOLEN' | 'FOLDED' | 'DROPPED'

export type NoteRole = 'lead' | 'bass' | 'harmony' | 'percussion'

export interface ArrangementNote {
  id: string; track: number; trackName: string; channel: number
  note: number; name: string | null; start: number; duration: number
  velocity: number; isDrum: boolean; routes: ArrangementRouteResult[]
  status: 'ACCEPTED' | 'FOLDED' | 'DELAYED' | 'DROPPED' | 'UNASSIGNED'
  /** rozszerzenia Auto Arrangera */
  outcome?: PerformanceOutcome
  role?: NoteRole
  deviceId?: string | null
  preferredDevice?: string | null
  actualStart?: number
  actualDuration?: number
  delayMs?: number
  reassigned?: boolean
  folded?: boolean
  reason?: string | null
}

export interface ReportBucket {
  kind: string
  requested: number; played: number; dropped: number; onTime: number
  reassigned: number; delayed: number; arpeggiated: number
  stolen: number; shortened: number; folded: number
  dropRate: number; meanDelayMs: number; maxDelayMs: number
  retention: number; activeTime: number; utilization: number
}

export interface ReportDevice {
  deviceId: string; type: string; notes: number; dropped: number
  activeTime: number; utilization: number
}

export interface ArrangementReport {
  sourceEvents: number
  lead: {
    requested: number; played: number; dropped: number
    delayed: number; preservation: number
  }
  leadDevices: {
    devices: string[]; notes: number; nonLeadEvents: number; clean: boolean
  }
  tonal: ReportBucket
  percussion: ReportBucket
  devices: ReportDevice[]
  totals: {
    requested: number; played: number; dropped: number; dropRate: number
    retention: number; delayed: number; arpeggiated: number; reassigned: number
    voiceSteals: number; shortened: number; folded: number
    meanDelayMs: number; maxDelayMs: number
  }
  duration: number
}

export interface OrchestraView {
  name: string
  policy: Record<string, number | string | boolean>
  devices: Array<{ id: string; type: string; name: string }>
}
export interface ArrangementView {
  arrangement: ArrangementDocument | null
  notes: ArrangementNote[]
  midiIdentity: ArrangementDocument['midi'] | null
  tracks: Array<{ index: number; name: string; isDrums: boolean; noteCount: number }>
  revision: number
  report?: ArrangementReport | null
  orchestra?: OrchestraView
}
