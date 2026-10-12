import {useEffect,useRef} from 'react'
import {Link,useNavigate} from 'react-router-dom'
import {useRuntime} from './runtime'
import {ArrangementPreview} from './components/ArrangementPreview'
import {StatusFooter} from './components/StatusFooter'

type Runtime=ReturnType<typeof useRuntime>

export function SettingsPage({app}:{app:Runtime}){
  const navigate=useNavigate(),s=app.state
  const virtual=s?.output.mode==='VIRTUAL'
  const disabled=!s||!app.connected||s.service.busy||!!app.midiLoading
  const events=app.firmwareEvents??[]
  const reverseStart=[...events].reverse().findIndex(event=>event.kind==='status'&&event.stage==='prepare')
  const started=reverseStart<0?-1:events.length-1-reverseStart
  const current=started>=0?events.slice(started):events
  const latest=[...current].reverse().find(event=>event.kind==='status')
  const firmware=s?.service.firmware
  const stage=latest?.stage??firmware?.stage??'idle'
  const flash=latest?.flash??firmware?.flash??'idle'
  const ble=latest?.ble??firmware?.ble??'idle'
  const progress=latest?latest.progress:firmware?.progress
  const issue=latest?latest.error:firmware?.error
  const consoleRef=useRef<HTMLPreElement>(null)
  useEffect(()=>{if(consoleRef.current)consoleRef.current.scrollTop=consoleRef.current.scrollHeight},[events])
  const labels:Record<string,string>={idle:'Gotowe',prepare:'Przygotowanie i zatrzymanie odtwarzania',build:'Kompilacja firmware',upload:'Upload przez USB',flash_confirmed:'Potwierdzenie flashowania',reboot_wait:'Restart ESP32',ble_connect:'Nawiązywanie BLE',ble_retry:'Ponawianie połączenia BLE',ready:'Handshake i kontroler gotowy',failed:'Błąd aktualizacji'}
  return <div className="workstation">
    <header className="top-bar settings-top"><div className="settings-shell settings-header">
      <Link to="/" className="settings-back">← Wróć</Link>
      <h1>Settings</h1>
    </div></header>
    <main className="settings-main">
      <div className="settings-shell settings-body">
        <section className="settings-section">
          <h2>Output</h2>
          <label><input type="checkbox" checked={virtual} disabled={disabled} onChange={e=>void app.send('output',{mode:e.target.checked?'VIRTUAL':'REAL'})}/> Virtual debug · Web Audio</label>
        </section>
        <section className="settings-section">
          <h2>Aranżacja</h2>
          <div className="settings-action">
            <label className="settings-select">Preset aranżacji
              <select aria-label="Preset aranżacji" value={s?.arrangementPreset??'balanced'} disabled={disabled} onChange={e=>void app.send('arrangement_preset',{preset:e.target.value})}>
                <option value="balanced">Balanced</option>
                <option value="fdd_quality">FDD Quality · eksperymentalny</option>
                <option value="dvd_lead_low_fdd">DVD Lead + Low FDD · eksperymentalny</option>
              </select>
            </label>
            <small>Zmiana presetu zatrzymuje odtwarzanie i przebudowuje plan.</small>
          </div>
          <ArrangementPreview revision={s?.revision??0} file={s?.file??null}/>
        </section>
        <section className="settings-section">
          <h2>Laboratory</h2>
          <button disabled={disabled} onClick={()=>{void app.send('lab_enter');navigate('/')}}>Laboratory · debug</button>
        </section>
        <section className="settings-section">
          <h2>Serwis</h2>
          <div className="settings-action">
            <button disabled={!app.connected||s?.service.busy||!firmware?.available} onClick={()=>void app.send('service',{operation:'firmware'})}>Wgraj firmware ESP32</button>
            <small>{firmware?.port?`Port USB: ${firmware.port} · kandydat CP2102 (tożsamość ESP32 potwierdzi upload)`:(firmware?.reason??'Wykrywanie USB…')}</small>
            {!!firmware?.ports?.length&&firmware.ports.length>1&&<small>Porty: {firmware.ports.join(', ')}</small>}
          </div>
          {(stage!=='idle'||current.some(event=>event.kind==='log'))&&<section className="firmware-panel" aria-label="Aktualizacja firmware">
            <h3>Aktualizacja firmware</h3>
            {flash==='success'&&<p className="firmware-success" role="status">✓ Firmware ESP32 zostało pomyślnie wgrane przez USB.</p>}
            <p role="status">Etap: {labels[stage]??stage}</p>
            {progress!=null&&stage==='upload'?<progress aria-label="Postęp uploadu" max="100" value={progress}/>:['prepare','build','upload','reboot_wait','ble_connect','ble_retry'].includes(stage)&&<progress aria-label="Operacja w toku"/>}
            <p>Flash USB: {flash==='success'?'zakończony pomyślnie':flash==='failed'?'nieudany':flash==='running'?'w toku':'jeszcze nie rozpoczęty'}</p>
            <p>BLE: {ble==='verified'?'połączono i zweryfikowano handshake':ble==='retrying'?'niedostępne, ponawianie':ble==='connecting'?'łączenie i weryfikacja':ble==='waiting'?'oczekiwanie na restart ESP32':'niezweryfikowane'}</p>
            <pre ref={consoleRef} className="firmware-console" aria-label="Log PlatformIO">{current.filter(event=>event.kind==='log').map(event=>event.line).join('\n')}</pre>
          </section>}
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
    <StatusFooter app={app} settings issue={issue}/>
  </div>
}
