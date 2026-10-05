import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeAll, expect, it } from 'vitest'
import { Element } from 'vexflow/bravura'
import { StaffNote, staffPitch } from './StaffNote'

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
it.each([0, 23, 55, 60, 66, 127])('renders MIDI %s with VexFlow SVG and a padded viewBox', async midiNote => {
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
