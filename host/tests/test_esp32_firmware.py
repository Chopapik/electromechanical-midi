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
 uint32_t now=10000;bool active[4]={};bool outputs=false;uint64_t previous=0;
 std::vector<std::pair<uint32_t,uint64_t>> edges;
 std::vector<std::string> boot;std::vector<std::array<uint8_t,5>> bytes;
 uint32_t us()override{return now;}
 void delayUs(uint32_t n)override{now+=n;}
 bool track0(uint8_t pin)override{for(int i=0;i<4;++i)if(pin==map::track0[i])return active[i];assert(false);return false;}
 void outputEnable(bool on)override{outputs=on;boot.push_back(on?"on":"off");}
 void beginSPI()override{boot.push_back("spi");}
 uint32_t frame(const uint8_t* b,size_t n)override{
  assert(n==5);std::array<uint8_t,5> copy;uint64_t bits=0;
  for(int i=0;i<5;++i){copy[i]=b[i];bits=(bits<<8)|b[i];}
  bytes.push_back(copy);now+=45;edges.push_back({now,bits});boot.push_back("frame");previous=bits;return now;
 }
 void vhs(uint8_t,float)override{}
};
int main(int argc,char** argv){
 std::string c=argv[1];Fake io;Controller d(io);d.begin();
 if(c=="map"){
  std::vector<int> used;for(auto b:map::step)used.push_back(b);for(auto b:map::dir)used.push_back(b);
  for(auto& group:map::sled)for(auto b:group)used.push_back(b);
  for(auto& group:map::hdd)for(auto b:group)used.push_back(b);
  for(auto& group:map::tray)for(auto b:group)used.push_back(b);used.push_back(map::sleep);
  bool seen[40]={};for(int b:used){assert(b<40&&!seen[b]);seen[b]=true;}
  for(int bit=0;bit<40;++bit){for(int b=0;b<40;++b)d.bus.setBit(b,b==bit);d.bus.flush();assert(io.previous==(uint64_t(1)<<bit));for(int b=0;b<40;++b)assert(d.bus.getBit(b)==(b==bit));}
 }else if(c=="boot"){
  assert(io.boot[0]=="off"&&io.boot[1]=="spi"&&io.boot[2]=="frame"&&io.boot[3]=="on");
  assert(io.previous==0x55&&io.outputs);for(auto& f:d.fdd)assert(!f.playing&&!f.homing&&!f.homed);
  for(auto& s:d.sled)assert(!s.enabled);for(auto& t:d.tray)assert(!t.enabled);
 }else if(c=="home"){
  d.command("FDD 1 HOME");assert(d.fdd[0].homing&&!d.fdd[1].homing);
  io.now+=6000;d.tick();assert(!d.fdd[0].homed);
  io.active[0]=true;d.tick();assert(d.fdd[0].homed&&d.fdd[0].directionAway&&d.fdd[0].awaySteps==0);
 }else if(c=="home_timeout"){
  d.command("HOME");io.now+=2000001;d.lastCommand=io.now;d.tick();assert(!d.fdd[0].homed&&!d.fdd[0].homing);assert(!strcmp(d.fdd[0].error,"HOME_FAILED"));
 }else if(c=="parallel"){
  for(auto& f:d.fdd){f.homed=true;f.play(410,io);}
  size_t n=io.edges.size();d.tick();assert(io.edges.size()==n+3);assert((io.edges[n+1].second&0x55)==0);assert((io.edges[n+2].second&0x55)==0x55);
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
  assert(!strcmp(d.command("SLED 2 PLAY 220"),"ERR DISABLED"));d.command("SLED 2 ENABLE 1");d.command("SLED 2 PLAY 220");
  int expected[4]={6,10,9,5};for(int p:expected){io.now+=5000;d.tick();assert(((io.previous>>12)&15)==p);}
  d.command("SLED 2 STOP");assert(((io.previous>>12)&15)==0);
  d.command("SLED 2 DIR REV");d.command("SLED 2 PLAY 220");io.now+=5000;d.tick();assert(((io.previous>>12)&15)==9);
 }else if(c=="tray"){
  assert(!strcmp(d.command("TRAY 1 PULSE FWD 80"),"ERR DISABLED"));d.command("TRAY 1 ENABLE 1");d.command("TRAY 1 PULSE REV 80");assert((io.previous>>32&3)==2);io.now+=80000;d.tick();assert(!d.tray[0].busy&&(io.previous>>32&3)==0);
 }else if(c=="watchdog"){
  d.fdd[0].homed=true;d.command("PLAY 220");d.command("HIT");io.now+=3000001;d.tick();assert(!d.fdd[0].playing&&d.hdd[0].state==Hdd::Idle&&io.previous==0x55);
 }else if(c=="protocol"){
  assert(!strcmp(d.command("PING"),"PONG"));assert(!strcmp(d.command("PLAY 220"),"ERR NOT_HOMED"));d.fdd[0].homed=true;d.command("PLAY 220");assert(d.fdd[0].playing);d.command("STOP");assert(!d.fdd[0].playing);
  d.command("DRUM 200");assert(d.amp==200);d.command("DRUMF 164.81");assert(d.frequency>164);d.command("ALL STOP");assert(d.amp==0&&d.frequency==0&&io.previous==0x55);
  assert(!strcmp(d.command("FDD 5 HOME"),"ERR ID"));assert(!strcmp(d.command("SLED 1 ENABLE 3"),"ERR DISABLED"));assert(!strcmp(d.command("FDD 1 PLAY nan"),"ERR VALUE"));
 }else if(c=="disable"){
  d.fdd[0].homed=true;d.command("PLAY 220");d.command("FDD 1 ENABLE 0");assert(!d.fdd[0].playing&&!d.fdd[0].enabled);assert(!strcmp(d.command("PLAY 220"),"ERR DISABLED"));
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

for case in ('map','boot','home','home_timeout','parallel','independent','away','timing','hdd','sled','tray','watchdog','protocol','disable','continuous_pitch'):
    def run(self, case=case):
        subprocess.run([str(self.binary), case], check=True, capture_output=True)
    setattr(Esp32CoreTests, 'test_'+case, run)
