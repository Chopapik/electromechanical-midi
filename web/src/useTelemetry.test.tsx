import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useTelemetry } from './useTelemetry'

const view = { file: 'song.mid', revision: 1, events: [], activity: {}, report: null }
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
it('fetches once for a plan, not on ordinary player position updates', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => view })))
  const hook = renderHook(({ revision }) => useTelemetry('song.mid', revision, 'extreme_v15', 'articulated'), { initialProps: { revision: 1 } })
  await waitFor(() => expect(hook.result.current.view).toEqual(view))
  for (let i = 0; i < 10; i++) hook.rerender({ revision: 1 })
  expect(fetch).toHaveBeenCalledTimes(1)
  hook.rerender({ revision: 2 })
  expect(hook.result.current.view).toBeNull()
  expect(fetch).toHaveBeenCalledTimes(2)
})
it('rejects a response for a different file or revision', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ ...view, file: 'other.mid' }) })))
  const hook = renderHook(() => useTelemetry('song.mid', 1))
  await act(async () => {})
  expect(hook.result.current.view).toBeNull()
})
it('shows a read error and never initializes or edits the plan', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false })))
  const hook = renderHook(() => useTelemetry('song.mid', 1))
  await waitFor(() => expect(hook.result.current.error).toBe('Telemetry unavailable'))
  expect(fetch).toHaveBeenCalledWith('/api/telemetry', expect.objectContaining({ signal: expect.any(AbortSignal) }))
  expect(fetch).toHaveBeenCalledTimes(1)
})

it('refreshes after an audio render and retries a version race without using cached telemetry', async () => {
  const fresh = { ...view, audioRevision: 2 }
  const fetcher = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ ...view, audioRevision: 1 }) })
    .mockResolvedValue({ ok: true, json: async () => fresh })
  vi.stubGlobal('fetch', fetcher)
  const hook = renderHook(({ audio }) => useTelemetry('song.mid', 1, 'extreme_v15', 'articulated', audio), { initialProps: { audio: 2 } })
  await waitFor(() => expect(hook.result.current.view).toEqual(fresh))
  expect(fetcher).toHaveBeenCalledTimes(2)
  expect(fetcher).toHaveBeenCalledWith('/api/telemetry', expect.objectContaining({ cache: 'no-store' }))
  hook.rerender({ audio: 3 })
  expect(hook.result.current.view).toBeNull()
})
