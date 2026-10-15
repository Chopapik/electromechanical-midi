import {describe,it,expect} from 'vitest'
import {pulseCoefficients} from './pulseWave'
function sample(amplitude:number,phase:number){
 const {real,imag}=pulseCoefficients(amplitude)
 return Array.from(real).reduce((sum,a,n)=>sum+a*Math.cos(2*Math.PI*n*phase)+imag[n]*Math.sin(2*Math.PI*n*phase),0)
}
describe('shared PWM pulse',()=>{
 it('has the intended high/low proportions at the same duty as REAL',()=>{
  for(const amp of [26,50,128]){
   const duty=amp/256
   expect(sample(amp,duty/2)).toBeCloseTo(2*(1-duty),1)
   expect(sample(amp,.7)).toBeCloseTo(-2*duty,1)
  }
 })
 it('50 percent is a square wave with only odd harmonics and no DC',()=>{
  const {real,imag}=pulseCoefficients(128)
  expect(real[0]).toBe(0);expect(imag[0]).toBe(0)
  for(let n=1;n<64;n++){
   expect(real[n]).toBeCloseTo(0,6)
   expect(imag[n]).toBeCloseTo(n%2?4/(Math.PI*n):0,6)
  }
 })
 it('zero duty has no AC signal',()=>{
  const {real,imag}=pulseCoefficients(0)
  expect([...real,...imag].every(v=>v===0)).toBe(true)
 })
})
