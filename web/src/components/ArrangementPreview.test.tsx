import {afterEach,describe,expect,it,vi} from 'vitest'
import {act,cleanup,fireEvent,render,screen} from '@testing-library/react'
import {ArrangementPreview} from './ArrangementPreview'
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
async function open(){
 const details=screen.getByText('Arrangement · PerformancePlan').parentElement as HTMLDetailsElement
 await act(async()=>{details.open=true;fireEvent(details,new Event('toggle'))})
}
describe('Arrangement plan preview',()=>{
 it('shows DVD and FDD performed durations, unison pair and reason from the plan',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({
   events:[{id:'a',trackName:'Guitar',deviceId:'fdd-3',deviceType:'FDD',playedNote:60,actualStart:12,actualDuration:.25,outcome:'ACCEPTED',hardware:{selection:{reason:'FDD articulated phrase'}}},
    {id:'b',trackName:'Bass',deviceId:'DVD_STEPPER_1',deviceType:'DVD_SLED',playedNote:48,actualStart:12,actualDuration:4,outcome:'ACCEPTED',hardware:{selection:{reason:'DVD sustain / stable phrase'}}}],
   reinforcements:[{sourceId:'a',sourceDevice:'fdd-3',deviceId:'fdd-4',start:12,duration:.25,kind:'UNISON'}],report:{totals:{played:2,dropped:0}},
  })}))
  render(<ArrangementPreview revision={1} file="song.mid"/>);await open()
  expect(await screen.findByText('fdd-3 + fdd-4')).toBeTruthy()
  expect(screen.getByText('DVD_STEPPER_1')).toBeTruthy();expect(screen.getByText('4.000')).toBeTruthy()
  expect(screen.getByText('0.250')).toBeTruthy();expect(screen.getByText(/DVD sustain \/ stable phrase · ACCEPTED/)).toBeTruthy()
 })
 it('fetches only when expanded and reloads after a new plan revision',async()=>{
  const fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>null});vi.stubGlobal('fetch',fetch)
  const view=render(<ArrangementPreview revision={1} file="song.mid"/>);expect(fetch).not.toHaveBeenCalled()
  await open();expect(fetch).toHaveBeenCalledTimes(1)
  await act(async()=>view.rerender(<ArrangementPreview revision={2} file="other.mid"/>))
  expect(fetch).toHaveBeenCalledTimes(2)
 })
 it('reports failed plan request',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false}));render(<ArrangementPreview revision={1} file="song.mid"/>)
  await open();expect((await screen.findByRole('alert')).textContent).toContain('Nie można pobrać planu')
 })
})

it('selects FDD Quality and displays mechanical diagnostics',async()=>{
 const onPreset=vi.fn()
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({events:[],reinforcements:[],report:{totals:{played:20,dropped:3},fddQuality:{fddNotes:12,fddSeconds:2.4,estimatedSteps:600,estimatedReversals:8,omittedNotes:3,dvdTakeovers:4,unisonEvents:1}}})}))
 render(<ArrangementPreview revision={1} file="song.mid" preset="balanced" onPreset={onPreset}/>);await open()
 fireEvent.change(screen.getByLabelText('Preset aranżacji'),{target:{value:'fdd_quality'}})
 expect(onPreset).toHaveBeenCalledWith('fdd_quality')
 expect(screen.getByLabelText('Diagnostyka FDD').textContent).toContain('12 nut · 2.40 s aktywności · ~600 kroków · ~8 zawróceń')
 expect(screen.getByLabelText('Diagnostyka FDD').textContent).toContain('4 nut przejętych przez DVD')
})

it('selects DVD Lead and displays octave and range diagnostics',async()=>{
 const onPreset=vi.fn()
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({events:[],reinforcements:[],report:{totals:{played:10,dropped:2},dvdLeadLowFdd:{dvdNotes:8,octaveLowered:2,octaveRangeFallback:1,shortenedNotes:0}}})}))
 render(<ArrangementPreview revision={1} file="song.mid" onPreset={onPreset}/>);await open()
 fireEvent.change(screen.getByLabelText('Preset aranżacji'),{target:{value:'dvd_lead_low_fdd'}})
 expect(onPreset).toHaveBeenCalledWith('dvd_lead_low_fdd')
 expect(screen.getByLabelText('Diagnostyka DVD Lead').textContent).toContain('DVD: 8 nut · FDD −12: 2 nut · bez obniżenia (zakres): 1 · skrócone: 0')
})
