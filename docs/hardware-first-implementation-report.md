# Raport wdrożenia hardware-first

## 1. Architektura przed / po

Przed: allocator korzystał z profili preview, a komendy hardware powstawały ze
zdarzeń VirtualOrchestra. Teraz fizyczna ścieżka ESP32 prowadzi przez centralne
HardwareProfile, ocenę kandydatów, PerformancePlan i bezpośredni scheduler
komend. Normalizacja duplikatów, analiza semantyczna i istniejąca artykulacja
pozostały wspólne. Virtual-only/Uno zachowują dotychczasową ścieżkę.

## 2. Zmienione pliki

- `Dockerfile` — dostarcza config do kontenera.
- `README.md` — odsyłacz do modelu hardware-first.
- `firmware/controller/include/orchestra_core.h` — wykonawcze profile, rampa DVD,
  hamowanie, parametry czasowe poszczególnych FDD/HDD; bez precyzyjnego licznika FDD.
- `firmware/controller/include/orchestra_protocol.h` — rozszerzone STATUS.
- `firmware/controller/src/esp32/main.cpp` — centralna stała zegara SPI, nadal 1 MHz.
- `host/playback/allocator.py` — wejście do fizycznej gałęzi planowania.
- `host/playback/engine.py` — integracja runtime, inventory, konfiguracja wykonawcza,
  telemetria i ochrona przed firmware bez obsługi profili.
- `host/playback/hardware.py` — komendy bezpośrednio z ocenionego planu.
- `host/playback/orchestra.py` — konfiguracja inventory i kompatybilne defaults.
- `host/playback/performance.py` — metadane ocen/telemetrii w planie i raporcie.
- `host/playback/virtual.py` — tylko kompatybilne dodatkowe pola konfiguracji;
  bez nowego physics-aware renderera.
- `host/tests/test_esp32_firmware.py` — native regression/rampa/profile.
- `host/tests/test_esp32_protocol.py` — rozszerzony i ograniczony rozmiarem STATUS.

## 3. Nowe pliki

- `config/hardware-profiles/theoretical.json`
- `config/hardware-profiles/instances.json`
- `host/playback/hardware_profiles.py`
- `host/playback/hardware_arranger.py`
- `scripts/generate_hardware_profiles.py`
- `firmware/controller/include/hardware_profiles_generated.h`
- `host/tests/test_hardware_profiles.py`
- `docs/research/orkiestra-model-teoretyczny.md` — kopia dostarczonego raportu.
- `docs/hardware-first.md` — API, pipeline, kalibracja, ograniczenia, checklist.
- `docs/hardware-first-implementation-report.md` — ten raport.

## 4. Struktury / profile

HardwareQuantity, HardwareProfile, HardwareRegistry, HardwareContext,
HardwareDeviceState, HardwareNote i HardwareEvaluation. Profile FDD, DVD_SLED,
HDD_PERCUSSION, HDD_TONAL oraz kompatybilny VHS. Dane przechowują evidence,
confidence, źródło, jednostkę i niepewność.

## 5. Urządzenia

- **FDD:** wzory minimalnej długości i reversal/travel; zachowana kalibracja
  FDD1 do 410 Hz, guard 72 i działająca polaryzacja DIR. TRACK0 pozostaje prawdą;
  firmware nie dodaje dokładnego position trackingu. Inne FDD mają teoretyczne
  wykonawcze priory, bez udawania kalibracji.
- **DVD:** audioFrequency oddzielone od stepRate, signed velocity ramp,
  przyspieszenie i wcześniejsze hamowanie. DVD1 zachowuje względne 140;
  DVD2–4 UNKNOWN, bez automatycznego ruchu. Sekwencja faz i mapowanie niezmienione.
- **HDD percussion:** readiness mechaniczne/thermal/impact, limity planowania
  ciągłego i burst, diagnostyczne fazy. Dotychczasowe 40/40/4 ms zachowane;
  pomierzone ustawienia mogą być przekazane jako profil tej instancji.
  Mocniejszy impuls z nieznanymi ratingami nie jest automatycznie autoryzowany.
- **HDD tonal:** osobny profil/rola, scoring harmonicznych i ciągłości stanu;
  fizyczny tonal executor pozostaje zablokowany.

## 6. Dobór urządzenia

Trzy osobne wyniki: TIMING, QUALITY, PHYSICAL_LOAD. Każdy może być
PASS / DEGRADED / UNKNOWN / BLOCKED. Kandydat musi być autoryzowany i mieścić
się w dopuszczalnym oknie czasowym. Kolejność: quality → transition →
braking/reversal → confidence → deterministyczne ID. Gałąź fizyczna nie
wykrada głosów przez nieuwzględnione przejścia actuatorów.

Końcowe długości po sustain są ponownie sprawdzane. Reinforcement jest
filtrowany przez rzeczywiste inventory/profile i rezerwacje nut głównych;
DVD duble korzystają obecnie tylko z końcowych wolnych miejsc.

## 7. Teoria i pomiary

