import {Link,useNavigate} from 'react-router-dom'
import {useRuntime} from './runtime'

type Runtime=ReturnType<typeof useRuntime>

export function SettingsPage({app}:{app:Runtime}){
  const navigate=useNavigate(),s=app.state
  const virtual=s?.output.mode==='VIRTUAL'
  const disabled=!s||!app.connected||s.service.busy
  return <div className="workstation">
    <header className="top-bar settings-top"><div className="settings-shell settings-header">
      <Link to="/" className="settings-back">← Wróć</Link>
      <h1>Settings</h1>
    </div></header>
    <main className="settings-main">
      {(app.error||s?.error)&&<p className="banner error" role="alert">{app.error||s?.error}</p>}
      <div className="settings-shell settings-body">
        <section className="settings-section">
          <h2>Output</h2>
          <label><input type="checkbox" checked={virtual} disabled={disabled} onChange={e=>void app.send('output',{mode:e.target.checked?'VIRTUAL':'REAL'})}/> Virtual debug · Web Audio</label>
        </section>
        <section className="settings-section">
          <h2>Laboratory</h2>
          <button disabled={disabled} onClick={()=>{void app.send('lab_enter');navigate('/')}}>Laboratory · debug</button>
        </section>
        <section className="settings-section">
          <h2>Serwis</h2>
          <div className="settings-action">
            <button disabled={disabled||!s?.service.firmware.available} onClick={()=>void app.send('service',{operation:'firmware'})}>Wgraj firmware ESP32</button>
            <small>{s?.service.firmware.reason}</small>
          </div>
          <div className="settings-action">
            <button disabled title={s?.service.reset.reason}>Reset ESP32 — niedostępny</button>
            <small>{s?.service.reset.reason}</small>
          </div>
          <div className="settings-action">
            <button disabled={disabled||!s?.service.home.available} onClick={()=>void app.send('service',{operation:'home'})}>Homing TRACK0</button>
          </div>
        </section>
        <section className="settings-section">
          <h2>Mute</h2>
          {s?.devices.map(d=><label key={d.id}><input type="checkbox" checked={s.output.muted.includes(d.id)} disabled={disabled} onChange={e=>void app.send('mute',{deviceId:d.id,muted:e.target.checked})}/> Mute {d.name}</label>)}
        </section>
      </div>
    </main>
  </div>
}
