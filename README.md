# Orkiestra elektromechaniczna

Lokalny odtwarzacz MIDI: Python/FastAPI, React/TypeScript i kontroler
ESP32-WROOM-32. REAL steruje urządzeniami przez BLE; VIRTUAL wykonuje ten sam
harmonogram przez Web Audio w przeglądarce. UNO pozostaje osobnym, starszym
firmware i narzędziami CLI, a nie wyborem kontrolera w obecnym UI.

## Uruchamianie

```sh
docker compose up -d --build orchestra
docker compose ps orchestra
```

Aplikacja i API: <http://localhost:5173>. MIDI są w `midi/` (bind mount).
Ustawienia głośników przetrwają przebudowę dzięki wolumenowi `speaker-settings`.
Kod i konfiguracja są kopiowane do obrazu: po ich zmianie przebuduj kontener.

Na macOS Docker wymaga natywnej bramki BLE:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r host/requirements.txt
.venv/bin/python host/ble_gateway.py
```

Compose łączy się z `host.docker.internal:8766`; szczegóły uprawnień Bluetooth,
instalacji usługi i USB są w [instrukcji ESP32](docs/esp32-orchestra.md#macos--docker).
Bramka nie zastępuje BLE połączeniem Serial. Flashowanie wymaga USB/CP2102.

Bez prób połączenia ze sprzętem:

```sh
ORCHESTRA_OFFLINE=1 docker compose up -d --build orchestra
```

Aplikacja zawsze startuje w REAL, również offline. W `/settings` → **Output**
włącz **Virtual debug · Web Audio** do odsłuchu bez kontrolera. REAL offline
pozwala importować i aranżować MIDI, ale blokuje Play. Po odzyskaniu BLE nie ma
automatycznego wznowienia utworu ani homingu przy samym połączeniu.

Uruchomienie natywne po instalacji zależności:

```sh
.venv/bin/python -m host.web.server --offline --port 8000
npm --prefix web ci
npm --prefix web run dev
```

Vite przekazuje API/WS do portu 8000. Produkcyjny backend serwuje zbudowane
`web/dist`. Interakcja z przeglądarką jest wymagana do uruchomienia Web Audio.
FDD/DVD są proceduralnym modelem impulsów i rezonansów, HDD modelem transjentów.
Velocity/CC nie sterują fizyczną amplitudą FDD/DVD; konfiguracja STEP jej nie
przekazuje. Barwa i poziom VIRTUAL nie są pomiarem tych egzemplarzy.

## Architektura i pipeline MIDI

```text
MIDI → MidiSource → normalizacja duplikatów i klasyfikacja
     → alokacja z profilami mechanicznymi → artykulacja / Source Continuity
     → rezerwacje UNISON i reinforcement → DVD sustain / walidacja chronologii
     → końcowe ograniczenie ataków FDD → PerformancePlan
     → compile_plan → ExecutionTimeline → Player → Router → REAL lub VIRTUAL
