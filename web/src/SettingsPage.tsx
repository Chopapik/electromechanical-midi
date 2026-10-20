import {waveformPoints} from './pulseWave'
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
  const outputDisabled=!s||!app.connected||s.service.busy
  const events=app.firmwareEvents??[]
  const reverseStart=[...events].reverse().findIndex(event=>event.kind==='status'&&event.stage==='prepare')
  const started=reverseStart<0?-1:events.length-1-reverseStart
  const current=started>=0?events.slice(started):events
  const latest=[...current].reverse().find(event=>event.kind==='status')
  const power=s?.service.power
  const powerDisabled=disabled||!power?.available
  const firmware=s?.service.firmware
  const stage=latest?.stage??firmware?.stage??'idle'
  const flash=latest?.flash??firmware?.flash??'idle'
  const ble=latest?.ble??firmware?.ble??'idle'
  const progress=latest?latest.progress:firmware?.progress
  const issue=latest?latest.error:firmware?.error
  const consoleRef=useRef<HTMLPreElement>(null)
  useEffect(()=>{if(consoleRef.current)consoleRef.current.scrollTop=consoleRef.current.scrollHeight},[events])
  const labels:Record<string,string>={idle:'Gotowe',prepare:'Przygotowanie i zatrzymanie odtwarzania',power_off:'Wyłączanie ATX i oczekiwanie po GPIO19 LOW',build:'Kompilacja firmware',upload:'Upload przez USB',flash_confirmed:'Potwierdzenie flashowania',reboot_wait:'Restart ESP32',ble_connect:'Nawiązywanie BLE',ble_retry:'Ponawianie połączenia BLE',ready:'Handshake i kontroler gotowy',failed:'Błąd aktualizacji'}
  return <div className="workstation">
    <header className="top-bar settings-top"><div className="settings-shell settings-header">
      <Link to="/" className="settings-back">← Wróć</Link>
      <h1>Settings</h1>
    </div></header>
    <main className="settings-main">
      <div className="settings-shell settings-body">
        <section className="settings-section">
          <h2>Output</h2>
          <label><input type="checkbox" checked={virtual} disabled={outputDisabled} onChange={e=>void app.send('output',{mode:e.target.checked?'VIRTUAL':'REAL'})}/> Virtual debug · Web Audio</label>
        </section>
        <section className="settings-section">
          <h2>Zasilanie ATX</h2>
          <p role="status">Stan logiczny: {power?.state??'UNAVAILABLE'}</p>
          <div className="settings-action">
            <button disabled={powerDisabled||power?.state==='ON'} onClick={()=>{
              if(window.confirm('Włączyć fizyczny zasilacz ATX? Upewnij się, że układ jest gotowy do zasilenia.'))void app.send('service',{operation:'power_on',confirmed:true})
            }}>Włącz ATX</button>
            <button disabled={powerDisabled} onClick={()=>void app.send('service',{operation:'power_off'})}>Wyłącz ATX</button>
          </div>
          <small>GPIO19 / PS_ON#: stan logiczny, bez pomiaru napięcia. POWER OFF nie potwierdza zaniku napięć ani nie rozwiązuje zasilania ESP32 i rejestrów z różnych źródeł.</small>
          {power?.operation&&<p role="status">Operacja: {power.operation==='firmware'?'Flashowanie firmware':power.operation}</p>}
          {power?.reason&&<p>{power.reason}</p>}
          {power?.error&&<p role="alert">{power.error}</p>}
        </section>
        <section className="settings-section">
          <h2>Brzmienie PC Speaker</h2>
          {s?.devices.filter(d=>d.type==='VHS').map(d=><div className="settings-action speaker-volume" key={d.id}>
            <h3>{d.name}</h3>
            <label>VIRTUAL · {Math.round(d.volume/2.5*100)}%
              <input aria-label={`${d.name} VIRTUAL głośność`} type="range" min="0" max="100" step="1" value={Math.round(d.volume/2.5*100)} disabled={disabled} onChange={e=>void app.send('speaker_volume',{deviceId:d.id,output:'VIRTUAL',value:Number(e.target.value)/100*2.5})}/>
            </label>
            <label>Modulacja prostokąta · REAL + VIRTUAL · {Math.round((d.realAmplitude??50)/128*100)}%
              <input aria-label={`${d.name} wypełnienie fali`} type="range" min="0" max="100" step="1" value={Math.round((d.realAmplitude??50)/128*100)} disabled={disabled} onChange={e=>void app.send('speaker_volume',{deviceId:d.id,output:'REAL',value:Math.round(Number(e.target.value)/100*128)})}/>
            </label>
            <svg className="pulse-preview" viewBox="0 0 200 40" role="img" aria-label={`${d.name} podgląd fali`}>
              <polyline points={waveformPoints('pulse',d.realAmplitude??50)} fill="none" stroke="currentColor" strokeWidth="1.5"/>
            </svg>
          </div>)}
          <small>Tylko prostokąt z regulacją wypełnienia, wspólną dla REAL i VIRTUAL. Skala modulacji 0–100% odpowiada przewodzeniu tranzystora przez 0–50% okresu; 100% daje symetryczny kwadrat, 0% ciszę. Modulacja zmienia barwę i słyszany poziom, nie jest niezależną regulacją głośności REAL. VIRTUAL ma osobny suwak głośności 0–100% (gain 0–2,5). Ustawienia zapisują się automatycznie.</small>
        </section>
        <section className="settings-section">
          <h2>Aranżacja</h2>
          <div className="settings-action">
            <label className="settings-select">Preset aranżacji
              <select aria-label="Preset aranżacji" value={s?.arrangementPreset??'balanced'} disabled={disabled} onChange={e=>void app.send('arrangement_preset',{preset:e.target.value})}>
                <option value="universal">Universal · adaptacyjny</option>
                <option value="balanced">Balanced</option>
                <option value="instrument_roles">FDD Riffs + DVD Tło</option>
                <option value="instrument_roles_unison">FDD Riffs + DVD Tło · Pary Unisono</option>
                <option value="instrument_roles_unison4">4 FDD Unisono · eksperymentalny</option>
                <option value="instrument_roles_duet">FDD Riffs + DVD Tło · Pary Dwugłos</option>
                <option value="fdd_quality">FDD Quality · eksperymentalny</option>
                <option value="fdd_quality_adaptive">FDD Quality Adaptive · eksperymentalny</option>
                <option value="dvd_lead_low_fdd">DVD Lead + Low FDD · eksperymentalny</option>
              </select>
            </label>
            <small>Zmiana presetu zatrzymuje odtwarzanie i przebudowuje plan.</small>
            {s?.arrangementPreset==='universal'&&<small>Lokalne frazy, wokal i ozdobniki; długie tło DVD. FDD uwzględnia odstęp ataków przed wyborem urządzenia.</small>}
            {s?.arrangementPreset==='instrument_roles'&&<small>FDD: krótkie nuty i zmiany wysokości. DVD: długie tło. PC Speaker: wokal, PC Speaker FX: ozdobniki. Perkusja bez zmian.</small>}
            {s?.arrangementPreset==='instrument_roles_unison'&&<small>FDD1+2 i FDD3+4: dwie partie, każda grana wspólnie tą samą nutą. Pary utrzymują frazy i przejmują aktywne partie podczas pauz. DVD: długie tło.</small>}
            {s?.arrangementPreset==='instrument_roles_unison4'&&<small>FDD1–4 grają jedną wspólną linię: ta sama nuta, start i długość. Wybór partii śledzi frazę i przejmuje inną podczas pauz. DVD, speakery i perkusja zachowują przydział FDD Riffs + DVD Tło. Mniej niezależnych głosów FDD; pozostałe nuty mogą zostać pominięte.</small>}
            {s?.arrangementPreset==='instrument_roles_duet'&&<small>FDD1+2 i FDD3+4: do dwóch różnych nut MIDI z jednej partii na parę. Pojedyncza linia: unisono. DVD: długie tło. Dwie niezależne partie FDD jednocześnie.</small>}
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
            {progress!=null&&stage==='upload'?<progress aria-label="Postęp uploadu" max="100" value={progress}/>:['prepare','power_off','build','upload','reboot_wait','ble_connect','ble_retry'].includes(stage)&&<progress aria-label="Operacja w toku"/>}
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
