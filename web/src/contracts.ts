/** Application wire contracts. Validate unknown JSON before it reaches state/audio. */
import type {SpeakerWaveform} from './pulseWave'
import type {Command} from './virtualOutput'
import {isArrangementPreset,type ArrangementPreset} from './generated/arrangementPresets'

export interface Device {id:string;name:string;type:string;enabled:boolean;realEnabled?:boolean;volume:number;realAmplitude?:number;waveform?:SpeakerWaveform;bands:number[][];labBands?:number[][];reason:string|null;continuousRotation?:boolean}
export interface LabTest {homing?:boolean;hz:number;currentHz:number;duration:number|null;mode:'off'|'sine'|'triangle';depth:number;period:number;elapsed:number;remaining:number|null}
export interface State {
  laboratory?:{active:Record<string,LabTest>};
  activity?:Record<string,Command>; homing?:boolean; state:'playing'|'stopped'|'paused'; position:number;duration:number;file:string|null;epoch:number;owner:string;
  arrangementPreset?:ArrangementPreset;revision:number;error:string|null;audioOwner:string|null;devices:Device[];
  output:{mode:'REAL'|'VIRTUAL';connected:boolean;unknown:boolean;message:string;muted:string[]};
  service:{power?:{state:'ON'|'OFF'|'UNKNOWN'|'UNAVAILABLE';available:boolean;operation:string|null;error:string|null;reason:string|null;measured:false};busy:boolean;error:string|null;reset:{available:boolean;reason:string|null};home:{available:boolean;reason:string|null};firmware:{available:boolean;reason:string|null;port?:string|null;ports?:string[];stage?:string;flash?:string;ble?:string;progress?:number|null;error?:string|null}}
}
export interface FirmwareEvent {type:'firmware_event';seq:number;kind:'status'|'log';line?:string;stage?:string;flash?:string;ble?:string;progress?:number|null;error?:string|null}
export interface MidiLoading {name:string;stage:'stopping'|'uploading'|'planning'}
export interface FileEntry {name:string;size:number;modified:number}
interface Modulation {mode?:'off'|'sine'|'triangle';depth?:number;period?:number}
interface LabPayload {deviceId:string;hz?:number;duration?:number|null;modulation?:Modulation|null}
export interface ClientPayloads {
  play:Record<never,never>;pause:Record<never,never>;stop:Record<never,never>;
  lab_enter:Record<never,never>;lab_leave:Record<never,never>;
  set_file:{file:string};arrangement_preset:{preset:ArrangementPreset};seek:{position:number};output:{mode:'REAL'|'VIRTUAL'};
  mute:{deviceId:string;muted:boolean};speaker_waveform:{deviceId:string;waveform:SpeakerWaveform};
  speaker_volume:{deviceId:string;output:'REAL'|'VIRTUAL';value:number};
  lab_test:LabPayload;lab_update:LabPayload;lab_stop:{deviceId:string};
  service:{operation:'home'|'firmware'|'power_on'|'power_off'|'power_status'|'reset';confirmed?:boolean};
  audio_error:{epoch:number;message?:string};audio_ack:{token:string};sync:{sent:number};
}
export type ClientAction=keyof ClientPayloads
export type CommandArguments<A extends ClientAction>=keyof ClientPayloads[A] extends never?[payload?:ClientPayloads[A]]:[payload:ClientPayloads[A]]
export type ClientCommand={[A in ClientAction]:{action:A;requestId?:string|null}&ClientPayloads[A]}[ClientAction]
export type ServerMessage=
  | {type:'hello';session:string}
  | {type:'state';state:State}
  | {type:'ack';requestId?:string|null;state?:State}
  | {type:'error';requestId?:string|null;message:string}
  | {type:'sync';sent:number;serverTime:number}
  | {type:'audio';owner:string|null;epoch:number;origin:number;serverTime:number;commands:Command[]}
  | {type:'audio_cancel';owner:string|null;token:string;deviceId:string|null;epoch:number|null}
  | FirmwareEvent

