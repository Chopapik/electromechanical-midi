/** Procedural mechanical preview, synthesized in the browser, not recorded calibration.
 * STEP impulses excite short chassis modes; VCM hits reuse the repository's impact model.
 */
export interface MechanicalArticulation {
  intensity?:number; resonance?:number; decay?:number; body?:number; click?:number;
  movement?:number; impulses?:number[]; raw?:boolean;
  frequency?:{times:number[];values:number[]}
}
function seedFor(id:string){let seed=2166136261;for(const c of id)seed=Math.imul(seed^c.charCodeAt(0),16777619);return seed>>>0}
export function mechanicalSamples(type:string,_id:string,hz:number,duration:number,rate:number,art:MechanicalArticulation={}):Float32Array {
  const out=new Float32Array(Math.max(1,Math.ceil(duration*rate)))
  // All units in a family share one acoustic signature; no invented unit variation.
  const seed=seedFor(type),variation=0
  let random=seed||1
  const noise=()=>{random^=random<<13;random^=random>>>17;random^=random<<5;return (random>>>0)/2147483648-1}
  if(type==='HDD_VCM'||type==='DVD_TRAY'){
    const decay=Math.max(.001,art.decay??.017),resonance=(art.resonance??290)*(1+variation)
    const impulses=art.impulses??[0],phase=(seed%97)*.065
    for(let n=0;n<out.length;n++){
      const t=n/rate;let sample=0
      for(let i=0;i<impulses.length;i++){
        const age=t-impulses[i];if(age<0||age>.2)continue
        const click=Math.exp(-age/.0013)*(Math.sin(age*2*Math.PI*(2100+seed%250)+phase)+.45*Math.sin(age*2*Math.PI*3713+.7)+.3*noise())
        const chassis=Math.exp(-age/decay)*(Math.sin(age*2*Math.PI*resonance)+.24*Math.sin(age*2*Math.PI*resonance*2.73))
        const body=Math.exp(-age/(decay*.75))*Math.sin(age*2*Math.PI*(112+variation*80))
        const movement=Math.exp(-age/.004)*Math.sin(age*2*Math.PI*877+phase)*Math.sin(age*2*Math.PI*1331)
        const layer=art.raw?click*.75:(art.click??.8)*click+(art.body??.18)*(chassis+.35*body)+(art.movement??.14)*movement
        sample+=(i%2===0?1:-.85)*layer/(1+i*.15)
      }
      out[n]=sample*.8
    }
  } else {
    // Family constants are acoustic estimates, independent of mechanical safety profiles.
    const dvd=type==='DVD_SLED',modes=dvd?[1300,2170,3190]:[900,2300,3710]
    const decays=dvd?[.0028,.0014,.0007]:[.0018,.0009,.0005]
    const states=modes.map((f,i)=>({real:0,imag:0,cos:Math.cos(2*Math.PI*f*(1+variation)/rate)*Math.exp(-1/(rate*decays[i])),sin:Math.sin(2*Math.PI*f*(1+variation)/rate)*Math.exp(-1/(rate*decays[i]))}))
    const transientDecay=Math.exp(-1/(rate*.0006)),weights=[.65,.27,.14],excitation=[1,.5,.23]
    const curve=art.frequency;let segment=0,phase=1,transient=0,previous=0,dc=0
    for(let n=0;n<out.length;n++){
      const t=n/rate;let frequency=hz
      if(curve?.times.length){
        while(segment+1<curve.times.length&&curve.times[segment+1]<=t)segment++
        const next=Math.min(segment+1,curve.times.length-1)
        const fraction=next===segment?0:Math.max(0,Math.min(1,(t-curve.times[segment])/(curve.times[next]-curve.times[segment])))
        frequency=curve.values[segment]+fraction*(curve.values[next]-curve.values[segment])
      }
      const impulses=Math.floor(phase);phase-=impulses;phase+=Math.max(1,frequency)/rate
      if(impulses){for(let i=0;i<states.length;i++)states[i].real+=impulses*excitation[i];transient=1}
      let sample=0
      for(let i=0;i<states.length;i++){const s=states[i],re=s.real*s.cos-s.imag*s.sin;s.imag=s.real*s.sin+s.imag*s.cos;s.real=re;sample+=s.imag*weights[i]}
      sample+=transient*noise()*(dvd?.06:.12);transient*=transientDecay
      // Small periodic actuator body under the sharper impacts. Remove DC, not pitch.
      sample+=.10*Math.sin(2*Math.PI*phase)
      dc=.995*(dc+sample-previous);previous=sample
      out[n]=Math.tanh(dc*.8)
    }
  }
  // Only edge de-clicking. Continuous STEP stays audible throughout its planned gate.
  for(let n=0;n<out.length;n++)out[n]*=Math.min(1,n/(rate*.001),(out.length-1-n)/(rate*.003))
  return out
}