```

Dokładna kolejność refinements zależy od presetu: Adaptive i pary pracują na
planie bazowym, zanim wspólny runtime ograniczy ataki FDD.

- `host/midi_source.py`: nuty, kanały, tempo, metrum, programy i tekst MIDI.
- `host/playback/analysis.py`, `semantic.py`, `sound_roles.py`: role muzyczne,
  wokal/lead, bas, perkusja i jawne efekty nietonalne; to heurystyki, nie odsłuch.
- `host/playback/duplicates.py`: normalizacja double-trackingu z proweniencją.
- `host/runtime/arranger.py` i `host/playback/hardware_arranger.py`: deterministyczny
  plan z zadeklarowanego inventory, niezależny od połączenia i wyboru wyjścia.
- `host/runtime/compiler.py`: uporządkowane komendy ze stabilnym `device_id`.
  Stykające się tony nie potrzebują STOP; DVD ma tolerancję 1 ns na błąd float.
- `player.py`, `router.py`, `outputs.py` w `host/runtime/`: jeden zegar i właściciel
  wykonania, jedno aktywne wyjście, mute i unieważnianie starych kolejek.
- `web/src/virtualOutput.ts`, `mechanicalAudio.ts`: Web Audio z wyprzedzeniem
  150 ms, synchronizacją zegara i anulowaniem epok. Modele dźwięku są syntetyczne.
- `host/runtime/device_service.py`: wyłączny serwis po STOP, upload USB i HOME.
  Reset przez BLE jest niedostępny.

STOP REAL wymaga `ALL STOP <token>` / `STOPPED <token>`. Brak potwierdzenia lub
utrata aktywnego transportu nie oznacza potwierdzonego zatrzymania sprzętu;
firmware ma też watchdog 3 s. STOP przechodzi mimo mute. Zmiana wyjścia lub
właściciela zatrzymuje wykonanie. Seek podczas gry kontynuuje od nowej pozycji,
a podczas pauzy zachowuje pauzę. Zamknięcie karty/utrata synchronizacji wycisza
Web Audio. Szczegóły: [ESP32](docs/esp32-orchestra.md), [profile](docs/hardware-first.md).

## Skład i sterowanie

Źródłem inventory jest lista `devices` w `config/devices.json` (opisowe pole
`name` może zawierać dawną liczebność). Profile są w
`config/hardware-profiles/{theoretical,instances}.json`.

| Rodzina | Liczba i stan | Rola / fizyczne wyjście |
| --- | --- | --- |
| FDD | 4 włączone | Riffy/harmonia; STEP/DIR przez 74HC595, TRACK0 do ESP32 |
| DVD stepper | 4 włączone | Tonalne głosy/tło; DRV8833, ciągły obrót |
| PC Speaker | 1 włączony | Wykryty wokal/lead, GPIO25, `vhs-1` / `drum:1` |
| PC Speaker FX | 1 włączony | Tonalne ozdobniki, GPIO26, `pc-speaker-fx` / `drum:2` |
| HDD VCM | 4 włączone | Perkusja przez DRV8833; brak wykonawcy tonalnego HDD |
| DVD tray | 2 wyłączone | Zarejestrowane, bez zatwierdzonego profilu runtime |

`VHS` jest zachowanym typem/protokołem obu PC Speakerów, nie aktualnym napędem VHS.
Główny speaker ma w konfiguracji transpozycję +12; FX nie ma tej transpozycji.
W **Settings → Brzmienie PC Speaker** ustawisz osobno gain VIRTUAL i wspólny
kształt pulse/sine/triangle/sawtooth. W pulse parametr REAL reguluje wypełnienie
w obu wyjściach; dla pozostałych fal poziom PWM REAL. Skala gain VIRTUAL 0–100%
odpowiada 0–2,5. [Szczegóły i ograniczenia fizyczne](docs/pc-speaker-fx.md).

Mute w `/settings` jest bramką wykonania i nie zwalnia miejsca w aranżacji.
Zmiana inventory/profili wymaga edycji JSON i restartu/przebudowy aplikacji.
`routing.mode: STRICT_TRACKS` w JSON kieruje cztery wybrane tracki wyłącznie na
FDD; nie jest presetem UI. Zapisany [eksperyment obniżenia FDD o oktawę](docs/fdd-octave-experiment.md)
ustawia cztery FDD na transpose -12 i preferowane 100–205 Hz we wszystkich
presetach. To bieżąca konfiguracja odsłuchowa, nie nowa kalibracja mechaniczna.

## Presety aranżacji

Wybór: **Settings (`/settings`) → Aranżacja → Preset aranżacji**.
Zmiana potwierdza STOP, przebudowuje plan i nie wznawia gry. Wybór jest sesyjny;
restart wczytuje `parameters.arrangementPreset` z JSON (obecnie `balanced`).

| Preset / ID | Zachowanie |
| --- | --- |
| Universal / `universal` | Frazy i rezerwacje wokalu/FX, elastyczny fallback tonalny, dobór FDD z odstępem ataków już podczas alokacji |
| Balanced / `balanced` | Mechanical-Aware: miękka preferencja krótkich, zmiennych nut na FDD i sustainu na DVD; opcjonalny dynamiczny UNISON |
| FDD Riffs + DVD Tło / `instrument_roles` | Krótkie riffy FDD, długie warstwy DVD, silniejszy sustain tła; bez dowolnego UNISON FDD |
| Pary Unisono / `instrument_roles_unison` | Jak wyżej, FDD1+2 i FDD3+4 grają po jednej partii zdwojoną nutą |
| Pary Dwugłos / `instrument_roles_duet` | Te same pary wybierają do dwóch istniejących nut jednej partii; pojedyncza linia przechodzi w unisono |
| FDD Quality / `fdd_quality` | Ocenia koszt kroków/zawróceń, skraca długie FDD i ogranicza kosztowne opcjonalne nuty |
| FDD Quality Adaptive / `fdd_quality_adaptive` | Na bazie Quality lokalna gęstość frazy steruje odzyskiwaniem ataków i krótkich gate'ów |
| DVD Lead + Low FDD / `dvd_lead_low_fdd` | Preferuje tonalne DVD; FDD próbuje oktawy niżej z fallbackiem do dozwolonego zakresu |

Wszystkie presety i STRICT_TRACKS dostają końcowy limit ataków FDD: domyślnie
120 ms między NOTE_ON na stację. Szybkie przebiegi mogą celowo tracić nuty.
W fizycznym allocatorze DVD obowiązuje sufit **600 Hz akustycznych**, przez
składanie oktawowe przed przeliczeniem `pitchRatio`; to wybór muzyczny, nie
zweryfikowana granica termiczna. Dynamiczny sustain DVD ma eksperymentalny
limit mostkowania 200 ms, tło Instrument Roles i par 350 ms, z ochroną pauz,
artykulacji, partii i rezerwacji. [Dokumentacja algorytmów](docs/README.md).
Nowy [Universal](docs/universal-arrangement.md) jest osobnym presetem; starsze
warianty pozostają dostępne, a domyślne `balanced` w JSON nie jest zmieniane.

## Testy i diagnostyka

```sh
.venv/bin/python -m unittest discover -s host/tests -q
npm --prefix web test
npm --prefix web run build
```

Testy API wymagają również `httpx` w środowisku testowym. Testy produkcyjnego
rdzenia C++ używają lokalnego kompilatora C++. Alternatywa z zależnościami w Dockerze:

```sh
docker compose --profile test run --rm --build backend-tests
docker compose --profile test run --rm --build frontend-tests
```

Firmware: `pio run -d firmware/controller -e esp32` (osobno `-e uno`).
Zgodność generowanego nagłówka: `.venv/bin/python scripts/generate_hardware_profiles.py --check`.
Nie generuj ponownie pliku przy samej edycji dokumentacji.

Diagnostyka: `/api/state`, `/api/plan`, `/api/timeline`, `/api/monitor/raw`,
`/api/firmware/events`; komendy aplikacji idą przez `/ws`. Podgląd
**Arrangement · PerformancePlan** znajduje się w Settings → Aranżacja.
**Settings → Laboratory → Laboratory · debug** otwiera skończone testy bez MIDI.
Nie ma panelu ocen rezonansu, edytora piano roll ani drawerów dawnego UI.

Metryki, symulacja i testy software nie mierzą dźwięku, temperatury, prądu ani
rzeczywistego położenia. [Tabela zasilania i niepewności](docs/esp32-orchestra.md#power-supplies-and-evidence),
[pełny indeks dokumentacji i historycznych benchmarków](docs/README.md).
