import {describe,expect,it} from 'vitest'
import {parseFileList,parseServerMessage,parseUploadResult,type ClientCommand,type State} from './contracts'
import {arrangementPresets,isArrangementPreset} from './generated/arrangementPresets'

const state:State={state:'stopped',position:0,duration:1,file:'test.mid',epoch:1,owner:'orchestra',revision:1,error:null,audioOwner:null,
 devices:[{id:'fdd-1',name:'FDD #1',type:'FDD',enabled:true,volume:.6,bands:[[100,410]],reason:null}],
 output:{mode:'REAL',connected:false,unknown:false,message:'Offline',muted:[]},
 service:{busy:false,error:null,reset:{available:false,reason:'offline'},home:{available:false,reason:null},firmware:{available:false,reason:null}}}

describe('application wire contracts',()=>{
 it('has the existing UI order and rejects unknown preset IDs',()=>{
  expect(arrangementPresets.map(p=>p.id)).toEqual(['universal','fdd_expressive','fdd_expressive_solo','adaptive_legato','fdd_legato','balanced','instrument_roles','instrument_roles_unison','instrument_roles_unison4','instrument_roles_duet','fdd_quality','fdd_quality_adaptive','dvd_lead_low_fdd'])
  expect(new Set(arrangementPresets.map(p=>p.id)).size).toBe(arrangementPresets.length)
  for(const preset of arrangementPresets){expect(isArrangementPreset(preset.id)).toBe(true);expect(preset.descriptions.length).toBeGreaterThan(0)}
  expect(isArrangementPreset('missing')).toBe(false)
  expect(isArrangementPreset({})).toBe(false)
 })
 it.each([
  {type:'hello',session:'browser'}, {type:'state',state},
  {type:'ack',requestId:'request',state}, {type:'ack',requestId:'legacy'},
  {type:'error',requestId:'request',message:'ERR HOME_FAILED FDD=1'},
  {type:'sync',sent:1,serverTime:2},
  {type:'audio',owner:'browser',epoch:1,origin:1,serverTime:2,commands:[{time:0,device_id:'fdd-1',kind:'tone',hz:110,duration:1,velocity:100,articulation:{kind:'fdd_legato',frequency:{times:[0],values:[110]}}}]},
  {type:'audio_cancel',owner:'browser',token:'cancel',deviceId:null,epoch:2},
  {type:'firmware_event',seq:1,kind:'log',line:'Building'},
  {type:'firmware_event',seq:2,kind:'status',stage:'upload',flash:'running',ble:'idle',progress:37,error:null},
 ])('accepts existing $type messages without changing fields',message=>{
  expect(parseServerMessage(JSON.stringify(message))).toEqual(message)
 })
 it.each([
  null,[],{}, {type:'hello',session:[]}, {type:'ack',requestId:3},
  {type:'error',message:{}}, {type:'state',state:{...state,devices:[{id:'fdd-1'}]}},
  {type:'state',state:{...state,service:{...state.service,power:{state:'OFF',available:true,operation:null,error:null,reason:null,measured:true}}}},
  {type:'sync',sent:'1',serverTime:2},
  {type:'audio',owner:'browser',epoch:1,origin:1,serverTime:2,commands:[{time:0,device_id:'fdd-1',kind:'tone',hz:'110',duration:1,velocity:100}]},
  {type:'audio_cancel',owner:'browser',token:'cancel',epoch:2},
  {type:'firmware_event',seq:2,kind:'status',progress:'37'},
 ])('rejects malformed input before it reaches consumers: %j',message=>{
  expect(()=>parseServerMessage(JSON.stringify(message))).toThrow(/Nieprawidłowa wiadomość backendu/)
 })
 it('handles invalid JSON and ignores future message types',()=>{
  expect(()=>parseServerMessage('{')).toThrow(/JSON/)
  expect(parseServerMessage('{"type":"future_event"}')).toBeNull()
 })
 it('checks HTTP file results without changing the response format',()=>{
  const files=[{name:'test.mid',size:25,modified:123}]
  expect(parseFileList(files)).toBe(files)
  expect(parseUploadResult({name:'test.mid'})).toEqual({name:'test.mid'})
  expect(()=>parseFileList([{name:'test.mid',size:'25',modified:123}])).toThrow()
  expect(()=>parseUploadResult({detail:'failed'})).toThrow()
 })
})

// Compile-time checks exercised by the regular TypeScript build.
if(false){
 const valid:ClientCommand={action:'lab_test',deviceId:'fdd-1',duration:null}
 void valid
 // @ts-expect-error service operation is required
 const invalid:ClientCommand={action:'service'}
 void invalid
}
