import {useState} from 'react'
import {Circle} from '@phosphor-icons/react'
import {useRuntime} from './runtime'
import {MidiFileSelector} from './components/MidiFileSelector'
import {PlayerControls} from './components/PlayerControls'
import {InstrumentGrid} from './components/InstrumentGrid'
import {ProgressBar} from './components/ProgressBar'

export default function App(){
  const app=useRuntime(),s=app.state
  const [settings,setSettings]=useState(false),[device,setDevice]=useState(''),[hz,setHz]=useState(200),[duration,setDuration]=useState(1)
  const virtual=s?.output.mode==='VIRTUAL',lab=s?.owner==='lab'
  const disabled=!s||!app.connected||s.service.busy
  const canPlay=!disabled&&!!s?.file&&(virtual||!!s?.output.connected)&&!s?.output.unknown
  return <div className="workstation">
    <header className="top-bar"><div className="top-bar-content">
      {lab?<>
        <h1>Laboratory · debug</h1>
        <button onClick={()=>void app.send('lab_leave')}>Wróć do Orkiestry</button>
      </>:<>
        <div className="top-bar-main">
          <div className="top-bar-playback">
            <PlayerControls state={s?.state??'stopped'} disabled={!canPlay} loading={s?.service.busy} onRestart={()=>void app.send('seek',{position:0})} onToggle={()=>void app.send(s?.state==='playing'?'pause':'play')} onStop={()=>void app.send('stop')}/>
          </div>
          <MidiFileSelector compact files={app.files} selected={s?.file??null} onSelect={file=>void app.send('set_file',{file})} onUpload={file=>void app.upload(file)}/>
        </div>
        <ProgressBar position={s?.position??0} duration={s?.duration??0} playing={s?.state==='playing'} onSeek={position=>void app.send('seek',{position})}/>
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
      <button className="settings-trigger" type="button" aria-label="Settings" aria-expanded={settings} onClick={()=>setSettings(!settings)}>Settings</button>
    </div></footer>
    {settings&&<aside className="settings-drawer" role="dialog" aria-label="Settings"><header><h2>Settings</h2><button onClick={()=>setSettings(false)}>Zamknij</button></header><div className="settings-body">
      <label><input type="checkbox" checked={virtual} disabled={disabled} onChange={e=>void app.send('output',{mode:e.target.checked?'VIRTUAL':'REAL'})}/> Virtual debug · Web Audio</label>
      <button disabled={disabled} onClick={()=>{void app.send('lab_enter');setSettings(false)}}>Laboratory · debug</button>
      <button disabled={disabled||!s?.service.firmware.available} onClick={()=>void app.send('service',{operation:'firmware'})}>Wgraj firmware ESP32</button><small>{s?.service.firmware.reason}</small>
      <button disabled title={s?.service.reset.reason}>Reset ESP32 — niedostępny</button><small>{s?.service.reset.reason}</small>
      <button disabled={disabled||!s?.service.home.available} onClick={()=>void app.send('service',{operation:'home'})}>Homing TRACK0</button>
      {s?.devices.map(d=><label key={d.id}><input type="checkbox" checked={s.output.muted.includes(d.id)} disabled={disabled} onChange={e=>void app.send('mute',{deviceId:d.id,muted:e.target.checked})}/> Mute {d.name}</label>)}
    </div></aside>}
  </div>
}
