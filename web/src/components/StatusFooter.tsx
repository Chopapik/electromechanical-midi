import {Circle} from '@phosphor-icons/react'
import {Link} from 'react-router-dom'
import type {useRuntime} from '../runtime'
import {laboratoryError} from '../laboratoryErrors'

export function StatusFooter({app,settings=false,issue}:{app:ReturnType<typeof useRuntime>;settings?:boolean;issue?:string|null}){
  const output=app.state?.output
  const unknown=output?.mode==='REAL'&&output.unknown
  const online=app.connected&&output?.mode==='REAL'&&output.connected&&!unknown
  const lab=app.state?.owner==='lab'
  const pending=Object.entries(app.state?.laboratory?.active??{}).filter(([,test])=>test.homing)
    .map(([id])=>app.state?.devices.find(d=>d.id===id)?.name??id)
  const waiting=(app.pendingActions??[]).map(action=>({play:'Przygotowanie odtwarzania',pause:'Wstrzymywanie',stop:'Zatrzymywanie',seek:'Zmiana pozycji',arrangement_preset:'Przygotowanie nowej aranżacji',output:'Zmiana wyjścia',mute_group:'Zmiana wyciszenia grupy'} as Record<string,string>)[action]).filter(Boolean)
  const homing=(app.state?.homingDevices??[]).map(id=>app.state?.devices.find(d=>d.id===id)?.name??id)
  const status=!app.connected?'Brak połączenia z aplikacją · ponawianie…':
    !output?'Łączenie z aplikacją…':
    app.state?.planning?`${app.state.planning.label}… · STOP anuluje zastosowanie planu`:
    waiting.length?`${waiting.join(' · ')}…`:
    unknown?'ESP32 · brak potwierdzenia STOP. Połącz sprzęt ponownie, aby potwierdzić zatrzymanie.':
    output.mode==='VIRTUAL'?'Tryb wirtualny · Web Audio':
    online&&lab&&pending.length?`Laboratorium · homing ${pending.join(', ')} · STOP przerywa`:
    online&&app.state?.homing?`Parkowanie FDD przed utworem${homing.length?': '+homing.join(', '):''} · STOP przerywa`:
    online?'ESP32 · połączony przez BLE':'Offline · ESP32 nie jest połączony'
  const errors=[...new Set([app.state?.diagnostics?.error?`Błąd zapisu diagnostyki: ${app.state.diagnostics.error}`:null,app.error,app.state?.error,output?.mode==='REAL'?app.state?.service?.error:null,output?.unknown?output.message:null,issue].filter((message):message is string=>!!message))]
  return <footer className="workstation-status"><div className="workstation-status-content">
    <div className="workstation-messages">
      <span role="status" className={unknown?'status-warning':online?'arduino-connected':''}>
        <Circle size={10} weight={online||unknown?'fill':'regular'} aria-hidden="true"/>{status}
      </span>
      {errors.length>0&&<div role="alert" className="status-error">{errors.map(message=>{
        const description=laboratoryError(message,app.state?.devices??[])
        return <div key={message}>{description}{description!==message&&<details><summary>Szczegóły techniczne</summary><div>{message}</div></details>}</div>
      })}</div>}
      {app.state?.lastFailure&&<details className="last-failure"><summary>Ostatnie przerwanie wykonania</summary>
        <div>{app.state.lastFailure.context.file??'Brak utworu'} · {app.state.lastFailure.context.preset??'—'} · {app.state.lastFailure.position.toFixed(2)} s</div>
        <div>{laboratoryError(app.state.lastFailure.message,app.state.devices)}</div>
        <code>{app.state.lastFailure.message}</code>
      </details>}
    </div>
    <Link className="settings-trigger" to={settings?'/':'/settings'} aria-label={settings?'Wróć do Orkiestry':'Settings'}>{settings?'Orkiestra':'Settings'}</Link>
  </div></footer>
}
