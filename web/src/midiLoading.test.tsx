import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {act,cleanup,renderHook,render,screen,fireEvent} from '@testing-library/react'
import {useRuntime} from './runtime'
import {MidiFileSelector} from './components/MidiFileSelector'
vi.mock('./virtualOutput',()=>({VirtualOutput:class {stop(){} close(){} state(){} }}))
class FakeSocket {
 static OPEN=1
 static instances:FakeSocket[]=[]
 readyState=1
 onopen:(()=>void)|null=null
 onclose:(()=>void)|null=null
 onmessage:((event:{data:string})=>void)|null=null
 sent:Array<{action:string;requestId?:string;file?:string}>=[]
 constructor(){FakeSocket.instances.push(this)}
 send(text:string){this.sent.push(JSON.parse(text))}
 close(){this.readyState=3;this.onclose?.()}
 deliver(message:unknown){this.onmessage?.({data:JSON.stringify(message)})}
}
beforeEach(()=>{
 FakeSocket.instances=[];vi.stubGlobal('WebSocket',FakeSocket)
 vi.stubGlobal('fetch',vi.fn(async(_url,options)=>({ok:true,json:async()=>options?{name:'new.mid'}:[]})))
})
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it('waits for STOP before upload and keeps loading until the new plan is acknowledged',async()=>{
 const {result}=renderHook(()=>useRuntime());const socket=FakeSocket.instances[0]
 await act(async()=>{})
 vi.mocked(fetch).mockClear()
 let upload:Promise<void>
 act(()=>{upload=result.current.upload(new File(['midi'],'new.mid'))})
 expect(result.current.midiLoading?.stage).toBe('stopping')
 expect(fetch).not.toHaveBeenCalled()
 const stop=socket.sent.find(m=>m.action==='stop')!
 await act(async()=>socket.deliver({type:'ack',requestId:stop.requestId}))
 expect(fetch).toHaveBeenCalledWith('/api/files',expect.objectContaining({method:'POST'}))
 expect(result.current.midiLoading?.stage).toBe('planning')
 const load=socket.sent.find(m=>m.action==='set_file')!
 expect(load.file).toBe('new.mid')
 expect(socket.sent.some(m=>m.action==='play')).toBe(false)
 await act(async()=>{socket.deliver({type:'ack',requestId:load.requestId});await upload!})
 expect(result.current.midiLoading).toBeNull()
 expect(result.current.error).toBeNull()
})
it('aborts loading when STOP fails and leaves an error',async()=>{
 const {result}=renderHook(()=>useRuntime());const socket=FakeSocket.instances[0]
 await act(async()=>{});vi.mocked(fetch).mockClear()
 let upload:Promise<void>
 act(()=>{upload=result.current.upload(new File(['midi'],'new.mid'))})
 const stop=socket.sent.find(m=>m.action==='stop')!
 await act(async()=>{socket.deliver({type:'error',requestId:stop.requestId,message:'Brak potwierdzenia STOP'});await upload!})
 expect(fetch).not.toHaveBeenCalled()
 expect(result.current.error).toContain('Brak potwierdzenia STOP')
 expect(result.current.midiLoading).toBeNull()
})
it('shows the selected filename while blocking another file selection',()=>{
 const onUpload=vi.fn()
 const {container}=render(<MidiFileSelector selected="old.mid" onUpload={onUpload} loading={{name:'new.mid',stage:'uploading'}}/>)
 expect(screen.getByText('new.mid')).toBeTruthy()
 expect((screen.getByRole('button',{name:'Wczytaj MIDI'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.change(container.querySelector('input')!,{target:{files:[new File([''],'another.mid')]}})
 expect(onUpload).not.toHaveBeenCalled()
})
