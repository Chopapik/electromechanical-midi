import type {RuntimeClient} from './runtimeClient'

const KEY='orchestra.diagnostics.pending.v1'
type Report={kind:string;message:string;stack?:string;occurredAt?:string}
const safe=(value:string)=>value.replace(/-----BEGIN .*?PRIVATE KEY-----[\s\S]*?-----END .*?PRIVATE KEY-----/g,'[REDACTED KEY]')
 .replace(/(bearer\s+|(?:password|secret|token|api[_-]?key)\s*[=:]\s*)[^\s,;]+/gi,'$1[REDACTED]').slice(0,2000)

/** Bounded browser outbox, retained through reload until backend ACK. */
export class BrowserDiagnostics {
 private reports:Report[]=[]
 private flushing=false
 private disposed=false
 constructor(private client:RuntimeClient){
  try{
   const saved=JSON.parse(localStorage.getItem(KEY)??'[]')
   if(Array.isArray(saved))this.reports=saved.filter(r=>r&&typeof r.kind==='string'&&typeof r.message==='string').slice(-20)
    .map(r=>({kind:safe(r.kind),message:safe(r.message),occurredAt:typeof r.occurredAt==='string'?safe(r.occurredAt):undefined,stack:typeof r.stack==='string'?safe(r.stack):undefined}))
  }catch{/* Storage can be unavailable; diagnostics must not break the app. */}
 }
 capture(kind:string,message:string,stack?:string){
  const report={occurredAt:new Date().toISOString(),kind:safe(kind),message:safe(message),stack:stack?safe(stack):undefined}
  if(this.reports.at(-1)?.message===report.message)return
  this.reports.push(report);this.reports=this.reports.slice(-20);this.save();void this.flush()
 }
 private save(){try{localStorage.setItem(KEY,JSON.stringify(this.reports))}catch{/* best effort */}}
 async flush(){
  if(this.flushing||this.disposed||!this.client.connected)return
  this.flushing=true
  try{
   while(this.reports.length&&this.client.connected&&!this.disposed){
    const report=this.reports[0]
    await this.client.command('client_error',report)
    const index=this.reports.indexOf(report)
    if(index>=0)this.reports.splice(index,1)
    this.save()
   }
  }catch{/* Keep unacknowledged report for reconnect. */}
  finally{this.flushing=false}
 }
 dispose(){this.disposed=true}
}
