import {useEffect,useRef,useState} from 'react'
import {VirtualOutput} from './virtualOutput'
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
  const client=useRef<RuntimeClient|null>(null),importer=useRef<MidiImportProcess|null>(null),history=useRef<FirmwareEvents|null>(null)
  const audio=useRef(new VirtualOutput()),session=useRef(''),latest=useRef<State|null>(null)
  useEffect(()=>{
    const firmware=new FirmwareEvents(setFirmwareEvents);history.current=firmware
    const transport=new RuntimeClient({
      connection:setConnected,disconnected:()=>audio.current.stop(),error:setError,
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
    const imports=new MidiImportProcess(transport,{loading:setMidiLoading,files:setFiles,error:setError})
    client.current=transport;importer.current=imports;transport.start();void imports.refresh()
    return()=>{
      imports.dispose();transport.dispose();audio.current.close()
      if(client.current===transport){client.current=null;importer.current=null;history.current=null}
    }
  },[])
  async function send<A extends ClientAction>(action:A,...args:CommandArguments<A>){
    const payload=args[0]??{}
    setError(null)
    try{
      const transport=client.current
      if(!transport?.connected)throw new Error('Brak połączenia z backendem')
      if((action==='play'||action==='lab_test')&&state?.output.mode==='VIRTUAL')await audio.current.unlock()
      let requestId:string|undefined
      if(action==='service'&&'operation' in payload&&payload.operation==='firmware'){
        requestId=crypto.randomUUID();history.current?.prepare(requestId)
      }
      transport.send({action,...payload,...(requestId?{requestId}:{})} as ClientCommand)
    }catch(error){setError(String(error))}
  }
  async function upload(file:File){
    if(importer.current)await importer.current.upload(file)
    else setError('Brak połączenia z backendem')
  }
  return {state,error,connected,files,send,upload,firmwareEvents,midiLoading}
}
