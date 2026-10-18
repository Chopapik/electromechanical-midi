#pragma once
#include <stdint.h>
#include <string.h>
namespace orchestra {
// Pulse-only protocol compatibility; both speakers use hardware LEDC PWM.
enum SpeakerWave:uint8_t {Pulse=0};
inline const char* speakerWaveName(uint8_t){return "pulse";}
inline int speakerWaveParse(const char* name){return !strcmp(name,"pulse")?Pulse:-1;}
}
