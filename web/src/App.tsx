import {Route,Routes} from 'react-router-dom'
import {StatusFooter} from './components/StatusFooter'
import {useRuntime} from './runtime'
import {MidiFileSelector} from './components/MidiFileSelector'
import {PlayerControls} from './components/PlayerControls'
import {InstrumentGrid} from './components/InstrumentGrid'
import {ProgressBar} from './components/ProgressBar'
import {SettingsPage} from './SettingsPage'
import {LaboratoryPage} from './LaboratoryPage'

export default function App(){
  const app=useRuntime()
  return <Routes>
    <Route path="/" element={<Orchestra app={app}/>}/>
    <Route path="/settings" element={<SettingsPage app={app}/>}/>
  </Routes>
}

function Orchestra({app}:{app:ReturnType<typeof useRuntime>}){
  const s=app.state
  const virtual=s?.output.mode==='VIRTUAL',lab=s?.owner==='lab'
  const pending=app.pendingActions??[]
  const loading=!!s?.planning||pending.some(action=>['play','pause','seek','arrangement_preset','output'].includes(action))
  const disabled=loading||!s||!app.connected||s.service.busy||!!app.midiLoading
  const canPlay=!disabled&&!!s?.file&&(virtual||!!s?.output.connected)&&!s?.output.unknown
  if(lab)return <LaboratoryPage app={app}/>
  return <div className="workstation">
    <header className="top-bar"><div className="top-bar-content">
        <ProgressBar position={s?.position??0} duration={s?.duration??0} playing={s?.state==='playing'} loading={!!app.midiLoading||loading} onSeek={position=>void app.send('seek',{position})}/>
        <div className="top-bar-main">
          <div className="top-bar-playback">
            <PlayerControls state={s?.state??'stopped'} disabled={!canPlay} loading={loading||s?.service.busy||s?.homing} onRestart={()=>void app.send('seek',{position:0})} onToggle={()=>void app.send(s?.state==='playing'?'pause':'play')} onStop={()=>void app.send('stop')}/>
          </div>
          <MidiFileSelector selected={s?.file??null} loading={app.midiLoading} onUpload={file=>void app.upload(file)}/>
        </div>
    </div></header>
    <main className="orchestra-content">
    <InstrumentGrid devices={s?.devices??[]} activity={s?.activity??{}} muted={s?.output.muted??[]} />
    </main>
    <StatusFooter app={app}/>
  </div>
}
