#include <Arduino.h>
#include <SPI.h>
#include "orchestra_core.h"
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
  SPI.beginTransaction(SPISettings(1000000,MSBFIRST,SPI_MODE0));
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
void status(){
 char line[160];queue("STATUS BEGIN");queue("STATUS CTRL board=esp32 protocol=2 ready=1");
 for(int i=0;i<4;++i){auto& d=ctrl.fdd[i];snprintf(line,sizeof(line),"STATUS FDD %d enabled=%d homed=%d playing=%d homing=%d dir=%s away_steps=%u track0=%d raw=%d hz=%.2f",i+1,d.enabled,d.homed,d.playing,d.homing,d.directionAway?"away":"toward",d.awaySteps,io.track0(d.track0Pin),digitalRead(d.track0Pin),d.hz);queue(line);}
 for(int i=0;i<4;++i){snprintf(line,sizeof(line),"STATUS HDD %d enabled=%d busy=%d",i+1,ctrl.hdd[i].enabled,ctrl.hdd[i].state!=Hdd::Idle);queue(line);}
 for(int i=0;i<4;++i){snprintf(line,sizeof(line),"STATUS SLED %d enabled=%d playing=%d hz=%.2f",i+1,ctrl.sled[i].enabled,ctrl.sled[i].playing,ctrl.sled[i].hz);queue(line);}
 for(int i=0;i<2;++i){snprintf(line,sizeof(line),"STATUS TRAY %d enabled=%d busy=%d",i+1,ctrl.tray[i].enabled,ctrl.tray[i].busy);queue(line);}
 snprintf(line,sizeof(line),"STATUS VHS enabled=%d amp=%d hz=%.2f",ctrl.vhsEnabled,ctrl.amp,ctrl.frequency);queue(line);queue("STATUS END");
}
void setup(){ctrl.begin();Serial.begin(115200);queue("READY protocol=2 board=esp32");}
void loop(){
 ctrl.tick();
 for(int i=0;i<4;++i)if(ctrl.fdd[i].error){char line[64];snprintf(line,sizeof(line),"ERR %s FDD=%d",ctrl.fdd[i].error,i+1);queue(line);ctrl.fdd[i].error=nullptr;}
 static char line[96];static size_t used=0;static bool overflow=false;
 // At most 16 bytes/iteration; motor scheduling remains responsive.
 for(int budget=16;budget&&Serial.available();--budget){char ch=Serial.read();if(ch=='\r')continue;if(ch=='\n'){
  line[used]=0;if(overflow)queue("ERR LINE_TOO_LONG");
  else if(!strncmp(line,"DIAG BIT ",9)){
   char* end;long bit=strtol(line+9,&end,10);
   if(*end||bit<0||bit>39)queue("ERR VALUE");else{ctrl.allStop();ctrl.bus.safeState();for(int b=0;b<40;++b)ctrl.bus.setBit(b,b==bit);ctrl.bus.flush();queue("OK DIAG: ACTUATORS MUST BE DISCONNECTED");}
  }else{const char* reply=ctrl.command(line);if(!strcmp(reply,"STATUS"))status();else if(strcmp(reply,"OK"))queue(reply);}
  used=0;overflow=false;
 }else if(used<sizeof(line)-1)line[used++]=ch;else overflow=true;}
 drainTx();
}
