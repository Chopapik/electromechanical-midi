import {describe,it,expect,vi,beforeEach,beforeAll} from 'vitest'
import {render,screen,fireEvent,cleanup} from '@testing-library/react'
import App from './App'
import {Element} from 'vexflow/bravura'
beforeAll(() => Element.setTextMeasurementCanvas({getContext: () => ({
 measureText: (text: string) => ({width:text.length*8,actualBoundingBoxAscent:16,actualBoundingBoxDescent:4}),
})} as unknown as HTMLCanvasElement))
const send=vi.fn()
const state={state:'stopped',position:0,duration:3,file:'test.mid',owner:'orchestra',epoch:0,revision:0,error:null,audioOwner:null,
  devices:[{id:'fdd-1',name:'FDD #1',type:'FDD',enabled:true,volume:.6,bands:[[200,410]],reason:null}],
  output:{mode:'REAL',connected:false,unknown:false,message:'Brak połączenia z ESP32',muted:[]},
  service:{busy:false,error:null,reset:{available:false,reason:'Brak komendy resetu'},home:{available:false,reason:'Offline'},firmware:{available:false,reason:'Podłącz ESP32 przez USB (CP2102), aby wgrać firmware'}}}
vi.mock('./runtime',()=>({useRuntime:()=>({state,send,error:null,connected:true,files:[{name:'test.mid',size:100,modified:0}],upload:vi.fn()})}))
beforeEach(()=>{cleanup();send.mockClear();state.output.mode='REAL';state.owner='orchestra'})
describe('Orchestra UI',()=>{
 it('starts offline REAL with disabled Play, still showing registry',()=>{render(<App/>);expect((screen.getByRole('button',{name:'Play'}) as HTMLButtonElement).disabled).toBe(true);expect(screen.getByText('Brak połączenia z ESP32')).toBeTruthy();expect(screen.getByRole('article',{name:'FDD #1'})).toBeTruthy();expect(screen.queryByText('Laboratory · debug')).toBeNull()})
 it('Settings only exposes debug, maintenance and device mute',()=>{render(<App/>);fireEvent.click(screen.getByText('Settings'));fireEvent.click(screen.getByLabelText('Virtual debug · Web Audio'));expect(send).toHaveBeenCalledWith('output',{mode:'VIRTUAL'});fireEvent.click(screen.getByLabelText('Mute FDD #1'));expect(send).toHaveBeenCalledWith('mute',{deviceId:'fdd-1',muted:true});expect((screen.getByText('Reset ESP32 — niedostępny') as HTMLButtonElement).disabled).toBe(true);expect(screen.queryByText('AUTO · 4 FDD')).toBeNull()})
 it('virtual is a manual output allowing offline Play',()=>{state.output.mode='VIRTUAL';render(<App/>);expect((screen.getByRole('button',{name:'Play'}) as HTMLButtonElement).disabled).toBe(false);fireEvent.click(screen.getByRole('button',{name:'Play'}));expect(send).toHaveBeenCalledWith('play')})
 it('Lab is entered through Settings and shares device labels',()=>{render(<App/>);fireEvent.click(screen.getByText('Settings'));fireEvent.click(screen.getByText('Laboratory · debug'));expect(send).toHaveBeenCalledWith('lab_enter')})
})

it('restores the footer status and Settings trigger below the centered instrument content',()=>{
 render(<App/>)
 const footer=screen.getByRole('contentinfo')
 expect(footer.contains(screen.getByRole('status'))).toBe(true)
 expect(footer.contains(screen.getByRole('button',{name:'Settings'}))).toBe(true)
 expect(screen.getByRole('main').contains(screen.getByRole('article',{name:'FDD #1'}))).toBe(true)
})
