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
 it('shows four-drive unison groups instead of hiding their copies',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({
   events:[{id:'a',trackName:'Guitar',deviceId:'fdd-1',deviceType:'FDD',playedNote:60,actualStart:0,actualDuration:.2,outcome:'ACCEPTED'}],
   reinforcements:[2,3,4].map(i=>({sourceId:'a',sourceDevice:'fdd-1',deviceId:`fdd-${i}`,start:0,duration:.2,kind:'FDD_UNISON4'})),
   report:{totals:{played:1,dropped:0}},
  })}))
  render(<ArrangementPreview revision={1} file="song.mid"/>);await open()
  expect(screen.getByText(/grupy 4×: 1/)).toBeTruthy()
  expect(screen.getByText(/fdd-1 \+ fdd-2/)).toBeTruthy()
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

it('displays FDD Quality mechanical diagnostics',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({events:[],reinforcements:[],report:{totals:{played:20,dropped:3},fddQuality:{fddNotes:12,fddSeconds:2.4,estimatedSteps:600,estimatedReversals:8,omittedNotes:3,dvdTakeovers:4,unisonEvents:1}}})}))
 render(<ArrangementPreview revision={1} file="song.mid"/>);await open()
 expect(screen.getByLabelText('Diagnostyka FDD').textContent).toContain('12 nut · 2.40 s aktywności · ~600 kroków · ~8 zawróceń')
 expect(screen.getByLabelText('Diagnostyka FDD').textContent).toContain('4 nut przejętych przez DVD')
})

it('displays DVD Lead octave and range diagnostics',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({events:[],reinforcements:[],report:{totals:{played:10,dropped:2},dvdLeadLowFdd:{dvdNotes:8,octaveLowered:2,octaveRangeFallback:1,shortenedNotes:0}}})}))
 render(<ArrangementPreview revision={1} file="song.mid"/>);await open()
 expect(screen.getByLabelText('Diagnostyka DVD Lead').textContent).toContain('DVD: 8 nut · FDD −12: 2 nut · bez obniżenia (zakres): 1 · skrócone: 0')
})

it('shows Adaptive density, recovery and independent activity',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({events:[],reinforcements:[],report:{totals:{played:10,dropped:2},fddAdaptive:{recoveredNotes:3,restoredGates:5,valuableOmittedNotes:1,dropReasons:{TIMING_CONFLICT:2},frames:[{start:0,end:.25,level:.8,independentParts:3,meanActiveFdd:2}],activity:{primary:{fractions:[.1,.2,.3,.3,.1]}},silence:{oneFddWithFeasibleUnusedSourceSeconds:.5}}}})}))
 render(<ArrangementPreview revision={1} file="song.mid"/>);await open()
 expect(screen.getByLabelText('Diagnostyka Adaptive').textContent).toContain('Odzyskane nuty: 3 · przywrócone gate: 5')
 expect(screen.getByText(/Aktywne niezależne FDD/).textContent).toContain('4: 10.0%')
 expect(screen.getByText('80.0%')).toBeTruthy()
 expect(screen.getByText(/Odrzucenia:/).textContent).toContain('TIMING_CONFLICT: 2')
})
