import {describe,it,expect} from 'vitest'
import {mechanicalSamples} from './mechanicalAudio'
const rate=48000
const rms=(x:Float32Array,start=0,end=x.length)=>Math.sqrt(x.slice(start,end).reduce((sum,v)=>sum+v*v,0)/(end-start))
const energy=(x:Float32Array,hz:number)=>{let re=0,im=0;for(let n=0;n<x.length;n++){const angle=2*Math.PI*hz*n/rate;re+=x[n]*Math.cos(angle);im+=x[n]*Math.sin(angle)}return re*re+im*im}
describe('Procedural mechanical sound',()=>{
 it('is deterministic, finite and declicked at both edges',()=>{
  const a=mechanicalSamples('FDD','fdd-1',220,.25,rate)
  expect(a).toEqual(mechanicalSamples('FDD','fdd-1',220,.25,rate))
  expect(a.every(Number.isFinite)).toBe(true);expect(a[0]).toBe(0);expect(Math.abs(a[a.length-1])).toBe(0)
 })
 it('gives every unit of the same family exactly the same samples',()=>{
  for(const type of ['FDD','DVD_SLED','HDD_VCM'])expect(mechanicalSamples(type,'unit-1',220,.1,rate)).toEqual(mechanicalSamples(type,'unit-4',220,.1,rate))
 })
 it('keeps STEP pitch and sustained impacts instead of decaying like a plucked synth',()=>{
  const a=mechanicalSamples('FDD','fdd-1',220,.5,rate)
  expect(energy(a,220)).toBeGreaterThan(energy(a,227)*8)
  expect(rms(a,12000,18000)/rms(a,2400,8400)).toBeGreaterThan(.8)
 })
 it('gives FDD and DVD distinct chassis spectra for the same note',()=>{
  const fdd=mechanicalSamples('FDD','unit',220,.5,rate),dvd=mechanicalSamples('DVD_SLED','unit',220,.5,rate)
  expect(fdd).not.toEqual(dvd)
  expect(energy(fdd,880)/energy(fdd,1320)).toBeGreaterThan(energy(dvd,880)/energy(dvd,1320))
 })
 it('renders HDD double taps at the planned impulse times with short decay',()=>{
  const single=mechanicalSamples('HDD_VCM','hdd-1',0,.12,rate,{impulses:[0],decay:.004,body:.1})
  const double=mechanicalSamples('HDD_VCM','hdd-1',0,.12,rate,{impulses:[0,.025],decay:.004,body:.1})
  expect(rms(double,1200,1440)).toBeGreaterThan(rms(single,1200,1440)*10)
  expect(rms(double,4800,5400)).toBeLessThan(rms(double,1200,1440)*.02)
 })
 it('uses planned pitch bend curves in the mechanical excitation',()=>{
  const steady=mechanicalSamples('FDD','fdd-1',220,.5,rate)
  const bent=mechanicalSamples('FDD','fdd-1',220,.5,rate,{frequency:{times:[0,.25,.5],values:[220,440,440]}})
  expect(energy(bent.slice(12000),440)).toBeGreaterThan(energy(steady.slice(12000),440)*2)
 })
})
