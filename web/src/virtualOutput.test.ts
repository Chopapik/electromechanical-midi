import {afterEach,describe,it,expect,vi} from 'vitest'
import {VirtualOutput,type Command} from './virtualOutput'
class Param {setValueAtTime=vi.fn();linearRampToValueAtTime=vi.fn();cancelScheduledValues=vi.fn()}
class Node {gain=new Param();frequency=new Param();playbackRate=new Param();connect=vi.fn();disconnect=vi.fn();start=vi.fn();stop=vi.fn();type='';setPeriodicWave=vi.fn();onended=()=>{}}
class Context {sampleRate=48000;currentTime=10;state='running';destination={};sources:Node[]=[];gains:Node[]=[];resume=vi.fn();close=vi.fn();createBuffer(_channels:number,length:number,rate:number){return {length,sampleRate:rate,copyToChannel:vi.fn()}}createBufferSource(){const n=new Node();this.sources.push(n);return Object.assign(n,{buffer:null})}createGain(){const n=new Node();this.gains.push(n);return n}createPeriodicWave(real:Float32Array,imag:Float32Array){return {real,imag}}createOscillator(){const n=new Node();this.sources.push(n);return n}}
const note=(device_id='fdd-1',time=0):Command=>({time,device_id,kind:'tone',duration:1,hz:220,velocity:100})
const devices={'fdd-1':{volume:.6,type:'FDD'},'fdd-2':{volume:.6,type:'FDD'}}
let output:VirtualOutput
async function setup(){vi.stubGlobal('AudioContext',Context);output=new VirtualOutput(()=>100);await output.unlock();output.sync(100,100);return output.context as unknown as Context}
afterEach(()=>{output?.close();vi.unstubAllGlobals()})
describe('Web Audio output',()=>{
 it('schedules Player times ahead on the audio clock',async()=>{const ctx=await setup();output.schedule({epoch:1,origin:100.1,serverTime:100,commands:[note()]},devices);expect(ctx.sources[0].start).toHaveBeenCalledWith(10.099999999999994,0);expect(ctx.sources[0].stop.mock.calls[0][0]).toBeCloseTo(11.1)})
 it('cancels queued notes and rejects packets from older epochs',async()=>{const ctx=await setup();output.schedule({epoch:1,origin:100.1,serverTime:100,commands:[note()]},devices);output.state(2,false);expect(ctx.sources[0].disconnect).toHaveBeenCalled();output.schedule({epoch:1,origin:100,serverTime:100,commands:[note()]},devices);expect(ctx.sources).toHaveLength(1)})
 it('mute cancels one device including future nodes',async()=>{const ctx=await setup();output.schedule({epoch:1,origin:100.1,serverTime:100,commands:[note(),note('fdd-2')]},devices);output.stop('fdd-1');expect(ctx.sources[0].disconnect).toHaveBeenCalled();expect(ctx.sources[1].disconnect).not.toHaveBeenCalled()})
 it('drops expired sounds instead of replaying backlog',async()=>{const ctx=await setup();output.schedule({epoch:1,origin:90,serverTime:100,commands:[note()]},devices);expect(ctx.sources).toHaveLength(0)})
 it('uses equal STEP levels regardless of unit mix and MIDI velocity',async()=>{
  const ctx=await setup();output.schedule({epoch:1,origin:100.1,serverTime:100,commands:[{...note(),velocity:20,articulation:{intensity:.1}},{...note('fdd-2'),velocity:127,articulation:{intensity:1}}]}, {'fdd-1':{volume:.1,type:'FDD'},'fdd-2':{volume:.9,type:'FDD'}})
  expect(ctx.gains[1].gain.linearRampToValueAtTime.mock.calls[0][0]).toBe(ctx.gains[3].gain.linearRampToValueAtTime.mock.calls[0][0])
 })
 it('keeps the two PC Speakers independent and square',async()=>{
  const ctx=await setup();output.schedule({epoch:1,origin:100.1,serverTime:100,commands:[note('vhs-1'),{...note('pc-speaker-fx'),hz:987.77}]}, {'vhs-1':{volume:.6,type:'VHS'},'pc-speaker-fx':{volume:.4,type:'VHS'}})
  expect(ctx.sources[0].setPeriodicWave).toHaveBeenCalledTimes(1)
  expect(ctx.sources[1].setPeriodicWave).toHaveBeenCalledTimes(1)
  expect(ctx.sources[0].frequency.setValueAtTime.mock.calls[0][0]).toBe(220)
  expect(ctx.sources[1].frequency.setValueAtTime.mock.calls[0][0]).toBe(987.77)
  output.stop('pc-speaker-fx');expect(ctx.sources[1].disconnect).toHaveBeenCalled();expect(ctx.sources[0].disconnect).not.toHaveBeenCalled()
 })
 it('changes one speaker live without restarting voices or touching its envelope',async()=>{
  const ctx=await setup();output.schedule({epoch:1,origin:100.1,serverTime:100,commands:[note('vhs-1'),note('pc-speaker-fx')]}, {'vhs-1':{volume:.6,type:'VHS'},'pc-speaker-fx':{volume:.4,type:'VHS'}})
  const envelopeCalls=ctx.gains[1].gain.linearRampToValueAtTime.mock.calls.length
  output.setVolumes([{id:'vhs-1',volume:0},{id:'pc-speaker-fx',volume:.4}])
  expect(ctx.gains[3].gain.setValueAtTime).toHaveBeenLastCalledWith(0,ctx.currentTime)
  expect(ctx.gains[6].gain.linearRampToValueAtTime).not.toHaveBeenCalled()
  expect(ctx.gains[1].gain.linearRampToValueAtTime.mock.calls).toHaveLength(envelopeCalls)
  expect(ctx.sources[0].start).toHaveBeenCalledTimes(1)
  expect(ctx.sources[1].start).toHaveBeenCalledTimes(1)
 })
 it('updates shared duty for one active speaker without changing pitch or restarting it',async()=>{
  const ctx=await setup();output.schedule({epoch:1,origin:100.1,serverTime:100,commands:[note('vhs-1'),note('pc-speaker-fx')]}, {'vhs-1':{volume:.6,type:'VHS',realAmplitude:50},'pc-speaker-fx':{volume:.4,type:'VHS',realAmplitude:50}})
  output.setVolumes([{id:'vhs-1',volume:.6,realAmplitude:128},{id:'pc-speaker-fx',volume:.4,realAmplitude:50}])
  expect(ctx.sources[0].setPeriodicWave).toHaveBeenCalledTimes(2)
  expect(ctx.sources[1].setPeriodicWave).toHaveBeenCalledTimes(1)
  expect(ctx.sources[0].frequency.setValueAtTime).toHaveBeenCalledTimes(1)
  expect(ctx.sources[0].start).toHaveBeenCalledTimes(1)
  output.setVolumes([{id:'vhs-1',volume:.6,realAmplitude:0}])
  expect(ctx.gains[3].gain.setValueAtTime).toHaveBeenLastCalledWith(0,ctx.currentTime)
 })
 it('zero silences active and queued speaker voices for pulse modulation, with live recovery',async()=>{
  const ctx=await setup()
  for(const waveform of ['pulse'] as const){
   output.stop()
   const pair={'vhs-1':{volume:.6,type:'VHS',realAmplitude:128,waveform},'pc-speaker-fx':{volume:.4,type:'VHS',realAmplitude:72,waveform}}
   output.schedule({epoch:1,origin:100.1,serverTime:100,commands:[note('vhs-1'),note('pc-speaker-fx',.5)]},pair)
   const levels=[ctx.gains.at(-4)!,ctx.gains.at(-1)!]
   output.setVolumes([{id:'vhs-1',volume:0,realAmplitude:128,waveform},{id:'pc-speaker-fx',volume:0,realAmplitude:72,waveform}])
   for(const level of levels){
    expect(level.gain.cancelScheduledValues).toHaveBeenLastCalledWith(ctx.currentTime)
    expect(level.gain.setValueAtTime).toHaveBeenLastCalledWith(0,ctx.currentTime)
   }
   output.setVolumes(Object.entries(pair).map(([id,d])=>({id,...d})))
   expect(levels[0].gain.linearRampToValueAtTime.mock.calls.at(-1)?.[0]).toBe(.6)
   expect(levels[1].gain.linearRampToValueAtTime.mock.calls.at(-1)?.[0]).toBe(.4)
  }
 })
 it('silences when Player stops',async()=>{const ctx=await setup();output.schedule({epoch:1,origin:100,serverTime:100,commands:[note()]},devices);output.state(1,false);expect(ctx.sources[0].stop).toHaveBeenLastCalledWith()})
})


