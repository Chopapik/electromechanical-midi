import {describe,it,expect} from 'vitest'
import {laboratoryError} from './laboratoryErrors'
import type {Device} from './runtime'
const devices=[{id:'fdd-8',name:'Stacja ósma'}] as Device[]
describe('Laboratory error mapping',()=>{
 it('maps all HOME failures using actual names, preserving uncertainty and other devices',()=>{
  const result=laboratoryError('Nieznany stan sprzętu. ERR HOME_FAILED FDD=8; ERR HOME_FAILED FDD=2',devices)
  expect(result).toContain('Nieznany stan sprzętu')
  expect(result).toContain('Stacja ósma: nie udało się zaparkować')
  expect(result).toContain('FDD 2: nie udało się zaparkować')
 })
 it.each([
  ['POWER_OFF','ATX jest logicznie wyłączony'],['NOT_HOMED','homing TRACK0'],
  ['DISABLED','Kanał jest wyłączony'],['STRICT_OUTPUT','STRICT TRACKS'],
  ['TRACK_REQUIRED','przypisania ścieżki'],['TRACK','Przypisanie ścieżki'],
  ['PROFILE','parametry profilu'],['TRAVEL_UNKNOWN','zakresu ruchu'],
  ['BUSY','Urządzenie jest zajęte'],['VALUE','wartość parametru'],
  ['ID','numeru urządzenia'],['COMMAND','nie rozpoznaje komendy'],
  ['LINE_TOO_LONG','limit długości'],['RX_OVERFLOW','bufor odbiorczy'],['TX_OVERFLOW','bufor odpowiedzi'],
 ])('maps %s without losing request context',(code,expected)=>{
  const result=laboratoryError(`Stacja ósma · zmiana parametrów: ERR ${code}`,devices)
  expect(result).toContain('Stacja ósma · zmiana parametrów:')
  expect(result).toContain(expected)
 })
 it.each([
  ['OUTSIDE_MUSICAL_RANGE','poza zakresem profilu'],['OUTSIDE_ALLOWED_BANDS','poza dozwolonymi pasmami'],
  ['STEP_INTERVAL_LIMIT','odstępu między krokami'],['BURST_WINDOW','limit uderzeń HDD'],
  ['PHYSICAL_UNKNOWN','nie potwierdza wymaganych parametrów'],
 ])('maps profile rejection %s while preserving device context',(code,expected)=>{
  const result=laboratoryError(`Stacja ósma · uruchomienie testu: Profil nie dopuszcza testu: ${code}`,devices)
  expect(result).toContain('Stacja ósma · uruchomienie testu:')
  expect(result).toContain(expected)
 })
 it('preserves unknown codes and unrelated errors verbatim',()=>{
  for(const text of ['ERR FUTURE_ERROR','Profil nie dopuszcza testu: FUTURE_PROFILE_REASON','Brak połączenia z ESP32']){
   expect(laboratoryError(text,devices)).toBe(text)
  }
 })
 it('retains the measured delivery lag and distinguishes restart from home failure',()=>{
  expect(laboratoryError('BLE realtime overrun: 259 ms delivery lag',devices)).toContain('259 ms')
  expect(laboratoryError('READY protocol=2 board=esp32',devices)).toContain('ESP32 uruchomiło się ponownie')
 })
})
