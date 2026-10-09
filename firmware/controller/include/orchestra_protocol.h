#pragma once
#include "orchestra_core.h"

namespace orchestra {
enum class Transport : uint8_t { Usb, Ble };
namespace ble {
constexpr const char* name = "Electromechanical-MIDI";
constexpr const char* service = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E";
constexpr const char* rx = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E";
constexpr const char* tx = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E";
constexpr uint8_t testPin = 27;
}

// One instance per transport: fragments/overflow never cross USB/BLE lines.
struct CommandLine {
 enum Result { Pending, Complete, TooLong, Invalid };
 char text[96] = {};
 size_t used = 0;
 bool overflow = false, invalid = false, discard = false;
 void reset() { used = 0; overflow = invalid = discard = false; }
 void discardUntilNewline() { reset(); discard = true; }
 Result push(uint8_t ch) {
  if (discard) { if (ch == '\n') reset(); return Pending; }
  if (ch == '\r') return Pending;
  if (ch == '\n') {
   text[used] = 0;
   Result result = overflow ? TooLong : invalid ? Invalid : Complete;
   used = 0; overflow = invalid = false;
   return result;
  }
  if (ch == 0 || ch > 127) invalid = true;
  if (used < sizeof(text)-1) text[used++] = char(ch); else overflow = true;
  return Pending;
 }
};

struct ResponseSink {
 virtual ~ResponseSink() {}
 // Queue only; never perform Serial writes or BLE notify in this method.
 virtual void send(Transport, const char*, uint32_t session = 0) = 0;
};
struct TestOutput {
 virtual ~TestOutput() {}
 virtual void set(bool) = 0;
};

// The only command dispatcher for both transports. Device commands keep using
// Controller::command; the motor core and the Uno protocol are unchanged.
struct CommandProtocol {
 Controller& ctrl;
 ResponseSink& sink;
 TestOutput& led;
 bool testOn = false;
 CommandLine usbLine, bleLine;
 uint32_t bleSession = 0;
 uint32_t homeSession[4] = {};
 Transport homeOwner[4] = {Transport::Usb, Transport::Usb, Transport::Usb, Transport::Usb};
 CommandProtocol(Controller& c, ResponseSink& s, TestOutput& t): ctrl(c), sink(s), led(t) {}
 void reply(Transport origin, const char* line) { sink.send(origin, line, origin == Transport::Ble ? bleSession : 0); }
 void beginTest() { testOn = false; led.set(false); }
 void newBleSession(uint32_t session) {
  if (bleSession != session) { bleSession = session; bleLine.reset(); }
 }
 void bleOverflow() { bleLine.discardUntilNewline(); reply(Transport::Ble, "ERR RX_OVERFLOW"); }
 void input(Transport origin, uint8_t ch) {
  CommandLine& line = origin == Transport::Usb ? usbLine : bleLine;
  switch (line.push(ch)) {
   case CommandLine::Complete: execute(origin, line.text); break;
   case CommandLine::TooLong: reply(origin, "ERR LINE_TOO_LONG"); break;
   case CommandLine::Invalid: reply(origin, "ERR COMMAND"); break;
   default: break;
  }
 }
 void execute(Transport origin, const char* line) {
  if (strlen(line) >= sizeof(usbLine.text)) { reply(origin, "ERR LINE_TOO_LONG"); return; }
  if (!strncmp(line, "TEST", 4) && (line[4] == ' ' || line[4] == 0)) {
   if (!strcmp(line, "TEST ON")) testOn = true;
   else if (!strcmp(line, "TEST OFF")) testOn = false;
   else if (!strcmp(line, "TEST TOGGLE")) testOn = !testOn;
   else if (strcmp(line, "TEST STATUS")) { reply(origin, "ERR COMMAND"); return; }
   if (strcmp(line, "TEST STATUS")) led.set(testOn);
   reply(origin, testOn ? "TEST ON" : "TEST OFF");
   return;
  }
  // Correlated acknowledgement is emitted only after hardware is stopped.
  // Legacy ALL STOP remains silent and compatible with existing clients.
  if (!strncmp(line,"ALL STOP ",9)) {
   const char* token=line+9;
   size_t length=strlen(token);
   if (!length || length>10 || strspn(token,"0123456789")!=length) {
    reply(origin,"ERR VALUE"); return;
   }
   ctrl.command("ALL STOP");
   char ack[32];snprintf(ack,sizeof(ack),"STOPPED %s",token);reply(origin,ack);
   return;
  }
  // Retain the existing explicit bring-up diagnostic through either transport.
  if (!strncmp(line, "DIAG BIT ", 9)) {
   char* end; long bit = strtol(line+9, &end, 10);
   if (*end || bit < 0 || bit > 39) reply(origin, "ERR VALUE");
   else {
    ctrl.allStop(); ctrl.bus.safeState();
    for (int b=0; b<40; ++b) ctrl.bus.setBit(b, b==bit);
    ctrl.bus.flush(); reply(origin, "OK DIAG: ACTUATORS MUST BE DISCONNECTED");
   }
   return;
  }
  uint32_t started[4]; bool homing[4];
  for (int i=0; i<4; ++i) { started[i]=ctrl.fdd[i].homeStartedUs; homing[i]=ctrl.fdd[i].homing; }
  const char* result = ctrl.command(line);
  for (int i=0; i<4; ++i)
   if (ctrl.fdd[i].homing && (!homing[i] || started[i]!=ctrl.fdd[i].homeStartedUs)) { homeOwner[i]=origin; homeSession[i]=bleSession; }
  if (!strcmp(result, "STATUS")) status(origin);
  else if (strcmp(result, "OK")) reply(origin, result); // Existing successful motor commands stay silent.
 }
 void pollErrors() {
  for (int i=0; i<4; ++i) if (ctrl.fdd[i].error) {
   char line[64]; snprintf(line, sizeof(line), "ERR %s FDD=%d", ctrl.fdd[i].error, i+1);
   sink.send(homeOwner[i], line, homeSession[i]); ctrl.fdd[i].error = nullptr;
  }
 }
 void status(Transport origin) {
  char line[160]; reply(origin, "STATUS BEGIN");
  snprintf(line,sizeof(line),"STATUS CTRL board=esp32 protocol=2 ready=1 stop_ack=1 hardware_profiles=1 strict_tracks=1 strict_active=%d",ctrl.strictTracks);
  reply(origin,line);
  for (int i=0; i<4; ++i) {
   auto& d=ctrl.fdd[i]; bool active=ctrl.io.track0(d.track0Pin);
   snprintf(line,sizeof(line),"STATUS FDD %d enabled=%d homed=%d playing=%d homing=%d dir=%s away_steps=%u track0=%d raw=%d hz=%.2f reversing=%d profile=FDD",i+1,d.enabled,d.homed,d.playing,d.homing,d.directionAway?"away":"toward",d.awaySteps,active,!active,d.hz,!due(ctrl.io.us(),d.directionReadyUs)); reply(origin,line);
  }
  for(int i=0;i<4;++i){snprintf(line,sizeof(line),"STATUS HDD %d enabled=%d busy=%d mode=percussion state=%s ready_at=%lu hz=0 safety=UNKNOWN profile=HDD_PERCUSSION",i+1,ctrl.hdd[i].enabled,ctrl.hdd[i].state!=Hdd::Idle,ctrl.hdd[i].state==Hdd::Park?"RESET":ctrl.hdd[i].state==Hdd::Settle?"SETTLE":ctrl.hdd[i].state==Hdd::Strike?"STRIKE":"READY",(unsigned long)(ctrl.hdd[i].state==Hdd::Idle?ctrl.io.us():ctrl.hdd[i].deadline+(ctrl.hdd[i].state==Hdd::Park?ctrl.hdd[i].settleUs+ctrl.hdd[i].strikeUs:ctrl.hdd[i].state==Hdd::Settle?ctrl.hdd[i].strikeUs:0)));reply(origin,line);}
  for(int i=0;i<4;++i){snprintf(line,sizeof(line),"STATUS SLED %d enabled=%d playing=%d hz=%.2f position=%d dir=%s soft_min=%d soft_max=%d rate=%.0f target=%.0f pos_conf=LOW ramp=%d",i+1,ctrl.sled[i].enabled,ctrl.sled[i].playing,ctrl.sled[i].hz,ctrl.sled[i].position,ctrl.sled[i].forward?"fwd":"rev",Sled::SOFT_MIN,ctrl.sled[i].softMax,ctrl.sled[i].currentStepRate,ctrl.sled[i].targetStepRate,fabsf(ctrl.sled[i].currentStepRate-ctrl.sled[i].targetStepRate)>1);reply(origin,line);}
  for(int i=0;i<2;++i){snprintf(line,sizeof(line),"STATUS TRAY %d enabled=%d busy=%d",i+1,ctrl.tray[i].enabled,ctrl.tray[i].busy);reply(origin,line);}
  snprintf(line,sizeof(line),"STATUS VHS enabled=%d amp=%d hz=%.2f",ctrl.vhsEnabled,ctrl.amp,ctrl.frequency);reply(origin,line);reply(origin,"STATUS END");
 }
};
}
