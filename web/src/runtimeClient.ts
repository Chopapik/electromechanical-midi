import {parseServerMessage,type ClientAction,type ClientCommand,type CommandArguments,type ServerMessage} from './contracts'

interface Callbacks {
  message:(message:ServerMessage)=>void
  connection:(connected:boolean)=>void
  disconnected:()=>void
  error:(error:string)=>void
}
interface Pending {resolve:()=>void;reject:(error:Error)=>void}

/** One transport session: retries, liveness and correlated responses, without React/audio. */
export class RuntimeClient {
  private socket:WebSocket|null=null
  private disposed=false
  private started=false
  private retry:ReturnType<typeof setTimeout>|undefined
  private heartbeat:ReturnType<typeof setInterval>|undefined
  private pending=new Map<string,Pending>()
  constructor(private callbacks:Callbacks,private url=`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`){}
  start(){
    if(this.disposed||this.started)return
    this.started=true
    this.connect()
    this.heartbeat=setInterval(()=>{
      if(this.connected)this.send({action:'sync',sent:performance.now()/1000})
    },200)
  }
  get connected(){return !this.disposed&&this.socket?.readyState===WebSocket.OPEN}
  private connect(){
    if(this.disposed)return
    const socket=new WebSocket(this.url);this.socket=socket
    const current=()=>!this.disposed&&this.socket===socket
    socket.onopen=()=>{if(current())this.callbacks.connection(true)}
    socket.onclose=()=>{
      if(!current())return
      this.socket=null
      this.callbacks.disconnected();this.callbacks.connection(false)
      this.rejectPending(new Error('Brak połączenia z backendem'))
      this.retry=setTimeout(()=>this.connect(),1000)
    }
    socket.onmessage=event=>{
      if(!current())return
      let message:ServerMessage|null
      try{message=parseServerMessage(event.data)}catch(error){this.callbacks.error(String(error));return}
      if(!message)return
      if((message.type==='ack'||message.type==='error')&&message.requestId){
        const request=this.pending.get(message.requestId)
        if(request){this.pending.delete(message.requestId);if(message.type==='error')request.reject(new Error(message.message));else request.resolve()}
      }
      this.callbacks.message(message)
    }
  }
  send(message:ClientCommand){
    if(!this.connected)throw new Error('Brak połączenia z backendem')
    this.socket!.send(JSON.stringify(message))
  }
  command<A extends ClientAction>(action:A,...args:CommandArguments<A>){
    return new Promise<void>((resolve,reject)=>{
      if(!this.connected){reject(new Error('Brak połączenia z backendem'));return}
      const requestId=crypto.randomUUID()
      const timer=setTimeout(()=>{
        this.pending.delete(requestId)
        reject(new Error(`Przekroczono czas oczekiwania na odpowiedź: ${action}. Stan operacji jest niepotwierdzony; sprawdź połączenie lub użyj STOP.`))
      },120000)
      this.pending.set(requestId,{resolve:()=>{clearTimeout(timer);resolve()},reject:error=>{clearTimeout(timer);reject(error)}})
      try{this.send({action,...(args[0]??{}),requestId} as ClientCommand)}
      catch(error){this.pending.get(requestId)?.reject(error instanceof Error?error:new Error(String(error)));this.pending.delete(requestId)}
    })
  }
  private rejectPending(error:Error){for(const request of this.pending.values())request.reject(error);this.pending.clear()}
  dispose(){
    if(this.disposed)return
    this.disposed=true;clearTimeout(this.retry);clearInterval(this.heartbeat)
    this.rejectPending(new Error('Brak połączenia z backendem'))
    this.socket?.close();this.socket=null
  }
}
