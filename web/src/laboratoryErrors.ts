import type {Device} from './runtime'

// Preserve request context and unknown codes; raw text remains in footer details.
const firmwareErrors:Record<string,string>={
 POWER_OFF:'ATX jest logicznie wyłączony. Włącz go w Settings przed testem REAL.',
 NOT_HOMED:'Brak potwierdzonego położenia FDD. Wymagany jest homing TRACK0 przed tonem.',
 DISABLED:'Kanał jest wyłączony w firmware. Sprawdź konfigurację urządzenia.',
 STRICT_OUTPUT:'Kanał jest zablokowany przez tryb STRICT TRACKS.',
 TRACK_REQUIRED:'Firmware wymaga przypisania ścieżki MIDI w trybie STRICT TRACKS.',
 TRACK:'Przypisanie ścieżki MIDI nie pasuje do konfiguracji kanału.',
 PROFILE:'Firmware odrzucił parametry profilu urządzenia.',
 TRAVEL_UNKNOWN:'Brakuje zatwierdzonego zakresu ruchu urządzenia.',
 BUSY:'Urządzenie jest zajęte. Zatrzymaj jego bieżącą operację.',
 VALUE:'Firmware odrzucił wartość parametru testu. Sprawdź zakres i zgodność firmware.',
 ID:'Firmware nie rozpoznaje numeru urządzenia. Sprawdź mapowanie kanałów.',
 COMMAND:'Firmware nie rozpoznaje komendy. Sprawdź zgodność wersji aplikacji i firmware.',
 LINE_TOO_LONG:'Komenda przekracza limit długości protokołu ESP32.',
 RX_OVERFLOW:'Przepełniony bufor odbiorczy ESP32. Sprawdź komunikację przed kolejnym testem.',
 TX_OVERFLOW:'Przepełniony bufor odpowiedzi ESP32. Sprawdź komunikację przed kolejnym testem.',
}
const profileErrors:Record<string,string>={
 OUTSIDE_MUSICAL_RANGE:'Częstotliwość jest poza zakresem profilu urządzenia',
 OUTSIDE_ALLOWED_BANDS:'Częstotliwość jest poza dozwolonymi pasmami urządzenia',
 STEP_INTERVAL_LIMIT:'Częstotliwość przekracza limit odstępu między krokami',
 STEP_INTERVAL_UNKNOWN:'Brakuje potwierdzonego odstępu między krokami',
 DEVICE_BUSY:'Urządzenie nie jest jeszcze gotowe na kolejny test',
 BURST_WINDOW:'Przekroczono limit uderzeń HDD w krótkiej serii',
 CONTINUOUS_HIT_RATE:'Przekroczono dozwoloną częstość uderzeń HDD',
 PHYSICAL_LIMIT:'Parametry przekraczają limit zapisany w profilu sprzętowym',
 PHYSICAL_UNKNOWN:'Profil nie potwierdza wymaganych parametrów fizycznych',
 TRAVEL_LIMIT_UNKNOWN:'Brakuje zatwierdzonego zakresu ruchu',
 PITCH_RATIO_UNKNOWN:'Brakuje przelicznika częstotliwości na ruch',
 ACCELERATION_UNKNOWN:'Brakuje parametrów przyspieszenia silnika',
}
export function laboratoryError(message:string,devices:Device[]):string{
 let description=message.replace(/BLE realtime overrun: execution ACK timeout \(250 ms\)/g, 'ESP32 nie potwierdziło wykonania pakietu w ciągu 250 ms. Odtwarzanie zatrzymano; przyczyna opóźnienia wymaga diagnostyki')
 .replace(/BLE realtime overrun: command queue full/g, 'Kolejka komend BLE jest pełna. Odtwarzanie zatrzymano, aby nie wykonywać zaległych nut')
 .replace(/BLE realtime overrun: stale commands/g, 'Komendy w kolejce BLE przekroczyły dopuszczalny wiek. Odtwarzanie zatrzymano')
 .replace(/ERR HOME_FAILED FDD=(\d+)\b/g,(_,id:string)=>{
  const name=devices.find(d=>d.id===`fdd-${id}`)?.name??`FDD ${id}`
  return `${name}: nie udało się zaparkować głowicy. Wykonanie przerwane. Sprawdź TRACK0 i połączenia stacji.`
 })
 description=description.replace(/\bERR ([A-Z_]+)\b/g,(original,code:string)=>firmwareErrors[code]??original)
 description=description.replace(/BLE realtime overrun:\s*([\d.]+) ms delivery lag/g,
  'Opóźnienie dostarczenia komend BLE: $1 ms. Harmonogram REAL został przerwany; sprawdź połączenie przed kolejnym testem.')
 description=description.replace(/READY protocol=\S+(?: board=\S+)?/g,
  'ESP32 uruchomiło się ponownie. Test przerwany; wymagane ponowne połączenie i potwierdzenie STOP.')
 if(/homing TRACK0 nie został potwierdzony/i.test(description)){
  description+=' Test tonu nie wystartował — upłynął czas oczekiwania na TRACK0.'
 }
 description=description.replace(/\b[A-Z][A-Z_]+\b/g,code=>profileErrors[code]??code)
 return description
}
