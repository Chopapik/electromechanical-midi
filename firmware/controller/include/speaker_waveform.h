#pragma once
#include <stdint.h>
#include <math.h>
#include <string.h>
namespace orchestra {
enum SpeakerWave:uint8_t {Pulse=0,Sine=1,Triangle=2,Sawtooth=3};
inline const char* speakerWaveName(uint8_t wave){return wave==Sine?"sine":wave==Triangle?"triangle":wave==Sawtooth?"sawtooth":"pulse";}
inline int speakerWaveParse(const char* name){for(int i=0;i<4;++i)if(!strcmp(name,speakerWaveName(i)))return i;return -1;}
struct SpeakerOscillator {
 uint8_t amp=0,wave=Pulse;float hz=0,phase=0;uint32_t last=0;
 uint8_t sample(uint32_t now){
  uint32_t elapsed=now-last;last=now;
  if(!amp||hz<=0)return 0;
  // Integrate wall time, never replay late samples or emit catch-up bursts.
  phase+=hz*(elapsed/1000000.f);phase-=floorf(phase);
  float value=wave==Sine?sinf(phase*6.28318530718f):wave==Triangle?1.f-4.f*fabsf(phase-.5f):2.f*phase-1.f;
  // Maintain commanded mean duty, not a claim about measured coil current.
  // No new peak GPIO voltage is introduced.
  float duty=amp*(1.f+value);
  return uint8_t(duty<0?0:duty>255?255:duty+.5f);
 }
};
}
