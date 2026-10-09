/** Jedno miejsce, w ktorym trzymany jest stan playera i polaczenie z backendem. */

import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchFiles, fetchMetadata, fetchPorts, uploadMidi } from './api'
import type {
  FileMetadata,
  MidiFileEntry,
  PlayerState,
  PortInfo,
  ServerMessage,
  VirtualConfig,
} from './types'

const RECONNECT_MS = 1200

export interface PlayerApi {
  labCommand: (action: string, payload?: Record<string, unknown>) => void
  state: PlayerState | null
  files: MidiFileEntry[]
  metadata: FileMetadata | null
  ports: PortInfo[]
  socketConnected: boolean
  uploading: boolean
  starting: boolean
  startingFrom: 'stopped' | 'paused'
  error: string | null
  dismissError: () => void
  play: () => void
  pause: () => void
  resume: () => void
  stop: () => void
  toggle: () => void
  seek: (position: number) => void
  selectFile: (name: string) => void
  selectTrack: (index: number) => void
  selectTranspose: (mode: string) => void
  reconnect: (port?: string) => void
  home: () => void
  setController: (target: string) => void
  refreshPorts: () => void
  refreshFiles: () => void
  startDrum: () => void
  stopDrum: () => void
  setDrum: (value: number) => void
  setDrumTone: (hz: number) => void
  selectDrumTrack: (track: number | null) => void
  selectDrumTranspose: (mode: string) => void
  selectDrumStrategy: (strategy: string) => void
  selectHddTrack: (track: number | null) => void
  selectHddNote: (note: number | null) => void
  selectHddRate: (rate: number | null) => void
  uploadFile: (file: File) => void
  configureVirtual: (config: VirtualConfig, enabled: boolean) => void
  setOutputMode: (virtual: boolean) => void
  setTrackRouting: (mode: 'AUTO' | 'STRICT_TRACKS', fourFddOnly: boolean, tracks: Array<number | null>) => void
}

function websocketUrl(): string {
  const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'

  return `${scheme}//${window.location.host}/ws`
}

