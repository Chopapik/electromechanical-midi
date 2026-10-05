"""Execute the actual firmware FloppyDrive class with fake Arduino GPIO/time."""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2]/'firmware/floppy/src/main.cpp'
STUB = r'''
#include <cstdint>
#include <sstream>
#include <cassert>
#include <string>
#include <vector>
#include <cstdio>
#define HIGH 1
#define LOW 0
#define INPUT_PULLUP 2
#define OUTPUT 3
#define F_CPU 16000000UL
struct __FlashStringHelper {};
#define F(x) reinterpret_cast<const __FlashStringHelper *>(x)
int sensor=HIGH, pulses=0;
unsigned long clockMs=0, clockUsOffset=0, sensorReadCost=0;
std::vector<unsigned long> physicalSteps;
int txAvailable=63;
unsigned long micros() { return clockMs*1000+clockUsOffset; }
void pinMode(int,int) {}
void digitalWrite(int pin,int value) { if(pin==3 && value==LOW) { ++pulses; physicalSteps.push_back(micros()); } }
int digitalRead(int) { clockUsOffset+=sensorReadCost; return sensor; }
void delayMicroseconds(unsigned long us) { clockUsOffset+=us; }
unsigned long millis() { return clockMs; }

struct SerialStub {
 std::ostringstream out;
 int availableForWrite() {return txAvailable;}
 void write(const uint8_t *p,int n) {out.write(reinterpret_cast<const char *>(p),n);}
 void print(const __FlashStringHelper *v) {out<<reinterpret_cast<const char *>(v);}
 template<class T> void print(T v) {out<<v;}
 template<class T> void println(T v) {print(v);out<<"\n";}
 void println(float v,int) {print(v);out<<"\n";}
} Serial;
'''
CASES = r'''
int main(int argc,char **argv) {
 FloppyDrive d(2,3,4,5); d.begin();
 d.homed_=true; d.playing_=true; d.directionAway_=false; d.awaySteps_=72;
 std::string c=argv[1];
 if(c=="track0") {
   sensor=LOW; d.musicalStep();
   assert(d.awaySteps()==0 && d.homed() && d.playing() && d.directionAway());
   assert(pulses==0 && Serial.out.str().empty());
 } else if(c=="away") {
   d.directionAway_=true; d.awaySteps_=0;
   for(int i=0;i<SAFE_AWAY_STEPS;++i) d.musicalStep();
   assert(pulses==72 && d.awaySteps()==72 && d.directionAway());
   d.musicalStep(); assert(pulses==72 && !d.directionAway());
   d.musicalStep(); assert(pulses==73 && d.awaySteps()==72);
 } else if(c=="unbounded_return") {
   sensor=HIGH;
   for(int i=0;i<10000;++i) d.musicalStep();
   assert(pulses==10000 && d.awaySteps()==72 && d.homed() && d.playing());
   assert(!d.directionAway() && Serial.out.str().empty());
   sensor=LOW; d.musicalStep();
   assert(pulses==10000 && d.directionAway() && d.awaySteps()==0);
 } else if(c=="lost_steps") {
   // GPIO pulses have no mechanical feedback; only TRACK0 matters.
   d.directionAway_=true; d.awaySteps_=0;
   for(int i=0;i<72;++i) d.musicalStep();
   d.musicalStep();
   for(int i=0;i<250;++i) d.musicalStep();
   assert(d.awaySteps()==72 && d.playing() && Serial.out.str().empty());
   sensor=LOW; d.musicalStep(); assert(d.awaySteps()==0 && d.directionAway());
 } else if(c=="home") {
   d.awaySteps_=53; d.requestHome(); sensor=LOW; d.updateMotion();
   assert(d.homed() && !d.busy() && d.directionAway() && d.awaySteps()==0);
   assert(pulses==0 && Serial.out.str().find("READY")!=std::string::npos);
 } else if(c=="home_sensor") {
   d.awaySteps_=7; d.requestHome(); sensor=HIGH;
   for(int i=1;i<200;++i) { clockMs=i*6; d.updateMotion(); }
   assert(!d.homed() && d.busy() && pulses>90);
   sensor=LOW; d.updateMotion();
   assert(d.homed() && !d.busy() && d.awaySteps()==0 && d.directionAway());
 } else if(c=="home_timeout") {
   d.requestHome(); sensor=HIGH;
   clockMs=HOME_TIMEOUT_MS; d.updateMotion();
   assert(!d.homed() && !d.busy());
   assert(Serial.out.str().find("ERR HOME_FAILED")!=std::string::npos);
 } else if(c=="physical_timing") {
   d.stepIntervalUs_=5102; clockUsOffset=6000; sensorReadCost=2200;
   d.updatePlayback(); assert(pulses==1 && d.lastStepUs_==physicalSteps.back());
   sensorReadCost=0;
   clockUsOffset=physicalSteps.back()+5101; d.updatePlayback(); assert(pulses==1);
   clockUsOffset=physicalSteps.back()+5102; d.updatePlayback(); assert(pulses==2);
   d.stopNote(); d.startNote(196);
   clockUsOffset=physicalSteps.back()+5101; d.updatePlayback(); assert(pulses==2);
   clockUsOffset=physicalSteps.back()+5102; d.updatePlayback(); assert(pulses==3);
   d.awaySteps_=72; d.directionAway_=true;
   clockUsOffset=physicalSteps.back()+6000; d.updatePlayback(); assert(pulses==3);
   clockUsOffset=d.directionReadyUs_-1; d.updatePlayback(); assert(pulses==3);
   clockUsOffset=d.nextStepUs_+5102; d.updatePlayback(); assert(pulses==4);
   sensor=LOW; clockUsOffset=d.nextStepUs_; d.updatePlayback();
   assert(d.awaySteps()==0 && d.directionAway() && pulses==4);
   assert(d.lastStepUs_==physicalSteps.back());
   sensor=HIGH; clockUsOffset=d.directionReadyUs_+5102; d.updatePlayback(); assert(pulses==5);
   for(size_t i=1;i<physicalSteps.size();++i) assert(physicalSteps[i]-physicalSteps[i-1]>=5102);
   assert(Serial.out.str().empty());
 } else if(c=="frequencies") {
   for(float hz : {130.0f,196.0f,410.0f}) {
     d.stopNote(); d.startNote(hz); d.directionAway_=false;
     const auto interval=d.stepIntervalUs_;
     clockUsOffset=d.lastStepUs_+interval+6000; d.updatePlayback();
     const auto edge=physicalSteps.back(); const int count=pulses;
     clockUsOffset=edge+interval-1; d.updatePlayback(); assert(pulses==count);
     clockUsOffset=edge+interval; d.updatePlayback(); assert(pulses==count+1);
     assert(physicalSteps.back()-edge>=interval);
   }
 }
}
'''

class FirmwareOpenLoopTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler=shutil.which('clang++') or shutil.which('g++')
        if not compiler: raise unittest.SkipTest('C++ compiler required for firmware GPIO tests')
        cls.tmp=tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        source=SOURCE.read_text()
        constants='\n'.join(re.findall(r'^constexpr[^\n]*;',source,re.M))
        start=source.index('class FloppyDrive')
        end=source.index('\n};',start)+3
        drive=source[start:end].replace('private:','public:')
        path=Path(cls.tmp.name)/'test.cpp'
        path.write_text(STUB+constants+'\n'+drive+CASES)
        cls.exe=Path(cls.tmp.name)/'test'
        subprocess.run([compiler,'-std=c++11',str(path),'-o',str(cls.exe)],check=True,capture_output=True,text=True)
    def run_case(self, case):
        subprocess.run([str(self.exe),case],check=True,capture_output=True,text=True)
    def test_track0_immediately_reverses_and_clears_away_steps(self): self.run_case('track0')
    def test_72_away_commands_reverse_without_extra_step(self): self.run_case('away')
    def test_return_has_no_step_budget_and_ends_only_at_track0(self): self.run_case('unbounded_return')
    def test_lost_physical_steps_have_no_software_representation(self): self.run_case('lost_steps')
    def test_home_at_active_track0_is_ready_without_start_offset(self): self.run_case('home')
    def test_home_uses_sensor_instead_of_expected_steps(self): self.run_case('home_sensor')
    def test_home_emergency_timeout_is_time_based(self): self.run_case('home_timeout')
    def test_physical_edges_obey_timing_through_dir_retrigger_and_track0(self): self.run_case('physical_timing')
    def test_note_periods_remain_intact_at_130_196_and_410_hz(self): self.run_case('frequencies')
