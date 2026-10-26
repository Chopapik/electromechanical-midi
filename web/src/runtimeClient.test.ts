import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest'
import {RuntimeClient} from './runtimeClient'

class Socket {
 static OPEN=1
 static instances:Socket[]=[]
 readyState=0
 sent:Array<Record<string,unknown>>=[]
 onopen:(()=>void)|null=null
 onclose:(()=>void)|null=null
 onmessage:((event:{data:string})=>void)|null=null
 failure:Error|null=null
 constructor(readonly url:string){Socket.instances.push(this)}
 open(){this.readyState=1;this.onopen?.()}
 close(){this.readyState=3;this.onclose?.()}
 send(text:string){if(this.failure)throw this.failure;this.sent.push(JSON.parse(text))}
 deliver(value:unknown){this.onmessage?.({data:JSON.stringify(value)})}
}
const clients:RuntimeClient[]=[]
function create(){
 const callbacks={message:vi.fn(),connection:vi.fn(),disconnected:vi.fn(),error:vi.fn()}
 const client=new RuntimeClient(callbacks,'ws://localhost/test')
 clients.push(client);client.start()
 const socket=Socket.instances.at(-1)!
 return {client,socket,callbacks}
}
beforeEach(()=>{vi.useFakeTimers();Socket.instances=[];vi.stubGlobal('WebSocket',Socket)})
afterEach(()=>{for(const client of clients.splice(0))client.dispose();vi.useRealTimers();vi.unstubAllGlobals()})

describe('RuntimeClient without React',()=>{
 it('keeps fire-and-forget writes separate from correlated acknowledgements',async()=>{
  const {client,socket,callbacks}=create();socket.open()
  client.send({action:'pause'})
  expect(socket.sent[0]).toEqual({action:'pause'})
  const resolved=vi.fn(),promise=client.command('set_file',{file:'test.mid'}).then(resolved)
  const request=socket.sent[1]
  expect(request).toMatchObject({action:'set_file',file:'test.mid',requestId:expect.any(String)})
  socket.deliver({type:'ack',requestId:'another-request'})
  await Promise.resolve();expect(resolved).not.toHaveBeenCalled()
  socket.deliver({type:'ack',requestId:request.requestId})
  await promise;expect(resolved).toHaveBeenCalledOnce()
  expect(callbacks.connection).toHaveBeenCalledWith(true)
  expect(callbacks.message).toHaveBeenLastCalledWith({type:'ack',requestId:request.requestId})
 })
 it('rejects a correlated command error and expires only the request timeout',async()=>{
  const {client,socket}=create();socket.open()
  const failed=client.command('stop');const failure=expect(failed).rejects.toThrow('STOP not confirmed')
  socket.deliver({type:'error',requestId:socket.sent.at(-1)!.requestId,message:'STOP not confirmed'})
  await failure
  const timed=client.command('set_file',{file:'large.mid'}),result=expect(timed).rejects.toThrow('Przekroczono czas oczekiwania')
  const settled=vi.fn();void timed.catch(settled)
  await vi.advanceTimersByTimeAsync(119999)
  expect(settled).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(1)
  await result;expect(settled).toHaveBeenCalledOnce()
  expect(client.connected).toBe(true)
 })
 it('disconnects pending requests, retries once and ignores stale socket callbacks',async()=>{
  const {client,socket,callbacks}=create();socket.open()
  const pending=client.command('stop'),rejected=expect(pending).rejects.toThrow('Brak połączenia')
  socket.close();await rejected
  expect(callbacks.disconnected).toHaveBeenCalledOnce()
  await vi.advanceTimersByTimeAsync(999)
  expect(Socket.instances).toHaveLength(1)
  await vi.advanceTimersByTimeAsync(1)
  const current=Socket.instances[1];current.open()
  socket.deliver({type:'hello',session:'stale'})
  socket.onopen?.();socket.onclose?.()
  expect(callbacks.message).not.toHaveBeenCalled()
  expect(callbacks.disconnected).toHaveBeenCalledOnce()
  expect(client.connected).toBe(true)
  current.deliver({type:'hello',session:'current'})
  expect(callbacks.message).toHaveBeenCalledWith({type:'hello',session:'current'})
  await vi.advanceTimersByTimeAsync(200)
  expect(current.sent.filter(m=>m.action==='sync')).toHaveLength(1)
  expect(socket.sent.filter(m=>m.action==='sync')).toHaveLength(0)
 })
 it('disposes pending work and all heartbeat/retry timers without accepting late data',async()=>{
  const {client,socket,callbacks}=create();socket.open()
  const pending=client.command('stop'),rejected=expect(pending).rejects.toThrow('Brak połączenia')
  client.dispose();client.dispose();await rejected
  socket.deliver({type:'hello',session:'late'});socket.onopen?.();socket.onclose?.()
  await vi.advanceTimersByTimeAsync(120001)
  expect(Socket.instances).toHaveLength(1)
  expect(socket.sent).toHaveLength(1)
  expect(callbacks.message).not.toHaveBeenCalled()
  expect(client.connected).toBe(false)
  expect(()=>client.send({action:'play'})).toThrow('Brak połączenia')
 })
 it('disposes a queued reconnect and handles malformed data without losing requests',async()=>{
  const first=create();first.socket.open();first.socket.close();first.client.dispose()
  await vi.advanceTimersByTimeAsync(1001)
  expect(Socket.instances).toHaveLength(1)
  const {client,socket,callbacks}=create();socket.open()
  const promise=client.command('stop'),resolved=vi.fn();void promise.then(resolved)
  const requestId=socket.sent.at(-1)!.requestId
  socket.onmessage?.({data:'{'})
  socket.deliver({type:'ack',requestId,state:{bad:'state'}})
  socket.deliver({type:'future_event'})
  await Promise.resolve()
  expect(callbacks.error).toHaveBeenCalledTimes(2)
  expect(callbacks.message).not.toHaveBeenCalled();expect(resolved).not.toHaveBeenCalled()
  socket.deliver({type:'ack',requestId})
  await promise;expect(resolved).toHaveBeenCalledOnce()
 })
 it('keeps separate client instances and their request errors independent',async()=>{
  const first=create(),second=create();first.socket.open();second.socket.open()
  const one=first.client.command('stop'),two=second.client.command('stop')
  const rejected=expect(one).rejects.toThrow('Brak połączenia')
  first.socket.close();await rejected
  expect(second.client.connected).toBe(true)
  expect(second.callbacks.disconnected).not.toHaveBeenCalled()
  second.socket.deliver({type:'ack',requestId:second.socket.sent[0].requestId})
  await expect(two).resolves.toBeUndefined()
 })
 it('removes pending timeouts after a synchronous write failure',async()=>{
  const {client,socket}=create();socket.open();socket.failure=new Error('write failed')
  await expect(client.command('stop')).rejects.toThrow('write failed')
  expect(vi.getTimerCount()).toBe(1) // Only the recurring heartbeat remains.
  client.dispose();expect(vi.getTimerCount()).toBe(0)
 })
})