function record(value:unknown):value is Record<string,unknown>{return value!==null&&typeof value==='object'&&!Array.isArray(value)}
function number(value:unknown):value is number{return typeof value==='number'&&Number.isFinite(value)}
function string(value:unknown):value is string{return typeof value==='string'}
function boolean(value:unknown):value is boolean{return typeof value==='boolean'}
function nullable<T>(check:(value:unknown)=>value is T){return (value:unknown):value is T|null=>value===null||check(value)}
function array<T>(check:(value:unknown)=>value is T){return (value:unknown):value is T[]=>Array.isArray(value)&&value.every(check)}
function optional(value:Record<string,unknown>,key:string,check:(item:unknown)=>boolean){return !(key in value)||check(value[key])}
const strings=array(string),numbers=array(number),nullableString=nullable(string),nullableNumber=nullable(number)
const outputMode=(value:unknown)=>value==='REAL'||value==='VIRTUAL'
function curve(value:unknown){return record(value)&&numbers(value.times)&&numbers(value.values)&&value.times.length===value.values.length}
function articulation(value:unknown){
  if(value===null)return true // Compiler serializes absent articulation as null.
  if(!record(value))return false
  return ['attack','decay','sustain','intensity','resonance','duration','body','click','movement'].every(key=>optional(value,key,number))&&
    optional(value,'kind',string)&&optional(value,'raw',boolean)&&optional(value,'impulses',numbers)&&
    optional(value,'gain',curve)&&optional(value,'frequency',curve)
}
function command(value:unknown):value is Command{
  return record(value)&&string(value.device_id)&&['tone','hit','stop'].includes(String(value.kind))&&
    ['time','duration','hz','velocity'].every(key=>number(value[key]))&&optional(value,'articulation',articulation)
}
function device(value:unknown):value is Device{
  return record(value)&&['id','name','type'].every(key=>string(value[key]))&&boolean(value.enabled)&&number(value.volume)&&
    array(numbers)(value.bands)&&nullableString(value.reason)&&optional(value,'labBands',array(numbers))&&
    optional(value,'realEnabled',boolean)&&optional(value,'realAmplitude',number)&&
    optional(value,'continuousRotation',boolean)&&optional(value,'waveform',wave=>wave==='pulse')
}
function availability(value:unknown){return record(value)&&boolean(value.available)&&nullableString(value.reason)}
function power(value:unknown){
  return record(value)&&availability(value)&&['ON','OFF','UNKNOWN','UNAVAILABLE'].includes(String(value.state))&&
    nullableString(value.operation)&&nullableString(value.error)&&value.measured===false
}
function labTest(value:unknown){
  return record(value)&&['hz','currentHz','depth','period','elapsed'].every(key=>number(value[key]))&&
    nullableNumber(value.duration)&&nullableNumber(value.remaining)&&['off','sine','triangle'].includes(String(value.mode))&&optional(value,'homing',boolean)
}
function dictionary(value:unknown,check:(item:unknown)=>boolean){return record(value)&&Object.values(value).every(check)}
function snapshot(value:unknown):value is State{
  if(!record(value)||!['playing','stopped','paused'].includes(String(value.state))||
    !['position','duration','epoch','revision'].every(key=>number(value[key]))||!string(value.owner)||
    !nullableString(value.file)||!nullableString(value.error)||!nullableString(value.audioOwner)||!array(device)(value.devices))return false
  const output=value.output,service=value.service
  return record(output)&&outputMode(output.mode)&&boolean(output.connected)&&boolean(output.unknown)&&string(output.message)&&strings(output.muted)&&
    record(service)&&boolean(service.busy)&&nullableString(service.error)&&availability(service.reset)&&availability(service.home)&&
    availability(service.firmware)&&record(service.firmware)&&
    ['stage','flash','ble'].every(key=>optional(service.firmware as Record<string,unknown>,key,string))&&
    optional(service.firmware,'port',nullableString)&&optional(service.firmware,'ports',strings)&&
    optional(service.firmware,'progress',nullableNumber)&&optional(service.firmware,'error',nullableString)&&optional(service,'power',power)&&
    optional(value,'arrangementPreset',isArrangementPreset)&&optional(value,'homing',boolean)&&
    optional(value,'activity',items=>dictionary(items,command))&&
    optional(value,'laboratory',items=>record(items)&&dictionary(items.active,labTest))
}
function firmware(value:Record<string,unknown>){
  return number(value.seq)&&(value.kind==='status'||value.kind==='log')&&
    ['line','stage','flash','ble'].every(key=>optional(value,key,string))&&
    optional(value,'progress',nullableNumber)&&optional(value,'error',nullableString)
}

/** Unknown future message types are ignored; malformed known messages never reach audio. */
export function parseServerMessage(text:string):ServerMessage|null{
  let value:unknown
  try{value=JSON.parse(text)}catch{throw new Error('Nieprawidłowy JSON z backendu')}
  if(!record(value)||!string(value.type))throw new Error('Nieprawidłowa wiadomość backendu')
  let valid:boolean
  switch(value.type){
    case 'hello':valid=string(value.session);break
    case 'state':valid=snapshot(value.state);break
    case 'ack':valid=optional(value,'requestId',nullableString)&&optional(value,'state',snapshot);break
    case 'error':valid=optional(value,'requestId',nullableString)&&string(value.message);break
    case 'sync':valid=number(value.sent)&&number(value.serverTime);break
    case 'audio':valid=nullableString(value.owner)&&['epoch','origin','serverTime'].every(key=>number(value[key]))&&array(command)(value.commands);break
    case 'audio_cancel':valid=nullableString(value.owner)&&string(value.token)&&nullableString(value.deviceId)&&nullableNumber(value.epoch);break
    case 'firmware_event':valid=firmware(value);break
    default:return null
  }
  if(!valid)throw new Error(`Nieprawidłowa wiadomość backendu: ${value.type}`)
  return value as ServerMessage
}

export function parseFileList(value:unknown):FileEntry[]{
  if(!array((item):item is FileEntry=>record(item)&&string(item.name)&&number(item.size)&&number(item.modified))(value))throw new Error('Nieprawidłowa lista MIDI z backendu')
  return value
}
export function parseUploadResult(value:unknown):{name:string}{
  if(!record(value)||!string(value.name))throw new Error('Nieprawidłowa odpowiedź importu MIDI')
  return {name:value.name}
}
