import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,act} from '@testing-library/react'
import {MemoryRouter} from 'react-router-dom'
import {LaboratoryPage} from './LaboratoryPage'
import type {State,useRuntime} from './runtime'
const send=vi.fn()
function makeApp(){return {state:{state:'stopped',owner:'lab',epoch:1,position:0,duration:0,file:null,revision:0,error:null,audioOwner:null,
 devices:[{id:'fdd-1',name:'FDD 1',type:'FDD',enabled:true,volume:.6,bands:[[40,410]],reason:null},{id:'fdd-2',name:'FDD 2',type:'FDD',enabled:true,volume:.6,bands:[[40,410]],reason:null},{id:'hdd-1',name:'HDD 1',type:'HDD_VCM',enabled:true,volume:.6,bands:[],reason:null}],
 laboratory:{active:{}},output:{mode:'VIRTUAL',connected:true,unknown:false,muted:[],message:''},service:{busy:false,error:null,power:{state:'ON',available:true,operation:null,error:null,reason:null,measured:false},home:{available:false,reason:'Test'},reset:{available:false,reason:'Test'},firmware:{available:false,reason:'Test'}}} as State,
 send,connected:true,error:null,files:[],firmwareEvents:[],upload:vi.fn(),midiLoading:null} as ReturnType<typeof useRuntime>}
