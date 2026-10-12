import {Circle} from '@phosphor-icons/react'
import {Link} from 'react-router-dom'
import type {useRuntime} from '../runtime'

export function StatusFooter({app,settings=false,issue}:{app:ReturnType<typeof useRuntime>;settings?:boolean;issue?:string|null}){
  const output=app.state?.output
  const unknown=output?.mode==='REAL'&&output.unknown
  const online=app.connected&&output?.mode==='REAL'&&output.connected&&!unknown
  const status=!app.connected?'Brak połączenia z aplikacją · ponawianie…':
    !output?'Łączenie z aplikacją…':
    unknown?'ESP32 · brak potwierdzenia STOP. Połącz sprzęt ponownie, aby potwierdzić zatrzymanie.':
    output.mode==='VIRTUAL'?'Tryb wirtualny · Web Audio':
    online?'ESP32 · połączony przez BLE':'Offline · ESP32 nie jest połączony'
  const errors=[...new Set([app.error,app.state?.error,issue].filter((message):message is string=>!!message))]
  return <footer className="workstation-status"><div className="workstation-status-content">
    <div className="workstation-messages">
      <span role="status" className={unknown?'status-warning':online?'arduino-connected':''}>
        <Circle size={10} weight={online||unknown?'fill':'regular'} aria-hidden="true"/>{status}
      </span>
      {errors.length>0&&<span role="alert" className="status-error">{errors.join(' · ')}</span>}
    </div>
    <Link className="settings-trigger" to={settings?'/':'/settings'} aria-label={settings?'Wróć do Orkiestry':'Settings'}>{settings?'Orkiestra':'Settings'}</Link>
  </div></footer>
}
