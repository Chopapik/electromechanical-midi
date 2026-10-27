import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {act,cleanup,fireEvent,render,screen} from '@testing-library/react'
import {MemoryRouter} from 'react-router-dom'
import {SettingsPage} from './SettingsPage'
import {useRuntime,type State} from './runtime'

class FakeSocket {
  static OPEN=1
  static instances:FakeSocket[]=[]
  readyState=1
  onopen:(()=>void)|null=null
  onclose:(()=>void)|null=null
  onmessage:((event:{data:string})=>void)|null=null
  sent:string[]=[]
  constructor(_url:string){FakeSocket.instances.push(this)}
  send(message:string){this.sent.push(message)}
  close(){this.readyState=3;this.onclose?.()}
  deliver(message:unknown){this.onmessage?.({data:JSON.stringify(message)})}
}
function Harness(){return <MemoryRouter><SettingsPage app={useRuntime()}/></MemoryRouter>}
const state:State={state:'stopped',position:0,duration:0,file:null,owner:'orchestra',epoch:0,revision:0,error:null,audioOwner:null,
 devices:[],output:{mode:'REAL',connected:false,unknown:false,message:'Brak ESP32 BLE',muted:[]},
 service:{busy:false,error:null,reset:{available:false,reason:'offline'},home:{available:false,reason:'offline'},
  firmware:{available:true,reason:null,port:'/dev/cu.usbserial-test',ports:['/dev/cu.usbserial-test'],stage:'idle',flash:'idle',ble:'idle'}}}
beforeEach(()=>{
 FakeSocket.instances=[]
 vi.stubGlobal('WebSocket',FakeSocket)
 vi.stubGlobal('fetch',vi.fn(async()=>({json:async()=>[]})))
})
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it('offers BLE only when available and shows its own transfer progress',async()=>{
 render(<Harness/>)
 const socket=FakeSocket.instances[0]
 await act(async()=>{socket.onopen?.();socket.deliver({type:'hello',session:'browser'});socket.deliver({type:'state',state})})
 expect((screen.getByRole('button',{name:'Wgraj firmware przez BLE'}) as HTMLButtonElement).disabled).toBe(true)
 const ready={...state,service:{...state.service,firmware:{...state.service.firmware,bleAvailable:true}}}
 await act(async()=>socket.deliver({type:'state',state:ready}))
 fireEvent.click(screen.getByRole('button',{name:'Wgraj firmware przez BLE'}))
 expect(socket.sent.map(text=>JSON.parse(text)).find(message=>message.action==='service')).toMatchObject({operation:'firmware_ble'})
 await act(async()=>socket.deliver({type:'firmware_event',seq:1,kind:'status',stage:'upload_ble',flash:'running',ble:'idle',transport:'BLE',progress:62}))
 expect(screen.getByText('Etap: Upload przez BLE')).toBeTruthy()
 expect((screen.getByRole('progressbar',{name:'Postęp uploadu'}) as HTMLProgressElement).value).toBe(62)
 await act(async()=>socket.deliver({type:'firmware_event',seq:2,kind:'status',stage:'reboot_wait',flash:'success',ble:'waiting',transport:'BLE'}))
 expect(screen.getByText('Flash BLE: zakończony pomyślnie')).toBeTruthy()
 expect(screen.queryByText('✓ Firmware ESP32 zostało pomyślnie wgrane przez USB.')).toBeNull()
})
it('uses the live socket from React through USB upload and verified BLE status',async()=>{
 render(<Harness/>)
 const socket=FakeSocket.instances[0]
 await act(async()=>{socket.onopen?.();socket.deliver({type:'hello',session:'browser'});socket.deliver({type:'state',state})})
 const button=screen.getByRole('button',{name:'Wgraj firmware ESP32'}) as HTMLButtonElement
 expect(button.disabled).toBe(false)
 fireEvent.click(button)
 const request=socket.sent.map(text=>JSON.parse(text)).find(message=>message.action==='service')
 expect(request).toMatchObject({action:'service',operation:'firmware'})
 expect(request.requestId).toEqual(expect.any(String))
 expect(screen.getByText('Etap: Przygotowanie i zatrzymanie odtwarzania')).toBeTruthy()
 await act(async()=>{
  socket.deliver({type:'firmware_event',seq:1,kind:'status',stage:'prepare',flash:'running',ble:'idle'})
  socket.deliver({type:'firmware_event',seq:2,kind:'log',line:'Writing at 0x1000 (37 %)'})
  socket.deliver({type:'firmware_event',seq:3,kind:'status',stage:'upload',flash:'running',ble:'idle',progress:37})
 })
 expect((screen.getByRole('progressbar',{name:'Postęp uploadu'}) as HTMLProgressElement).value).toBe(37)
 expect(screen.getByLabelText('Log PlatformIO').textContent).toContain('Writing at')
 await act(async()=>{
  socket.deliver({type:'firmware_event',seq:4,kind:'status',stage:'reboot_wait',flash:'success',ble:'waiting'})
  socket.deliver({type:'firmware_event',seq:5,kind:'status',stage:'ble_retry',flash:'success',ble:'retrying'})
 })
 expect(screen.getByText('Flash USB: zakończony pomyślnie')).toBeTruthy()
 expect(screen.getByText('BLE: niedostępne, ponawianie')).toBeTruthy()
 await act(async()=>socket.deliver({type:'firmware_event',seq:6,kind:'status',stage:'ready',flash:'success',ble:'verified'}))
 expect(screen.getByText('BLE: połączono i zweryfikowano handshake')).toBeTruthy()
})