export function usePlayer(): PlayerApi {
  const [state, setState] = useState<PlayerState | null>(null)
  const [files, setFiles] = useState<MidiFileEntry[]>([])
  const [metadata, setMetadata] = useState<FileMetadata | null>(null)
  const [ports, setPorts] = useState<PortInfo[]>([])
  const [socketConnected, setSocketConnected] = useState(false)
  const [startRequested, setStartRequested] = useState(false)
  const [startingFrom, setStartingFrom] = useState<'stopped' | 'paused'>('stopped')
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const socketRef = useRef<WebSocket | null>(null)
  const autoSelectedRef = useRef(false)
  const gateSequence = useRef(0)
  const pendingGates = useRef<{ requestId: number; devices: VirtualConfig['devices'] } | null>(null)

  const send = useCallback((action: string, payload: Record<string, unknown> = {}) => {
    const socket = socketRef.current

    if (socket?.readyState !== WebSocket.OPEN) {
      setError('Brak połączenia z backendem')
      return
    }

    if (action === 'play' || action === 'resume') {
      setStartingFrom(action === 'resume' ? 'paused' : 'stopped')
      setStartRequested(true)
    }
    if (['stop', 'pause', 'set_file'].includes(action)) setStartRequested(false)
    socket.send(JSON.stringify({ action, ...payload }))
  }, [])

  // --- WebSocket: stan + sterowanie ---
  useEffect(() => {
    let disposed = false
    let timer: number | undefined

    const connect = () => {
      const socket = new WebSocket(websocketUrl())
      socketRef.current = socket

      socket.onopen = () => {
        setSocketConnected(true)
        // Backend wrocil - nie trzymajmy starego modala "brak polaczenia".
        setError((current) =>
          current === 'Brak połączenia z backendem' ? null : current,
        )
      }

      socket.onclose = () => {
        setSocketConnected(false)
        setStartRequested(false)
        pendingGates.current = null
        if (!disposed) timer = window.setTimeout(connect, RECONNECT_MS)
      }

      socket.onerror = () => { setSocketConnected(false); setStartRequested(false) }

      socket.onmessage = (event: MessageEvent<string>) => {
        let message: ServerMessage

        try {
          message = JSON.parse(event.data) as ServerMessage
        } catch {
          return
        }

        if (message.type === 'state' && message.state) {
          if (message.requestId === pendingGates.current?.requestId) pendingGates.current = null
          const pending = pendingGates.current
          setState(pending && message.state.virtual ? {
            ...message.state, virtual: { ...message.state.virtual, config: {
              ...message.state.virtual.config, devices: message.state.virtual.config.devices.map(device => ({
                ...device, enabled: pending.devices.find(d => d.id === device.id)?.enabled ?? device.enabled,
              })),
            } },
          } : message.state)
          if (message.state.state === 'playing' || ['play', 'resume', 'stop'].includes(message.completedAction ?? '')) setStartRequested(false)
        } else if (message.type === 'error') {
          setStartRequested(false)
          setError(message.message ?? 'Nieznany błąd backendu')
        }
      }
    }

    connect()

    return () => {
      disposed = true
      window.clearTimeout(timer)
      socketRef.current?.close()
      socketRef.current = null
    }
  }, [])

  const refreshFiles = useCallback(() => {
    fetchFiles().then(setFiles).catch((cause: Error) => setError(cause.message))
  }, [])

  const refreshPorts = useCallback(() => {
    fetchPorts()
      .then((data) => setPorts(data.ports))
      .catch((cause: Error) => setError(cause.message))
  }, [])

  useEffect(() => {
    refreshFiles()
    refreshPorts()
  }, [refreshFiles, refreshPorts])

  // --- metadane aktualnie wybranego pliku ---
  const currentFile = state?.file ?? null

  useEffect(() => {
    if (!currentFile) {
      setMetadata(null)
      return
    }

    let cancelled = false

    fetchMetadata(currentFile)
      .then((data) => {
        if (!cancelled) setMetadata(data)
      })
      .catch((cause: Error) => {
        if (!cancelled) setError(cause.message)
      })

    return () => {
      cancelled = true
    }
  }, [currentFile])

  // --- pierwszy plik wybieramy automatycznie, zeby UI bylo od razu gotowe ---
  useEffect(() => {
    if (autoSelectedRef.current || currentFile || files.length === 0) return

    autoSelectedRef.current = true
    send('set_file', { file: files[0].name })
  }, [currentFile, files, send])

  // --- akcje ---
  const play = useCallback(() => send('play'), [send])
  const configureVirtual = useCallback((config: VirtualConfig, enabled: boolean) => {
    const withoutGates = (value: VirtualConfig) => JSON.stringify({ ...value,
      devices: value.devices.map(({ enabled: _enabled, ...device }) => device),
    })
    const gatesOnly = state?.virtual && enabled === state.virtual.enabled &&
      withoutGates(config) === withoutGates(state.virtual.config)
    const requestId = ++gateSequence.current
    if (gatesOnly && socketRef.current?.readyState === WebSocket.OPEN) {
      pendingGates.current = { requestId, devices: config.devices }
      setState(current => current?.virtual ? { ...current, virtual: {
        ...current.virtual, config: { ...current.virtual.config, devices: config.devices },
      } } : current)
    }
    send('set_virtual', { config: { ...config, enabled }, requestId })
  }, [send, state])
  const setTrackRouting = useCallback((mode: 'AUTO' | 'STRICT_TRACKS', fourFddOnly: boolean,
    tracks: Array<number | null>) => send('set_track_routing', { mode, fourFddOnly, tracks }), [send])
  const setOutputMode = useCallback((virtual: boolean) => send('set_output_mode', { virtual }), [send])
  const pause = useCallback(() => send('pause'), [send])
  const resume = useCallback(() => send('resume'), [send])
  const stop = useCallback(() => send('stop'), [send])
  const seek = useCallback((position: number) => send('seek', { position }), [send])

  const toggle = useCallback(() => {
    if (!state) return

    if (state.state === 'playing') {
      send('pause')
    } else if (state.state === 'paused') {
      send('resume')
    } else {
      send('play')
    }
  }, [send, state])

  const selectFile = useCallback(
    (name: string) => {
      setMetadata(null)
      send('set_file', { file: name })
    },
    [send],
  )

  const selectTrack = useCallback((index: number) => send('set_track', { track: index }), [send])
  const selectTranspose = useCallback((mode: string) => send('set_transpose', { mode }), [send])

  const home = useCallback(() => send('home'), [send])
  const setController = useCallback((target: string) => send('set_controller', { target }), [send])

  const reconnect = useCallback(
    (port?: string) => {
      send('reconnect', port ? { port } : {})
      window.setTimeout(refreshPorts, 1500)
    },
    [refreshPorts, send],
  )

  const dismissError = useCallback(() => setError(null), [])

  // --- wgranie nowego pliku MIDI z przegladarki ---
  const uploadFile = useCallback(
    (file: File) => {
      setUploading(true)

      uploadMidi(file)
        .then((result) => {
          setFiles(result.files)
          setMetadata(null)
          send('set_file', { file: result.name })
        })
        .catch((cause: Error) => setError(cause.message))
        .finally(() => setUploading(false))
    },
    [send],
  )

  // --- VHS drum (manualnie, niezależnie od MIDI) ---
  const startDrum = useCallback(() => send('start_drum'), [send])
  const stopDrum = useCallback(() => send('stop_drum'), [send])
  const setDrum = useCallback((value: number) => send('set_drum', { value }), [send])
  const setDrumTone = useCallback((hz: number) => send('set_drum_tone', { hz }), [send])
  const selectDrumTrack = useCallback(
    (track: number | null) => send('set_drum_track', { track }),
    [send],
  )
  const selectDrumTranspose = useCallback(
    (mode: string) => send('set_drum_transpose', { mode }),
    [send],
  )
  const selectDrumStrategy = useCallback(
    (strategy: string) => send('set_drum_strategy', { strategy }),
    [send],
  )
  const selectHddTrack = useCallback(
    (track: number | null) => send('set_hdd_track', { track }),
    [send],
  )
  const selectHddNote = useCallback(
    (note: number | null) => send('set_hdd_note', { note }),
    [send],
  )
  const selectHddRate = useCallback(
    (rate: number | null) => send('set_hdd_rate', { rate }),
    [send],
  )

  return {
    labCommand: send,
    state,
    files,
    metadata,
    ports,
    socketConnected,
    uploading,
    startingFrom,
    starting: socketConnected && (startRequested || Boolean(state?.hardware.pendingPlay) ||
      (state?.state === 'playing' && Boolean(state.virtual?.enabled) && state.virtual?.audioClockRunning === false)),
    error,
    dismissError,
    play,
    pause,
    resume,
    stop,
    toggle,
    seek,
    selectFile,
    selectTrack,
    selectTranspose,
    reconnect,
    home,
    setController,
    refreshPorts,
    refreshFiles,
    startDrum,
    stopDrum,
    setDrum,
    setDrumTone,
    selectDrumTrack,
    selectDrumTranspose,
    selectDrumStrategy,
    selectHddTrack,
    selectHddNote,
    selectHddRate,
    uploadFile,
    configureVirtual,
    setOutputMode,
    setTrackRouting,
  }
}
