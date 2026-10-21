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
  const status=!app.connected?'Brak połączenia z aplikacją · ponawianie…':
    !output?'Łączenie z aplikacją…':
    unknown?'ESP32 · brak potwierdzenia STOP. Połącz sprzęt ponownie, aby potwierdzić zatrzymanie.':
    output.mode==='VIRTUAL'?'Tryb wirtualny · Web Audio':
    online&&lab&&pending.length?`Laboratorium · homing ${pending.join(', ')} · STOP przerywa`:
    online&&app.state?.homing?'Parkowanie FDD przed utworem · STOP przerywa':
    online?'ESP32 · połączony przez BLE':'Offline · ESP32 nie jest połączony'
  const errors=[...new Set([app.error,app.state?.error,issue].filter((message):message is string=>!!message))]
  return <footer className="workstation-status"><div className="workstation-status-content">
    <div className="workstation-messages">
      <span role="status" className={unknown?'status-warning':online?'arduino-connected':''}>
        <Circle size={10} weight={online||unknown?'fill':'regular'} aria-hidden="true"/>{status}
      </span>
      {errors.length>0&&<div role="alert" className="status-error">{errors.map(message=>{
        const description=lab?laboratoryError(message,app.state?.devices??[]):message
        return <div key={message}>{description}{description!==message&&<details><summary>Szczegóły techniczne</summary><div>{message}</div></details>}</div>
      })}</div>}
    </div>
    <Link className="settings-trigger" to={settings?'/':'/settings'} aria-label={settings?'Wróć do Orkiestry':'Settings'}>{settings?'Orkiestra':'Settings'}</Link>
  </div></footer>
}
