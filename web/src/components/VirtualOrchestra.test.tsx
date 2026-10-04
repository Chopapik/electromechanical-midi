import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { VirtualOrchestra } from './VirtualOrchestra'
import type { VirtualState } from '../types'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
it('sends one master gain for the whole orchestra and displays boosted volume', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ json: async () => ({ presets: {} }) })))
  const configure = vi.fn()
  const virtual = { enabled: true, config: { name: 'Test', devices: [], masterVolume: 4 }, activity: {}, report: {}, profiles: [] } as VirtualState
  await act(async () => { render(<VirtualOrchestra virtual={virtual} metadata={null} configure={configure} />) })
  expect(screen.getByText('400%')).toBeDefined()
  const slider = screen.getByRole('slider', { name: 'Master Volume' })
  expect(slider.getAttribute('max')).toBe('20')
  fireEvent.change(slider, { target: { value: '8' } })
  expect(configure).toHaveBeenCalledWith({ ...virtual.config, masterVolume: 8 }, true)
})

it('switches RAW versus ARTICULATED without changing device routing', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ json: async () => ({ presets: {} }) })))
  const configure = vi.fn()
  const virtual = { enabled: true, config: { name: 'Test', devices: [], masterVolume: 4 }, activity: {}, report: {}, profiles: [] } as VirtualState
  await act(async () => { render(<VirtualOrchestra virtual={virtual} metadata={null} configure={configure} />) })
  const selector = screen.getByRole('combobox', { name: 'HDD sound' }) as HTMLSelectElement
  expect(selector.value).toBe('articulated')
  fireEvent.change(selector, { target: { value: 'raw' } })
  expect(configure).toHaveBeenCalledWith({ ...virtual.config, hddMode: 'raw' }, true)
})

it('switches tonal articulation while preserving HDD mode and routing', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ json: async () => ({ presets: {} }) })))
  const configure = vi.fn()
  const virtual = { enabled: true, config: { name: 'Test', devices: [], hddMode: 'raw' }, activity: {}, report: {}, profiles: [] } as VirtualState
  await act(async () => { render(<VirtualOrchestra virtual={virtual} metadata={null} configure={configure} />) })
  const selector = screen.getByRole('combobox', { name: 'Tonal sound' }) as HTMLSelectElement
  expect(selector.value).toBe('articulated')
  fireEvent.change(selector, { target: { value: 'raw' } })
  expect(configure).toHaveBeenCalledWith({ ...virtual.config, tonalMode: 'raw' }, true)
  fireEvent.change(selector, { target: { value: 'extreme' } })
  expect(configure).toHaveBeenCalledWith({ ...virtual.config, tonalMode: 'extreme' }, true)
  expect(screen.getByRole('option', { name: 'TONAL EXTREME · diagnostic' })).toBeDefined()
})
