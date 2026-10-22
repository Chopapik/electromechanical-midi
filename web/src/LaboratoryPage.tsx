import {useEffect,useRef,useState} from 'react'
import {Play,Square,ArrowLeft,AudioLines,SlidersHorizontal} from 'lucide-react'
import {StatusFooter} from './components/StatusFooter'
import type {Device,useRuntime} from './runtime'

type Settings={hz:number;duration:number;continuous:boolean;mode:'off'|'sine'|'triangle';depth:number;period:number}
const storageKey='orchestra.laboratory.v1'
const families=[['FDD','Stacje dyskietek'],['DVD_SLED','Silniki DVD'],['VHS','PC Speakery'],['HDD_VCM','Perkusja HDD']]
const presets=[110,130.81,164.81,196,220,261.63,300,329.63,392,440,523.25,659.25,880,987.77]
function bands(d:Device){return d.labBands?.length?d.labBands:d.bands.length?d.bands:[[1,10000]]}
function initial(d:Device):Settings{const [lo,hi]=bands(d)[0];return {hz:Math.max(lo,Math.min(hi,220)),duration:5,continuous:false,mode:'off',depth:5,period:4}}
function note(hz:number){const n=Math.round(69+12*Math.log2(hz/440));return `${['C','C♯','D','D♯','E','F','F♯','G','G♯','A','A♯','B'][(n%12+12)%12]}${Math.floor(n/12)-1}`}
function read():Record<string,Settings>{try{const data=JSON.parse(localStorage.getItem(storageKey)??'{}');return data&&typeof data==='object'?data:{}}catch{return {}}}
function seconds(s:number){return `${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,'0')}`}

