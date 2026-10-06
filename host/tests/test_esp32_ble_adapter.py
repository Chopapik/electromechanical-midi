"""Run the actual ESP32 adapter offline with fake Arduino/NimBLE/FreeRTOS.

This tests callback/loop boundaries and queues, never radio or electrical timing.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from test_esp32_firmware import ROOT

ARDUINO = r'''
#pragma once
#include <stdint.h>
#include <cstring>
#include <string>
#include <vector>
#include <deque>
#include <utility>
constexpr int LOW=0,HIGH=1,INPUT=2,OUTPUT=3;
uint32_t fakeUs=10000; int gpio[40]={}, modes[40]={}, taskCore=-1;
std::vector<std::pair<int,int>> writes;
uint32_t micros(){return ++fakeUs;}
uint32_t millis(){return fakeUs/1000;}
void delayMicroseconds(uint32_t n){fakeUs+=n;}
void digitalWrite(int pin,int value){gpio[pin]=value;writes.push_back({pin,value});}
void pinMode(int pin,int mode){modes[pin]=mode;}
int digitalRead(int pin){return gpio[pin];}
void ledcSetup(int,float,int){} void ledcAttachPin(int,int){} void ledcWrite(int,int){}
struct FakeSerial {
 std::deque<uint8_t> rx; std::string sent;size_t capacity=64;
 void begin(int){} size_t availableForWrite(){return capacity;}
 int available(){return rx.size();} uint8_t read(){uint8_t c=rx.front();rx.pop_front();return c;}
 void write(uint8_t c){sent+=char(c);}
} Serial;
struct FakeQueue { size_t count,size; std::deque<std::vector<uint8_t>> items; };
using QueueHandle_t=FakeQueue*;
constexpr int pdTRUE=1,pdPASS=1;
#define pdMS_TO_TICKS(n) (n)
QueueHandle_t xQueueCreate(size_t count,size_t size){return new FakeQueue{count,size,{}};}
int xQueueSend(QueueHandle_t q,const void* p,int){if(q->items.size()==q->count)return 0;auto* b=static_cast<const uint8_t*>(p);q->items.emplace_back(b,b+q->size);return pdTRUE;}
int xQueueReceive(QueueHandle_t q,void* p,int){if(q->items.empty())return 0;memcpy(p,q->items.front().data(),q->size);q->items.pop_front();return pdTRUE;}
void xQueueReset(QueueHandle_t q){q->items.clear();}
size_t uxQueueMessagesWaiting(QueueHandle_t q){return q->items.size();}
void vTaskDelay(uint32_t n){fakeUs+=n*1000;}
int xTaskCreatePinnedToCore(void(*)(void*),const char*,int,void*,int,void*,int core){taskCore=core;return pdPASS;}
'''
SPI = r'''
#pragma once
constexpr int MSBFIRST=1,SPI_MODE0=0;
struct SPISettings { SPISettings(int,int,int){} };
struct FakeSPI {
 void begin(int clock,int,int data,int){} void beginTransaction(SPISettings){}
 void transfer(uint8_t){++fakeUs;} void endTransaction(){}
} SPI;
'''
NIMBLE = r'''
#pragma once
struct ble_gap_conn_desc {};
class NimBLECharacteristic;
class NimBLEServer;
struct NimBLECharacteristicCallbacks {
 enum Status {SUCCESS_NOTIFY};
 virtual void onWrite(NimBLECharacteristic*){}
 virtual void onSubscribe(NimBLECharacteristic*,ble_gap_conn_desc*,uint16_t){}
 virtual void onStatus(NimBLECharacteristic*,Status,int){}
 virtual ~NimBLECharacteristicCallbacks(){}
};
struct NimBLEServerCallbacks {
 virtual void onConnect(NimBLEServer*){} virtual void onDisconnect(NimBLEServer*){}
 virtual ~NimBLEServerCallbacks(){}
};
namespace NIMBLE_PROPERTY {constexpr int WRITE=1,WRITE_NR=2,NOTIFY=4;}
struct NimBLECharacteristic {
 std::string uuid,value; int properties; uint16_t maxLength;
 NimBLECharacteristicCallbacks* callbacks=nullptr;
 std::vector<std::string> notifications; bool failOnce=false;
 std::string getValue(){return value;}
 void setCallbacks(NimBLECharacteristicCallbacks* c){callbacks=c;}
 void notify(const uint8_t* bytes,size_t n){
  if(failOnce){failOnce=false;callbacks->onStatus(this,NimBLECharacteristicCallbacks::SUCCESS_NOTIFY,1);return;}
  notifications.emplace_back(reinterpret_cast<const char*>(bytes),n);
  callbacks->onStatus(this,NimBLECharacteristicCallbacks::SUCCESS_NOTIFY,0);
 }
};
struct NimBLEService {
 std::string uuid; std::vector<NimBLECharacteristic*> chars;
 NimBLECharacteristic* createCharacteristic(const char* id,int p,uint16_t n){auto* c=new NimBLECharacteristic;c->uuid=id;c->properties=p;c->maxLength=n;chars.push_back(c);return c;}
 void start(){}
};
struct NimBLEServer {
 NimBLEServerCallbacks* callbacks=nullptr;NimBLEService svc;bool restartAdvertising=false;
 void setCallbacks(NimBLEServerCallbacks* c,bool){callbacks=c;}
 void advertiseOnDisconnect(bool b){restartAdvertising=b;}
 NimBLEService* createService(const char* id){svc.uuid=id;return &svc;}
} fakeServer;
struct NimBLEAdvertising {std::string uuid;bool scanResponse=false,started=false;
 void addServiceUUID(const char* id){uuid=id;}void setScanResponse(bool b){scanResponse=b;}void start(){started=true;}
} fakeAdvertising;
namespace NimBLEDevice {
 std::string name;
 void init(const char* n){name=n;}
 NimBLEServer* createServer(){return &fakeServer;}
 NimBLEAdvertising* getAdvertising(){return &fakeAdvertising;}
}
'''
SOURCE = r'''
#include <cassert>
//PRODUCTION_INCLUDE
void connectBle(){fakeServer.callbacks->onConnect(&fakeServer);bleTx->callbacks->onSubscribe(bleTx,nullptr,1);}
void writeBle(const std::string& value){auto* rx=fakeServer.svc.chars[0];rx->value=value;rx->callbacks->onWrite(rx);}
void drainInput(){for(int i=0;i<100;++i)pollBle();}
std::string drainBle(){BleReply packet;std::string text;while(xQueueReceive(bleTxQueue,&packet,0)==pdTRUE){bleNotify(packet);}for(auto& fragment:bleTx->notifications){assert(fragment.size()<=20);text+=fragment;}return text;}
int main(int argc,char** argv){
 std::string c=argv[1];for(int pin:orchestra::map::track0)gpio[pin]=HIGH;
 setup();
 if(c=="serial_boot_once"){
  Serial.capacity=0;for(int i=0;i<100;++i)loop();assert(Serial.sent.empty());
  Serial.capacity=7;for(int i=0;i<10000;++i)loop();
  const std::string ready="READY protocol=2 board=esp32\n";
  assert(Serial.sent==ready&&txRead==txWrite);
  connectBle();writeBle("PING\n");drainInput();assert(drainBle()=="PONG\n");
  fakeServer.callbacks->onDisconnect(&fakeServer);connectBle();
  for(uint8_t ch:std::string("PING\nSTATUS\n"))Serial.rx.push_back(ch);
  for(int i=0;i<10000;++i)loop();
  assert(Serial.sent.find(ready,ready.size())==std::string::npos);
  assert(Serial.sent.find("PONG\n")!=std::string::npos&&Serial.sent.find("STATUS END\n")!=std::string::npos);
  return 0;
 }
 txRead=txWrite=0;connectBle();
 if(c=="boot"){
  assert(writes[0]==std::make_pair(27,LOW)&&gpio[27]==LOW&&modes[27]==OUTPUT);
  assert(NimBLEDevice::name=="Electromechanical-MIDI"&&fakeServer.svc.uuid==orchestra::ble::service);
  assert(fakeServer.svc.chars[0]->uuid==orchestra::ble::rx&&bleTx->uuid==orchestra::ble::tx);
  assert(fakeServer.svc.chars[0]->properties==(NIMBLE_PROPERTY::WRITE|NIMBLE_PROPERTY::WRITE_NR));
  assert(bleTx->properties==NIMBLE_PROPERTY::NOTIFY&&fakeAdvertising.scanResponse&&fakeAdvertising.started&&fakeServer.restartAdvertising&&taskCore==0);
 }else if(c=="callback_deferred"){
  size_t n=writes.size();writeBle("TEST ON\n");assert(gpio[27]==LOW&&writes.size()==n&&uxQueueMessagesWaiting(bleRxQueue)==1);
  drainInput();assert(gpio[27]==HIGH&&drainBle()=="TEST ON\n");
 }else if(c=="motor_deferred"){
  ctrl.fdd[0].homed=true;size_t n=writes.size();writeBle("FDD 1 PLAY 220\n");
  assert(!ctrl.fdd[0].playing&&writes.size()==n);drainInput();assert(ctrl.fdd[0].playing);
  fakeServer.callbacks->onDisconnect(&fakeServer);assert(ctrl.fdd[0].playing&&writes.size()>n);
 }else if(c=="routing"){
  writeBle("PI");pollBle();for(uint8_t ch:std::string("PING\n"))Serial.rx.push_back(ch);
  loop();assert(Serial.sent=="PONG\n"&&uxQueueMessagesWaiting(bleTxQueue)==0);
  writeBle("NG\n");drainInput();assert(drainBle()=="PONG\n"&&Serial.sent=="PONG\n");
 }else if(c=="reconnect"){
  writeBle("TEST O");drainInput();fakeServer.callbacks->onDisconnect(&fakeServer);connectBle();
  writeBle("N\n");drainInput();assert(gpio[27]==LOW);
  writeBle("TEST ON\n");fakeServer.callbacks->onDisconnect(&fakeServer);connectBle();drainInput();assert(gpio[27]==LOW);
  writeBle("TEST ON\n");drainInput();assert(gpio[27]==HIGH);
 }else if(c=="stale_reply"){
  writeBle("PING\n");drainInput();assert(uxQueueMessagesWaiting(bleTxQueue)==1);
  fakeServer.callbacks->onDisconnect(&fakeServer);connectBle();assert(drainBle().empty());
 }else if(c=="overflow"){
  for(int i=0;i<9;++i)writeBle("TEST O");pollBle();assert(gpio[27]==LOW&&uxQueueMessagesWaiting(bleRxQueue)==0);
  writeBle("N\nPING\n");drainInput();assert(gpio[27]==LOW&&drainBle()=="ERR RX_OVERFLOW\nPONG\n");
 }else if(c=="notify"){
  writeBle("STATUS\n");drainInput();size_t n=writes.size();bleTx->failOnce=true;
  auto text=drainBle();assert(text.find("STATUS BEGIN\n")==0&&text.substr(text.size()-11)=="STATUS END\n");
  assert(writes.size()==n); // TX never drives GPIO, even on retry.
 }else if(c=="empty_write"){
  writeBle("");assert(uxQueueMessagesWaiting(bleRxQueue)==0);writeBle("PING\n");drainInput();assert(drainBle()=="PONG\n");
 }else assert(false);
}
'''


class Esp32BleAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if not compiler:
            raise RuntimeError('C++ compiler required for BLE adapter tests')
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        for name, content in [('Arduino.h', ARDUINO), ('SPI.h', SPI), ('NimBLEDevice.h', NIMBLE)]:
            (root/name).write_text(content)
        source = root/'ble.cpp'
        production = ROOT/'firmware/controller/src/esp32/main.cpp'
        source.write_text(SOURCE.replace('//PRODUCTION_INCLUDE', f'#include "{production}"'))
        cls.binary = source.with_suffix('')
        subprocess.run([compiler, '-std=c++11', '-I', str(root), '-I', str(ROOT/'firmware/controller/include'),
                        str(source), '-o', str(cls.binary)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

for case in ('serial_boot_once', 'boot', 'callback_deferred', 'motor_deferred', 'routing', 'reconnect',
             'stale_reply', 'overflow', 'notify', 'empty_write'):
    def run(self, case=case):
        subprocess.run([str(self.binary), case], check=True, capture_output=True)
    setattr(Esp32BleAdapterTests, 'test_'+case, run)