let app:ReturnType<typeof useRuntime>
function mount(){return render(<MemoryRouter><LaboratoryPage app={app}/></MemoryRouter>)}
beforeEach(()=>{localStorage.clear();send.mockClear();app=makeApp()})
afterEach(()=>{cleanup();vi.useRealTimers()})
describe('Laboratory rack',()=>{
 it('shows device list and right inspector instead of orchestra cards',()=>{mount();expect(screen.getByRole('region',{name:'Lista urządzeń'})).toBeTruthy();expect(screen.getByRole('complementary',{name:'Panel FDD 1'})).toBeTruthy();expect(screen.queryByRole('article')).toBeNull();expect(screen.getByRole('slider',{name:'Suwak częstotliwości'})).toBeTruthy()})
 it('offers low-frequency presets while blocking 25 Hz below the FDD limit',()=>{
  mount()
  const below=screen.getByRole('button',{name:'25'}) as HTMLButtonElement
  expect(below.disabled).toBe(true)
  expect(below.title).toBe('Poniżej dolnego limitu 40 Hz')
  for(const hz of [50,75,100]){
   fireEvent.click(screen.getByRole('button',{name:String(hz)}))
   expect((screen.getByLabelText('Częstotliwość Hz') as HTMLInputElement).value).toBe(String(hz))
   expect((screen.getByRole('button',{name:'Uruchom'}) as HTMLButtonElement).disabled).toBe(false)
  }
  fireEvent.click(screen.getByRole('button',{name:'50'}));fireEvent.click(screen.getByRole('button',{name:'Uruchom'}))
  expect(send).toHaveBeenLastCalledWith('lab_test',{deviceId:'fdd-1',hz:50,duration:5,modulation:{mode:'off',depth:5,period:4}})
  fireEvent.change(screen.getByLabelText('Częstotliwość Hz'),{target:{value:'39'}})
  expect((screen.getByRole('button',{name:'Uruchom'}) as HTMLButtonElement).disabled).toBe(true)
 })
 it('retains independent frequency, modulation and duration when changing devices',()=>{
  mount();fireEvent.change(screen.getByLabelText('Częstotliwość Hz'),{target:{value:'300'}});fireEvent.click(screen.getByRole('button',{name:'∞ Do STOP'}));fireEvent.click(screen.getByRole('button',{name:'Vibrato'}));fireEvent.change(screen.getByRole('slider',{name:'Głębokość modulacji Hz'}),{target:{value:'12'}})
  fireEvent.click(screen.getByRole('button',{name:'Ustawienia FDD 2'}));expect((screen.getByLabelText('Częstotliwość Hz') as HTMLInputElement).value).toBe('220');fireEvent.change(screen.getByLabelText('Częstotliwość Hz'),{target:{value:'200'}})
  fireEvent.click(screen.getByRole('button',{name:'Ustawienia FDD 1'}));expect((screen.getByLabelText('Częstotliwość Hz') as HTMLInputElement).value).toBe('300');expect(screen.getByRole('button',{name:'∞ Do STOP'}).getAttribute('aria-pressed')).toBe('true');expect((screen.getByRole('slider',{name:'Głębokość modulacji Hz'}) as HTMLInputElement).value).toBe('12')
 })
 it('starts two continuous tones without an intervening stop',()=>{
  mount();fireEvent.click(screen.getByRole('button',{name:'300'}));fireEvent.click(screen.getByRole('button',{name:'∞ Do STOP'}));fireEvent.click(screen.getByRole('button',{name:'Uruchom'}));
  fireEvent.click(screen.getByRole('button',{name:'Ustawienia FDD 2'}));fireEvent.click(screen.getByRole('button',{name:'∞ Do STOP'}));fireEvent.click(screen.getByRole('button',{name:'Uruchom'}));
  expect(send.mock.calls.map(c=>c[0])).toEqual(['lab_test','lab_test']);expect(send.mock.calls[0][1]).toEqual({deviceId:'fdd-1',hz:300,duration:null,modulation:{mode:'off',depth:5,period:4}});expect(send.mock.calls[1][1].deviceId).toBe('fdd-2')
 })
 it('persists drafts over a remount but never autostarts',()=>{
  const view=mount();fireEvent.change(screen.getByLabelText('Częstotliwość Hz'),{target:{value:'330'}});view.unmount();mount();expect((screen.getByLabelText('Częstotliwość Hz') as HTMLInputElement).value).toBe('330');expect(send).not.toHaveBeenCalled()
 })
 it('removes obsolete saved devices but retains settings for disabled catalog members',()=>{
  app.state!.devices[1].enabled=false
  const kept={'fdd-1':{hz:300},'fdd-2':{hz:330}}
  localStorage.setItem('orchestra.laboratory.v1',JSON.stringify({...kept,'obsolete-device':{hz:440}}))
  mount()
  expect(JSON.parse(localStorage.getItem('orchestra.laboratory.v1')!)).toEqual(kept)
  expect((screen.getByLabelText('Częstotliwość Hz') as HTMLInputElement).value).toBe('300')
  expect(send).not.toHaveBeenCalled()
 })
 it('prunes saved settings after a live catalog change without losing other drafts',()=>{
  const view=mount()
  fireEvent.change(screen.getByLabelText('Częstotliwość Hz'),{target:{value:'300'}})
  fireEvent.click(screen.getByRole('button',{name:'Ustawienia FDD 2'}))
  fireEvent.change(screen.getByLabelText('Częstotliwość Hz'),{target:{value:'330'}})
  app.state={...app.state!,devices:app.state!.devices.filter(d=>d.id!=='fdd-2')}
  view.rerender(<MemoryRouter><LaboratoryPage app={app}/></MemoryRouter>)
  const saved=JSON.parse(localStorage.getItem('orchestra.laboratory.v1')!)
  expect(saved['fdd-2']).toBeUndefined()
  expect(saved['fdd-1'].hz).toBe(300)
  expect(screen.queryByRole('button',{name:'Ustawienia FDD 2'})).toBeNull()
  expect(send).not.toHaveBeenCalled()
 })
 it('provides pitch shortcuts and a duration beyond ten seconds',()=>{
  mount();fireEvent.click(screen.getByRole('button',{name:'300'}));fireEvent.click(screen.getByRole('button',{name:'− oktawa'}));expect((screen.getByLabelText('Częstotliwość Hz') as HTMLInputElement).value).toBe('150');fireEvent.click(screen.getByRole('button',{name:'30 s'}));fireEvent.click(screen.getByRole('button',{name:'Uruchom'}));expect(send.mock.calls.at(-1)?.[1].duration).toBe(30)
 })
 it('debounces live frequency changes without affecting the deadline or other device',()=>{
  vi.useFakeTimers();app.state!.laboratory!.active['fdd-1']={hz:220,currentHz:220,duration:5,mode:'off',depth:5,period:4,elapsed:1,remaining:4};mount();
  fireEvent.change(screen.getByLabelText('Częstotliwość Hz'),{target:{value:'300'}});fireEvent.change(screen.getByLabelText('Częstotliwość Hz'),{target:{value:'310'}});expect(send).not.toHaveBeenCalled();act(()=>vi.advanceTimersByTime(251));expect(send).toHaveBeenCalledTimes(1);expect(send).toHaveBeenCalledWith('lab_update',{deviceId:'fdd-1',hz:310,modulation:{mode:'off',depth:5,period:4}})
 })
 it('offers per-device stop and a separate global stop',()=>{
  mount();fireEvent.click(screen.getByRole('button',{name:'Stop FDD 1'}));expect(send).toHaveBeenLastCalledWith('lab_stop',{deviceId:'fdd-1'});fireEvent.click(screen.getByRole('button',{name:'Zatrzymaj wszystko'}));expect(send).toHaveBeenLastCalledWith('stop');fireEvent.click(screen.getByRole('button',{name:'Orkiestra'}));expect(send).toHaveBeenLastCalledWith('lab_leave')
 })
 it('blocks invalid modulation ranges and REAL with ATX OFF',()=>{
  mount();fireEvent.click(screen.getByRole('button',{name:'Vibrato'}));fireEvent.change(screen.getByLabelText('Częstotliwość Hz'),{target:{value:'410'}});expect((screen.getByRole('button',{name:'Uruchom'}) as HTMLButtonElement).disabled).toBe(true);cleanup();app.state!.output.mode='REAL';app.state!.service.power!.state='OFF';mount();expect((screen.getByRole('button',{name:'Uruchom'}) as HTMLButtonElement).disabled).toBe(true);expect(screen.getByText('Włącz ATX w Settings przed testem REAL')).toBeTruthy()
 })
 it('keeps percussion as a single hit and filters devices',()=>{
  mount();fireEvent.click(screen.getByRole('button',{name:'Ustawienia HDD 1'}));expect(screen.queryByRole('button',{name:'∞ Do STOP'})).toBeNull();fireEvent.click(screen.getByRole('button',{name:'Uderz'}));expect(send.mock.calls.at(-1)?.[1]).toMatchObject({deviceId:'hdd-1',duration:1,modulation:{mode:'off'}});fireEvent.change(screen.getByRole('searchbox'),{target:{value:'FDD 2'}});expect(screen.queryByRole('button',{name:'Ustawienia FDD 1'})).toBeNull();expect(screen.getByRole('button',{name:'Ustawienia FDD 2'})).toBeTruthy()
 })
 it('shows homing and keeps start disabled while allowing stop',()=>{
  app.state!.output.mode='REAL'
  app.state!.laboratory!.active['fdd-1']={homing:true,hz:220,currentHz:220,duration:5,mode:'off',depth:0,period:4,elapsed:0,remaining:5}
  mount()
  expect(screen.getByText('Homing — oczekiwanie na TRACK0')).toBeTruthy()
  expect((screen.getByRole('button',{name:'Trwa homing…'}) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button',{name:'Stop FDD 1'}))
  expect(send).toHaveBeenLastCalledWith('lab_stop',{deviceId:'fdd-1'})
 })

})
