#include <Arduino.h>
#include <SPI.h>
#include <NimBLEDevice.h>
#include <atomic>
#include "orchestra_protocol.h"
using namespace orchestra;
class EspIO:public IO {
public:
 uint32_t us()override{return micros();}
 void delayUs(uint32_t n)override{delayMicroseconds(n);}
 bool track0(uint8_t pin)override{return digitalRead(pin)==LOW;}
 void outputEnable(bool on)override{digitalWrite(map::oe,on?LOW:HIGH);pinMode(map::oe,OUTPUT);}
 void beginSPI()override{
  pinMode(map::latch,OUTPUT);digitalWrite(map::latch,LOW);
  for(auto pin:map::track0)pinMode(pin,INPUT); // External pull-ups, never INPUT_PULLUP.
  SPI.begin(map::clock,-1,map::data,-1);
  pinMode(map::vhs,OUTPUT);digitalWrite(map::vhs,LOW);
  ledcSetup(0,20000,8);ledcAttachPin(map::vhs,0);ledcWrite(0,0);
 }
 uint32_t frame(const uint8_t* bytes,size_t size)override{
  SPI.beginTransaction(SPISettings(orchestra::physical::spiClockHz,MSBFIRST,SPI_MODE0));
  digitalWrite(map::latch,LOW);for(size_t i=0;i<size;++i)SPI.transfer(bytes[i]);
  digitalWrite(map::latch,HIGH);uint32_t edge=micros();SPI.endTransaction();return edge;
 }
 void vhs(uint8_t amp,float hz)override{ledcSetup(0,hz>0?hz:20000,8);ledcWrite(0,amp);}
} io;
Controller ctrl(io);
// Bounded TX ring. Never block on Serial: no print in the pulse generator.
char tx[2048];size_t txRead=0,txWrite=0;bool txOverflow=false;
void queue(const char* line){size_t count=strlen(line)+1;size_t free=(txRead+sizeof(tx)-txWrite-1)%sizeof(tx);if(count>free){txOverflow=true;return;}while(*line){tx[txWrite]=*line++;txWrite=(txWrite+1)%sizeof(tx);}tx[txWrite]='\n';txWrite=(txWrite+1)%sizeof(tx);}
void drainTx(){size_t available=Serial.availableForWrite();while(available--&&txRead!=txWrite){Serial.write(uint8_t(tx[txRead]));txRead=(txRead+1)%sizeof(tx);}if(txOverflow&&txRead==txWrite){txOverflow=false;queue("ERR TX_OVERFLOW");}}

struct BleInput { uint32_t session; uint16_t length; uint8_t bytes[512]; };
struct BleReply { uint32_t session; uint16_t length; uint8_t bytes[160]; };
QueueHandle_t bleRxQueue, bleTxQueue;
NimBLECharacteristic* bleTx = nullptr;
std::atomic<uint32_t> bleEpoch{0}, bleRxOverflow{0}, bleTxOverflow{0};
std::atomic<bool> bleConnected{false}, bleSubscribed{false};
std::atomic<int> notifyCode{-1};

// These callbacks only copy input/update transport flags. No parser, GPIO,
// Controller calls, Serial logging or notification transmission here.
class BleRxCallbacks : public NimBLECharacteristicCallbacks {
 void onWrite(NimBLECharacteristic* characteristic) override {
  const auto value = characteristic->getValue();
  if (!value.length()) return;
  const uint32_t epoch = bleEpoch.load();
  if (!bleConnected.load() || bleRxOverflow.load()==epoch) return;
  BleInput packet{}; packet.session=epoch; packet.length=value.length();
  if (packet.length>sizeof(packet.bytes)) { bleRxOverflow.store(epoch); return; }
  memcpy(packet.bytes,value.data(),packet.length);
  if (xQueueSend(bleRxQueue,&packet,0)!=pdTRUE) bleRxOverflow.store(epoch);
 }
} bleRxCallbacks;
class BleTxCallbacks : public NimBLECharacteristicCallbacks {
 void onSubscribe(NimBLECharacteristic*, ble_gap_conn_desc*, uint16_t value) override {
  bleSubscribed.store((value & 1)!=0);
 }
 void onStatus(NimBLECharacteristic*, Status, int code) override { notifyCode.store(code); }
} bleTxCallbacks;
class BleServerCallbacks : public NimBLEServerCallbacks {
 void onConnect(NimBLEServer*) override {
  bleSubscribed.store(false); bleEpoch.fetch_add(1); bleConnected.store(true);
 }
 void onDisconnect(NimBLEServer*) override {
  bleConnected.store(false); bleSubscribed.store(false); bleEpoch.fetch_add(1);
 }
} bleServerCallbacks;

