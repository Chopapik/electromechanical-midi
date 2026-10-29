import {StrictMode,type ReactNode} from 'react'
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest'
import {act,cleanup,renderHook} from '@testing-library/react'
import {useRuntime} from './runtime'
import type {State} from './contracts'

const audio=vi.hoisted(()=>({instances:[] as Array<{
 epoch:number;unlocked:boolean;accepted:number[];resetSession:ReturnType<typeof vi.fn>;close:ReturnType<typeof vi.fn>
}>}))
vi.mock('./virtualOutput',()=>({VirtualOutput:class {
 epoch=-1;unlocked=false;accepted:number[]=[]
 constructor(){audio.instances.push(this)}
 stop=vi.fn()
 close=vi.fn(()=>{this.unlocked=false})
 resetSession=vi.fn(()=>{this.stop();this.epoch=-1})
 unlock=vi.fn(async()=>{this.unlocked=true})
 setVolumes=vi.fn()
 sync=vi.fn()
 state(epoch:number){if(epoch>=this.epoch)this.epoch=epoch}
 schedule(packet:{epoch:number}){
  if(packet.epoch<this.epoch)return
  if(!this.unlocked)throw new Error('Audio locked')
  this.epoch=packet.epoch;this.accepted.push(packet.epoch)
 }
}}))
class Socket {
 static OPEN=1
 static instances:Socket[]=[]
 readyState=0
 sent:Array<Record<string,unknown>>=[]
 onopen:(()=>void)|null=null;onclose:(()=>void)|null=null
 onmessage:((event:{data:string})=>void)|null=null
 constructor(){Socket.instances.push(this)}
 open(){this.readyState=1;this.onopen?.()}
 close(){this.readyState=3;this.onclose?.()}
 send(value:string){this.sent.push(JSON.parse(value))}
 deliver(message:unknown){this.onmessage?.({data:JSON.stringify(message)})}
}
function snapshot(epoch:number,owner='browser'):State{return {state:'playing',position:0,duration:10,file:'test.mid',epoch,owner:'orchestra',revision:1,error:null,audioOwner:owner,
 devices:[],output:{mode:'VIRTUAL',connected:true,unknown:false,message:'Web Audio',muted:[]},
 service:{busy:false,error:null,reset:{available:false,reason:'offline'},home:{available:false,reason:null},firmware:{available:false,reason:null}}}}
function packet(epoch:number,owner='browser'){return {type:'audio',owner,epoch,origin:0,serverTime:0,commands:[]}}
beforeEach(()=>{
 vi.useFakeTimers();Socket.instances=[];audio.instances=[];vi.stubGlobal('WebSocket',Socket)
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>[]})))
})
afterEach(()=>{cleanup();vi.useRealTimers();vi.unstubAllGlobals()})

