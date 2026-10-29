import {beforeEach,expect,it,vi} from 'vitest'
import {BrowserDiagnostics} from './browserDiagnostics'
import type {RuntimeClient} from './runtimeClient'
const key='orchestra.diagnostics.pending.v1'
beforeEach(()=>localStorage.clear())
it('retains offline reports through reload and removes only after ACK',async()=>{
 const client={connected:false,command:vi.fn().mockResolvedValue(undefined)}
 const first=new BrowserDiagnostics(client as unknown as RuntimeClient)
 first.capture('error','crash');first.dispose()
 expect(JSON.parse(localStorage.getItem(key)!)).toHaveLength(1)
 client.connected=true
 const next=new BrowserDiagnostics(client as unknown as RuntimeClient)
 await next.flush()
 expect(client.command).toHaveBeenCalledWith('client_error',expect.objectContaining({message:'crash'}))
 expect(JSON.parse(localStorage.getItem(key)!)).toEqual([])
})
it('keeps reports on failure and caps and redacts offline queue',async()=>{
 const client={connected:false,command:vi.fn().mockRejectedValue(new Error('offline'))}
 const log=new BrowserDiagnostics(client as unknown as RuntimeClient)
 for(let i=0;i<25;i++)log.capture('error',`failure ${i} token=abc123`)
 const saved=localStorage.getItem(key)!
 expect(JSON.parse(saved)).toHaveLength(20);expect(saved).not.toContain('abc123')
 client.connected=true;await log.flush()
 expect(JSON.parse(localStorage.getItem(key)!)).toHaveLength(20)
})
