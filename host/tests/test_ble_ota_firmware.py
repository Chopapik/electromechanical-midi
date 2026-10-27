"""Production OTA state machine; fake Flash, no radio, reboot or GPIO."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SOURCE=r'''
#include "ble_ota.h"
#include <cassert>
#include <vector>
#include <string>
using namespace orchestra::ota;
struct FlashStore:Storage {
 bool auth=true,checksum=true,writeOk=true,selectOk=true,enabled=true;
 int begins=0,selections=0,reboots=0;std::vector<uint8_t> image;
 uint32_t capacity()override{return enabled?1024:0;}
 void random(uint8_t* p,size_t n)override{memset(p,42,n);}
 bool authenticate(const uint8_t* nonce,const uint8_t* meta)override{return auth&&nonce[0]==42&&meta[36]==55;}
 bool begin(uint32_t)override{++begins;image.clear();return true;}
 bool write(const uint8_t* p,size_t n)override{image.insert(image.end(),p,p+n);return writeOk;}
 bool finish(const uint8_t*)override{return checksum;}
 bool select()override{if(selectOk)++selections;return selectOk;}
 void abort()override{}
 void restart()override{++reboots;}
};
struct Sink:Replies {
 std::vector<std::vector<uint8_t>> packets;std::vector<uint32_t> epochs;
 void send(const uint8_t* p,size_t n,uint32_t epoch)override{assert(n<=20);packets.emplace_back(p,p+n);epochs.push_back(epoch);}
 uint8_t last(){return packets.back()[0];}
 uint8_t error(){assert(last()==Error);return packets.back()[1];}
};
int main(int argc,char** argv){
 std::string test=argv[1];FlashStore storage;Sink replies;Session session(storage,replies);
 uint32_t now=100,epoch=1;bool off=true;
 auto input=[&](std::vector<uint8_t> p){session.input(p.data(),p.size(),epoch,now,off);};
 auto begin=[&](uint32_t size=4){
  input({Query});assert(replies.last()==Challenge&&replies.packets.back().size()==18);
  uint8_t meta[100]={};write32(meta,size);meta[36]=55;
  for(int offset=0;offset<100;offset+=18){std::vector<uint8_t> p={Meta,uint8_t(offset)};for(int i=offset;i<offset+18&&i<100;++i)p.push_back(meta[i]);input(p);}
  input({Begin});
 };
 auto data=[&](){input({uint8_t(Data|0x80),0,0,0,0,1,2,3,4});};
 if(test=="success"){
  begin();assert(session.busy()&&replies.last()==Ready&&storage.begins==1);
  input({Data,0,0,0,0,1,2});assert(replies.last()==Ready);
  input({uint8_t(Data|0x80),2,0,0,0,3,4});assert(replies.last()==Progress&&read32(replies.packets.back().data()+1)==4);
  input({End});assert(replies.last()==Verified&&storage.selections==0&&storage.reboots==0);
  input({Commit});assert(replies.last()==Committed&&storage.selections==1&&session.busy());
  session.tick(now+499999,epoch,off);assert(storage.reboots==0);
  session.tick(now+500000,epoch+1,off);session.tick(now+600000,epoch+1,off);assert(storage.reboots==1);
 }else if(test=="auth"){
  storage.auth=false;begin();assert(replies.error()==Auth&&storage.begins==0&&!session.busy());
  input({Begin});assert(replies.error()==State&&storage.begins==0); // nonce consumed
 }else if(test=="unsafe"){
  off=false;begin();assert(replies.error()==Unsafe&&storage.begins==0&&!session.busy());
 }else if(test=="size"){
  begin(1025);assert(replies.error()==Size&&storage.begins==0);
 }else if(test=="checksum"){
  storage.checksum=false;begin();data();input({End});assert(replies.error()==Digest&&!session.busy()&&storage.selections==0);
  input({Commit});assert(storage.selections==0);
 }else if(test=="missing_bytes"){
  begin();input({End});assert(replies.error()==State&&storage.selections==0&&!session.busy());
 }else if(test=="duplicate"){
  begin();data();data();assert(replies.error()==Offset&&storage.selections==0&&!session.busy());
 }else if(test=="offset"){
  begin();input({uint8_t(Data|0x80),2,0,0,0,3,4});assert(replies.error()==Offset&&storage.image.empty());
 }else if(test=="disconnect"){
  begin();session.tick(now,epoch+1,off);assert(!session.busy()&&storage.selections==0);
  ++epoch;input({Begin});assert(replies.error()==State);
 }else if(test=="timeout"){
  begin();session.tick(now+10000001,epoch,off);assert(!session.busy()&&replies.error()==Timeout&&storage.selections==0);
 }else if(test=="abort"){
  begin();input({Abort});assert(replies.last()==Aborted&&!session.busy()&&storage.selections==0);
 }else if(test=="overflow"){
  begin();session.overflow();assert(replies.error()==Overflow&&!session.busy()&&storage.selections==0);
 }else if(test=="write_fail"){
  begin();storage.writeOk=false;data();assert(replies.error()==Flash&&!session.busy()&&storage.selections==0);
 }else if(test=="select_fail"){
  begin();data();input({End});storage.selectOk=false;input({Commit});assert(replies.error()==Flash&&!session.busy()&&storage.selections==0);
 }else if(test=="unsupported"){
  storage.enabled=false;input({Query});assert(replies.error()==Unsupported&&storage.begins==0);
 }else if(test=="metadata"){
  input({Query});input({Meta,1,2});assert(replies.error()==Protocol&&storage.begins==0);
 }else assert(false);
}
'''


class OtaFirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler=shutil.which('clang++') or shutil.which('g++')
        if not compiler:raise RuntimeError('C++ compiler required')
        cls.directory=tempfile.TemporaryDirectory()
        source=Path(cls.directory.name)/'ota.cpp';source.write_text(SOURCE)
        cls.binary=source.with_suffix('')
        subprocess.run([compiler,'-std=c++11','-Wall','-Wextra','-I',str(ROOT/'firmware/controller/include'),str(source),'-o',str(cls.binary)],check=True,capture_output=True)
    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()


for case in ('success','auth','unsafe','size','checksum','missing_bytes','duplicate','offset','disconnect','timeout','abort','overflow','write_fail','select_fail','unsupported','metadata'):
    def run(self,case=case):subprocess.run([str(self.binary),case],check=True,capture_output=True)
    setattr(OtaFirmwareTests,'test_'+case,run)