class Replies : public ResponseSink {
public:
 void send(Transport origin,const char* line,uint32_t epoch=0) override {
  if (origin==Transport::Usb) { queue(line); return; }
  if (!bleConnected.load() || !bleSubscribed.load() || epoch!=bleEpoch.load()) return;
  // A correlated STOP acknowledgement must not sit behind obsolete telemetry.
  if (!strncmp(line,"STOPPED ",8)) xQueueReset(bleTxQueue);
  BleReply packet{}; packet.session=epoch;
  size_t count=strlen(line);
  if (count>=sizeof(packet.bytes)) { bleTxOverflow.store(epoch); return; }
  memcpy(packet.bytes,line,count);packet.bytes[count]='\n';packet.length=count+1;
  if (xQueueSend(bleTxQueue,&packet,0)!=pdTRUE) bleTxOverflow.store(epoch);
 }
} replies;
class TestLed : public TestOutput {
public:
 void set(bool on) override { digitalWrite(ble::testPin,on?HIGH:LOW); }
} testLed;
CommandProtocol protocol(ctrl,replies,testLed);

// NimBLE notify can allocate/wait inside the stack. Keep it OFF loopTask
// (motor scheduler, core 1). Only this core-0 worker transmits notifications.
bool currentBleSession(uint32_t epoch) {
 return bleConnected.load() && bleSubscribed.load() && epoch==bleEpoch.load();
}
void bleNotify(const BleReply& packet) {
 for(size_t offset=0;offset<packet.length && currentBleSession(packet.session);) {
  size_t count=packet.length-offset; if(count>20) count=20; // Works with MTU=23.
  notifyCode.store(-1);
  bleTx->notify(packet.bytes+offset,count);
  // The stack reports completion asynchronously from its own task. Do not
  // retransmit a fragment just because that callback has not run yet.
  uint32_t started=millis();
  while(notifyCode.load()==-1 && currentBleSession(packet.session) && uint32_t(millis()-started)<100)
   vTaskDelay(pdMS_TO_TICKS(1));
  if(notifyCode.load()==0) offset+=count;
  // Backpressure/retry without blocking STEP, and without flooding the stack.
  vTaskDelay(pdMS_TO_TICKS(20));
 }
}
void bleTransmitTask(void*) {
 for(;;) {
  BleReply packet{};
  if(xQueueReceive(bleTxQueue,&packet,pdMS_TO_TICKS(20))==pdTRUE) bleNotify(packet);
  uint32_t epoch=bleEpoch.load();
  if(bleTxOverflow.load()==epoch && currentBleSession(epoch) && uxQueueMessagesWaiting(bleTxQueue)==0) {
   bleTxOverflow.store(0);packet.session=epoch;
   const char* error="ERR TX_OVERFLOW\n";packet.length=strlen(error);
   memcpy(packet.bytes,error,packet.length);bleNotify(packet);
  }
 }
}
void beginBle() {
 bleRxQueue=xQueueCreate(8,sizeof(BleInput));
 bleTxQueue=xQueueCreate(32,sizeof(BleReply));
 if(!bleRxQueue || !bleTxQueue) { queue("ERR BLE_INIT"); return; }
 NimBLEDevice::init(ble::name);
 auto* server=NimBLEDevice::createServer();server->setCallbacks(&bleServerCallbacks,false);
 server->advertiseOnDisconnect(true);
 auto* service=server->createService(ble::service);
 auto* rx=service->createCharacteristic(ble::rx,NIMBLE_PROPERTY::WRITE|NIMBLE_PROPERTY::WRITE_NR,512);
 rx->setCallbacks(&bleRxCallbacks);
 bleTx=service->createCharacteristic(ble::tx,NIMBLE_PROPERTY::NOTIFY,160);
 bleTx->setCallbacks(&bleTxCallbacks);
 service->start();
 if(xTaskCreatePinnedToCore(bleTransmitTask,"ble-tx",4096,nullptr,1,nullptr,0)!=pdPASS) {
  queue("ERR BLE_INIT");return;
 }
 auto* advertising=NimBLEDevice::getAdvertising();
 advertising->addServiceUUID(ble::service);advertising->setScanResponse(true);advertising->start();
}
void pollBle() {
 if(!bleRxQueue) return;
 static BleInput packet{};static size_t offset=0;
 uint32_t epoch=bleEpoch.load();protocol.newBleSession(epoch);
 if(bleRxOverflow.load()==epoch && bleConnected.load()) {
  xQueueReset(bleRxQueue);packet.length=0;offset=0;protocol.bleOverflow();
  bleRxOverflow.compare_exchange_strong(epoch,0);
 }
 for(int budget=16;budget;--budget) {
  if(offset==packet.length) {
   if(xQueueReceive(bleRxQueue,&packet,0)!=pdTRUE) break;
   offset=0;
  }
  if(!bleConnected.load() || packet.session!=bleEpoch.load()) { offset=packet.length;continue; }
  protocol.newBleSession(packet.session);
  protocol.input(Transport::Ble,packet.bytes[offset++]);
 }
}
void setup(){
 digitalWrite(ble::testPin,LOW);pinMode(ble::testPin,OUTPUT);protocol.beginTest();
 ctrl.begin();Serial.begin(115200);queue("READY protocol=2 board=esp32");beginBle();
}
void loop(){
 ctrl.tick();
 protocol.pollErrors();
 // Separate 16-byte budgets: neither transport can starve the other or STEP.
 for(int budget=16;budget&&Serial.available();--budget) protocol.input(Transport::Usb,Serial.read());
 ctrl.tick();pollBle();
 drainTx();
}
