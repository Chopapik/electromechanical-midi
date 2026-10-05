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
