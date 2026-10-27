#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>

namespace orchestra { namespace ota {
constexpr const char* controlUuid="6E400005-B5A3-F393-E0A9-E50E24DCCA9E";
constexpr const char* dataUuid="6E400006-B5A3-F393-E0A9-E50E24DCCA9E";
enum Op:uint8_t { Query=1, Meta=2, Begin=3, Data=4, End=5, Commit=6, Abort=7,
 Challenge=0x81, Ready=0x82, Progress=0x83, Verified=0x84, Committed=0x85, Aborted=0x86, Error=0xff };
enum Failure:uint8_t { Unsupported=1, Protocol=2, Unsafe=3, Auth=4, Size=5, Flash=6,
 Offset=7, Digest=8, State=9, Timeout=10, Overflow=11 };
inline uint32_t read32(const uint8_t* p){return uint32_t(p[0])|(uint32_t(p[1])<<8)|(uint32_t(p[2])<<16)|(uint32_t(p[3])<<24);}
inline void write32(uint8_t* p,uint32_t n){for(int i=0;i<4;++i)p[i]=uint8_t(n>>(8*i));}
struct Storage {
 virtual ~Storage(){}
 virtual uint32_t capacity()=0;
 virtual void random(uint8_t*,size_t)=0;
 virtual bool authenticate(const uint8_t* nonce,const uint8_t* manifest)=0;
 virtual bool begin(uint32_t)=0;
 virtual bool write(const uint8_t*,size_t)=0;
 virtual bool finish(const uint8_t* expectedSha)=0;
 virtual bool select()=0;
 virtual void abort()=0;
 virtual void restart()=0;
};
struct Replies {
 virtual ~Replies(){}
 virtual void send(const uint8_t*,size_t,uint32_t epoch)=0;
};

// Main-loop only. GATT callbacks must enqueue, never erase/write flash or move
// hardware. Six input fragments per credit fit the adapter's eight RX slots.
class Session {
 enum Phase { Idle, Writing, Checked, Selected, Rebooting } phase=Idle;
 Storage& storage;Replies& replies;
 uint8_t nonce[16]={},manifest[100]={};size_t metaUsed=0;
 bool challengeValid=false;
 uint32_t epoch=0,total=0,received=0,last=0,rebootAt=0;
 void reply(uint8_t op,bool offset=false){uint8_t b[5]={op};write32(b+1,received);replies.send(b,offset?5:1,epoch);}
 void error(uint8_t code){uint8_t b[2]={Error,code};replies.send(b,2,epoch);}
 void clear(){storage.abort();phase=Idle;challengeValid=false;metaUsed=0;}
 void fail(uint8_t code){clear();error(code);}
public:
 Session(Storage& s,Replies& r):storage(s),replies(r){}
 bool busy()const{return phase!=Idle;}
 void overflow(){if(phase!=Selected&&phase!=Rebooting)fail(Overflow);}
 void input(const uint8_t* p,size_t n,uint32_t session,uint32_t now,bool powerOff){
  if(!n)return;
  if(session!=epoch){if(busy()){if(phase!=Selected&&phase!=Rebooting)clear();else return;}epoch=session;challengeValid=false;metaUsed=0;}
  uint8_t op=p[0];
  if(op==Query){
   if(n!=1||busy()){error(State);return;}
   if(!storage.capacity()){error(Unsupported);return;}
   storage.random(nonce,sizeof(nonce));challengeValid=true;metaUsed=0;last=now;
   uint8_t b[18]={Challenge,1};memcpy(b+2,nonce,16);replies.send(b,sizeof(b),epoch);return;
  }
  // An unauthenticated nearby client cannot abort an authenticated update.
  // Abort is reserved for the BLE epoch that owns it; reconnect clears writing.
  if(op==Abort){if(n!=1||phase==Selected||phase==Rebooting){error(State);return;}clear();reply(Aborted);return;}
  if(op==Meta){
   if(busy()||!challengeValid||uint32_t(now-last)>10000000u||n<3||p[1]!=metaUsed||metaUsed+n-2>sizeof(manifest)){error(Protocol);return;}
   memcpy(manifest+metaUsed,p+2,n-2);metaUsed+=n-2;return;
  }
  if(op==Begin){
   if(n!=1||busy()||!challengeValid||metaUsed!=sizeof(manifest)||uint32_t(now-last)>10000000u){error(State);return;}
   challengeValid=false; // Every authentication attempt consumes its nonce.
   if(!powerOff){fail(Unsafe);return;}
   total=read32(manifest);received=0;
   if(!total||total>storage.capacity()){fail(Size);return;}
   if(!storage.authenticate(nonce,manifest)){fail(Auth);return;}
   if(!storage.begin(total)){fail(Flash);return;}
   phase=Writing;last=now;reply(Ready,true);return;
  }
  if(phase==Selected||phase==Rebooting){error(State);return;}
  if(!powerOff||!busy()||uint32_t(now-last)>10000000u){fail(!powerOff?Unsafe:State);return;}
  last=now;
  if((op&0x7f)==Data){
   if(phase!=Writing||n<6){fail(Protocol);return;}
   if(read32(p+1)!=received||n-5>total-received){fail(Offset);return;}
   if(!storage.write(p+5,n-5)){fail(Flash);return;}
   received+=n-5;if(op&0x80)reply(Progress,true);return;
  }
  if(op==End){
   if(n!=1||phase!=Writing||received!=total){fail(State);return;}
   if(!storage.finish(manifest+4)){fail(Digest);return;}
   phase=Checked;reply(Verified);return;
  }
  if(op==Commit){
   if(n!=1||phase!=Checked){fail(State);return;}
   if(!storage.select()){fail(Flash);return;}
   phase=Selected;rebootAt=now+500000u;reply(Committed);return;
  }
  fail(Protocol);
 }
 void tick(uint32_t now,uint32_t session,bool powerOff){
  if(phase==Selected){if(int32_t(now-rebootAt)>=0){phase=Rebooting;storage.restart();}return;}
  if(phase==Rebooting)return;
  if(busy()&&(session!=epoch||!powerOff||uint32_t(now-last)>10000000u))fail(session!=epoch?State:!powerOff?Unsafe:Timeout);
 }
};
}}
