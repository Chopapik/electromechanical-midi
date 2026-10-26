import {describe,expect,it,vi} from 'vitest'
import {FirmwareEvents} from './firmwareEvents'
import type {FirmwareEvent} from './contracts'

describe('FirmwareEvents without React or hardware',()=>{
 it('publishes immutable optimistic progress and correlates only its own failure',()=>{
  const publish=vi.fn(),history=new FirmwareEvents(publish)
  history.prepare('upload')
  const prepared=publish.mock.calls.at(-1)![0] as FirmwareEvent[]
  expect(prepared).toEqual([{type:'firmware_event',seq:0,kind:'status',stage:'prepare',flash:'running',ble:'idle'}])
  history.accept({type:'error',requestId:'other',message:'unrelated'})
  expect(publish).toHaveBeenCalledOnce()
  history.accept({type:'error',requestId:'upload',message:'OFF not confirmed'})
  const failed=publish.mock.calls.at(-1)![0] as FirmwareEvent[]
  expect(failed).toHaveLength(2)
  expect(failed[1]).toMatchObject({stage:'failed',flash:'failed',error:'OFF not confirmed'})
  expect(prepared).toHaveLength(1)
  history.accept({type:'error',requestId:'upload',message:'duplicate'})
  expect(publish).toHaveBeenCalledTimes(2)
 })
 it('deduplicates sequence numbers and accepts a restarted sequence after hello',()=>{
  const publish=vi.fn(),history=new FirmwareEvents(publish)
  history.accept({type:'firmware_event',seq:7,kind:'log',line:'old'})
  history.accept({type:'firmware_event',seq:7,kind:'log',line:'duplicate'})
  history.accept({type:'firmware_event',seq:6,kind:'log',line:'out of order'})
  expect(publish).toHaveBeenCalledOnce()
  history.accept({type:'hello',session:'new'})
  expect(publish).toHaveBeenLastCalledWith([])
  history.accept({type:'firmware_event',seq:1,kind:'log',line:'new process'})
  expect(publish).toHaveBeenLastCalledWith([{type:'firmware_event',seq:1,kind:'log',line:'new process'}])
 })
 it('caps server history at 3000 events and clears an acknowledged local request',()=>{
  const publish=vi.fn(),history=new FirmwareEvents(publish)
  for(let seq=1;seq<=3005;seq++)history.accept({type:'firmware_event',seq,kind:'log',line:String(seq)})
  const events=publish.mock.calls.at(-1)![0] as FirmwareEvent[]
  expect(events).toHaveLength(3000);expect(events[0].seq).toBe(6);expect(events.at(-1)!.seq).toBe(3005)
  history.prepare('success')
  history.accept({type:'ack',requestId:'success'})
  const count=publish.mock.calls.length
  history.accept({type:'error',requestId:'success',message:'late duplicate'})
  expect(publish).toHaveBeenCalledTimes(count)
 })
})
