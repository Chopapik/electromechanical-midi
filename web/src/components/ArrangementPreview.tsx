import {useEffect,useState} from 'react'
export interface PlannedNote {id:string;trackName:string;deviceId:string|null;deviceType:string|null;playedNote:number|null;actualStart:number;actualDuration:number;outcome:string;hardware?:{selection?:{reason:string;sustainAffinity?:number}}}
export interface PlannedUnison {sourceId:string;sourceDevice:string;deviceId:string;start:number;duration:number;kind:string}
export interface PlanPreview {events:PlannedNote[];reinforcements:PlannedUnison[];report:{totals:{played:number;dropped:number};dvdLeadLowFdd?:{dvdNotes:number;octaveLowered:number;octaveRangeFallback:number;shortenedNotes:number};fddQuality?:{fddNotes:number;fddSeconds:number;estimatedSteps:number;estimatedReversals:number;omittedNotes:number;dvdTakeovers:number;unisonEvents:number}}}
export function ArrangementPreview({revision,file}:{revision:number;file:string|null}){
 const [plan,setPlan]=useState<PlanPreview|null>(null),[error,setError]=useState(''),[page,setPage]=useState(0),[open,setOpen]=useState(false)
 useEffect(()=>{
  let active=true;setPlan(null);setPage(0);setError('')
  if(file&&open)void fetch('/api/plan').then(r=>{if(!r.ok)throw new Error('Nie można pobrać planu');return r.json()}).then(p=>{if(active)setPlan(p)}).catch(e=>{if(active)setError(String(e))})
  return()=>{active=false}
 },[revision,file,open])
 const unisons=plan?.reinforcements.filter(e=>e.kind==='UNISON')??[]
 return <details className="arrangement-preview" onToggle={e=>setOpen(e.currentTarget.open)}><summary>Arrangement · PerformancePlan</summary>
  {plan?.report.dvdLeadLowFdd&&<p aria-label="Diagnostyka DVD Lead">DVD: {plan.report.dvdLeadLowFdd.dvdNotes} nut · FDD −12: {plan.report.dvdLeadLowFdd.octaveLowered} nut · bez obniżenia (zakres): {plan.report.dvdLeadLowFdd.octaveRangeFallback} · skrócone: {plan.report.dvdLeadLowFdd.shortenedNotes}</p>}
  {plan?.report.fddQuality&&<p aria-label="Diagnostyka FDD">FDD: {plan.report.fddQuality.fddNotes} nut · {plan.report.fddQuality.fddSeconds.toFixed(2)} s aktywności · ~{Math.round(plan.report.fddQuality.estimatedSteps)} kroków · ~{plan.report.fddQuality.estimatedReversals} zawróceń · {plan.report.fddQuality.omittedNotes} pominiętych · {plan.report.fddQuality.dvdTakeovers} nut przejętych przez DVD · {plan.report.fddQuality.unisonEvents} UNISON</p>}
  {error&&<p role="alert">{error}</p>}
  {!plan?<p>Wczytaj MIDI, aby zobaczyć plan wykonania.</p>:<>
   <p>{plan.report.totals.played} nut · {plan.report.totals.dropped} odrzuconych · UNISON ×2: {unisons.length}</p>
   <p>DVD · sustain; FDD · frazy i akcenty. Czas oznacza planowaną długość wykonania.</p>
   <div className="arrangement-table"><table><thead><tr><th>Start (s)</th><th>Partia / nuta MIDI</th><th>Instrument</th><th>Czas (s)</th><th>UNISON ×2</th><th>Decyzja</th></tr></thead><tbody>
    {plan.events.slice(page*100,(page+1)*100).map(e=><tr key={e.id} className={e.deviceType==='DVD_SLED'?'dvd-note':'fdd-note'}>
     <td>{e.actualStart.toFixed(3)}</td><td>{e.trackName} · {e.playedNote??'—'}</td><td>{e.deviceId??'DROPPED'}</td><td>{e.actualDuration.toFixed(3)}</td>
     <td>{unisons.filter(u=>u.sourceId===e.id).map(u=>`${u.sourceDevice} + ${u.deviceId}`).join(', ')||'—'}</td>
     <td title={JSON.stringify(e.hardware)}>{e.hardware?.selection?.reason?`${e.hardware.selection.reason} · ${e.outcome}`:e.outcome}</td>
    </tr>)}
   </tbody></table></div>
   <button disabled={page===0} onClick={()=>setPage(p=>p-1)}>Poprzednie nuty</button><span> {page+1} / {Math.max(1,Math.ceil(plan.events.length/100))} </span><button disabled={(page+1)*100>=plan.events.length} onClick={()=>setPage(p=>p+1)}>Następne nuty</button>
  </>}
 </details>
}
