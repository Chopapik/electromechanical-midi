import {useState} from 'react'
import {Link,Route,Routes} from 'react-router-dom'
import {Circle} from '@phosphor-icons/react'
import {useRuntime} from './runtime'
import {MidiFileSelector} from './components/MidiFileSelector'
import {PlayerControls} from './components/PlayerControls'
import {InstrumentGrid} from './components/InstrumentGrid'
import {ProgressBar} from './components/ProgressBar'
import {SettingsPage} from './SettingsPage'

export default function App(){
  const app=useRuntime()
  return <Routes>
    <Route path="/" element={<Orchestra app={app}/>}/>
    <Route path="/settings" element={<SettingsPage app={app}/>}/>
  </Routes>
}

function Orchestra({app}:{app:ReturnType<typeof useRuntime>}){
  const s=app.state
  const [device,setDevice]=useState(''),[hz,setHz]=useState(200),[duration,setDuration]=useState(1)
  const virtual=s?.output.mode==='VIRTUAL',lab=s?.owner==='lab'
  const disabled=!s||!app.connected||s.service.busy
  const canPlay=!disabled&&!!s?.file&&(virtual||!!s?.output.connected)&&!s?.output.unknown
  return <div className="workstation">
    <header className="top-bar"><div className="top-bar-content">
      {lab?<>
        <h1>Laboratory · debug</h1>
        <button onClick={()=>void app.send('lab_leave')}>Wróć do Orkiestry</button>
      </>:<>
        <ProgressBar position={s?.position??0} duration={s?.duration??0} playing={s?.state==='playing'} onSeek={position=>void app.send('seek',{position})}/>
        <div className="top-bar-main">
          <div className="top-bar-playback">
            <PlayerControls state={s?.state??'stopped'} disabled={!canPlay} loading={s?.service.busy} onRestart={()=>void app.send('seek',{position:0})} onToggle={()=>void app.send(s?.state==='playing'?'pause':'play')} onStop={()=>void app.send('stop')}/>
          </div>
          <MidiFileSelector selected={s?.file??null} onUpload={file=>void app.upload(file)}/>
        </div>
      </>}
    </div></header>
    <main className="orchestra-content">
    {(app.error||s?.error)&&<p className="banner error" role="alert">{app.error||s?.error}</p>}
    {lab&&<section className="runtime-lab">
      <label>Urządzenie <select aria-label="Urządzenie" value={device} onChange={e=>{setDevice(e.target.value);const d=s?.devices.find(d=>d.id===e.target.value);setHz(d?.bands[0]?.[0]??200)}}>
        <option value="">Wybierz</option>{s?.devices.map(d=><option key={d.id} value={d.id}>{d.name}{d.reason?` · ${d.reason}`:''}</option>)}
      </select></label>
      <label>Częstotliwość Hz <input type="number" value={hz} onChange={e=>setHz(Number(e.target.value))}/></label>
      <label>Czas (s) <input type="number" min="0.1" max="10" step="0.1" value={duration} onChange={e=>setDuration(Number(e.target.value))}/></label>
      <button disabled={disabled||!device||(!virtual&&!s?.output.connected)||!s?.devices.find(d=>d.id===device)?.enabled} onClick={()=>void app.send('lab_test',{deviceId:device,hz,duration})}>Uruchom test</button>
      <button onClick={()=>void app.send('stop')}>Stop</button>
      <p>{s?.devices.find(d=>d.id===device)?.bands.map(b=>`${b[0]}–${b[1]} Hz`).join(', ')}</p>
    </section>}
    <InstrumentGrid devices={s?.devices??[]} activity={s?.activity??{}} muted={s?.output.muted??[]} />
    </main>
    <footer className="workstation-status"><div className="workstation-status-content">
      <span role="status" className={app.connected&&s?.output.mode==='REAL'&&s.output.connected?'arduino-connected':''}><Circle size={10} weight={app.connected&&s?.output.mode==='REAL'&&s.output.connected?'fill':'regular'} aria-hidden="true"/> {!app.connected?'Brak połączenia z backendem':s?.output.message}</span>
      <Link className="settings-trigger" to="/settings" aria-label="Settings">Settings</Link>
    </div></footer>
  </div>
}
