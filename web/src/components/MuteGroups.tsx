import type {useRuntime} from '../runtime'

export function MuteGroups({app}:{app:ReturnType<typeof useRuntime>}){
 const s=app.state
 if(!s)return null
 const enabled=s.devices.filter(d=>d.enabled)
 const fdds=enabled.filter(d=>d.type==='FDD')
 const groups=[
  {name:'Wszystkie FDD',devices:fdds},
  {name:'FDD 1–4',devices:fdds.filter(d=>/^fdd-[1-4]$/.test(d.id))},
  {name:'FDD 5–8',devices:fdds.filter(d=>/^fdd-[5-8]$/.test(d.id))},
  {name:'DVD',devices:enabled.filter(d=>d.type==='DVD_SLED')},
  {name:'HDD',devices:enabled.filter(d=>d.type==='HDD_VCM')},
  {name:'Speakery',devices:enabled.filter(d=>d.type==='VHS')},
 ]
 const disabled=!app.connected||s.service.busy||!!s.planning||!!app.midiLoading||app.pendingActions?.includes('mute_group')
 return <section className="mute-groups" aria-label="Wyciszanie grup instrumentów">
  {groups.filter(g=>g.devices.length).map(group=>{
   const ids=group.devices.map(d=>d.id)
   const count=ids.filter(id=>s.output.muted.includes(id)).length
   const all=count===ids.length
   return <button className="button" key={group.name} disabled={disabled} aria-pressed={all}
    aria-label={`${all?'Włącz':'Wycisz'} ${group.name}`}
    onClick={()=>void app.send('mute_group',{deviceIds:ids,muted:!all})}>
    {group.name} · {count}/{ids.length} wyciszone
   </button>
  })}
 </section>
}
