import { memo, useEffect, useRef } from 'react'
import { Accidental, Barline, Formatter, Renderer, Stave, StaveNote, Voice } from 'vexflow/bravura'
import { noteName } from '../telemetry'

const SHARPS = ['c', 'c#', 'd', 'd#', 'e', 'f', 'f#', 'g', 'g#', 'a', 'a#', 'b']
const FLATS = ['c', 'db', 'd', 'eb', 'e', 'f', 'gb', 'g', 'ab', 'a', 'bb', 'b']

// MIDI has no enharmonic spelling. Match the monitor's sharp names by default.
export function staffPitch(midiNote: number, preferFlats = false) {
  const pitch = (preferFlats ? FLATS : SHARPS)[midiNote % 12]
  return { key: `${pitch}/${Math.floor(midiNote / 12) - 1}`, accidental: pitch.slice(1), clef: midiNote < 60 ? 'bass' : 'treble' }
}

/** One VexFlow SVG note. Stable pitch does not redraw on every audio-clock tick. */
export const StaffNote = memo(function StaffNote({ midiNote, preferFlats = false }: { midiNote: number; preferFlats?: boolean }) {
  const host = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const element = host.current
    if (!element || !Number.isInteger(midiNote) || midiNote < 0 || midiNote > 127) return
    let cancelled = false
    const draw = () => {
      if (cancelled) return
      element.replaceChildren()
      const pitch = staffPitch(midiNote, preferFlats)
      const renderer = new Renderer(element, Renderer.Backends.SVG)
      renderer.resize(160, 100)
      const context = renderer.getContext()
      context.setFillStyle('currentColor').setStrokeStyle('currentColor')
      const stave = new Stave(0, 0, 160).addClef(pitch.clef)
        .setBegBarType(Barline.type.NONE).setEndBarType(Barline.type.NONE)
      stave.setContext(context).draw()
      const note = new StaveNote({ clef: pitch.clef, keys: [pitch.key], duration: 'q', autoStem: true })
      if (pitch.accidental) note.addModifier(new Accidental(pitch.accidental), 0)
      const voice = new Voice({ numBeats: 1, beatValue: 4 }).addTickables([note])
      new Formatter().joinVoices([voice]).formatToStave([voice], stave)
      voice.draw(context, stave)
      const svg = element.querySelector('svg')!
      // Fit the actual engraving, including stems and ledger lines at either extreme.
      // Browser SVG bounds also include the clef. Fallback supports DOM test environments.
      const bounds = note.getBoundingBox()
      const top = Math.min(stave.getYForLine(0) - 25, bounds.getY())
      const bottom = Math.max(stave.getYForLine(4) + 25, bounds.getY() + bounds.getH())
      const box = typeof svg.getBBox === 'function' ? svg.getBBox() : { x: 0, y: top, width: 160, height: bottom - top }
      svg.setAttribute('viewBox', `${box.x - 8} ${box.y - 8} ${box.width + 16} ${box.height + 16}`)
      svg.setAttribute('preserveAspectRatio', 'xMidYMid meet')
      svg.setAttribute('aria-hidden', 'true')
    }
    // The Bravura build bundles its fonts; no runtime CDN request is needed.
    if (document.fonts) void document.fonts.ready.then(draw)
    else draw()
    return () => { cancelled = true; element.replaceChildren() }
  }, [midiNote, preferFlats])
  return <div ref={host} className="staff-note" role="img" aria-label={`Nuta ${noteName(midiNote)} na pięciolinii`} />
})
