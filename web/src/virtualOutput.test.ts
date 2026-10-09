import {afterEach,describe,it,expect,vi} from 'vitest'
import {VirtualOutput,type Command} from './virtualOutput'
class Param {setValueAtTime=vi.fn();linearRampToValueAtTime=vi.fn();cancelScheduledValues=vi.fn()}
class Node {gain=new Param();frequency=new Param();connect=vi.fn();disconnect=vi.fn();start=vi.fn();stop=vi.fn();type='';onended=()=>{}}
class Context {currentTime=10;state='running';destination={};sources:Node[]=[];gains:Node[]=[];resume=vi.fn();close=vi.fn();createGain(){const n=new Node();this.gains.push(n);return n}createOscillator(){const n=new Node();this.sources.push(n);return n}}
const note=(device_id='fdd-1',time=0):Command=>({time,device_id,kind:'tone',duration:1,hz:220,velocity:100})
const devices={'fdd-1':{volume:.6,type:'FDD'},'fdd-2':{volume:.6,type:'FDD'}}
let output:VirtualOutput
async function setup(){vi.stubGlobal('AudioContext',Context);output=new VirtualOutput(()=>100);await output.unlock();output.sync(100,100);return output.context as unknown as Context}
afterEach(()=>{output?.close();vi.unstubAllGlobals()})
describe('Web Audio output',()=>{
 it('schedules Player times ahead on the audio clock',async()=>{const ctx=await setup();output.schedule({epoch:1,origin:100.1,serverTime:100,commands:[note()]},devices);expect(ctx.sources[0].start).toHaveBeenCalledWith(10.099999999999994);expect(ctx.sources[0].stop.mock.calls[0][0]).toBeCloseTo(11.1)})
 it('cancels queued notes and rejects packets from older epochs',async()=>{const ctx=await setup();output.schedule({epoch:1,origin:100.1,serverTime:100,commands:[note()]},devices);output.state(2,false);expect(ctx.sources[0].disconnect).toHaveBeenCalled();output.schedule({epoch:1,origin:100,serverTime:100,commands:[note()]},devices);expect(ctx.sources).toHaveLength(1)})
 it('mute cancels one device including future nodes',async()=>{const ctx=await setup();output.schedule({epoch:1,origin:100.1,serverTime:100,commands:[note(),note('fdd-2')]},devices);output.stop('fdd-1');expect(ctx.sources[0].disconnect).toHaveBeenCalled();expect(ctx.sources[1].disconnect).not.toHaveBeenCalled()})
 it('drops expired sounds instead of replaying backlog',async()=>{const ctx=await setup();output.schedule({epoch:1,origin:90,serverTime:100,commands:[note()]},devices);expect(ctx.sources).toHaveLength(0)})
 it('silences when Player stops',async()=>{const ctx=await setup();output.schedule({epoch:1,origin:100,serverTime:100,commands:[note()]},devices);output.state(1,false);expect(ctx.sources[0].stop).toHaveBeenLastCalledWith()})
})
