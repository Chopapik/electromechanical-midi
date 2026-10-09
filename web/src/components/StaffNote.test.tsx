import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeAll, expect, it } from 'vitest'
import { Element } from 'vexflow/bravura'
import { StaffNote, staffPitch, displayPitch } from './StaffNote'

beforeAll(() => Element.setTextMeasurementCanvas({ getContext: () => ({
  measureText: (text: string) => ({ width: text.length * 8, actualBoundingBoxAscent: 16, actualBoundingBoxDescent: 4 }),
}) } as unknown as HTMLCanvasElement))
afterEach(cleanup)

it('maps the real MIDI octave, clef and enharmonic accidentals', () => {
  expect(staffPitch(55)).toEqual({ key: 'g/3', accidental: '', clef: 'bass' })
  expect(staffPitch(60)).toEqual({ key: 'c/4', accidental: '', clef: 'treble' })
  expect(staffPitch(66)).toEqual({ key: 'f#/4', accidental: '#', clef: 'treble' })
  expect(staffPitch(58, true)).toEqual({ key: 'bb/3', accidental: 'b', clef: 'bass' })
})
it.each([0, 23, 55, 60, 66, 127])('renders MIDI %s with VexFlow SVG and a fixed viewBox', async midiNote => {
  render(<StaffNote midiNote={midiNote} />)
  await waitFor(() => expect(screen.getByRole('img').querySelector('svg')).not.toBeNull())
  const svg = screen.getByRole('img').querySelector('svg')!
  expect(svg.querySelector('.vf-stavenote')).not.toBeNull()
  expect(svg.querySelector('.vf-stem')).not.toBeNull()
  expect(svg.querySelector('.vf-stave')).not.toBeNull()
  expect(svg.getAttribute('viewBox')!.split(' ').map(Number).every(Number.isFinite)).toBe(true)
})
it('renders a flat and retains the SVG when only the parent rerenders', async () => {
  const hook = render(<StaffNote midiNote={58} preferFlats />)
  await waitFor(() => expect(screen.getByRole('img').querySelector('svg')).not.toBeNull())
  const svg = screen.getByRole('img').querySelector('svg')
  expect(svg?.textContent).toContain('\uE260') // Bravura accidentalFlat glyph.
  hook.rerender(<StaffNote midiNote={58} preferFlats />)
  expect(screen.getByRole('img').querySelector('svg')).toBe(svg)
})

it('keeps the staff viewport and clef fixed through silence and pitch changes', async () => {
  const hook = render(<StaffNote midiNote={null} />)
  await waitFor(() => expect(screen.getByRole('img').querySelector('svg')).not.toBeNull())
  const originalStaff = screen.getByRole('img').querySelector('.vf-stave')
  for (const pitch of [null, 36, 59, 60, 84, null]) {
    hook.rerender(<StaffNote midiNote={pitch} />)
    await waitFor(() => {
      const image = screen.getByRole('img')
      const svg = image.querySelector('svg')!
      expect(svg).not.toBeNull()
      expect(svg.querySelector('.vf-stave')).toBe(originalStaff)
      expect(svg.getAttribute('viewBox')).toBe('-8 -30 176 170')
      expect(svg.textContent).toContain('\uE050') // Fixed treble clef, including below middle C.
      expect(svg.querySelectorAll('.vf-stavenote').length).toBe(pitch === null ? 0 : 1)
    })
  }
})

it('uses compact octave notation for G2 and keeps all MIDI pitches in a readable range', () => {
  expect(displayPitch(43)).toEqual({written:67,label:'15mb'})
  for (let note=0; note<128; note++) {
    const display=displayPitch(note)
    expect(display.written).toBeGreaterThanOrEqual(60)
    expect(display.written).toBeLessThanOrEqual(79)
    expect(display.written%12).toBe(note%12)
  }
})
it.each([0,43,127])('keeps the notehead and stem within the fixed viewport for MIDI %s', async midiNote => {
  render(<StaffNote midiNote={midiNote} />)
  await waitFor(() => expect(screen.getByRole('img').querySelector('.vf-stavenote')).not.toBeNull())
  const svg = screen.getByRole('img').querySelector('svg')!
  const stem = svg.querySelector('.vf-stem path')!
  const values = stem.getAttribute('d')!.match(/-?\d+(?:\.\d+)?/g)!.map(Number)
  const yValues = values.filter((_,i)=>i%2===1)
  expect(Math.max(...yValues)-Math.min(...yValues)).toBeLessThanOrEqual(40)
  expect(Math.min(...yValues)).toBeGreaterThanOrEqual(-30)
  expect(Math.max(...yValues)).toBeLessThanOrEqual(140)
})
