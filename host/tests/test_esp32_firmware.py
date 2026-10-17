"""Run the production ESP32 core offline with a latch/GPIO/clock simulator."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = r'''
#include "orchestra_core.h"
#include <cassert>
#include <vector>
#include <string>
#include <array>
using namespace orchestra;
struct Fake: IO {
 bool atxOn=false;std::vector<bool> powerWrites;
 void atx(bool on)override{atxOn=on;powerWrites.push_back(on);}
 uint8_t fxAmp=0;float fxHz=0;
 uint32_t now=10000;bool active[8]={};bool outputs=false;uint64_t previous=0;
 std::vector<std::pair<uint32_t,uint64_t>> edges;
 std::vector<std::string> boot;std::vector<std::array<uint8_t,6>> bytes;
 uint32_t us()override{return now;}
 void delayUs(uint32_t n)override{now+=n;}
 bool track0(uint8_t pin)override{for(int i=0;i<8;++i)if(pin==map::track0[i])return active[i];assert(false);return false;}
 void outputEnable(bool on)override{outputs=on;boot.push_back(on?"on":"off");}
 void beginSPI()override{boot.push_back("spi");}
 uint32_t frame(const uint8_t* b,size_t n)override{
  assert(n==6);std::array<uint8_t,6> copy;uint64_t bits=0;
  for(int i=0;i<6;++i){copy[i]=b[i];bits=(bits<<8)|b[i];}
  bytes.push_back(copy);now+=53;edges.push_back({now,bits});boot.push_back("frame");previous=bits;return now;
 }
 void vhs(uint8_t,float)override{}
 void vhsFx(uint8_t amp,float hz)override{fxAmp=amp;fxHz=hz;}
};
int main(int argc,char** argv){
 std::string c=argv[1];Fake io;Controller d(io);d.begin();if(c!="boot"&&c!="power")d.command("POWER ON");
 auto runFor=[&](uint32_t time){uint32_t start=io.now;while(uint32_t(io.now-start)<time){io.now+=100;d.lastCommand=io.now;d.tick();}};
 auto nextPhase=[&](int id){auto& s=d.sled[id];int phase=s.phase;for(int n=0;n<10000&&s.phase==phase;++n){io.now+=100;d.lastCommand=io.now;d.tick();}assert(s.phase!=phase);};
 if(c=="power"){
  assert(map::atx==19&&!d.powerOn&&!io.atxOn&&io.powerWrites.front()==false);
  const char* blocked[]={"HOME","PLAY 220","HIT","DRUM 50","DRUMF 220","FDD ALL HOME","FDD 8 HOME","FDD 1 PLAY 220","SLED 6 PLAY 220","HDD 4 HIT","VHS AMP 50","VHS FREQ 220","VHS2 AMP 50","VHS2 FREQ 830"};
  for(auto text:blocked)assert(!strcmp(d.command(text),"ERR POWER_OFF"));
  assert(!strcmp(d.command("POWER STATUS"),"POWER STATUS OFF gpio19=0"));
  assert(!strcmp(d.command("POWER ON"),"POWER ON gpio19=1"));assert(d.powerOn&&io.atxOn);
  assert(!strcmp(d.command("POWER STATUS"),"POWER STATUS ON gpio19=1"));
  for(auto& f:d.fdd){f.enabled=true;f.homed=true;f.play(220,io);}
  for(auto& l:d.sled){l.enabled=true;l.play(220);}
  for(auto& h:d.hdd)h.hit(d.bus);
  d.command("VHS AMP 50");d.command("VHS FREQ 220");
  d.command("VHS2 ENABLE 1");d.command("VHS2 AMP 50");d.command("VHS2 FREQ 830");
  assert(!strcmp(d.command("POWER OFF"),"POWER OFF gpio19=0"));
  for(auto& f:d.fdd)assert(!f.playing&&!f.homing);for(auto& l:d.sled)assert(!l.playing);for(auto& h:d.hdd)assert(h.state==Hdd::Idle);
  assert(!d.powerOn&&!io.atxOn&&!d.amp&&!d.fxAmp&&(io.previous&0xffffffff0000ULL)==0);
  assert(!strcmp(d.command("ALL STOP"),"OK"));assert(!strcmp(d.command("POWER OFF"),"POWER OFF gpio19=0"));
  d.command("POWER ON");d.command("FDD ALL HOME");d.begin();
  assert(!d.powerOn&&!io.atxOn);for(auto& f:d.fdd)assert(!f.homing&&!f.playing);
  d.command("POWER ON");io.now+=3000001;d.tick();assert(d.powerOn&&io.atxOn&&d.watchdogStopped);
 }else if(c=="map"){
  std::vector<int> used;for(auto b:map::step)used.push_back(b);for(auto b:map::dir)used.push_back(b);
  for(auto& group:map::sled)for(auto b:group)used.push_back(b);
  for(auto& group:map::hdd)for(auto b:group)used.push_back(b);
  assert(used.size()==48);
  bool seen[48]={};for(int b:used){assert(b<48&&!seen[b]);seen[b]=true;}for(bool assigned:seen)assert(assigned);
  for(int bit=0;bit<48;++bit){for(int b=0;b<48;++b)d.bus.setBit(b,b==bit);d.bus.flush();assert(io.previous==(uint64_t(1)<<bit));for(int b=0;b<48;++b)assert(d.bus.getBit(b)==(b==bit));}
  const uint8_t expectedTrack[8]={34,35,36,39,32,33,16,17};
  for(int i=0;i<8;++i){assert(map::track0[i]==expectedTrack[i]);assert(map::step[i]==2*i&&map::dir[i]==2*i+1);}
  for(int i=0;i<6;++i)for(int j=0;j<4;++j)assert(map::sled[i][j]==16+4*i+j);
  for(int i=0;i<4;++i)for(int j=0;j<2;++j)assert(map::hdd[i][j]==40+2*i+j);
  uint64_t last=io.previous;d.bus.setBit(48,true);d.bus.setBit(255,true);d.bus.flush();assert(io.previous==last&&!d.bus.getBit(48)&&!d.bus.getBit(255));
 }else if(c=="boot"){
  assert(io.boot[0]=="off"&&io.boot[1]=="spi"&&io.boot[2]=="frame"&&io.boot[3]=="on");
  assert(io.previous==0x5555&&io.outputs);for(auto& f:d.fdd)assert(!f.playing&&!f.homing&&!f.homed);
  for(auto& s:d.sled)assert(!s.enabled);
  const std::array<uint8_t,6> expected={{0,0,0,0,0x55,0x55}};assert(io.bytes.front()==expected);
  for(int i=0;i<8;++i)assert(d.fdd[i].enabled==(i<4));
  auto bootBits=io.previous;io.now+=100000;d.tick();assert(io.previous==bootBits);
  assert(!d.powerOn&&!io.atxOn&&io.powerWrites.front()==false);d.command("POWER ON");
  d.command("FDD ALL HOME");for(int i=0;i<8;++i)assert(d.fdd[i].homing==(i<4));
  d.command("ALL STOP");for(auto& f:d.fdd)assert(!f.homing&&!f.playing&&!f.homed);
 }else if(c=="home"){
  d.command("FDD 1 HOME");assert(d.fdd[0].homing&&!d.fdd[1].homing);
  io.now+=6000;d.tick();assert(!d.fdd[0].homed);
  io.active[0]=true;d.tick();assert(d.fdd[0].homed&&d.fdd[0].directionAway&&d.fdd[0].awaySteps==0);
 }else if(c=="extended_fdd"){
  for(int i=4;i<8;++i){
   auto& f=d.fdd[i];assert(!f.enabled&&!f.homed&&!f.homing);
   assert(f.safeAwaySteps==physical::fddTravel[0]&&f.reversalIntervalUs==physical::fddReversalUs[0]&&f.minStepUs==physical::fddMinStepUs[0]);
   char cmd[80];snprintf(cmd,sizeof(cmd),"FDD %d HOME",i+1);assert(!strcmp(d.command(cmd),"ERR DISABLED"));
   snprintf(cmd,sizeof(cmd),"FDD %d PLAY 220",i+1);assert(!strcmp(d.command(cmd),"ERR DISABLED"));
   snprintf(cmd,sizeof(cmd),"FDD %d ENABLE 1",i+1);assert(!strcmp(d.command(cmd),"OK"));assert(!f.homing&&!f.homed);
   snprintf(cmd,sizeof(cmd),"FDD %d PLAY 220",i+1);assert(!strcmp(d.command(cmd),"ERR NOT_HOMED"));
   snprintf(cmd,sizeof(cmd),"FDD %d HOME",i+1);assert(!strcmp(d.command(cmd),"OK"));io.active[i]=true;d.tick();assert(f.homed&&!f.homing&&f.awaySteps==0);io.active[i]=false;
   snprintf(cmd,sizeof(cmd),"FDD %d PROFILE 60 18000 3000",i+1);assert(!strcmp(d.command(cmd),"OK"));assert(f.safeAwaySteps==60&&f.reversalIntervalUs==18000&&f.minStepUs==3000);
   snprintf(cmd,sizeof(cmd),"FDD %d PLAY 220",i+1);assert(!strcmp(d.command(cmd),"OK"));runFor(30000);assert(f.playing&&f.awaySteps>0);
   snprintf(cmd,sizeof(cmd),"FDD %d ENABLE 0",i+1);assert(!strcmp(d.command(cmd),"OK"));assert(!f.enabled&&!f.playing);
   for(int j=0;j<4;++j)assert(!d.fdd[j].homing&&!d.fdd[j].playing&&d.fdd[j].safeAwaySteps==physical::fddTravel[j]);
  }
  assert(!strcmp(d.command("FDD 9 HOME"),"ERR ID"));assert(!strcmp(d.command("FDD 0 HOME"),"ERR ID"));
  assert(!strcmp(d.command("HDD 5 HIT"),"ERR ID"));assert(!strcmp(d.command("SLED 7 PLAY 220"),"ERR ID"));
 }else if(c=="extended_stop"){
  for(auto& f:d.fdd){f.enabled=true;f.homed=true;assert(f.play(220,io));}
  d.command("SLED 4 ENABLE 1");d.command("SLED 4 PLAY 220");d.command("HDD 4 HIT");d.command("VHS AMP 50");d.command("VHS2 ENABLE 1");d.command("VHS2 AMP 50");d.command("VHS2 FREQ 830");
  runFor(20000);assert((io.previous&0xffff00000000ULL)!=0);
  d.command("ALL STOP");for(auto& f:d.fdd)assert(!f.playing&&!f.homing);
  for(auto& h:d.hdd)assert(h.state==Hdd::Idle);for(auto& l:d.sled)assert(!l.playing);
  assert(io.previous==0x5555&&d.amp==0&&io.fxAmp==0);
  for(int i=4;i<8;++i){d.fdd[i].homed=false;char cmd[40];snprintf(cmd,sizeof(cmd),"FDD %d HOME",i+1);d.command(cmd);}
  d.command("ALL STOP");for(auto& f:d.fdd)assert(!f.homing);
  for(int i=4;i<8;++i){d.fdd[i].homed=true;assert(d.fdd[i].play(220,io));}
  d.bus.setBit(47,true);io.now+=3000001;d.tick();for(auto& f:d.fdd)assert(!f.playing&&!f.homing);assert((io.previous&0xff0000000000ULL)==0);
 }else if(c=="extended_strict"){
  d.command("FDD 8 ENABLE 1");d.fdd[7].homed=true;
  d.command("TRACKS SET 3 1 4 8");
  assert(!strcmp(d.command("FDD 8 PLAY 220"),"ERR STRICT_OUTPUT"));
  assert(!strcmp(d.command("FDD 8 PLAY 220 TRACK 3"),"ERR STRICT_OUTPUT"));assert(!d.fdd[7].playing);
  d.command("TRACKS OFF");assert(!strcmp(d.command("FDD 8 PLAY 220"),"OK"));
 }else if(c=="home_timeout"){
  d.command("HOME");io.now+=2000001;d.lastCommand=io.now;d.tick();assert(!d.fdd[0].homed&&!d.fdd[0].homing);assert(!strcmp(d.fdd[0].error,"HOME_FAILED"));
 }else if(c=="parallel"){
  for(auto& f:d.fdd){f.enabled=true;f.homed=true;assert(f.play(410,io));}
  size_t n=io.edges.size();d.tick();assert(io.edges.size()==n+3);assert((io.edges[n+1].second&0x5555)==0);assert((io.edges[n+2].second&0x5555)==0x5555);
  for(auto& f:d.fdd)assert(f.awaySteps==1&&f.lastStepUs==d.fdd[0].lastStepUs);
 }else if(c=="independent"){
  d.fdd[0].homed=true;d.fdd[0].play(130,io);d.fdd[1].homed=true;d.fdd[1].play(410,io);
  for(int i=0;i<50;++i){io.now+=200;d.tick();}assert(d.fdd[1].awaySteps>d.fdd[0].awaySteps);assert(!d.fdd[2].playing&&d.fdd[2].awaySteps==0);
 }else if(c=="away"){
  auto& f=d.fdd[0];f.homed=true;f.play(410,io);
  for(int i=0;i<72;++i){io.now+=6000;d.lastCommand=io.now;d.tick();}assert(f.awaySteps==72&&f.directionAway);
  d.tick();assert(!f.directionAway);for(int i=0;i<500;++i){io.now+=6000;d.lastCommand=io.now;d.tick();}assert(f.playing&&f.awaySteps==72&&!f.error);
  io.active[0]=true;d.tick();assert(f.directionAway&&f.awaySteps==0&&f.playing);
 }else if(c=="timing"){
  auto& f=d.fdd[0];f.homed=true;f.play(410,io);f.awaySteps=70;
  for(int i=0;i<300;++i){io.now+=100;d.tick();if(i==70){f.stop();f.play(410,io);}if(i==110)io.active[0]=true;if(i==160)io.active[0]=false;}
  uint32_t last=0;bool high=true;int count=0;for(auto e:io.edges){bool next=e.second&1;if(high&&!next){if(last)assert(e.first-last>=2439);last=e.first;++count;}high=next;}assert(count>3);
 }else if(c=="continuous_pitch"){
  auto& f=d.fdd[0];f.homed=true;d.command("FDD 1 PLAY 220");
  uint32_t start=io.now;
  while(io.now-start<180000){io.now+=100;d.tick();}
  bool high=true;uint32_t last=0;int count=0;
  for(auto e:io.edges){bool next=e.second&1;if(high&&!next){
   if(last){assert(e.first-last>=4545);assert(e.first-last<5000);}
   last=e.first;++count;
  }high=next;}
  assert(count>=35&&count<=40);assert(f.playing&&f.awaySteps==count);
 }else if(c=="hdd"){
  assert(!strcmp(d.command("HDD 4 HIT"),"OK"));assert(d.hdd[3].state==Hdd::Park&&d.hdd[0].state==Hdd::Idle);
  io.now+=40000;d.tick();assert(d.hdd[3].state==Hdd::Settle);io.now+=40000;d.tick();assert(d.hdd[3].state==Hdd::Strike);io.now+=4000;d.tick();assert(d.hdd[3].state==Hdd::Idle);
 }else if(c=="sled"){
  assert(!strcmp(d.command("SLED 2 PLAY 220"),"ERR DISABLED"));d.command("SLED 2 ENABLE 1");
  d.command("SLED 2 PROFILE -1 5000 1");assert(!strcmp(d.command("SLED 2 PLAY 220"),"ERR TRAVEL_UNKNOWN"));
  assert(!strcmp(d.command("SLED 2 PROFILE 140 5000 1"),"OK"));d.command("SLED 2 PLAY 220");
  int expected[4]={6,10,9,5};for(int p:expected){nextPhase(1);assert(((io.previous>>20)&15)==p);}
  d.command("SLED 2 STOP");assert(((io.previous>>20)&15)==0);
  d.command("SLED 2 DIR REV");d.command("SLED 2 PLAY 220");nextPhase(1);assert(((io.previous>>20)&15)==9);
 }else if(c=="six_sleds"){
  assert(sizeof(d.sled)/sizeof(d.sled[0])==6&&sizeof(d.hdd)/sizeof(d.hdd[0])==4);
  for(int i=0;i<6;++i)assert(sledDefaults::profileIndex(i)==(i<4?i:3));
  for(int i=4;i<6;++i){
   auto& s=d.sled[i];assert(!s.enabled&&!s.playing&&s.softMax==physical::sledTravel[3]);
   assert(s.accelerationLimit==physical::sledAcceleration[3]&&s.pitchRatio==physical::sledPitchRatio[3]&&s.pitchRatio==1);
   char cmd[80];snprintf(cmd,sizeof(cmd),"SLED %d PLAY 220",i+1);assert(!strcmp(d.command(cmd),"ERR DISABLED"));
   snprintf(cmd,sizeof(cmd),"SLED %d ENABLE 1",i+1);assert(!strcmp(d.command(cmd),"OK")&&!s.playing);
   snprintf(cmd,sizeof(cmd),"SLED %d PLAY 220",i+1);assert(!strcmp(d.command(cmd),"OK"));
   nextPhase(i);assert(s.position==1&&s.currentStepRate>0);assert(((io.previous>>(16+4*i))&15)==6);
   // All profile-indexed bands use the fallback too; higher timer rates still reject.
   snprintf(cmd,sizeof(cmd),"SLED %d PLAY 10001",i+1);assert(!strcmp(d.command(cmd),"ERR VALUE"));
   snprintf(cmd,sizeof(cmd),"SLED %d STOP",i+1);d.command(cmd);assert(((io.previous>>(16+4*i))&15)==0);
   snprintf(cmd,sizeof(cmd),"SLED %d PROFILE -1 5000 1",i+1);assert(!strcmp(d.command(cmd),"OK"));
   snprintf(cmd,sizeof(cmd),"SLED %d PLAY 220",i+1);assert(!strcmp(d.command(cmd),"ERR TRAVEL_UNKNOWN"));
   snprintf(cmd,sizeof(cmd),"SLED %d PROFILE 0 5000 2",i+1);assert(!strcmp(d.command(cmd),"OK"));
   snprintf(cmd,sizeof(cmd),"SLED %d DIR REV",i+1);d.command(cmd);
   snprintf(cmd,sizeof(cmd),"SLED %d PLAY 440",i+1);assert(!strcmp(d.command(cmd),"OK")&&s.targetStepRate==-220);nextPhase(i);assert(s.position==0&&!s.forward);
   snprintf(cmd,sizeof(cmd),"SLED %d PROFILE 0 1000 1",i+1);assert(!strcmp(d.command(cmd),"ERR BUSY"));
   snprintf(cmd,sizeof(cmd),"SLED %d ENABLE 0",i+1);d.command(cmd);assert(!s.playing&&!s.enabled&&((io.previous>>(16+4*i))&15)==0);
  }
  for(int i=0;i<4;++i)assert(!d.sled[i].playing&&d.sled[i].position==0);
  assert((io.previous>>40)==0); // no unintended HDD bridge activity
  d.command("SLED 6 ENABLE 1");d.command("TRACKS SET 1 2 3 4");assert(!strcmp(d.command("SLED 6 PLAY 220"),"ERR STRICT_OUTPUT"));
  assert(!strcmp(d.command("SLED 7 STOP"),"ERR ID"));assert(!strcmp(d.command("HDD 5 STOP"),"ERR ID"));
 }else if(c=="all_actuators_stop"){
  auto startAll=[&](){
   for(auto& f:d.fdd){f.enabled=true;f.homed=true;assert(f.play(220,io));}
   for(int i=0;i<6;++i){char cmd[40];snprintf(cmd,sizeof(cmd),"SLED %d ENABLE 1",i+1);d.command(cmd);snprintf(cmd,sizeof(cmd),"SLED %d PLAY 220",i+1);assert(!strcmp(d.command(cmd),"OK"));}
   for(int i=0;i<4;++i){char cmd[40];snprintf(cmd,sizeof(cmd),"HDD %d HIT",i+1);assert(!strcmp(d.command(cmd),"OK"));}
   d.command("VHS AMP 50");d.command("VHS FREQ 440");d.command("VHS2 ENABLE 1");d.command("VHS2 AMP 50");d.command("VHS2 FREQ 830");runFor(20000);
  };
  auto stopped=[&](){for(auto& f:d.fdd)assert(!f.playing&&!f.homing);for(auto& s:d.sled)assert(!s.playing&&s.currentStepRate==0);for(auto& h:d.hdd)assert(h.state==Hdd::Idle);assert(io.previous==0x5555&&d.amp==0&&io.fxAmp==0);};
  startAll();assert((io.previous>>40)!=0);d.command("SLED 5 STOP");assert(!d.sled[4].playing&&d.sled[5].playing&&((io.previous>>32)&15)==0);
  d.command("ALL STOP");stopped();
  startAll();io.now+=3000001;d.tick();stopped();
  io.now+=1000;d.tick();stopped(); // no late restart
 }else if(c=="sled_forward"){
  d.command("SLED 1 ENABLE 1");d.command("SLED 1 DIR FWD");d.command("SLED 1 PLAY 280");
  auto& s=d.sled[0];assert(s.position==0);nextPhase(0);assert(s.position==1&&s.forward);
  nextPhase(0);assert(s.position==2);
 }else if(c=="sled_reverse"){
  auto& s=d.sled[0];s.position=73;d.command("SLED 1 ENABLE 1");d.command("SLED 1 DIR REV");d.command("SLED 1 PLAY 280");
  nextPhase(0);assert(s.position==72&&!s.forward);
 }else if(c=="sled_bounce_max"){
  d.command("SLED 1 PROFILE 140 5000 1");
  auto& s=d.sled[0];s.position=139;d.command("SLED 1 ENABLE 1");d.command("SLED 1 PLAY 300");
  nextPhase(0);assert(s.position==138&&!s.forward&&s.playing);
  d.command("SLED 1 DIR FWD");assert(s.forward);runFor(100000);assert(s.position<=140&&s.playing);
 }else if(c=="sled_bounce_min"){
  d.command("SLED 1 PROFILE 140 5000 1");
  auto& s=d.sled[0];s.position=1;d.command("SLED 1 ENABLE 1");d.command("SLED 1 DIR REV");d.command("SLED 1 PLAY 280");
  nextPhase(0);assert(s.position==2&&s.forward&&s.playing);
  d.command("SLED 1 DIR REV");runFor(100000);assert(s.position>=0&&s.playing);
 }else if(c=="sled_bounds"){
  d.command("SLED 1 PROFILE 140 5000 1");
  d.command("SLED 1 ENABLE 1");d.command("SLED 1 PLAY 400");auto& s=d.sled[0];bool forward=false,reverse=false;
  for(int n=0;n<30000;++n){io.now+=100;d.lastCommand=io.now;d.tick();
   assert(s.position>=0&&s.position<=s.softMax&&s.playing);forward|=s.currentStepRate>0;reverse|=s.currentStepRate<0;
  }assert(forward&&reverse);
 }else if(c=="sled_stop_position"){
  d.command("SLED 1 ENABLE 1");d.command("SLED 1 PLAY 280");nextPhase(0);auto& s=d.sled[0];int position=s.position;
  d.command("SLED 1 STOP");assert(!s.playing&&s.position==position&&((io.previous>>16)&15)==0);
  runFor(10000);assert(s.position==position);d.command("SLED 1 PLAY 280");nextPhase(0);assert(s.position==position+1);
  d.command("ALL STOP");assert(s.position==position+1&&!s.playing);
 }else if(c=="sled_dir"){
  d.command("SLED 1 ENABLE 1");auto& s=d.sled[0];s.position=70;
  d.command("SLED 1 DIR REV");d.command("SLED 1 PLAY 280");nextPhase(0);assert(s.position==69&&s.phase==3&&((io.previous>>16)&15)==9);
  d.command("SLED 1 DIR FWD");runFor(100000);assert(s.currentStepRate>0&&s.position>69);
 }else if(c=="sled_ramp"){
  d.command("SLED 1 PROFILE 0 5000 1");
  d.command("SLED 1 ENABLE 1");d.command("SLED 1 PLAY 300");auto& s=d.sled[0];s.position=70;d.tick();float previous=0;
  for(int n=0;n<250;++n){uint32_t before=io.now;io.now+=100;d.tick();float dt=(io.now-before)/1000000.f;
   assert(s.currentStepRate-previous<=s.accelerationLimit*dt+.01f);assert(s.currentStepRate<=300);previous=s.currentStepRate;
  }assert(previous>0&&previous<300);
  d.command("SLED 1 DIR REV");runFor(150000);assert(s.currentStepRate<0&&s.playing);
 }else if(c=="hdd_profile"){
  assert(!strcmp(d.command("HDD 1 PROFILE 40 40 2"),"OK"));assert(d.hdd[0].strikeUs==2000&&d.hdd[1].strikeUs==4000);
  d.command("HDD 1 HIT");assert(!strcmp(d.command("HDD 1 PROFILE 40 40 4"),"ERR BUSY"));
  io.now+=40000;d.tick();io.now+=40000;d.tick();assert(d.hdd[0].state==Hdd::Strike);
  io.now+=2000;d.tick();assert(d.hdd[0].state==Hdd::Idle);
  assert(!strcmp(d.command("HDD 1 PROFILE 40 40 nan"),"ERR PROFILE"));
  assert(!strcmp(d.command("HDD 1 PROFILE 40 40 0.00001"),"ERR PROFILE"));
 }else if(c=="sled_brake"){
  d.command("SLED 1 PROFILE 140 5000 1");
  d.command("SLED 1 ENABLE 1");d.command("SLED 1 PLAY 400");auto& s=d.sled[0];s.position=125;
  s.currentStepRate=400;s.clockStarted=true;s.last=io.now;
  io.now+=100;d.tick();assert(!s.forward&&s.targetStepRate<0&&s.position<140&&s.currentStepRate>0);
  runFor(200000);assert(s.currentStepRate<0&&s.position<140);
 }else if(c=="fdd_profile_timing"){
  auto& f=d.fdd[1];assert(!strcmp(d.command("FDD 2 PROFILE 60 18000 3000"),"OK"));
  f.homed=true;f.awaySteps=60;f.hasStep=true;f.lastStepUs=io.now;uint32_t previous=io.now;
  d.command("FDD 2 PLAY 220");d.tick();assert(!f.directionAway);
  io.now=previous+17999;assert(!f.wantsStep(d.bus));io.now=previous+18000;assert(f.wantsStep(d.bus));
  assert(d.bus.getBit(f.dirBit)); // toward is HIGH
  io.active[1]=true;f.wantsStep(d.bus);assert(f.awaySteps==0&&f.directionAway&&!d.bus.getBit(f.dirBit));
 }else if(c=="profiles"){
  for(int i=0;i<4;++i)assert(d.sled[i].softMax==0);
  assert(d.fdd[0].safeAwaySteps==72&&d.fdd[0].minStepUs==2439);
  assert(!strcmp(d.command("SLED 2 PROFILE -1 5000 1"),"OK"));
  assert(!strcmp(d.command("SLED 2 PROFILE 0 5000 1"),"OK"));
  assert(!strcmp(d.command("SLED 1 PROFILE 140 nan 1"),"ERR PROFILE"));
  d.command("SLED 1 ENABLE 1");d.command("SLED 1 PROFILE 140 5000 0.5");d.command("SLED 1 PLAY 140");runFor(100000);
  assert(d.sled[0].hz==140&&fabsf(d.sled[0].targetStepRate)==280);
  assert(!strcmp(d.command("SLED 1 PROFILE 140 5000 1"),"ERR BUSY"));
 }else if(c=="speaker_waves"){
  assert(!strcmp(d.command("VHS WAVE sine"),"OK")&&d.vhsWave==Sine);
  assert(!strcmp(d.command("VHS2 WAVE triangle"),"OK")&&d.fxWave==Triangle);
  assert(!strcmp(d.command("VHS WAVE invalid"),"ERR VALUE")&&d.vhsWave==Sine);
  assert(!strcmp(d.command("VHS FREQ 2001"),"ERR VALUE"));d.command("VHS2 ENABLE 1");assert(!strcmp(d.command("VHS2 FREQ 2001"),"ERR VALUE"));
  SpeakerOscillator s;s.amp=50;s.hz=100;s.wave=Sine;s.last=0;
  assert(s.sample(2500)==100);assert(s.sample(7500)==0);
  s.wave=Triangle;s.phase=0;s.last=0;assert(s.sample(5000)==100);assert(s.sample(10000)==0);
  s.wave=Sawtooth;s.phase=0;s.last=0;assert(s.sample(5000)==50);
  for(int wave=1;wave<4;++wave){s.wave=wave;s.phase=0;s.last=0;int sum=0;for(int i=1;i<=200;++i){int value=s.sample(i*50);assert(value>=0&&value<=100);sum+=value;}assert(abs(sum/200-50)<=1);}
  s.amp=0;assert(s.sample(100000)==0);
  d.command("TRACKS SET 1 2 3 4");assert(!strcmp(d.command("VHS WAVE sine"),"ERR STRICT_OUTPUT"));
 }else if(c=="speaker_fx"){
  assert(map::speakerFx==26&&map::vhs==25&&io.fxAmp==0);
  assert(!strcmp(d.command("VHS2 FREQ 830"),"ERR DISABLED"));
  d.command("VHS2 ENABLE 1");d.command("VHS AMP 50");d.command("VHS FREQ 220");
  d.command("VHS2 AMP 50");d.command("VHS2 FREQ 987");assert(io.fxAmp==50&&io.fxHz==987&&d.frequency==220);
  d.command("VHS2 STOP");assert(io.fxAmp==0&&d.amp==50&&d.frequency==220);
  d.command("VHS2 AMP 50");d.command("VHS2 FREQ 740");d.command("ALL STOP");assert(io.fxAmp==0&&io.fxHz==0&&d.amp==0);
  d.command("VHS2 AMP 50");d.command("VHS2 FREQ 830");io.now+=3000001;d.tick();assert(io.fxAmp==0&&io.fxHz==0);
  assert(!strcmp(d.command("VHS2 FREQ nan"),"ERR VALUE"));
  d.command("VHS2 ENABLE 0");assert(io.fxAmp==0&&!d.fxEnabled);
 }else if(c=="watchdog"){

  d.fdd[0].homed=true;d.command("PLAY 220");d.command("HIT");io.now+=3000001;d.tick();assert(!d.fdd[0].playing&&d.hdd[0].state==Hdd::Idle&&io.previous==0x5555);
 }else if(c=="protocol"){
  assert(!strcmp(d.command("PING"),"PONG"));assert(!strcmp(d.command("PLAY 220"),"ERR NOT_HOMED"));d.fdd[0].homed=true;d.command("PLAY 220");assert(d.fdd[0].playing);d.command("STOP");assert(!d.fdd[0].playing);
  d.command("DRUM 200");assert(d.amp==200);d.command("DRUMF 164.81");assert(d.frequency>164);d.command("ALL STOP");assert(d.amp==0&&d.frequency==0&&io.previous==0x5555);
  assert(!strcmp(d.command("FDD 5 HOME"),"ERR DISABLED"));assert(!strcmp(d.command("SLED 1 ENABLE 3"),"ERR DISABLED"));assert(!strcmp(d.command("FDD 1 PLAY nan"),"ERR VALUE"));
 }else if(c=="sled_allowed_bands"){
  d.command("SLED 1 ENABLE 1");
  for(int hz: {150,160,220,250,320,490,49,125,175,195,265,305,335,475,501}){
   char cmd[40];snprintf(cmd,sizeof(cmd),"SLED 1 PLAY %d",hz);
   assert(!strcmp(d.command(cmd),"OK"));assert(d.sled[0].playing);d.command("SLED 1 STOP");
  }
  for(int hz: {50,100,120,180,190,270,280,300,340,400,440,470}){
   char cmd[40];snprintf(cmd,sizeof(cmd),"SLED 1 PLAY %d",hz);
   assert(!strcmp(d.command(cmd),"OK"));assert(d.sled[0].playing);
   d.command("SLED 1 STOP");
  }
  d.command("SLED 2 ENABLE 1");assert(!strcmp(d.command("SLED 2 PLAY 250"),"OK"));
 }else if(c=="sled_bands_ratio"){
  d.command("SLED 1 ENABLE 1");d.command("SLED 1 PROFILE 140 5000 2");
  assert(!strcmp(d.command("SLED 1 PLAY 440"),"OK")); // physical 220 is unrestricted
  assert(!strcmp(d.command("SLED 1 PLAY 200"),"OK")); // physical 100 is allowed
  assert(d.sled[0].targetStepRate==100);d.command("SLED 1 STOP");
  d.command("SLED 1 PROFILE 140 5000 0.001");
  assert(!strcmp(d.command("SLED 1 PLAY 100"),"ERR VALUE"));
 }else if(c=="sled_calibration"){
  for(int id=0;id<4;++id){
   auto& s=d.sled[id];assert(s.pitchRatio==(id<3?.5f:1.f));assert(s.softMax==0);
   char cmd[60];snprintf(cmd,sizeof(cmd),"SLED %d ENABLE 1",id+1);d.command(cmd);
   for(int hz: {200,500}){
    snprintf(cmd,sizeof(cmd),"SLED %d PLAY %d",id+1,hz);assert(!strcmp(d.command(cmd),"OK"));
    assert(s.hz==hz);assert(s.targetStepRate==hz/s.pitchRatio);
    assert(s.period==uint32_t(1000000.f/(hz/s.pitchRatio)));
    runFor(300000);assert(s.currentStepRate==s.targetStepRate&&s.forward);
    snprintf(cmd,sizeof(cmd),"SLED %d STOP",id+1);d.command(cmd);assert(!s.playing&&s.currentStepRate==0);
   }
  }
  // Existing firmware defaults can be overridden without rebuilding/flashing.
  d.command("SLED 1 PROFILE 0 5000 1");d.command("SLED 1 PLAY 200");assert(d.sled[0].targetStepRate==200);
  d.command("SLED 1 STOP");assert(!strcmp(d.command("SLED 1 PROFILE 0 5000 0.5"),"OK"));
  d.command("SLED 1 PLAY 200");assert(d.sled[0].targetStepRate==400);
  d.command("SLED 1 STOP");assert(!strcmp(d.command("SLED 1 PLAY 5001"),"ERR VALUE"));
 }else if(c=="sled_continuous"){
  d.command("SLED 1 ENABLE 1");auto& s=d.sled[0];assert(s.softMax==0);
  for(int hz: {10,150,220,490,1200,5000}){
   char cmd[40];snprintf(cmd,sizeof(cmd),"SLED 1 PLAY %d",hz);assert(!strcmp(d.command(cmd),"OK"));d.command("SLED 1 STOP");
  }
  assert(!strcmp(d.command("SLED 1 PLAY 10001"),"ERR VALUE"));
  d.command("SLED 1 PLAY 1000");s.position=32766;s.currentStepRate=1000;
  runFor(100000);assert(s.position>32767&&s.forward&&s.playing&&s.currentStepRate>0);
  s.position=INT32_MAX;nextPhase(0);assert(s.position==INT32_MAX&&s.playing&&s.forward);
  d.command("SLED 1 STOP");assert(!s.playing&&((io.previous>>16)&15)==0);
  d.command("SLED 1 DIR REV");d.command("SLED 1 PLAY 1000");s.position=INT32_MIN;
  nextPhase(0);assert(s.position==INT32_MIN&&s.playing&&!s.forward);
  d.command("ALL STOP");assert(!s.playing);
 }else if(c=="disable"){
  d.fdd[0].homed=true;d.command("PLAY 220");d.command("FDD 1 ENABLE 0");assert(!d.fdd[0].playing&&!d.fdd[0].enabled);assert(!strcmp(d.command("PLAY 220"),"ERR DISABLED"));
 }else if(c=="strict_tracks"){
  for(auto& f:d.fdd)f.homed=true;
  assert(!strcmp(d.command("TRACKS SET 3 1 4 8"),"OK"));
  assert(d.strictTracks&&d.strictTrack[0]==3&&d.strictTrack[3]==8);
  assert(!strcmp(d.command("FDD 1 PLAY 220"),"ERR TRACK_REQUIRED"));
  assert(!strcmp(d.command("PLAY 220"),"ERR TRACK_REQUIRED"));
  assert(!strcmp(d.command("FDD 1 PLAY 220 TRACK 1"),"ERR TRACK"));
  assert(!strcmp(d.command("FDD 1 PLAY 220 TRACK 3 EXTRA"),"ERR COMMAND"));
  assert(!d.fdd[0].playing);
  assert(!strcmp(d.command("FDD 1 PLAY 220 TRACK 3"),"OK"));
  assert(d.fdd[0].playing&&!d.fdd[1].playing);
  assert(!strcmp(d.command("TRACKS SET 3 3 4 8"),"ERR TRACK"));
  assert(d.fdd[0].playing&&d.strictTrack[1]==1);
  assert(!strcmp(d.command("TRACKS SET 3 1 -1 8"),"OK"));
  assert(!d.fdd[0].playing);
  assert(!strcmp(d.command("FDD 3 PLAY 220 TRACK 4"),"ERR TRACK"));
  assert(!strcmp(d.command("HDD 1 HIT"),"ERR STRICT_OUTPUT"));
  assert(!strcmp(d.command("SLED 1 PLAY 220"),"ERR STRICT_OUTPUT"));
  assert(!strcmp(d.command("VHS AMP 30"),"ERR STRICT_OUTPUT"));
  assert(!strcmp(d.command("TRACKS OFF"),"OK"));
  assert(!d.strictTracks&&!strcmp(d.command("FDD 1 PLAY 220"),"OK"));
 }else assert(false);
}
'''


class Esp32CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if not compiler: raise RuntimeError('C++ compiler required for firmware safety tests')
        cls.directory = tempfile.TemporaryDirectory()
        source = Path(cls.directory.name)/'core.cpp'
        source.write_text(SOURCE)
        cls.binary = source.with_suffix('')
        subprocess.run([compiler, '-std=c++11', '-Wall', '-Wextra', '-I', str(ROOT/'firmware/controller/include'), str(source), '-o', str(cls.binary)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls): cls.directory.cleanup()

for case in ('power','map','boot','home','home_timeout','extended_fdd','extended_stop','extended_strict','parallel','independent','away','timing','hdd','sled','six_sleds','all_actuators_stop','speaker_fx','speaker_waves','watchdog','protocol','disable','strict_tracks','continuous_pitch','sled_forward','sled_reverse','sled_bounce_max','sled_bounce_min','sled_bounds','sled_stop_position','sled_dir','sled_ramp','profiles','sled_brake','fdd_profile_timing','hdd_profile','sled_allowed_bands','sled_bands_ratio','sled_continuous','sled_calibration'):
    def run(self, case=case):
        subprocess.run([str(self.binary), case], check=True, capture_output=True)
    setattr(Esp32CoreTests, 'test_'+case, run)
