#pragma once
#include <stdint.h>
#include <stddef.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "hardware_profiles_generated.h"
#include "speaker_waveform.h"

namespace orchestra {
namespace map {
constexpr uint8_t fddCount=8, hostFddCount=4, registerCount=6, bitCount=registerCount*8;
constexpr uint8_t sledCount=6, hostSledCount=4, hddCount=4;
constexpr uint8_t data=23, clock=18, latch=22, oe=21, vhs=25, speakerFx=26, atx=19;
constexpr uint8_t track0[fddCount]={34,35,36,39,32,33,16,17};
constexpr uint8_t step[fddCount]={0,2,4,6,8,10,12,14}, dir[fddCount]={1,3,5,7,9,11,13,15};
constexpr uint8_t sled[sledCount][4]={{16,17,18,19},{20,21,22,23},{24,25,26,27},{28,29,30,31},{32,33,34,35},{36,37,38,39}};
constexpr uint8_t hdd[hddCount][2]={{40,41},{42,43},{44,45},{46,47}};
}
namespace fddDefaults {
// The unchanged generator/host inventory contains four existing profile entries only.
// New, disabled channels explicitly borrow FDD1's working execution parameters;
// this fallback is NOT individual hardware qualification of FDD5-8.
static_assert(sizeof(physical::fddTravel)/sizeof(physical::fddTravel[0])==map::hostFddCount,"FDD profile count changed");
static_assert(sizeof(physical::fddReversalUs)/sizeof(physical::fddReversalUs[0])==map::hostFddCount,"FDD reversal profile count changed");
static_assert(sizeof(physical::fddMinStepUs)/sizeof(physical::fddMinStepUs[0])==map::hostFddCount,"FDD STEP profile count changed");
constexpr uint8_t profileIndex(uint8_t id){return id<map::hostFddCount?id:0;}
}
namespace sledDefaults {
// The generator still owns four profiles. Unqualified DVD5-6 temporarily use
// DVD4's defaults, including ratio=1 rather than the tuner hypothesis for DVD1-3.
// Every generated-array lookup, including the frequency-band check, uses this index.
static_assert(sizeof(physical::sledTravel)/sizeof(physical::sledTravel[0])==map::hostSledCount,"DVD profile count changed");
static_assert(sizeof(physical::sledAcceleration)/sizeof(physical::sledAcceleration[0])==map::hostSledCount,"DVD acceleration count changed");
static_assert(sizeof(physical::sledPitchRatio)/sizeof(physical::sledPitchRatio[0])==map::hostSledCount,"DVD pitch ratio count changed");
static_assert(sizeof(physical::sledAllowedBandCount)/sizeof(physical::sledAllowedBandCount[0])==map::hostSledCount,"DVD band count changed");
static_assert(sizeof(physical::sledAllowedBandsHz)/sizeof(physical::sledAllowedBandsHz[0])==map::hostSledCount,"DVD band table count changed");
constexpr uint8_t profileIndex(uint8_t id){return id<map::hostSledCount?id:map::hostSledCount-1;}
}
struct IO {
 virtual ~IO() {}
 virtual uint32_t us()=0;
 virtual void delayUs(uint32_t)=0;
 virtual bool track0(uint8_t)=0;
 virtual void outputEnable(bool)=0;
 virtual void beginSPI()=0;
 // Return timestamp immediately after the latch edge, before any other work.
 virtual uint32_t frame(const uint8_t*,size_t)=0;
 virtual void atx(bool)=0;
 virtual void vhs(uint8_t,float)=0;
 virtual void vhsFx(uint8_t,float){}
 virtual void speakerWave(uint8_t,uint8_t){}
 virtual bool speakerAudioReady(){return false;}
};
struct ShiftRegisterBus {
 IO& io; uint8_t shadow[map::registerCount]={};
 explicit ShiftRegisterBus(IO& value):io(value){}
 void setBit(uint8_t bit,bool value) { if(bit<map::bitCount) {uint8_t mask=1u<<(bit%8); if(value)shadow[bit/8]|=mask;else shadow[bit/8]&=~mask;} }
 bool getBit(uint8_t bit)const {return bit<map::bitCount && (shadow[bit/8]&(1u<<(bit%8)));}
 uint32_t flush(){uint8_t bytes[map::registerCount];for(size_t i=0;i<sizeof(bytes);++i)bytes[i]=shadow[sizeof(bytes)-1-i];return io.frame(bytes,sizeof(bytes));}
 void disableOutputs(){io.outputEnable(false);}
 void enableOutputs(){io.outputEnable(true);}
 void safeState(){memset(shadow,0,sizeof(shadow));for(auto b:map::step)setBit(b,true);}
 void begin(){disableOutputs();io.beginSPI();safeState();flush();enableOutputs();}
};
inline bool due(uint32_t now,uint32_t when){return int32_t(now-when)>=0;}
struct FloppyDrive {
 uint8_t track0Pin,stepBit,dirBit; bool enabled,homed=false,playing=false,directionAway=true,homing=false;
 uint8_t awaySteps=0; uint32_t stepIntervalUs=1000,nextStepUs=0,lastStepUs=0,directionReadyUs=0,homeStartedUs=0;
 uint8_t safeAwaySteps; uint32_t reversalIntervalUs,minStepUs;
 bool hasStep=false; float hz=0; const char* error=nullptr;
 FloppyDrive(uint8_t id):track0Pin(map::track0[id]),stepBit(map::step[id]),dirBit(map::dir[id]),enabled(id<map::hostFddCount),safeAwaySteps(physical::fddTravel[fddDefaults::profileIndex(id)]),reversalIntervalUs(physical::fddReversalUs[fddDefaults::profileIndex(id)]),minStepUs(physical::fddMinStepUs[fddDefaults::profileIndex(id)]){}
 void stop(){playing=false;homing=false;hz=0;}
 void direction(bool away,ShiftRegisterBus& bus){directionAway=away;bus.setBit(dirBit,!away); uint32_t edge=bus.flush();directionReadyUs=edge+physical::fddDirSetupUs;
  if(hasStep && !due(directionReadyUs,lastStepUs+reversalIntervalUs))directionReadyUs=lastStepUs+reversalIntervalUs;}
 void home(ShiftRegisterBus& bus){stop();homed=false;error=nullptr;homing=true;direction(false,bus);homeStartedUs=bus.io.us();}
 bool play(float value,IO& io){if(!enabled||!homed||homing||!isfinite(value)||value<physical::fddProtocolMinHz||value>physical::fddProtocolMaxHz)return false;hz=value;stepIntervalUs=uint32_t(lroundf(1000000/value));if(!playing)nextStepUs=io.us();else if(uint32_t(nextStepUs-io.us())>stepIntervalUs)nextStepUs=io.us()+stepIntervalUs;playing=true;return true;}
 bool wantsStep(ShiftRegisterBus& bus){
  if(!enabled||(!playing&&!homing))return false;
  uint32_t now=bus.io.us();
  if(!directionAway && bus.io.track0(track0Pin)){
   awaySteps=0; if(homing){homing=false;homed=true;} direction(true,bus);return false;
  }
  if(homing && uint32_t(now-homeStartedUs)>=physical::fddHomeTimeoutUs){stop();homed=false;error="HOME_FAILED";return false;}
  if(playing && directionAway && awaySteps>=safeAwaySteps){direction(false,bus);return false;}
  uint32_t period=homing?physical::fddHomePeriodUs:(stepIntervalUs>minStepUs?stepIntervalUs:minStepUs);
  return due(now,directionReadyUs) && (homing||due(now,nextStepUs)) && (!hasStep||uint32_t(now-lastStepUs)>=period);
 }
 void stepped(uint32_t edge){lastStepUs=edge;hasStep=true;nextStepUs=edge+(homing?physical::fddHomePeriodUs:(stepIntervalUs>minStepUs?stepIntervalUs:minStepUs));if(!homing&&directionAway)++awaySteps;}
};
struct Bridge {
 uint8_t a,b; bool enabled; Bridge(uint8_t aa,uint8_t bb,bool on):a(aa),b(bb),enabled(on){}
 void drive(ShiftRegisterBus& bus,int direction){bus.setBit(a,direction>0);bus.setBit(b,direction<0);}
};
struct Hdd:Bridge {
 enum State {Idle,Park,Settle,Strike}; State state=Idle;uint32_t deadline=0,parkUs,settleUs,strikeUs;
 Hdd(uint8_t id):Bridge(map::hdd[id][0],map::hdd[id][1],true),parkUs(physical::hddParkUs[id]),settleUs(physical::hddSettleUs[id]),strikeUs(physical::hddStrikeUs[id]){}
 void stop(ShiftRegisterBus& bus){state=Idle;drive(bus,0);}
 bool hit(ShiftRegisterBus& bus){if(!enabled||state!=Idle)return false;state=Park;drive(bus,-1);deadline=bus.io.us()+parkUs;return true;}
 void tick(ShiftRegisterBus& bus){if(state==Idle||!due(bus.io.us(),deadline))return;if(state==Park){state=Settle;drive(bus,0);deadline=bus.io.us()+settleUs;}else if(state==Settle){state=Strike;drive(bus,1);deadline=bus.io.us()+strikeUs;}else stop(bus);}
};
struct Sled {
 static constexpr int16_t SOFT_MIN=0;
 // Relative STEP command counter, not measured physical position. No endstop:
 // softMax=0 selects continuous rotation; -1 remains unknown travel.
 // Saturating telemetry never stops an unlimited stepper or wraps its counter.
 int32_t position=0;int16_t softMax;
 uint8_t id,phase=0;bool enabled=false,playing=false,forward=true,clockStarted=false;
 uint32_t period=0,last=0;float hz=0,currentStepRate=0,targetStepRate=0,accelerationLimit,pitchRatio,fraction=0;
 Sled(uint8_t i):softMax(physical::sledTravel[sledDefaults::profileIndex(i)]),id(i),accelerationLimit(physical::sledAcceleration[sledDefaults::profileIndex(i)]),pitchRatio(physical::sledPitchRatio[sledDefaults::profileIndex(i)]){}
 void stop(ShiftRegisterBus& bus){playing=false;hz=0;currentStepRate=targetStepRate=fraction=0;clockStarted=false;for(auto b:map::sled[id])bus.setBit(b,false);}
 bool play(float value){
  if(!enabled||softMax<0||!isfinite(value)||value<=0||accelerationLimit<=0||pitchRatio<=0)return false;
  if(!physical::sledFrequencyAllowed(sledDefaults::profileIndex(id),value/pitchRatio))return false;
  double interval=1000000.0/(value/pitchRatio);
  if(interval<physical::sledMinPeriodUs||interval>2147483647)return false;
  period=uint32_t(interval);hz=value;targetStepRate=(forward?1.f:-1.f)*value/pitchRatio;playing=true;return true;
 }
 void tick(ShiftRegisterBus& bus){
  if(!playing)return;
  uint32_t now=bus.io.us();
  if(!clockStarted){last=now;clockStarted=true;return;}
  uint32_t elapsed=now-last;last=now;
  // Slow servicing cannot cause catch-up bursts. Projection loses time instead.
  float dt=float(elapsed>physical::sledRampMaxTickUs?physical::sledRampMaxTickUs:elapsed)/1000000.f;
  float speed=fabsf(currentStepRate),brake=speed*speed/(2*accelerationLimit);
  // Start braking before the endpoint; the integer counter is only a guard.
  if(softMax>0){
   if(currentStepRate>0 && softMax-position<=brake+physical::sledBrakingGuardSteps)forward=false;
   else if(currentStepRate<0 && position<=brake+physical::sledBrakingGuardSteps)forward=true;
   if(position>=softMax && currentStepRate>=0)forward=false;
   else if(position<=SOFT_MIN && currentStepRate<=0)forward=true;
  }
  targetStepRate=(forward?1.f:-1.f)*hz/pitchRatio;
  float old=currentStepRate,delta=targetStepRate-currentStepRate,change=accelerationLimit*dt;
  currentStepRate+=delta>change?change:delta<-change?-change:delta;
  if((old<0&&currentStepRate>=0)||(old>0&&currentStepRate<=0))fraction=0;
  fraction+=fabsf(currentStepRate)*dt;
  if(fraction<1.f)return;
  bool stepForward=currentStepRate>0;
  if(softMax>0&&((stepForward&&position>=softMax)||(!stepForward&&position<=SOFT_MIN))){
   currentStepRate=0;fraction=0;return; // final guard; never phase outside travel
  }
  fraction-=1.f;if(fraction>1.f)fraction=1.f;
  phase=(phase+(stepForward?1:3))%4;
  constexpr uint8_t seq[4]={5,6,10,9};
  for(int i=0;i<4;++i)bus.setBit(map::sled[id][i],seq[phase]&(1u<<i));
  if(stepForward){if(position<INT32_MAX)++position;}else if(position>INT32_MIN)--position;
 }
};
struct Controller {
 IO& io;ShiftRegisterBus bus;FloppyDrive fdd[map::fddCount]={{0},{1},{2},{3},{4},{5},{6},{7}};Hdd hdd[map::hddCount]={{0},{1},{2},{3}};Sled sled[map::sledCount]={{0},{1},{2},{3},{4},{5}};
 uint8_t vhsWave=Pulse,fxWave=Pulse;
 bool fxEnabled=false;uint8_t fxAmp=0;float fxFrequency=0;
 bool vhsEnabled=true;uint8_t amp=0;float frequency=0;uint32_t lastCommand=0;bool watchdogStopped=false;
 bool powerOn=false;
 bool strictTracks=false; int16_t strictTrack[4]={-1,-1,-1,-1};
 explicit Controller(IO& value):io(value),bus(value){}
 void begin(){powerOn=false;io.atx(false);for(auto& d:fdd){d.stop();d.homed=false;}for(auto& d:hdd)d.stop(bus);for(auto& d:sled)d.stop(bus);amp=fxAmp=0;frequency=fxFrequency=0;bus.begin();io.vhs(0,0);io.vhsFx(0,0);lastCommand=io.us();}
 void allStop(){for(auto& d:fdd)d.stop();for(auto& d:hdd)d.stop(bus);for(auto& d:sled)d.stop(bus);amp=0;frequency=0;io.vhs(0,0);fxAmp=0;fxFrequency=0;io.vhsFx(0,0);for(auto b:map::step)bus.setBit(b,true);bus.flush();}
 void tick(){
  if(uint32_t(io.us()-lastCommand)>physical::hostWatchdogUs){if(!watchdogStopped){allStop();watchdogStopped=true;}return;}
  if(!powerOn)return;
  for(auto& d:hdd)d.tick(bus);for(auto& d:sled)d.tick(bus);
  bus.flush();
  bool step[map::fddCount]={};bool any=false;
  for(int i=0;i<map::fddCount;++i){step[i]=fdd[i].wantsStep(bus);any|=step[i];}
  // Directions may have taken time to flush: each candidate must still be due.
  if(any){for(int i=0;i<map::fddCount;++i)if(step[i])bus.setBit(fdd[i].stepBit,false);
   uint32_t edge=bus.flush();for(int i=0;i<map::fddCount;++i)if(step[i])fdd[i].stepped(edge);
   io.delayUs(physical::fddStepLowUs);for(int i=0;i<map::fddCount;++i)if(step[i])bus.setBit(fdd[i].stepBit,true);bus.flush();}
 }
 // Pure parser shared with native tests. Responses are queued outside STEP generation.
 const char* command(const char* text){
  char copy[96];if(strlen(text)>=sizeof(copy))return "ERR LINE_TOO_LONG";strcpy(copy,text);
  char* args[6]={};unsigned n=0;char* save=nullptr;
  for(char* p=strtok_r(copy," ",&save);p;p=strtok_r(nullptr," ",&save)){
   if(n==6)return "ERR COMMAND";
   args[n++]=p;
  }
  if(!n)return "ERR COMMAND";lastCommand=io.us();watchdogStopped=false;
  if(!strcmp(args[0],"PING")&&n==1)return "PONG";
  if(!strcmp(args[0],"STATUS")&&n==1)return "STATUS";
  if(!strcmp(text,"ALL STOP")){allStop();return "OK";}
  if(!strcmp(text,"POWER OFF")){allStop();io.atx(false);powerOn=false;for(auto& d:fdd)d.homed=false;return "POWER OFF gpio19=0";}
  if(!strcmp(text,"POWER ON")){if(!powerOn){allStop();io.atx(true);io.delayUs(100000);bus.flush();powerOn=true;}return "POWER ON gpio19=1";}
  if(!strcmp(text,"POWER STATUS"))return powerOn?"POWER STATUS ON gpio19=1":"POWER STATUS OFF gpio19=0";

  // Host supplies MIDI provenance on every PLAY while this guard is active.
  // -1 disables a lane. Switching modes always silences the current output.
  if(!strcmp(text,"TRACKS OFF")){allStop();strictTracks=false;for(auto& t:strictTrack)t=-1;return "OK";}
  if(n==6&&!strcmp(args[0],"TRACKS")&&!strcmp(args[1],"SET")){
   int16_t tracks[4];
   for(int i=0;i<4;++i){
    char* end;long value=strtol(args[i+2],&end,10);
    if(*end||value < -1||value > 32767)return "ERR TRACK";
    for(int j=0;j<i;++j)if(value!=-1&&tracks[j]==value)return "ERR TRACK";
    tracks[i]=int16_t(value);
   }
   allStop();for(int i=0;i<4;++i)strictTrack[i]=tracks[i];strictTracks=true;return "OK";
  }
  char expanded[96];
  if(!strcmp(args[0],"PLAY")&&n==2){snprintf(expanded,96,"FDD 1 PLAY %s",args[1]);return command(expanded);}
  if(!strcmp(text,"STOP"))return command("FDD 1 STOP");
  if(!strcmp(text,"HOME"))return command("FDD 1 HOME");
  if(!strcmp(text,"HIT"))return command("HDD 1 HIT");
  if(!strcmp(text,"HDD 0"))return command("ALL STOP");
  if((!strcmp(args[0],"DRUM")||!strcmp(args[0],"DRUMF"))&&n==2){snprintf(expanded,96,"VHS %s %s",!strcmp(args[0],"DRUM")?"AMP":"FREQ",args[1]);return command(expanded);}
  if(!powerOn && (
    ((!strcmp(args[0],"VHS")||!strcmp(args[0],"VHS2")) && n>=2 && (!strcmp(args[1],"AMP")||!strcmp(args[1],"FREQ"))) ||
    !strcmp(text,"FDD ALL HOME") ||
    (n>=3 && (!strcmp(args[0],"FDD")||!strcmp(args[0],"SLED")||!strcmp(args[0],"HDD")) &&
     (!strcmp(args[2],"PLAY")||!strcmp(args[2],"HOME")||!strcmp(args[2],"HIT")))))return "ERR POWER_OFF";
  if(!strcmp(args[0],"VHS2")){
   if(n==2&&!strcmp(args[1],"STOP")){fxAmp=0;fxFrequency=0;io.vhsFx(0,0);return "OK";}
   if(strictTracks&&strcmp(text,"VHS2 ENABLE 0"))return "ERR STRICT_OUTPUT";
   if(n==3&&!strcmp(args[1],"WAVE")){int wave=speakerWaveParse(args[2]);if(wave<0||(wave!=Pulse&&fxFrequency>2000))return "ERR VALUE";fxWave=wave;io.speakerWave(1,fxWave);return "OK";}
   if(n!=3)return "ERR COMMAND";char* end;float v=strtof(args[2],&end);if(*end||!isfinite(v)||v<0)return "ERR VALUE";
   if(!strcmp(args[1],"ENABLE")&&(v==0||v==1)){fxEnabled=v==1;if(!fxEnabled){fxAmp=0;fxFrequency=0;io.vhsFx(0,0);}return "OK";}
   if(!fxEnabled)return "ERR DISABLED";
   if(!strcmp(args[1],"AMP")&&v<=255)fxAmp=uint8_t(v);else if(!strcmp(args[1],"FREQ")&&v>0&&v<=(fxWave==Pulse?20000:2000))fxFrequency=v;else return "ERR VALUE";
   io.vhsFx(fxAmp,fxFrequency);return "OK";
  }
  if(!strcmp(args[0],"VHS")){
   if(n==2&&!strcmp(args[1],"STOP")){amp=0;frequency=0;io.vhs(0,0);return "OK";}
   if(strictTracks&&strcmp(text,"VHS ENABLE 0"))return "ERR STRICT_OUTPUT";
   if(n==3&&!strcmp(args[1],"WAVE")){int wave=speakerWaveParse(args[2]);if(wave<0||(wave!=Pulse&&frequency>2000))return "ERR VALUE";vhsWave=wave;io.speakerWave(0,vhsWave);return "OK";}
   if(n!=3)return "ERR COMMAND";char* end;float v=strtof(args[2],&end);if(*end||!isfinite(v)||v<0)return "ERR VALUE";
   if(!strcmp(args[1],"ENABLE")&&(v==0||v==1)){vhsEnabled=v==1;if(!vhsEnabled){amp=0;frequency=0;io.vhs(0,0);}return "OK";}
   if(!vhsEnabled)return "ERR DISABLED";
   if(!strcmp(args[1],"AMP")&&v<=255)amp=uint8_t(v);else if(!strcmp(args[1],"FREQ")&&v<=(vhsWave==Pulse?20000:2000))frequency=v;else return "ERR VALUE";io.vhs(amp,frequency);return "OK";
  }
  if(!strcmp(text,"FDD ALL HOME")){for(auto& d:fdd)if(d.enabled)d.home(bus);return "OK";}
  if(n<3)return "ERR COMMAND";char* end;long id=strtol(args[1],&end,10);if(*end||id<1)return "ERR ID";--id;
  bool isFdd=!strcmp(args[0],"FDD"),isHdd=!strcmp(args[0],"HDD"),isSled=!strcmp(args[0],"SLED");
  if((!isFdd&&!isHdd&&!isSled)||id>=(isFdd?map::fddCount:isSled?map::sledCount:map::hddCount))return "ERR ID";
  if(strictTracks&&isFdd&&n>=4&&!strcmp(args[2],"PLAY")){
   // STRICT_TRACKS remains the unchanged four-lane host contract.
   if(id>=map::hostFddCount)return "ERR STRICT_OUTPUT";
   if(n!=6||strcmp(args[4],"TRACK"))return "ERR TRACK_REQUIRED";
   char* trackEnd;long track=strtol(args[5],&trackEnd,10);
   if(*trackEnd||track<0||track>32767||strictTrack[id]!=track)return "ERR TRACK";
  }
  if(strictTracks&&((isHdd&&n==3&&!strcmp(args[2],"HIT"))||
      (isSled&&n>=3&&!strcmp(args[2],"PLAY"))))return "ERR STRICT_OUTPUT";
  bool* enabled=isFdd?&fdd[id].enabled:isHdd?&hdd[id].enabled:&sled[id].enabled;
  if(n==3&&!strcmp(args[2],"STOP")){if(isFdd)fdd[id].stop();else if(isHdd)hdd[id].stop(bus);else sled[id].stop(bus);bus.flush();return "OK";}
  if(n==4&&!strcmp(args[2],"ENABLE")&&(!strcmp(args[3],"0")||!strcmp(args[3],"1"))){snprintf(expanded,96,"%s %ld STOP",args[0],id+1);command(expanded);*enabled=args[3][0]=='1';return "OK";}
  // Execution parameters only while stopped. SLED travel 0 explicitly selects
  // continuous rotation; unknown travel stays -1. PROFILE never moves outputs.
  if((isFdd||isSled||isHdd)&&n==6&&!strcmp(args[2],"PROFILE")){
   char* e1;char* e2;char* e3;float a=strtof(args[3],&e1),b=strtof(args[4],&e2),c=strtof(args[5],&e3);
   if(*e1||*e2||*e3||!isfinite(a)||!isfinite(b)||!isfinite(c)||b<=0||c<=0)return "ERR PROFILE";
   if(isHdd){
    if(hdd[id].state!=Hdd::Idle)return "ERR BUSY";
    if(a*1000<1||b*1000<1||c*1000<1||a*1000>2147483647.f||b*1000>2147483647.f||c*1000>2147483647.f)return "ERR PROFILE";
    hdd[id].parkUs=uint32_t(lroundf(a*1000));hdd[id].settleUs=uint32_t(lroundf(b*1000));hdd[id].strikeUs=uint32_t(lroundf(c*1000));
   }else if(isFdd){
    if(fdd[id].playing||fdd[id].homing)return "ERR BUSY";
    if(a<1||a>255||a!=floorf(a)||b>2147483647.f||c>2147483647.f)return "ERR PROFILE";
    fdd[id].safeAwaySteps=uint8_t(a);fdd[id].reversalIntervalUs=uint32_t(b);fdd[id].minStepUs=uint32_t(c);
   }else{
    if(sled[id].playing)return "ERR BUSY";
    if((a!=-1&&(a<0||a>32767||a!=floorf(a)))||(a>0&&(sled[id].position>a||sled[id].position<0)))return "ERR PROFILE";
    sled[id].softMax=int16_t(a);sled[id].accelerationLimit=b;sled[id].pitchRatio=c;
   }
   return "OK";
  }
  if(!*enabled)return "ERR DISABLED";
  if(isFdd&&n==3&&!strcmp(args[2],"HOME")){fdd[id].home(bus);return "OK";}
  if(isHdd&&n==3&&!strcmp(args[2],"HIT")){bool ok=hdd[id].hit(bus);bus.flush();return ok?"OK":"ERR BUSY";}
  if((isFdd||isSled)&&(n==4||(strictTracks&&isFdd&&n==6))&&!strcmp(args[2],"PLAY")){float value=strtof(args[3],&end);if(*end||!isfinite(value))return "ERR VALUE";bool ok=isFdd?fdd[id].play(value,io):sled[id].play(value);if(isSled&&sled[id].softMax<0)return "ERR TRAVEL_UNKNOWN";return ok?"OK":isFdd&&!fdd[id].homed?"ERR NOT_HOMED":"ERR VALUE";}
  if(isSled&&n==4&&!strcmp(args[2],"DIR")&&(!strcmp(args[3],"FWD")||!strcmp(args[3],"REV"))){sled[id].forward=!strcmp(args[3],"FWD");return "OK";}
  return "ERR COMMAND";
 }
};
}
