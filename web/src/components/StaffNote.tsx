import { memo, useEffect, useRef } from 'react'
import { Accidental, Barline, Formatter, Renderer, Stave, StaveNote, Voice } from 'vexflow/bravura'
import { noteName } from '../noteName'

const SHARPS = ['c', 'c#', 'd', 'd#', 'e', 'f', 'f#', 'g', 'g#', 'a', 'a#', 'b']
const FLATS = ['c', 'db', 'd', 'eb', 'e', 'f', 'gb', 'g', 'ab', 'a', 'bb', 'b']

// MIDI has no enharmonic spelling. Match the monitor's sharp names by default.
export function staffPitch(midiNote: number, preferFlats = false) {
  const pitch = (preferFlats ? FLATS : SHARPS)[midiNote % 12]
  return { key: `${pitch}/${Math.floor(midiNote / 12) - 1}`, accidental: pitch.slice(1), clef: midiNote < 60 ? 'bass' : 'treble' }
}

// Compact octave notation keeps extreme pitches readable on the fixed treble staff.
// This affects engraving only; the MIDI pitch, frequency and playback stay unchanged.
export function displayPitch(midiNote: number) {
  let written = midiNote, octaves = 0
  while (written < 60) { written += 12; octaves++ }
  while (written > 79) { written -= 12; octaves-- }
  const labels = octaves > 0 ? ['8vb', '15mb', '22mb'] : ['8va', '15ma', '22ma']
  return { written, label: octaves === 0 ? '' : labels[Math.abs(octaves) - 1] ?? `${Math.abs(octaves)} okt. ${octaves > 0 ? '↓' : '↑'}` }
}

/** One VexFlow SVG note. Stable pitch does not redraw on every audio-clock tick. */
export const StaffNote = memo(function StaffNote({ midiNote, preferFlats = false }: { midiNote: number | null; preferFlats?: boolean }) {
  const host = useRef<HTMLDivElement>(null)
  const latest = useRef({ midiNote, preferFlats })
  latest.current = { midiNote, preferFlats }
  const updateNote = useRef<(() => void) | null>(null)
  useEffect(() => {
    const element = host.current
    if (!element) return
    let cancelled = false
    const draw = () => {
      if (cancelled) return
      element.replaceChildren()
      const clef = 'treble'
      const renderer = new Renderer(element, Renderer.Backends.SVG)
      renderer.resize(160, 100)
      const context = renderer.getContext()
      context.setFillStyle('currentColor').setStrokeStyle('currentColor')
      const stave = new Stave(0, 0, 160).addClef(clef)
        .setBegBarType(Barline.type.NONE).setEndBarType(Barline.type.NONE)
      stave.setContext(context).draw()
      const svg = element.querySelector('svg')!
      updateNote.current = () => {
        svg.querySelector('.vf-current-note')?.remove()
        const { midiNote: value, preferFlats: flats } = latest.current
        if (value === null || !Number.isInteger(value) || value < 0 || value > 127) return
        const display = displayPitch(value)
        const pitch = staffPitch(display.written, flats)
        context.openGroup('current-note')
        const note = new StaveNote({ clef, keys: [pitch.key], duration: 'q', autoStem: true })
        if (pitch.accidental) note.addModifier(new Accidental(pitch.accidental), 0)
        const voice = new Voice({ numBeats: 1, beatValue: 4 }).addTickables([note])
        new Formatter().joinVoices([voice]).formatToStave([voice], stave)
        voice.draw(context, stave)
        if (display.label) {
          context.setFont('Arial', 10)
          context.fillText(display.label, 110, 20)
        }
        context.closeGroup()
      }
      updateNote.current()
      // Side padding keeps the clef unclipped; YMin pulls the staff up under the title.
      svg.setAttribute('viewBox', '-18 -20 196 112')
      svg.setAttribute('preserveAspectRatio', 'xMidYMin meet')
      svg.setAttribute('aria-hidden', 'true')
    }
    // The Bravura build bundles its fonts; no runtime CDN request is needed.
    if (document.fonts) void document.fonts.ready.then(draw)
    else draw()
    return () => { cancelled = true; updateNote.current = null; element.replaceChildren() }
  }, [])
  useEffect(() => { updateNote.current?.() }, [midiNote, preferFlats])
  return <div ref={host} className="staff-note" role="img" aria-label={midiNote === null ? 'Pięciolinia' : `Nuta ${noteName(midiNote)} na pięciolinii`} />
})
