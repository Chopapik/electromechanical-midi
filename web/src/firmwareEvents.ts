import type {FirmwareEvent,ServerMessage} from './contracts'

/** UI history only; physical upload and recovery remain server responsibilities. */
export class FirmwareEvents {
  private events:FirmwareEvent[]=[]
  private sequence=0
  private request:string|null=null
  constructor(private publish:(events:FirmwareEvent[])=>void){}
  prepare(request:string){
    this.request=request
    this.events=[...this.events,{type:'firmware_event',seq:0,kind:'status',stage:'prepare',flash:'running',ble:'idle'}]
    this.publish(this.events)
  }
  accept(message:ServerMessage){
    if(message.type==='hello'){this.sequence=0;this.events=[];this.publish(this.events)}
    if((message.type==='ack'||message.type==='error')&&message.requestId&&message.requestId===this.request){
      this.request=null
      if(message.type==='error'){
        this.events=[...this.events,{type:'firmware_event',seq:0,kind:'status',stage:'failed',flash:'failed',ble:'idle',error:message.message}]
        this.publish(this.events)
      }
    }
    if(message.type==='firmware_event'&&message.seq>this.sequence){
      this.sequence=message.seq;this.events=[...this.events,message].slice(-3000);this.publish(this.events)
    }
  }
}
