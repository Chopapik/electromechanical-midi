import {useEffect,useRef,useState} from 'react'
import {VirtualOutput,type Command} from './virtualOutput'
export interface Device {id:string;name:string;type:string;enabled:boolean;volume:number;bands:number[][];reason:string|null;continuousRotation?:boolean}
export interface State {
  activity?:Record<string,Command>; state:'playing'|'stopped'|'paused'; position:number;duration:number;file:string|null;epoch:number;owner:string;
  revision:number;error:string|null;audioOwner:string|null;devices:Device[];
  output:{mode:'REAL'|'VIRTUAL';connected:boolean;unknown:boolean;message:string;muted:string[]};
  service:{busy:boolean;error:string|null;reset:{available:boolean;reason:string};home:{available:boolean;reason:string};firmware:{available:boolean;reason:string|null;port?:string|null;ports?:string[];stage?:string;flash?:string;ble?:string;progress?:number|null;error?:string|null}}
}
export interface FirmwareEvent {type:'firmware_event';seq:number;kind:'status'|'log';line?:string;stage?:string;flash?:string;ble?:string;progress?:number|null;error?:string|null}
export function useRuntime(){
  const [state,setState]=useState<State|null>(null),[error,setError]=useState<string|null>(null)
  const [connected,setConnected]=useState(false),[files,setFiles]=useState<{name:string;size:number;modified:number}[]>([])
  const [firmwareEvents,setFirmwareEvents]=useState<FirmwareEvent[]>([])
  const lastFirmwareSeq=useRef(0)
  const pendingFirmwareRequest=useRef<string|null>(null)
  const socket=useRef<WebSocket|null>(null),audio=useRef(new VirtualOutput()),session=useRef(''),latest=useRef<State|null>(null)
  useEffect(()=>{
    let closed=false,retry:ReturnType<typeof setTimeout>
    const connect=()=>{
      const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`);socket.current=ws
      ws.onopen=()=>setConnected(true)
      ws.onclose=()=>{audio.current.stop();setConnected(false);if(!closed)retry=setTimeout(connect,1000)}
      ws.onmessage=event=>{
        const msg=JSON.parse(event.data)
        if(msg.type==='hello'){
          session.current=msg.session
          lastFirmwareSeq.current=0
          setFirmwareEvents([])
        }
        if(msg.type==='error')setError(msg.message)
        if(msg.requestId&&msg.requestId===pendingFirmwareRequest.current){
          pendingFirmwareRequest.current=null
          if(msg.type==='error')setFirmwareEvents(events=>[...events,{type:'firmware_event',seq:0,kind:'status',stage:'failed',flash:'failed',ble:'idle',error:msg.message}])
        }
        if(msg.type==='firmware_event'&&msg.seq>lastFirmwareSeq.current){
          lastFirmwareSeq.current=msg.seq
          setFirmwareEvents(events=>[...events,msg].slice(-3000))
        }
        if(msg.state&&(!latest.current||msg.state.epoch>=latest.current.epoch)){latest.current=msg.state;setState(msg.state);audio.current.state(msg.state.epoch,msg.state.state==='playing'&&msg.state.output.mode==='VIRTUAL'&&msg.state.audioOwner===session.current)}
        if(msg.type==='sync')audio.current.sync(msg.sent,msg.serverTime)
        if(msg.type==='audio'&&msg.owner===session.current){
          const devices=Object.fromEntries((latest.current?.devices??[]).map(d=>[d.id,d]));try{audio.current.schedule(msg,devices)}catch(e){audio.current.stop();setError(String(e));ws.send(JSON.stringify({action:'audio_error',message:String(e),epoch:msg.epoch}))}
        }
        if(msg.type==='audio_cancel'&&msg.owner===session.current){if(msg.epoch!==null)audio.current.state(msg.epoch,false);audio.current.stop(msg.deviceId??undefined);ws.send(JSON.stringify({action:'audio_ack',token:msg.token}))}
      }
    };connect()
    const heartbeat=setInterval(()=>{if(socket.current?.readyState===WebSocket.OPEN)socket.current.send(JSON.stringify({action:'sync',sent:performance.now()/1000}))},200)
    void fetch('/api/files').then(r=>r.json()).then(setFiles).catch(e=>setError(String(e)))
    return()=>{closed=true;clearTimeout(retry);clearInterval(heartbeat);socket.current?.close();audio.current.close()}
  },[])
  async function send(action:string,payload:Record<string,unknown>={}){
    setError(null)
    try{
      if(socket.current?.readyState!==WebSocket.OPEN)throw new Error('Brak połączenia z backendem')
      if((action==='play'||action==='lab_test')&&state?.output.mode==='VIRTUAL')await audio.current.unlock()
      let requestId:string|undefined
      if(action==='service'&&payload.operation==='firmware'){
        requestId=crypto.randomUUID()
        pendingFirmwareRequest.current=requestId
        setFirmwareEvents(events=>[...events,{type:'firmware_event',seq:0,kind:'status',stage:'prepare',flash:'running',ble:'idle'}])
      }
      socket.current.send(JSON.stringify({action,...payload,...(requestId?{requestId}:{})}))
    }catch(e){setError(String(e))}
  }
  async function upload(file:File){
    try{const data=new FormData();data.append('file',file);const response=await fetch('/api/files',{method:'POST',body:data});const result=await response.json();if(!response.ok)throw new Error(result.detail);setFiles(await fetch('/api/files').then(r=>r.json()));await send('set_file',{file:result.name})}catch(e){setError(String(e))}
  }
  return {state,error,connected,files,send,upload,firmwareEvents}
}
