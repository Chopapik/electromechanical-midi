import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { VirtualOrchestra } from './VirtualOrchestra'
import type { VirtualState } from '../types'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
it('sends one master gain for the whole orchestra and displays boosted volume', () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ json: async () => ({ presets: {} }) })))
  const configure = vi.fn()
  const virtual = { enabled: true, config: { name: 'Test', devices: [], masterVolume: 4 }, activity: {}, report: {}, profiles: [] } as VirtualState
  render(<VirtualOrchestra virtual={virtual} metadata={null} configure={configure} />)
  expect(screen.getByText('400%')).toBeDefined()
  const slider = screen.getByRole('slider', { name: 'Master Volume' })
  expect(slider.getAttribute('max')).toBe('20')
  fireEvent.change(slider, { target: { value: '8' } })
  expect(configure).toHaveBeenCalledWith({ ...virtual.config, masterVolume: 8 }, true)
})
