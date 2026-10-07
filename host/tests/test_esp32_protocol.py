"""Compile the production dispatcher: USB/BLE share parser, not motor state copies."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from test_esp32_firmware import SOURCE as CORE_SOURCE, ROOT

SOURCE = CORE_SOURCE.split('int main(')[0].replace('"orchestra_core.h"', '"orchestra_protocol.h"') + r'''
struct Reply { Transport origin; std::string text; uint32_t session; };
struct Sink: ResponseSink {
 std::vector<Reply> replies;
 void send(Transport origin,const char* line,uint32_t session=0)override { replies.push_back({origin,line,session}); }
};
struct Led: TestOutput { bool on=true; int writes=0; void set(bool value)override{on=value;++writes;} };
void feed(CommandProtocol& p,Transport origin,const std::string& text){for(uint8_t ch:text)p.input(origin,ch);}
int main(int argc,char** argv){
 std::string c=argv[1];Fake io;Controller ctrl(io);ctrl.begin();Sink sink;Led led;CommandProtocol p(ctrl,sink,led);p.beginTest();p.newBleSession(1);
 if(c=="led"){
  assert(!led.on&&!p.testOn&&led.writes==1);
  p.execute(Transport::Ble,"TEST ON");assert(led.on&&sink.replies.back().text=="TEST ON");
  p.execute(Transport::Usb,"TEST OFF");assert(!led.on&&sink.replies.back().text=="TEST OFF");
  p.execute(Transport::Ble,"TEST TOGGLE");assert(led.on);
  p.execute(Transport::Usb,"TEST TOGGLE");assert(!led.on);
 }else if(c=="led_status"){
  p.execute(Transport::Ble,"TEST ON");int writes=led.writes;
  p.execute(Transport::Usb,"TEST STATUS");assert(led.on&&led.writes==writes&&sink.replies.back().text=="TEST ON");
  size_t frames=io.edges.size();p.execute(Transport::Usb,"TEST INVALID");
  assert(led.on&&led.writes==writes&&sink.replies.back().text=="ERR COMMAND"&&io.edges.size()==frames);
 }else if(c=="ping"){
  feed(p,Transport::Usb,"PING\n");feed(p,Transport::Ble,"PING\n");
  assert(sink.replies.size()==2&&sink.replies[0].origin==Transport::Usb&&sink.replies[1].origin==Transport::Ble);
  assert(sink.replies[0].text=="PONG"&&sink.replies[1].text=="PONG");
  assert(sink.replies[0].session==0&&sink.replies[1].session==1);
 }else if(c=="status"){
  p.execute(Transport::Usb,"STATUS");size_t n=sink.replies.size();assert(n==18);
  p.execute(Transport::Ble,"STATUS");assert(sink.replies.size()==2*n);
  for(size_t i=0;i<n;++i){assert(sink.replies[i].origin==Transport::Usb&&sink.replies[i+n].origin==Transport::Ble);assert(sink.replies[i].text==sink.replies[i+n].text);}
  assert(sink.replies[n].text=="STATUS BEGIN"&&sink.replies.back().text=="STATUS END");
 }else if(c=="fragment"){
  feed(p,Transport::Ble,"TE");feed(p,Transport::Ble,"ST O");assert(!led.on&&sink.replies.empty());
  feed(p,Transport::Ble,"N\r");assert(!led.on);feed(p,Transport::Ble,"\nPING\nTEST OFF\n");
  assert(!led.on&&sink.replies.size()==3&&sink.replies[1].text=="PONG");
 }else if(c=="separate_lines"){
  feed(p,Transport::Ble,"PI");feed(p,Transport::Usb,"TEST O");
  feed(p,Transport::Ble,"NG\n");assert(!led.on&&sink.replies.back().origin==Transport::Ble);
  feed(p,Transport::Usb,"N\n");assert(led.on&&sink.replies.back().origin==Transport::Usb);
 }else if(c=="line_overflow"){
  feed(p,Transport::Ble,std::string(110,'X')+"TEST ON\nPING\n");
  assert(!led.on&&sink.replies.size()==2&&sink.replies[0].text=="ERR LINE_TOO_LONG"&&sink.replies[1].text=="PONG");
 }else if(c=="rx_overflow"){
  feed(p,Transport::Ble,"TEST O");p.bleOverflow();feed(p,Transport::Ble,"N\nPING\n");
  assert(!led.on&&sink.replies.size()==2&&sink.replies[0].text=="ERR RX_OVERFLOW"&&sink.replies[1].text=="PONG");
 }else if(c=="session"){
  feed(p,Transport::Ble,"TEST O");feed(p,Transport::Usb,"PI");p.newBleSession(2);
  feed(p,Transport::Ble,"N\n");assert(!led.on&&sink.replies.back().text=="ERR COMMAND");
  feed(p,Transport::Usb,"NG\n");assert(sink.replies.back().text=="PONG");
  feed(p,Transport::Ble,"TEST ON\n");assert(led.on&&sink.replies.back().session==2);
 }else if(c=="nul"){
  feed(p,Transport::Ble,std::string("TEST ON\0",8)+"\nPING\n");
  assert(!led.on&&sink.replies[0].text=="ERR COMMAND"&&sink.replies.back().text=="PONG");
 }else if(c=="shared_motor"){
  ctrl.fdd[0].homed=true;p.execute(Transport::Ble,"FDD 1 PLAY 220");assert(ctrl.fdd[0].playing&&ctrl.fdd[0].hz==220);
  p.execute(Transport::Usb,"FDD 1 STOP");assert(!ctrl.fdd[0].playing&&sink.replies.empty());
  p.execute(Transport::Usb,"HDD 2 HIT");assert(ctrl.hdd[1].state==Hdd::Park);
  p.execute(Transport::Ble,"VHS AMP 25");assert(ctrl.amp==25);
  p.execute(Transport::Ble,"ALL STOP");assert(ctrl.hdd[1].state==Hdd::Idle&&ctrl.amp==0&&io.previous==0x55);
 }else if(c=="error_routing"){
  p.execute(Transport::Ble,"FDD 1 PLAY 220");assert(sink.replies.back().origin==Transport::Ble&&sink.replies.back().text=="ERR NOT_HOMED");
  p.execute(Transport::Ble,"FDD 1 HOME");p.execute(Transport::Usb,"FDD 2 HOME");
  io.now+=2000001;ctrl.lastCommand=io.now;ctrl.tick();p.newBleSession(3);p.pollErrors();
  assert(sink.replies[1].origin==Transport::Ble&&sink.replies[1].session==1&&sink.replies[1].text=="ERR HOME_FAILED FDD=1");
  assert(sink.replies[2].origin==Transport::Usb&&sink.replies[2].text=="ERR HOME_FAILED FDD=2");
  p.pollErrors();assert(sink.replies.size()==3);
 }else if(c=="stop_ack"){
  for(auto& f:ctrl.fdd){f.homed=true;f.play(220,io);}
  ctrl.hdd[0].hit(ctrl.bus);ctrl.amp=100;
  p.execute(Transport::Ble,"ALL STOP 42");
  for(auto& f:ctrl.fdd)assert(!f.playing&&!f.homing);
  assert(ctrl.hdd[0].state==Hdd::Idle&&ctrl.amp==0);
  assert(sink.replies.back().text=="STOPPED 42"&&sink.replies.back().origin==Transport::Ble&&sink.replies.back().session==1);
  p.execute(Transport::Usb,"ALL STOP 43");assert(sink.replies.back().text=="STOPPED 43"&&sink.replies.back().origin==Transport::Usb);
  p.execute(Transport::Ble,"ALL STOP invalid");assert(sink.replies.back().text=="ERR VALUE");
 }else if(c=="diag"){
  p.execute(Transport::Ble,"DIAG BIT 39");assert(io.previous==(uint64_t(1)<<39)&&sink.replies.back().origin==Transport::Ble);
  p.execute(Transport::Usb,"ALL STOP");assert((io.previous&0x55)==0x55);
 }else assert(false);
}
'''


class Esp32ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if not compiler:
            raise RuntimeError('C++ compiler required for firmware protocol tests')
        cls.directory = tempfile.TemporaryDirectory()
        source = Path(cls.directory.name) / 'protocol.cpp'
        source.write_text(SOURCE)
        cls.binary = source.with_suffix('')
        subprocess.run([compiler, '-std=c++11', '-I', str(ROOT/'firmware/controller/include'),
                        str(source), '-o', str(cls.binary)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

for case in ('led', 'led_status', 'ping', 'status', 'fragment', 'separate_lines',
             'line_overflow', 'rx_overflow', 'session', 'nul', 'shared_motor', 'error_routing', 'diag', 'stop_ack'):
    def run(self, case=case):
        subprocess.run([str(self.binary), case], check=True, capture_output=True)
    setattr(Esp32ProtocolTests, 'test_'+case, run)
