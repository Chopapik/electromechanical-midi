import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { usePlaybackPosition } from './usePlaybackPosition'

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers() })
it('interpolates output-clock samples locally and freezes through stale updates', () => {
  vi.useFakeTimers()
  let now = 0
  vi.spyOn(performance, 'now').mockImplementation(() => now)
  const hook = renderHook(() => usePlaybackPosition(10, true))
  act(() => { now = 100; vi.advanceTimersByTime(100) })
  expect(hook.result.current).toBeCloseTo(10.1)
  act(() => { now = 1000; vi.advanceTimersByTime(900) })
  expect(hook.result.current).toBeCloseTo(10.2)
})
it('waits for audio start, and resets immediately on seek/pause', () => {
  vi.useFakeTimers()
  let now = 0
  vi.spyOn(performance, 'now').mockImplementation(() => now)
  const hook = renderHook(({ position, advancing }) => usePlaybackPosition(position, advancing), { initialProps: { position: 3, advancing: false } })
  act(() => { now = 500; vi.advanceTimersByTime(500) })
  expect(hook.result.current).toBe(3)
  hook.rerender({ position: 10, advancing: true })
  act(() => { now = 600; vi.advanceTimersByTime(100) })
  expect(hook.result.current).toBeCloseTo(10.1)
  hook.rerender({ position: 1, advancing: false })
  expect(hook.result.current).toBe(1)
})