describe('runtime lifecycle',()=>{
 it('keeps one live transport in StrictMode and ignores callbacks from its disposed mount',async()=>{
  const wrapper=({children}:{children:ReactNode})=><StrictMode>{children}</StrictMode>
  const {result,unmount}=renderHook(()=>useRuntime(),{wrapper})
  await act(async()=>{})
  expect(Socket.instances).toHaveLength(2)
  const stale=Socket.instances[0],current=Socket.instances[1]
  expect(stale.readyState).toBe(3)
  await act(async()=>{current.open();current.deliver({type:'hello',session:'browser'});current.deliver({type:'state',state:snapshot(4)})})
  expect(result.current.connected).toBe(true)
  await act(async()=>{stale.onopen?.();stale.onclose?.();stale.deliver({type:'state',state:snapshot(999)});await vi.advanceTimersByTimeAsync(200)})
  expect(result.current.state?.epoch).toBe(4)
  expect(current.sent.filter(m=>m.action==='sync')).toHaveLength(1)
  expect(stale.sent).toHaveLength(0)
  await act(async()=>{
   const done=result.current.send('play')
   await Promise.resolve()
   const socket=Socket.instances.at(-1)!
   socket.deliver({type:'ack',requestId:[...socket.sent].reverse().find(m=>m.action==='play')!.requestId})
   await done
  })
  expect(current.sent.filter(m=>m.action==='play')).toHaveLength(1)
  unmount()
  await act(async()=>vi.advanceTimersByTimeAsync(2000))
  expect(Socket.instances).toHaveLength(2)
  expect(current.sent.filter(m=>m.action==='sync')).toHaveLength(1)
  expect(audio.instances.filter(instance=>instance.unlocked)).toHaveLength(0)
 })
 it('accepts new backend epochs after reconnect and rejects packets from an old owner/socket',async()=>{
  const {result}=renderHook(()=>useRuntime());const old=Socket.instances[0]
  await act(async()=>{old.open();old.deliver({type:'hello',session:'browser'});old.deliver({type:'state',state:snapshot(20)})})
  await act(async()=>{
   const done=result.current.send('play')
   await Promise.resolve()
   const socket=Socket.instances.at(-1)!
   socket.deliver({type:'ack',requestId:[...socket.sent].reverse().find(m=>m.action==='play')!.requestId})
   await done
  })
  await act(async()=>old.deliver(packet(20)))
  expect(audio.instances.flatMap(instance=>instance.accepted)).toContain(20)
  await act(async()=>{old.close();await vi.advanceTimersByTimeAsync(1000)})
  const current=Socket.instances[1]
  await act(async()=>{current.open();current.deliver({type:'hello',session:'restarted'});current.deliver({type:'state',state:snapshot(0,'restarted')})})
  expect(result.current.state?.epoch).toBe(0)
  await act(async()=>{
   const done=result.current.send('play')
   await Promise.resolve()
   const socket=Socket.instances.at(-1)!
   socket.deliver({type:'ack',requestId:[...socket.sent].reverse().find(m=>m.action==='play')!.requestId})
   await done
  })
  await act(async()=>{current.deliver(packet(1,'restarted'));current.deliver(packet(99,'browser'));old.deliver(packet(100));old.deliver({type:'state',state:snapshot(100)})})
  expect(audio.instances.flatMap(instance=>instance.accepted)).toEqual([20,1])
  expect(audio.instances.reduce((count,instance)=>count+instance.resetSession.mock.calls.length,0)).toBe(2)
  expect(result.current.state?.epoch).toBe(0)
 })
 it('aborts HTTP import on unmount and never installs its late result',async()=>{
  let finish:((result:{ok:boolean;json:()=>Promise<{name:string}>})=>void)|undefined
  let signal:AbortSignal|undefined
  vi.stubGlobal('fetch',vi.fn(async(_url:string,options?:RequestInit)=>{
   if(options?.method==='POST'){
    signal=options.signal as AbortSignal
    return new Promise(resolve=>{finish=resolve})
   }
   return {ok:true,json:async()=>[]}
  }))
  const {result,unmount}=renderHook(()=>useRuntime());const socket=Socket.instances[0]
  await act(async()=>socket.open())
  let upload:Promise<void>|undefined
  act(()=>{upload=result.current.upload(new File(['midi'],'late.mid'))})
  const stop=socket.sent.find(m=>m.action==='stop')!
  await act(async()=>socket.deliver({type:'ack',requestId:stop.requestId}))
  expect(result.current.midiLoading?.stage).toBe('uploading')
  expect(signal?.aborted).toBe(false)
  unmount();expect(signal?.aborted).toBe(true)
  await act(async()=>{finish?.({ok:true,json:async()=>({name:'late.mid'})});await upload})
  expect(socket.sent.some(m=>m.action==='set_file')).toBe(false)
 })
})

it('shows pending Play immediately, rejects duplicates, and clears it on ACK/error',async()=>{
 const {result}=renderHook(()=>useRuntime());const socket=Socket.instances[0]
 await act(async()=>{socket.open();socket.deliver({type:'state',state:{...snapshot(0),state:'stopped'}})})
 let done:Promise<void>|undefined
 act(()=>{done=result.current.send('play')})
 expect(result.current.pendingActions).toContain('play')
 await act(async()=>{await result.current.send('play');await Promise.resolve()})
 expect(socket.sent.filter(m=>m.action==='play')).toHaveLength(1)
 await act(async()=>{socket.deliver({type:'ack',requestId:socket.sent.find(m=>m.action==='play')!.requestId});await done})
 expect(result.current.pendingActions).not.toContain('play')
 act(()=>{done=result.current.send('arrangement_preset',{preset:'fdd_legato'})})
 expect(result.current.pendingActions).toContain('arrangement_preset')
 await act(async()=>{socket.deliver({type:'error',requestId:socket.sent.at(-1)!.requestId,message:'Plan failed'});await done})
 expect(result.current.pendingActions).toHaveLength(0)
 expect(result.current.error).toContain('Plan failed')
})