describe('Laboratory live audio lease',()=>{
 it('renews one speaker oscillator and updates pitch without reattack',async()=>{
  const ctx=await setup(),pair={'vhs-1':{volume:.6,type:'VHS'}}
  const tone={...note('vhs-1'),duration:.5,articulation:{kind:'laboratory'}}
  output.schedule({epoch:1,origin:100,serverTime:100,commands:[tone]},pair)
  output.schedule({epoch:1,origin:100,serverTime:100,commands:[{...tone,time:.1,hz:300}]},pair)
  expect(ctx.sources).toHaveLength(1);expect(ctx.sources[0].start).toHaveBeenCalledTimes(1)
  expect(ctx.sources[0].frequency.linearRampToValueAtTime).toHaveBeenLastCalledWith(300,expect.any(Number))
  expect(ctx.sources[0].stop.mock.calls.at(-1)?.[0]).toBeCloseTo(10.6)
  output.stop('vhs-1');expect(ctx.sources[0].disconnect).toHaveBeenCalled()
 })
 it('loops bounded mechanical buffers with independent live pitches',async()=>{
  const ctx=await setup(),tone={...note(),duration:.5,articulation:{kind:'laboratory'}}
  output.schedule({epoch:1,origin:100,serverTime:100,commands:[tone,{...tone,device_id:'fdd-2'}]},devices)
  output.schedule({epoch:1,origin:100,serverTime:100,commands:[{...tone,time:.1,hz:330}]},devices)
  expect(ctx.sources).toHaveLength(2)
  expect(ctx.sources[0].playbackRate.linearRampToValueAtTime).toHaveBeenLastCalledWith(1.5,expect.any(Number))
  expect(ctx.sources[1].playbackRate.linearRampToValueAtTime).not.toHaveBeenCalled()
  expect((ctx.sources[0] as unknown as AudioBufferSourceNode).loop).toBe(true)
 })
 it('bounds the buffer allocation for extremely low allowed DVD frequencies',async()=>{
  const ctx=await setup(),allocation=vi.spyOn(ctx,'createBuffer')
  output.schedule({epoch:1,origin:100,serverTime:100,commands:[{...note('dvd'),duration:.5,hz:.001,articulation:{kind:'laboratory'}}]}, {dvd:{volume:.6,type:'DVD_SLED'}})
  expect(allocation.mock.calls[0][1]).toBeLessThanOrEqual(ctx.sampleRate*.25)
 })
})