export function LaboratoryPage({app}:{app:ReturnType<typeof useRuntime>}){
 const s=app.state!,devices=s.devices,active=s.laboratory?.active??{}
 const [selected,setSelected]=useState(()=>devices.find(d=>d.enabled)?.id??devices[0]?.id??'')
 const [saved,setSaved]=useState(read),[filter,setFilter]=useState('')
 const catalogIds=JSON.stringify(devices.map(d=>d.id))
 const device=devices.find(d=>d.id===selected)??devices[0]
 const settings=device?{...initial(device),...saved[device.id]}:null
 const running=device?active[device.id]:undefined
 const virtual=s.output.mode==='VIRTUAL'
 const disabled=!app.connected||s.service.busy||!!app.midiLoading
 const blocked=disabled||!device?.enabled||!!device?.reason||s.output.unknown||(!virtual&&(device?.realEnabled===false||!s.output.connected||s.service.power?.state!=='ON'))||!!device&&s.output.muted.includes(device.id)
 const latest=useRef(app);latest.current=app
 const liveKey=JSON.stringify(settings&&{hz:settings.hz,mode:settings.mode,depth:settings.depth,period:settings.period})
 const applied=useRef<string|null>(null)
 useEffect(()=>{
  const known=new Set<string>(JSON.parse(catalogIds))
  setSaved(old=>{
   const entries=Object.entries(old)
   return entries.every(([id])=>known.has(id))?old:Object.fromEntries(entries.filter(([id])=>known.has(id)))
  })
 },[catalogIds])
 useEffect(()=>{try{localStorage.setItem(storageKey,JSON.stringify(saved))}catch{/* Storage may be disabled. */}},[saved])
 useEffect(()=>{
  if(!device||!settings||!running||device.type==='HDD_VCM'||blocked){applied.current=null;return}
  const key=device.id+liveKey
  const actual=JSON.stringify({hz:running.hz,mode:running.mode,depth:running.depth,period:running.period})
  if(actual===liveKey){applied.current=key;return}
  if(applied.current===key)return
  const timer=setTimeout(()=>{applied.current=key;void latest.current.send('lab_update',{deviceId:device.id,hz:settings.hz,modulation:{mode:settings.mode,depth:settings.depth,period:settings.period}})},250)
  return ()=>clearTimeout(timer)
 },[selected,liveKey,!!running,blocked])
 if(!device||!settings)return <div className="workstation"><p>Brak urządzeń w rejestrze.</p><button onClick={()=>void app.send('lab_leave')}>Wróć do Orkiestry</button></div>
 const percussion=device.type==='HDD_VCM',allowed=bands(device)
 const band=allowed.find(([lo,hi])=>settings.hz>=lo&&settings.hz<=hi)??allowed[0]
 const [lo,hi]=band
 const valid=Number.isFinite(settings.hz)&&allowed.some(([a,b])=>settings.hz>=a&&settings.hz<=b)&&Number.isFinite(settings.depth)&&settings.depth>=0&&(settings.mode==='off'||allowed.some(([a,b])=>settings.hz-settings.depth>=a&&settings.hz+settings.depth<=b))
 const change=(patch:Partial<Settings>)=>setSaved(old=>({...old,[device.id]:{...settings,...patch}}))
 const setHz=(hz:number)=>change({hz:Math.round(Math.max(lo,Math.min(hi,hz))*100)/100})
 const position=Math.log(settings.hz/lo)/Math.log(hi/lo)*1000
 const start=()=>void app.send('lab_test',{deviceId:device.id,hz:settings.hz,duration:percussion?1:settings.continuous?null:settings.duration,modulation:{mode:percussion?'off':settings.mode,depth:settings.depth,period:settings.period}})
 const reason=!device.enabled?device.reason??'Urządzenie nieaktywne':s.output.muted.includes(device.id)?'Urządzenie wyciszone w Settings':!virtual&&device.realEnabled===false?'Urządzenie oczekuje kwalifikacji i realEnabled=true':!virtual&&s.service.power?.state!=='ON'?'Włącz ATX w Settings przed testem REAL':!virtual&&!s.output.connected?'Połącz ESP32 przed testem REAL':null
 return <div className="workstation lab-workstation">
  <header className="top-bar"><div className="lab-top">
   <div><span className="lab-eyebrow">STUDIO / TESTY URZĄDZEŃ</span><h1>Laboratorium</h1></div>
   <div className="lab-top-actions"><span className="lab-output">{virtual?'VIRTUAL · Web Audio':'REAL · ESP32'} · {Object.keys(active).length} aktywnych</span><button className="lab-stop-all" onClick={()=>void app.send('stop')}><Square size={14}/> Zatrzymaj wszystko</button><button onClick={()=>void app.send('lab_leave')}><ArrowLeft size={14}/> Orkiestra</button></div>
  </div></header>
  <main className="lab-layout">
   <section className="lab-device-list" aria-label="Lista urządzeń">
    <div className="lab-list-heading"><h2>Urządzenia <span>{devices.length}</span></h2><p>Wybierz, ustaw, posłuchaj razem.</p><input type="search" aria-label="Szukaj urządzenia" placeholder="Szukaj urządzenia…" value={filter} onChange={e=>setFilter(e.target.value)}/></div>
    {families.map(([type,title])=>{const list=devices.filter(d=>d.type===type&&d.name.toLowerCase().includes(filter.toLowerCase()));return !!list.length&&<div className="lab-family" key={type}><h3>{title}</h3>{list.map(d=>{const live=active[d.id],draft=saved[d.id]??initial(d);return <button key={d.id} className={`lab-device-row ${d.id===device.id?'selected':''} ${live?'playing':''}`} aria-pressed={d.id===device.id} aria-label={`Ustawienia ${d.name}`} onClick={()=>setSelected(d.id)}>
     <span className="lab-dot"/><span className="lab-device-name">{d.name}<small>{!d.enabled?'Nieaktywne':live?.homing?'Homing…':live?'Gra teraz':'Gotowe'}</small></span><span className="lab-device-pitch">{d.type==='HDD_VCM'?'Uderzenie':`${(live?.currentHz??draft.hz).toFixed(1)} Hz`}<small>{live?(live.remaining===null?'∞ · '+seconds(live.elapsed):seconds(live.remaining)+' do końca'):draft.continuous?'∞ · do STOP':`${draft.duration} s`}</small></span>
    </button>})}</div>})}
    {!devices.some(d=>d.name.toLowerCase().includes(filter.toLowerCase()))&&<p className="lab-empty">Brak pasujących urządzeń.</p>}
   </section>
   <aside className="lab-inspector" aria-label={`Panel ${device.name}`}>
    <div className="lab-inspector-title"><div><span className="lab-eyebrow">{percussion?'TEST IMPULSU':'GENERATOR CZĘSTOTLIWOŚCI'}</span><h2>{device.name}</h2></div><SlidersHorizontal size={20}/></div>
    <div className={`lab-live-state ${running?'on':''}`}><span className="lab-dot"/>{running?.homing?'Homing — oczekiwanie na TRACK0':running?`Gra · ${seconds(running.elapsed)}${running.remaining===null?' · bez limitu czasu':` · pozostało ${seconds(running.remaining)}`}`:'Zatrzymane'}<span>{running&&!percussion?`${running.currentHz.toFixed(1)} Hz`:''}</span></div>
    <div className="lab-transport"><button className="lab-start" disabled={blocked||!percussion&&(!valid||!settings.continuous&&(!Number.isFinite(settings.duration)||settings.duration<.1||settings.duration>3600))||!!running} onClick={start}><Play size={16}/>{percussion?'Uderz':running?.homing?'Trwa homing…':running?'Test aktywny':'Uruchom'}</button><button className="lab-stop" disabled={!app.connected} onClick={()=>void app.send('lab_stop',{deviceId:device.id})}><Square size={16}/>Stop {device.name}</button></div>
    {!percussion&&<>
     <section className="lab-control-section">
      <div className="lab-frequency"><label htmlFor="lab-hz">Częstotliwość<input id="lab-hz" aria-label="Częstotliwość Hz" type="number" min={lo} max={hi} step="0.01" value={settings.hz} onChange={e=>change({hz:Number(e.target.value)})}/></label><span>Hz <b>{settings.hz>0?note(settings.hz):'—'}</b></span></div>
      <input className="lab-range" aria-label="Suwak częstotliwości" type="range" min="0" max="1000" step="1" value={Number.isFinite(position)?Math.max(0,Math.min(1000,position)):0} onChange={e=>setHz(lo*(hi/lo)**(Number(e.target.value)/1000))}/>
      <div className="lab-scale"><span>{lo.toFixed(lo<1?3:0)} Hz</span><span>{hi.toFixed(0)} Hz</span></div>
      {allowed.length>1&&<div className="lab-chips">{allowed.map(([a,b])=><button key={a} onClick={()=>change({hz:a,mode:'off'})}>{a}–{b} Hz</button>)}</div>}
      <div className="lab-step-buttons">{[[-12,'− oktawa'],[-1,'− półton'],[1,'+ półton'],[12,'+ oktawa']].map(([n,label])=><button key={n} onClick={()=>setHz(settings.hz*2**(Number(n)/12))}>{label}</button>)}</div>
      <div className="lab-chips">{presets.filter(h=>h>=lo&&h<=hi).map(h=><button key={h} className={Math.abs(h-settings.hz)<.01?'chosen':''} onClick={()=>setHz(h)}>{Number.isInteger(h)?h:note(h)}</button>)}</div>
      <small className="lab-help">Zmiany częstotliwości i modulacji działają podczas testu.</small>
     </section>
     <section className="lab-control-section">
      <h3><AudioLines size={16}/> Modulacja częstotliwości</h3>
      <div className="lab-segmented" role="group" aria-label="Modulacja częstotliwości">{[['off','Stały ton'],['sine','Vibrato'],['triangle','Przemiatanie']].map(([mode,label])=><button key={mode} aria-pressed={settings.mode===mode} onClick={()=>change({mode:mode as Settings['mode']})}>{label}</button>)}</div>
      {settings.mode!=='off'&&<><svg className="lab-mod-preview" viewBox="0 0 300 48" role="img" aria-label="Podgląd modulacji częstotliwości"><line x1="0" x2="300" y1="24" y2="24"/><polyline points={Array.from({length:101},(_,i)=>`${i*3},${24-18*(settings.mode==='sine'?Math.sin(i/100*Math.PI*4):1-4*Math.abs((i/50+.25)%1-.5))}`).join(' ')}/></svg>
       <label className="lab-slider-label">Głębokość <span>±{settings.depth} Hz</span><input aria-label="Głębokość modulacji Hz" type="range" min="0" max={Math.max(1,Math.floor((hi-lo)/2))} step="1" value={settings.depth} onChange={e=>change({depth:Number(e.target.value)})}/></label>
       <label className="lab-slider-label">Pełny cykl <span>{settings.period} s</span><input aria-label="Okres modulacji s" type="range" min="1" max="30" step="0.5" value={settings.period} onChange={e=>change({period:Number(e.target.value)})}/></label>
       <small className="lab-help">Modulujemy wysokość tonu. PC Speaker zachowuje prostokątny przebieg.</small>
      </>}
     </section>
     <section className="lab-control-section"><h3>Czas testu</h3>
      <div className="lab-segmented"><button aria-pressed={!settings.continuous} onClick={()=>change({continuous:false})}>Odliczanie</button><button aria-pressed={settings.continuous} onClick={()=>change({continuous:true})}>∞ Do STOP</button></div>
      {!settings.continuous&&<div className="lab-duration"><label>Sekundy <input aria-label="Czas testu s" type="number" min="0.1" max="3600" step="0.1" value={settings.duration} onChange={e=>change({duration:Number(e.target.value)})}/></label><div className="lab-chips">{[5,10,30,60].map(t=><button key={t} onClick={()=>change({duration:t})}>{t} s</button>)}</div></div>}
      <small className="lab-help">{running?'Nowy czas obowiązuje przy kolejnym uruchomieniu.':'Każde urządzenie ma własny zegar.'}{settings.continuous?' Tryb ciągły nie potwierdza bezpieczeństwa termicznego — nadzoruj sprzęt.':''}</small>
     </section>
    </>}
    {percussion&&<p className="lab-help">Pojedyncze uderzenie z czasami i odstępami profilu HDD. Bez ciągłego zasilania cewki.</p>}
    {device.type==='VHS'&&<section className="lab-control-section"><h3>Brzmienie prostokąta</h3><label className="lab-slider-label">Modulacja prostokąta <span>{Math.round((device.realAmplitude??50)/128*100)}%</span><input type="range" aria-label="Modulacja prostokąta" min="0" max="100" value={Math.round((device.realAmplitude??50)/128*100)} disabled={disabled} onChange={e=>void app.send('speaker_volume',{deviceId:device.id,output:'REAL',value:Math.round(Number(e.target.value)*128/100)})}/></label>{virtual&&<label className="lab-slider-label">Głośność VIRTUAL <span>{Math.round(device.volume/2.5*100)}%</span><input type="range" aria-label="Głośność VIRTUAL" min="0" max="100" value={Math.round(device.volume/2.5*100)} disabled={disabled} onChange={e=>void app.send('speaker_volume',{deviceId:device.id,output:'VIRTUAL',value:Number(e.target.value)*2.5/100})}/></label>}</section>}
    {reason&&<p className="lab-notice">{reason}</p>}
    {!valid&&!percussion&&<p className="lab-notice">Ton i cała modulacja muszą mieścić się w jednym dozwolonym paśmie.</p>}

    <p className="lab-help">Wybór innego urządzenia zachowuje ustawienia i nie przerywa testu. Wyjście z laboratorium lub utrata sesji zatrzymuje wszystkie testy. W REAL przycisk Uruchom najpierw parkuje wybraną FDD i czeka na potwierdzenie TRACK0. Czas testu zaczyna się po homingu.</p>
   </aside>
  </main>
  <StatusFooter app={app}/>
 </div>
}
