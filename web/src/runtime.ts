import {useEffect,useRef,useState} from 'react'
import {VirtualOutput} from './virtualOutput'
import {BrowserDiagnostics} from './browserDiagnostics'
import {RuntimeClient} from './runtimeClient'
import {MidiImportProcess} from './midiImport'
import {FirmwareEvents} from './firmwareEvents'
import type {State,FirmwareEvent,MidiLoading,FileEntry,ClientAction,ClientCommand,CommandArguments} from './contracts'
export type {Device,LabTest,State,FirmwareEvent,MidiLoading} from './contracts'

/** React composition: transport/import/history have independent, testable lifecycles. */
export function useRuntime(){
  const [state,setState]=useState<State|null>(null),[error,setError]=useState<string|null>(null)
  const [connected,setConnected]=useState(false),[files,setFiles]=useState<FileEntry[]>([])
  const [firmwareEvents,setFirmwareEvents]=useState<FirmwareEvent[]>([])
  const [midiLoading,setMidiLoading]=useState<MidiLoading|null>(null)
  const [pendingActions,setPendingActions]=useState<ClientAction[]>([])
  const pending=useRef(new Set<ClientAction>())
  const client=useRef<RuntimeClient|null>(null),importer=useRef<MidiImportProcess|null>(null),history=useRef<FirmwareEvents|null>(null)
  const audio=useRef(new VirtualOutput()),session=useRef(''),latest=useRef<State|null>(null)
  useEffect(()=>{
    const firmware=new FirmwareEvents(setFirmwareEvents);history.current=firmware
    let browserDiagnostics:BrowserDiagnostics|undefined
    const transport=new RuntimeClient({
      connection:value=>{setConnected(value);if(value)void browserDiagnostics?.flush()},disconnected:()=>audio.current.stop(),error:setError,
      message:msg=>{
        firmware.accept(msg)
        if(msg.type==='hello'){audio.current.resetSession();session.current=msg.session;latest.current=null}
        if(msg.type==='error')setError(msg.message)
        if((msg.type==='state'||msg.type==='ack')&&msg.state&&(!latest.current||msg.state.epoch>=latest.current.epoch)){
          latest.current=msg.state;setState(msg.state);audio.current.setVolumes(msg.state.devices)
          audio.current.state(msg.state.epoch,msg.state.state==='playing'&&msg.state.output.mode==='VIRTUAL'&&msg.state.audioOwner===session.current)
        }
        if(msg.type==='sync')audio.current.sync(msg.sent,msg.serverTime)
        if(msg.type==='audio'&&msg.owner===session.current){
          const devices=Object.fromEntries((latest.current?.devices??[]).map(d=>[d.id,d]))
          try{audio.current.schedule(msg,devices)}catch(error){
            audio.current.stop();setError(String(error));transport.send({action:'audio_error',message:String(error),epoch:msg.epoch})
          }
        }
        if(msg.type==='audio_cancel'&&msg.owner===session.current){
          if(msg.epoch!==null)audio.current.state(msg.epoch,false)
          audio.current.stop(msg.deviceId??undefined);transport.send({action:'audio_ack',token:msg.token})
        }
      },
    })
    browserDiagnostics=new BrowserDiagnostics(transport)
    const onError=(event:ErrorEvent)=>browserDiagnostics?.capture('window_error',event.message,event.error instanceof Error?event.error.stack:undefined)
    const onRejection=(event:PromiseRejectionEvent)=>browserDiagnostics?.capture('unhandled_rejection',String(event.reason),event.reason instanceof Error?event.reason.stack:undefined)
    window.addEventListener('error',onError);window.addEventListener('unhandledrejection',onRejection)
    const imports=new MidiImportProcess(transport,{loading:setMidiLoading,files:setFiles,error:setError})
    client.current=transport;importer.current=imports;transport.start();void imports.refresh()
    return()=>{
      window.removeEventListener('error',onError);window.removeEventListener('unhandledrejection',onRejection)
      browserDiagnostics?.dispose();imports.dispose();transport.dispose();audio.current.close()
      if(client.current===transport){client.current=null;importer.current=null;history.current=null}
    }
  },[])
  async function send<A extends ClientAction>(action:A,...args:CommandArguments<A>){
    const payload=args[0]??{}
    if(pending.current.has(action)&&['play','pause','seek','arrangement_preset','output'].includes(action))return
    setError(null)
    pending.current.add(action);setPendingActions([...pending.current])
    try{
      const transport=client.current
      if(!transport?.connected)throw new Error('Brak połączenia z backendem')
      if((action==='play'||action==='lab_test')&&state?.output.mode==='VIRTUAL')await audio.current.unlock()
      let requestId:string|undefined
      if(action==='service'&&'operation' in payload&&(payload.operation==='firmware'||payload.operation==='firmware_ble')){
        requestId=crypto.randomUUID();history.current?.prepare(requestId,payload.operation==='firmware_ble'?'BLE':undefined)
      }
      if(requestId)transport.send({action,...payload,requestId} as ClientCommand)
      else await transport.command(action,...args)
    }catch(error){setError(String(error))}
    finally{pending.current.delete(action);setPendingActions([...pending.current])}
  }
  async function upload(file:File){
    if(importer.current)await importer.current.upload(file)
    else setError('Brak połączenia z backendem')
  }
  return {state,error,connected,files,send,upload,firmwareEvents,midiLoading,...({pendingActions} as {pendingActions?:ClientAction[]})}
}
