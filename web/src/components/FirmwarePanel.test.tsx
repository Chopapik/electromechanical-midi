import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { FirmwarePanel } from './FirmwarePanel'

afterEach(() => vi.unstubAllGlobals())
test('upload shows busy state, uses firmware endpoint and reports READY', async () => {
  let resolve!: (value: unknown) => void
  const fetch = vi.fn(() => new Promise(r => { resolve = r }))
  vi.stubGlobal('fetch', fetch)
  render(<FirmwarePanel />)
  fireEvent.click(screen.getByRole('button', { name: 'Wgraj ponownie firmware' }))
  expect(screen.getByRole('button', { name: 'Wgrywanie firmware…' }).hasAttribute('disabled')).toBe(true)
  resolve({ ok: true, json: async () => ({ ready: true, port: '/dev/uno', log: 'SUCCESS' }) })
  await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Arduino READY'))
  expect(fetch).toHaveBeenCalledWith('/api/firmware/upload', { method: 'POST' })
})
test('upload failure is visible and permits retry', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, json: async () => ({ detail: 'port busy' }) })))
  render(<FirmwarePanel />)
  fireEvent.click(screen.getByRole('button', { name: 'Wgraj ponownie firmware' }))
  await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('port busy'))
  expect(screen.getByRole('button', { name: 'Wgraj ponownie firmware' }).hasAttribute('disabled')).toBe(false)
})

test('explicit ESP32 target uses ESP32 upload endpoint', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ ready: true, port: '/dev/cp2102', log: 'ESP32 built' }) })))
  render(<FirmwarePanel />)
  fireEvent.change(screen.getByRole('combobox', { name: 'Firmware target' }), { target: { value: 'esp32' } })
  fireEvent.click(screen.getByRole('button', { name: 'Wgraj ponownie firmware' }))
  await screen.findByText(/Firmware wgrany/)
  expect(fetch).toHaveBeenCalledWith('/api/firmware/upload?target=esp32', { method: 'POST' })
})
test('controller selection updates normal runtime without flashing', () => {
 const change=vi.fn();const fetch=vi.fn();vi.stubGlobal('fetch',fetch)
 render(<FirmwarePanel selectedTarget="uno" onTargetChange={change} />)
 fireEvent.change(screen.getByRole('combobox',{name:'Firmware target'}),{target:{value:'esp32'}})
 expect(change).toHaveBeenCalledWith('esp32')
 expect(fetch).not.toHaveBeenCalled()
})
