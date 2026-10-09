import {mechanicalSamples,type MechanicalArticulation} from './mechanicalAudio'
/** Web Audio executes Player timestamps. It owns audio nodes, never song time. */
export interface Command {
  time:number; device_id:string; kind:'tone'|'hit'|'pulse'|'stop'; duration:number;
  hz:number; velocity:number; articulation?:MechanicalArticulation & {attack?:number; decay?:number; sustain?:number; intensity?:number; resonance?:number; kind?:string; duration?:number;
    gain?:{times:number[];values:number[]}; frequency?:{times:number[];values:number[]}}
}
type Voice={source:OscillatorNode|AudioBufferSourceNode; gain:GainNode; start:number; end:number; device:string}
export class VirtualOutput {
  context:AudioContext|null=null
  private voices:Voice[]=[]
  private bus:GainNode|null=null
  private epoch=-1
  private offset:number|null=null
  private lastHeartbeat=0
  private watchdog:ReturnType<typeof setInterval>|null=null
  constructor(private now=()=>performance.now()/1000) {}
  async unlock() {
    this.context??=new AudioContext()
    await this.context.resume()
    if(this.context.state!=='running') throw new Error('Przeglądarka nie uruchomiła Web Audio')
    if(!this.bus){this.bus=this.context.createGain();this.bus.connect(this.context.destination)}
    this.heartbeat()
    this.watchdog??=setInterval(()=>{if(this.now()-this.lastHeartbeat>.5)this.stop()},50)
  }
  private heartbeat(){
    this.lastHeartbeat=this.now()
    if(this.context&&this.bus){const now=this.context.currentTime;this.bus.gain.cancelScheduledValues(now);this.bus.gain.setValueAtTime(1,now);this.bus.gain.setValueAtTime(0,now+.5)}
  }
  sync(sent:number,serverTime:number) {
    const received=this.now()
    // Clock sample uses RTT midpoint, not accumulated UI animation deltas.
    this.offset=serverTime-(sent+received)/2
    this.heartbeat()
  }
  state(epoch:number,playing:boolean) {
    if(epoch<this.epoch)return
    if(epoch>this.epoch || !playing)this.stop()
    this.epoch=epoch
    this.heartbeat()
  }
  stop(device?:string) {
    for(const voice of [...this.voices])if(!device || voice.device===device) {
      try { voice.gain.gain.cancelScheduledValues(0); voice.gain.gain.setValueAtTime(0,this.context?.currentTime??0); voice.source.stop() } catch { /* already ended */ }
      voice.source.disconnect(); voice.gain.disconnect()
      this.voices=this.voices.filter(v=>v!==voice)
    }
  }
  schedule(packet:{epoch:number;origin:number;serverTime:number;commands:Command[]}, devices:Record<string,{volume:number;type:string}>) {
    const ctx=this.context
    if(packet.epoch<this.epoch)return
    if(!ctx || ctx.state!=='running')throw new Error('Wyjście Web Audio nie działa')
    if(packet.epoch>this.epoch){this.stop();this.epoch=packet.epoch}
    this.offset??=packet.serverTime-this.now()
    const serverNow=this.now()+this.offset
    for(const c of packet.commands){
      const when=ctx.currentTime+packet.origin+c.time-serverNow
      if(c.kind==='stop'){
        for(const v of this.voices)if(v.device===c.device_id && v.start<=when+.001){
          const at=Math.max(ctx.currentTime,when)
          v.gain.gain.cancelScheduledValues(at);v.gain.gain.setValueAtTime(0,at)
          try{v.source.stop(at)}catch{/* already stopped */}
        }
        continue
      }
      const end=when+c.duration
      if(end<=ctx.currentTime || ((c.kind==='hit'||c.kind==='pulse')&&ctx.currentTime-when>.1))continue
      const start=Math.max(ctx.currentTime,when)
      for(const v of this.voices)if(v.device===c.device_id && v.end>start && v.start<=start){
        v.gain.gain.cancelScheduledValues(start);v.gain.gain.setValueAtTime(0,start)
        try{v.source.stop(start)}catch{/* ended */}
      }
      const gain=ctx.createGain(),device=devices[c.device_id],a=c.articulation
      const mechanical=device?.type!=='VHS'
      let source:OscillatorNode|AudioBufferSourceNode
      if(mechanical){
        const samples=mechanicalSamples(device?.type??'FDD',c.device_id,c.hz,c.duration,ctx.sampleRate,a)
        const buffer=ctx.createBuffer(1,samples.length,ctx.sampleRate);buffer.copyToChannel(samples,0)
        source=ctx.createBufferSource();source.buffer=buffer
      } else {
        source=ctx.createOscillator();source.type='sine';source.frequency.setValueAtTime(c.hz,start)
      }
      // Hardware STEP has no per-note amplitude control. Equal units share the same level.
      const stepper=device?.type==='FDD'||device?.type==='DVD_SLED'
      const volume=(mechanical ? .22*.6 : .12*(device?.volume??.5))*(stepper?1:(a?.intensity??(c.velocity/127)**.65))
      const attack=Math.min(mechanical ? .001 : (a?.attack??.003),(end-start)/4)
      gain.gain.setValueAtTime(0,start)
      gain.gain.linearRampToValueAtTime(volume,start+attack)
      gain.gain.linearRampToValueAtTime(volume*(mechanical?1:(a?.sustain??.15)),Math.min(end,start+attack+(a?.decay??.08)))
      if('frequency' in source && a?.frequency)for(let i=0;i<a.frequency.times.length;i++){
        const at=when+a.frequency.times[i]
        if(at>=start&&at<end)source.frequency.linearRampToValueAtTime(a.frequency.values[i],at)
      }
      // MIDI channel gain/expression curves retain their planned timestamps.
      const expression=ctx.createGain();expression.gain.setValueAtTime(stepper?1:(a?.gain?.values[0]??1),start)
      if(!stepper&&a?.gain)for(let i=0;i<a.gain.times.length;i++){
        const at=when+a.gain.times[i]
        if(at>=start&&at<end)expression.gain.linearRampToValueAtTime(a.gain.values[i],at)
      }
      if(!mechanical&&c.kind!=='tone')gain.gain.linearRampToValueAtTime(0,Math.min(end,start+(a?.duration??.1)))
      gain.gain.setValueAtTime(0,end)
      source.connect(gain);gain.connect(expression);expression.connect(this.bus??ctx.destination)
      const voice={source,gain,start,end,device:c.device_id};this.voices.push(voice)
      source.onended=()=>{source.disconnect();gain.disconnect();expression.disconnect();this.voices=this.voices.filter(v=>v!==voice)}
      if('buffer' in source)source.start(start,Math.max(0,start-when))
      else source.start(start)
      source.stop(end)
    }
  }
  close(){this.stop();if(this.watchdog)clearInterval(this.watchdog);this.watchdog=null;void this.context?.close();this.context=null;this.bus=null}
}