describe('Phrase-legato FDD audio',()=>{
 it('retunes touching tones on one buffer without a new attack or pitch glide',async()=>{
  const ctx=await setup(),tone={...note(),duration:.2,hz:130,articulation:{kind:'fdd_legato'}}
  output.schedule({epoch:1,origin:100.1,serverTime:100,commands:[tone,{...tone,time:.2,hz:165}]},devices)
  expect(ctx.sources).toHaveLength(1)
  expect(ctx.sources[0].start).toHaveBeenCalledTimes(1)
  expect(ctx.sources[0].playbackRate.setValueAtTime).toHaveBeenLastCalledWith(165/130,expect.any(Number))
  expect(ctx.sources[0].playbackRate.linearRampToValueAtTime).not.toHaveBeenCalled()
  expect(ctx.sources[0].stop.mock.calls.at(-1)?.[0]).toBeCloseTo(10.5)
 })
 it('starts a new buffer after a real phrase rest',async()=>{
  const ctx=await setup(),tone={...note(),duration:.2,hz:130,articulation:{kind:'fdd_legato'}}
  output.schedule({epoch:1,origin:100.1,serverTime:100,commands:[tone,{...tone,time:.3,hz:165}]},devices)
  expect(ctx.sources).toHaveLength(2)
 })
 it('does not revive a voice explicitly stopped at a boundary',async()=>{
  const ctx=await setup(),tone={...note(),duration:.2,hz:130,articulation:{kind:'fdd_legato'}}
  output.schedule({epoch:1,origin:100.1,serverTime:100,commands:[tone,{...tone,kind:'stop',time:.2},{...tone,time:.2,hz:165}]},devices)
  expect(ctx.sources).toHaveLength(2)
  output.state(2,false)
  expect(ctx.sources[1].stop).toHaveBeenLastCalledWith()
 })
})


it('resets epochs and queued voices only at a new backend session',async()=>{
 const ctx=await setup()
 output.schedule({epoch:20,origin:100.1,serverTime:100,commands:[note()]},devices)
 output.resetSession()
 expect(ctx.sources[0].disconnect).toHaveBeenCalled()
 output.sync(100,100)
 output.state(0,false)
 output.schedule({epoch:1,origin:100.1,serverTime:100,commands:[note()]},devices)
 expect(ctx.sources).toHaveLength(2)
 output.schedule({epoch:0,origin:100.1,serverTime:100,commands:[note()]},devices)
 expect(ctx.sources).toHaveLength(2)
})
