import { cleanup, render } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { PianoRoll } from './PianoRoll'
import type { ArrangementNote } from '../types'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('follows the playhead while playing and leaves manual scroll alone when paused', () => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(800)
  const note = { id: '0:0', track: 0, trackName: 'Melody', channel: 1, note: 60,
    name: 'C4', start: 0, duration: .5, velocity: 90, isDrum: false,
    status: 'UNASSIGNED', routes: [] } as ArrangementNote
  const props = { notes: [note], devices: [], position: 0, playing: false,
    mode: 'source' as const, selectedId: null, hiddenTracks: new Set<number>(),
    hiddenDevices: new Set<string>(), onSelect: vi.fn(), onSeek: vi.fn() }
  const { container, rerender } = render(<PianoRoll {...props} />)
  const scroller = container.querySelector('.piano-scroller') as HTMLDivElement
  rerender(<PianoRoll {...props} position={20} playing />)
  expect(scroller.scrollLeft).toBeGreaterThan(1000)
  const followed = scroller.scrollLeft
  rerender(<PianoRoll {...props} position={30} playing={false} />)
  expect(scroller.scrollLeft).toBe(followed)
  rerender(<PianoRoll {...props} position={0} playing />)
  expect(scroller.scrollLeft).toBe(0)
})
