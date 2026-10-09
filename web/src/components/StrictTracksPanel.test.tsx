import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { StrictTracksPanel } from './StrictTracksPanel'
import type { PlayerApi } from '../usePlayer'

const devices = [1, 2, 3, 4].map(i => ({ id: `fdd-${i}`, name: `FDD #${i}`, type: 'FDD', enabled: true }))
const tracks = [[1, 35], [3, 72], [4, 28], [8, 50]].map(([index, program]) => ({
  index, name: '(bez nazwy)', noteCount: 100, isDrums: false, programs: [program],
}))

describe('StrictTracksPanel', () => {
  it('offers the Police mapping and restores standard AUTO without playing', () => {
    const setTrackRouting = vi.fn()
    const player = {
      state: { state: 'stopped', file: 'Every breath you take.mid',
        virtual: { config: { devices } },
        trackRouting: { mode: 'AUTO', fourFddOnly: false, tracks: [null, null, null, null] } },
      metadata: { tracks }, setTrackRouting,
    } as unknown as PlayerApi
    render(<StrictTracksPanel player={player} />)
    expect(screen.getAllByRole('option', { name: /3 · Piccolo/ })).toHaveLength(4)
    fireEvent.click(screen.getByRole('button', { name: /The Police/ }))
    expect(setTrackRouting).toHaveBeenCalledWith('STRICT_TRACKS', true, [3, 1, 4, 8])
    fireEvent.click(screen.getByRole('button', { name: 'AUTO · 4 FDD' }))
    expect(setTrackRouting).toHaveBeenCalledWith('AUTO', true, [3, 1, 4, 8])
    fireEvent.click(screen.getByRole('button', { name: 'Przywróć standardowe AUTO' }))
    expect(setTrackRouting).toHaveBeenCalledWith('AUTO', false, [3, 1, 4, 8])
  })
})
