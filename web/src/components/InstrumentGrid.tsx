import type {Device} from '../runtime'
import type {Command} from '../virtualOutput'
import {StaffNote} from './StaffNote'
import {noteName} from '../noteName'
export function InstrumentGrid({devices,activity,muted}:{devices:Device[];activity:Record<string,Command>;muted:string[]}){
 return <section className="instrument-grid runtime-grid" aria-label="Orkiestra · nuty instrumentów">
  {devices.map(d=>{
   const e=activity[d.id],isMuted=muted.includes(d.id),active=!!e&&!isMuted&&d.enabled
   const tonal=['FDD','DVD_SLED','VHS'].includes(d.type)
   const pitch=active&&e.hz>0?Math.max(0,Math.min(127,Math.round(69+12*Math.log2(e.hz/440)))):null
   const name=d.name.replace(/^DVD Stepper /,'DVD ').replace(/^HDD_VCM #/,'HDD ').replace(/^FDD #/,'FDD ').replace(/^DVD Tray /,'TRAY ')
   return <article key={d.id} aria-label={d.name} className={`instrument-tile${active?' is-active':''}${isMuted?' is-muted':''}`}>
    <h2><span className="instrument-name">{name}</span><span className={`instrument-led ${active?'lit':''}`} /></h2>
    {tonal?<><div className="instrument-staff"><StaffNote midiNote={pitch}/></div>
     <div className="instrument-pitch-row"><span className="note-name">{noteName(pitch)}</span><span className="hz">{active?`${e.hz.toFixed(1)} Hz`:''}</span></div></>:
     <><div className="instrument-event instrument-action">{active?(e.kind==='hit'?(e.articulation?.kind?.replaceAll('_',' ')??'HIT'):'PULSE'):'—'}</div><div className="hit-meter"><i style={{width:active?`${e.velocity/127*100}%`:'0%'}}/></div></>}
    <div className="instrument-source">{isMuted?'Mute':d.reason??(active?'Zaplanowane wykonanie':d.type)}</div>
   </article>
  })}
 </section>
}