Teoria → zapisany profil konkretnego lane → jawny hardwareOverrides.
MEASURED nie jest nadpisywane niepomierzoną hipotezą. Jawny null unieważnia
wartość, nie uruchamia ukrytego fallbacku. DVD1 nie kalibruje pozostałych DVD.
Zakres FDD1 [130,410] ma DERIVED: pomierzony jest górny endpoint, dolne 130
pozostało konfiguracją, nie nowym pomiarem.

## 8. UNKNOWN

UNKNOWN nie jest zerem, nieskończonością, PASS ani dowodem bezpieczeństwa.
Brak danych travel/timingu wymaganych do wykonania blokuje danego kandydata.
Brak safety ratings jest widoczny w PHYSICAL_LOAD; nie autoryzuje agresywnego
sterowania. Dotychczasowe nominalne drive może pozostać planowane, z jawnym
UNKNOWN i bez deklaracji fizycznego bezpieczeństwa.

## 9. Telemetria

Per-note oceny, candidate reasons i qualityReasons, oraz per-device requested,
accepted, played, dropped, degraded, dropReasons, transitions, przewidywane
reversals/travelReversals, accelerationLimited, tooShort, outsidePreferredRange,
outsideStableRange i physicalUnknown. Efektywne profile i przewidywane end states
są w PerformancePlan/report/snapshot `hardwarePlanning`.

Liczniki są oznaczone **planned**, nie pomierzone. Requested/dropped per-device
liczą próby oceny/odmowy kandydatów, a played — wybrane zdarzenia planu.
Nie udajemy potwierdzenia ruchu/dźwięku. Realne niskopoziomowe wartości pochodzą
z osobnego STATUS. Inventory jest deklaracją operatora: enabled nie jest
czujnikiem podłączonego silnika.

Drop reasons obejmują m.in. NO_DEVICE, TRAVEL_LIMIT_UNKNOWN,
STEP_INTERVAL_LIMIT, TIMING_CONFLICT, DEVICE_BUSY, PHYSICAL_UNKNOWN,
PHYSICAL_LIMIT i HDD_TONAL_EXECUTOR_UNAVAILABLE.

## 10. Testy

Końcowe polecenie:

```sh
.venv/bin/python -m unittest discover -s host/tests
```

**632 testy, OK** (45,610 s). W tym **53 testy native firmware/BLE/protokołu**
i **80 testów nowych profili, fizycznego arrangera oraz integracji runtime**.
Wszystkie uruchomione z atrapami transportu/clock/GPIO, bez portu ani urządzenia.
Pokryto m.in. rampa/deceleracja/signed reversal, travel UNKNOWN, kalibracje,
limity/quality, harmoniczne, readiness/rate, stabilne mapowanie, konfigurację
wykonawczą i rozmiar całego STATUS w istniejących buforach Serial/BLE.

`generate_hardware_profiles.py --check`: OK.
`git diff --check`: OK.
Frontend niezmieniony; testów/builda frontendu w tym zadaniu nie uruchamiano.

## 11. Build

`pio run -e esp32`: **SUCCESS** (5,980 s, końcowy firmware).
RAM 38 916 / 327 680 B (11,9%), Flash 615 977 / 1 310 720 B (47,0%).
Nie użyto upload. Uno firmware nie było modyfikowane; jego build nie był potrzebny
ani uruchamiany w tym kroku.

## 12. Co pozostaje niezweryfikowane

Fizyczne ratingi prądu/energii/temperatury, rzeczywisty pitchRatio DVD,
trajektoria bez czujnika, rzeczywiste rezonanse/centrowanie HDD i psychoakustyczna
trafność score. Teoretyczna rampa nie dowodzi, że konkretny motor utrzyma kroki.
HDD tonal wymaga osobnego wykonawczego projektu i pomiarów; nie dodano
niezweryfikowanego oscylatora. Tray/free-stepper nie mają fizycznego profilu w
raporcie, więc nowy planner ich nie autoryzuje; istniejące komendy pozostają.

## 13. Pierwsze testy fizyczne — tylko lista

1. Sprawdzić wiring, inventory i ręczną startową pozycję DVD1.
2. STATUS, polaryzacja DIR/TRACK0, STOP i watchdog na kontrolowanym teście.
3. FDD1: powrót TRACK0, zakres 130–410, czasy STEP/reversal.
4. DVD1: niska prędkość, rampa, signed reversal, wcześniejsze hamowanie,
   weryfikacja travel i pomiar pitchRatio; pozostałe DVD osobno.
5. HDD1: dotychczasowy impuls 4 ms, reset/settle, pomiary prądu/temperatury/impact.
6. Zapisać wyniki w profilach konkretnych instancji.
7. Porównać rzadki i gęsty MIDI z reasons/qualityReasons i pomiarami STEP.
8. Przed HDD tonal osobno zbadać centrowanie/excursion/current/resonances.

**Żaden test fizyczny nie został wykonany.** Nie flashowano, nie otwierano
USB/BLE, nie wysyłano komend do silników. Aplikacji nie restartowano, bo może
automatycznie połączyć BLE i wykonać HOME. Bez commita/pusha.
