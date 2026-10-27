#pragma once
#include "ble_ota.h"
#include <esp_ota_ops.h>
#include <esp_system.h>
#include <mbedtls/ecdsa.h>
#include <mbedtls/sha256.h>

namespace orchestra { namespace ota {
#if __has_include("../.generated/ble_ota_key.h")
#include "../.generated/ble_ota_key.h"
#else
// Standalone builds remain possible, but remote flashing is disabled until a
// private installation key is provisioned by the shared USB service build.
constexpr bool keyProvisioned=false;
constexpr uint8_t installationPublicKey[65]={};
#endif
class EspStorage:public Storage {
 const esp_partition_t* partition=nullptr;
 esp_ota_handle_t handle=0;bool opened=false,checked=false;
 mbedtls_sha256_context sha;
 static bool equal(const uint8_t* a,const uint8_t* b,size_t n){uint8_t delta=0;for(size_t i=0;i<n;++i)delta|=a[i]^b[i];return delta==0;}
public:
 EspStorage(){mbedtls_sha256_init(&sha);}
 uint32_t capacity()override{
  if(!keyProvisioned)return 0;
  auto* next=esp_ota_get_next_update_partition(nullptr);
  return next&&next!=esp_ota_get_running_partition()?next->size:0;
 }
 void random(uint8_t* p,size_t n)override{esp_fill_random(p,n);}
 bool authenticate(const uint8_t* nonce,const uint8_t* manifest)override{
  if(!keyProvisioned)return false;
  uint8_t message[52],digest[32];memcpy(message,nonce,16);memcpy(message+16,manifest,36);
  if(mbedtls_sha256_ret(message,sizeof(message),digest,0))return false;
  mbedtls_ecdsa_context context;mbedtls_ecdsa_init(&context);
  mbedtls_mpi r,s;mbedtls_mpi_init(&r);mbedtls_mpi_init(&s);
  bool valid=mbedtls_ecp_group_load(&context.grp,MBEDTLS_ECP_DP_SECP256R1)==0&&
   mbedtls_ecp_point_read_binary(&context.grp,&context.Q,installationPublicKey,65)==0&&
   mbedtls_mpi_read_binary(&r,manifest+36,32)==0&&mbedtls_mpi_read_binary(&s,manifest+68,32)==0&&
   mbedtls_ecdsa_verify(&context.grp,digest,32,&context.Q,&r,&s)==0;
  mbedtls_mpi_free(&r);mbedtls_mpi_free(&s);mbedtls_ecdsa_free(&context);return valid;
 }
 bool begin(uint32_t size)override{
  abort();partition=esp_ota_get_next_update_partition(nullptr);
  if(!capacity()||size>partition->size||esp_ota_begin(partition,size,&handle)!=ESP_OK)return false;
  opened=true;return mbedtls_sha256_starts_ret(&sha,0)==0;
 }
 bool write(const uint8_t* p,size_t n)override{
  return opened&&esp_ota_write(handle,p,n)==ESP_OK&&mbedtls_sha256_update_ret(&sha,p,n)==0;
 }
 bool finish(const uint8_t* expected)override{
  uint8_t actual[32];
  if(!opened||mbedtls_sha256_finish_ret(&sha,actual)||!equal(actual,expected,32))return false;
  opened=false;checked=esp_ota_end(handle)==ESP_OK;return checked;
 }
 bool select()override{return checked&&esp_ota_set_boot_partition(partition)==ESP_OK;}
 void abort()override{if(opened)esp_ota_abort(handle);opened=checked=false;}
 void restart()override{esp_restart();}
};
}}
