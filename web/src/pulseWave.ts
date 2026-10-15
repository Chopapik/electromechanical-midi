/** AC pulse Fourier series; duty is the same 8-bit PWM value used by ESP32. */
export function pulseCoefficients(amplitude:number,harmonics=64){
  const duty=Math.max(0,Math.min(128,amplitude))/256
  const real=new Float32Array(harmonics+1),imag=new Float32Array(harmonics+1)
  for(let n=1;n<=harmonics;n++){
    real[n]=2*Math.sin(2*Math.PI*n*duty)/(Math.PI*n)
    imag[n]=2*(1-Math.cos(2*Math.PI*n*duty))/(Math.PI*n)
  }
  return {real,imag}
}

export type SpeakerWaveform='pulse'|'sine'|'triangle'|'sawtooth'
export function waveformPoints(waveform:SpeakerWaveform,amplitude:number){
 const duty=amplitude/256
 if(amplitude===0)return '0,32 200,32'
 if(waveform==='pulse')return `0,8 ${duty*100},8 ${duty*100},32 100,32 100,8 ${100+duty*100},8 ${100+duty*100},32 200,32`
 return Array.from({length:129},(_,i)=>{
  const phase=(i/64)%1
  const sample=waveform==='sine'?Math.sin(2*Math.PI*phase):waveform==='triangle'?1-4*Math.abs(phase-.5):2*phase-1
  return `${i/128*200},${20-sample*12}`
 }).join(' ')
}
