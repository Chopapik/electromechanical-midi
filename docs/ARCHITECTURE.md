# Architektura i obsługa aplikacji

Katalog i adresacja hosta odpowiadają firmware: **8 FDD, 6 DVD, 4 HDD i 2 speakery**.
Z 20 wpisów aktywnych pozostaje 14: FDD1–4, DVD1–4, HDD1–4 i oba speakery.
FDD5–8 i DVD5–6 mają `enabled:false` i `present:false`; nie są fizycznie
zakwalifikowane ani automatycznie aranżowane. Zmiana pojemności nie zmienia
presetów ani harmonogramu aktywnego zestawu. STRICT_TRACKS zachowuje cztery sloty.
[Inventory i kwalifikacja](HARDWARE_DEVICES.md#inventory-i-identyfikatory).

## Jeden harmonogram wykonawczy

```text
MIDI → MidiSource → Arranger → PerformancePlan → compiler → ExecutionTimeline
                                                        ↓
                                                     Player
                                                        ↓
                                                     Router
                                                   ↙        ↘
                                          REAL / BLE     VIRTUAL / Web Audio
```

[MidiSource](../host/midi_source.py) parsuje nuty, tempo, metrum, programy,
kontrolery i lyrics. [Runtime Arranger](../host/runtime/arranger.py) przekazuje
AUTO do [alokatora sprzętowego](../host/playback/hardware_arranger.py):
normalizacja duplikatów, role i kandydaci, zajętość oraz profile, artykulacja,
rezerwacje dodatkowe i walidacja. Kolejność refinements wewnątrz alokatora
zależy od presetu; [algorytmy](ARRANGEMENT.md) są opisane w jednym miejscu.

Runtime dodaje ekspresję tonalną i artykulację HDD, po czym wykonuje wspólny
pass ograniczania ataków FDD. Universal ma po nim dodatkowe odzyskiwanie głosów,
sprawdzające pełną chronologię każdej nowej rezerwacji. `PerformancePlan` zawiera
źródłowe dane, wykonane zdarzenia, pominięcia z powodami, extras i sidecary ekspresji.
Nie jest jeszcze kolejką transportową.

[compile_plan](../host/runtime/compiler.py) tworzy uporządkowany
`ExecutionTimeline`: tone/hit/stop ze stabilnym `device_id`. Stykające się tony
nie mają pośredniego STOP; dla DVD tolerancja błędu float granicy wynosi 1 ns.
Rzeczywiste przerwy nadal generują STOP. Liczenie STOP i ciągłych odcinków pracy
musi korzystać z tej warstwy, obejmując również dodatkowe głosy.

[Player](../host/runtime/player.py) ma jeden zegar, epokę i właściciela
(orchestra, lab albo service). [Router](../host/runtime/router.py) przekazuje
wykonanie do jednego aktywnego wyjścia. Mute filtruje wykonanie, bez zmiany
alokacji lub zwalniania głosów; STOP zawsze przechodzi. Seek podczas gry ustawia
nową pozycję i odtwarza trwające tam nuty, podczas pauzy zachowuje pauzę;
seek ze STOP nie uruchamia gry. Zmiana wyjścia/właściciela anuluje stare kolejki
i zatrzymuje wykonanie, bez automatycznego wznowienia.

## Wyjścia i serwis

[REAL](../host/runtime/outputs.py) używa ESP32 BLE, bez automatycznego fallbacku
na Serial. Wysyła profile i ENABLE; ciągłe DVD dostają też DIR FWD.
Konfiguracja jawnie wysyła `FDD 5..8 ENABLE 0` oraz `SLED 5..6 ENABLE 0`,
bez HOME/PLAY dla tych kanałów; HDD1–4 zachowują ENABLE 1 i wykonanie HIT.
Registry oraz `bind_devices(..., 2)` liczą ordynały również wyłączonych pozycji,
więc wyłączenie FDD1 nie przenosi FDD2 na kanał 1. OrchestraLink sprawdza
osobne granice FDD 1–8, SLED 1–6 i HDD 1–4, odrzucając także ID typu bool.
Wymaga `board=esp32`, protocol 2, `ready=1`, `stop_ack=1`, `hardware_profiles=1`
oraz capabilities potrzebnych planowi (m.in. `dvd_continuous`, `speaker_fx`,
`speaker_waves`, `strict_tracks`). Konfigurację potwierdza kompletna transakcja
STATUS. Firmware zachowuje 17 rekordów STATUS z FDD1–4; dodatkowe kanały
są widoczne tylko przez osobne `DIAG FDD` / `DIAG SLED`. Dotychczasowy parser hosta ma
limit 20 linii transakcji. FDD wymagają jawnego HOME. USB służy flashowaniu i diagnostyce.

VIRTUAL odbiera ten sam timeline, z wyprzedzeniem 150 ms względem czasu
wykonania (REAL bez takiego lookahead). [virtualOutput.ts](../web/src/virtualOutput.ts)
synchronizuje zegar i epoki; [mechanicalAudio.ts](../web/src/mechanicalAudio.ts)
syntezuje dźwięk proceduralnie. Nie parsuje MIDI i nie układa drugiej aranżacji.
Velocity/CC i obwiednia modelu audio nie są fizyczną regulacją amplitudy FDD/DVD.
Utrata synchronizacji wycisza audio; brzmienie, poziom i rezonanse wymagają
osobnej kalibracji wobec urządzeń.

[DeviceService](../host/runtime/device_service.py) po potwierdzonym STOP
przejmuje wyłączne sterowanie na czas USB uploadu, homingu lub operacji POWER.
Nie ma resetowania kontrolera przez BLE. STOP/ACK, watchdog i postępowanie
przy niepewnym stanie opisuje [procedura awarii](HARDWARE_TESTING.md#awarie).

## Logiczne zasilanie ATX

DeviceService publikuje `service.power`: ON / OFF / UNKNOWN / UNAVAILABLE,
`operation`, `available`, `reason`, `error` i `measured:false`. OFF/ON odnoszą
się do sterowania GPIO19, UNKNOWN do braku pewnego bieżącego potwierdzenia,
a UNAVAILABLE do braku połączenia przy starcie albo braku obsługi POWER
w firmware. Nie jest to pomiar napięcia. Rozłączenie znanego kontrolera zmienia
stan na UNKNOWN; ponowne BLE odczytuje POWER STATUS, nigdy nie odtwarza ON.
REAL wymaga ON przed ready/dispatch/HOME, VIRTUAL nie wymaga ATX.
Potwierdzone OFF unieważnia HOME FDD; przed dalszą grą wymagany jest homing.

`/settings` → **Zasilanie ATX** zawiera ręczne ON/OFF i potwierdzenie przed ON.
Backend także wymaga `confirmed:true` dla włączenia. Operacje używają wspólnej
wyłączności serwisowej; żądania POWER/upload podczas zajętości są odrzucane.
WebSocket udostępnia je tylko z Origin zgodnym z Host lokalnego adresu
localhost / 127.0.0.1 / ::1. Brama BLE i port Compose są związane z loopback.
To ograniczenie lokalnej aplikacji, nie uwierzytelnianie radiowego NUS: USB
wymaga dostępu fizycznego, BLE nadal wymaga zaufanego otoczenia i kontroli dostępu
do komputera. Nie wystawiaj aplikacji/bramy przez publiczny proxy/tunel.

Upload wymaga potwierdzonego ALL STOP i POWER OFF, odczekuje 1 s, zwalnia BLE
przed sprawdzaniem portu i budowaniem, następnie używa istniejącego PlatformIO.
Powrót BLE po uploadzie potwierdza OFF, bez automatycznego ON i autoplay.
Wspólne wejście dla narzędzi to [safe_upload.py](../scripts/safe_upload.py);
[procedura i pierwszy bootstrap](HARDWARE_TESTING.md#firmware-i-sama-logika).
Stan szyn 74HC595 przy osobnym USB ESP32 pozostaje
[ograniczeniem sprzętowym](HARDWARE_WIRING.md#sterowanie-atx-przez-ps_on).

## Obsługa i konfiguracja

| Miejsce | Funkcja |
| --- | --- |
| `/` | Import/wybór MIDI, transport i karty urządzeń; również sesja lab |
| `/settings` → Output | REAL albo Virtual debug · Web Audio |
| `/settings` → Aranżacja | Preset oraz Arrangement · PerformancePlan |
| `/settings` → Brzmienie PC Speaker | Gain VIRTUAL, fala i duty/poziom REAL osobno dla dwóch speakerów |
| `/settings` → Zasilanie ATX | Ręczne ON/OFF, stan logiczny i potwierdzenie ON |
| `/settings` → Serwis | Wgraj firmware ESP32, Homing |
| `/settings` → Laboratory | Laboratory · debug, skończony test bez MIDI |

Aplikacja zawsze startuje w REAL, nawet offline. Wybór presetu jest sesyjny:
restart odczytuje `parameters.arrangementPreset` z JSON (obecnie `balanced`).
Zmiana presetu potwierdza STOP, przebudowuje plan i zwiększa rewizję,
bez autoplay. Inventory/profil zmieniasz w JSON, potem przebudowujesz aplikację;
nie ma panelu dodawania urządzeń ani wyboru kontrolera. Mute nie zmienia inventory.

[devices.json](../config/devices.json) definiuje fizyczne lanes, transpozycje,
preferencje i politykę; [profile](HARDWARE_DEVICES.md) określają ich interpretację.
`routing.mode: STRICT_TRACKS` jest trybem JSON przypisującym cztery tracki tylko
na FDD; nie dziewiątym presetem. Nie włącza DVD/speakerów/perkusji.

Ustawienia speakerów zapisują się atomowo, osobno od obrazu aplikacji:
Docker volume `speaker-settings`, plik `/app/settings/speaker-volumes.json`.
Natywnie domyślnie `config/.runtime/speaker-volumes.json`; override przez
`ORCHESTRA_SPEAKER_SETTINGS`. Restart/rebuild nie resetuje zapisanych ustawień.

## Uruchamianie

W katalogu repozytorium:

```sh
docker compose up -d --build orchestra
docker compose ps orchestra
```

[Compose](../compose.yaml) publikuje `127.0.0.1:5173` (override `APP_PORT`),
backend słucha w kontenerze na 8000. Healthcheck odczytuje `/api/state`.
MIDI są w bind mount `./midi:/app/midi`. Kod, firmware i konfiguracja są kopiowane
do obrazu: ich zmianę wdraża rebuild/restart, sama dokumentacja go nie wymaga.

Na macOS Docker korzysta z natywnej bramki Bleak, uruchomionej poza kontenerem:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r host/requirements.txt
.venv/bin/python host/ble_gateway.py
```

Pozwól używać Bluetooth procesowi uruchamiającemu bramkę w ustawieniach macOS.
Domyślny TCP port to 8766; Compose wskazuje `host.docker.internal:8766` przez
`ORCHESTRA_BLE_GATEWAY`. Dostęp hosta do kontenera/USB zależy od środowiska;
konfiguracja Compose uwzględnia OrbStack i porty CP2102 w `/host-dev`.
Bramka nie zamienia BLE na Serial. Można zainstalować LaunchAgent:
`.venv/bin/python host/ble_gateway.py --install-macos-service`.
Plik usługi i logi wskazuje instalator; nie uruchamiaj drugiej instancji na tym
samym porcie. Kod instalatora: [ble_gateway.py](../host/ble_gateway.py).

Bez prób łączenia ze sprzętem:

```sh
ORCHESTRA_OFFLINE=1 docker compose up -d --build orchestra
```

Następnie wybierz VIRTUAL w Settings i uruchom audio gestem w przeglądarce.
REAL offline pozwala importować i aranżować, ale blokuje Play.

Natywny backend i frontend developerski (dwa terminale, po instalacji zależności):

```sh
.venv/bin/python -m host.web.server --offline --port 8000
npm --prefix web ci
npm --prefix web run dev
```

Vite proxy kieruje API/WS na port 8000. Produkcyjny backend serwuje zbudowany
`web/dist`; użyj `npm --prefix web run build`, jeżeli uruchamiasz go bez Vite.

## API i diagnoza

| Endpoint | Dane |
| --- | --- |
| GET `/api/state` | Transport, wyjście, połączenie, stan/rewizja aplikacji |
| GET `/api/plan` | Zdarzenia, pominięcia, dodatkowe rezerwacje i raport artykulacji |
| GET `/api/timeline` | Skompilowany harmonogram wykonawczy |
| GET `/api/files`, `/api/files/{name}` | Biblioteka i plik MIDI |
| POST `/api/files` | Import pliku |
| GET `/api/monitor/raw`, `/api/firmware/events` | Surowy ruch i zdarzenia kontrolera |
| WebSocket `/ws` | Komendy aplikacji, stan i synchronizacja |

Kontrakt implementuje [server.py](../host/web/server.py). Nie należy wyciągać
obecnych ścieżek UI ani protokołu aplikacji z raportów starego renderera.

## Testy

```sh
.venv/bin/python -m unittest discover -s host/tests -q
npm --prefix web test
npm --prefix web run build
.venv/bin/python scripts/generate_hardware_profiles.py --check
pio run -d firmware/controller -e esp32
```

Zainstaluj `httpx` w środowisku testowym dla testów API; testy natywnego rdzenia
C++ potrzebują lokalnego kompilatora. `npm ci` instaluje frontendowe zależności.
Generator z `--check` sprawdza zgodność bez zapisywania konfiguracji/nagłówka.
[Testy pojemności backendu](../host/tests/test_backend_capacity.py) sprawdzają
20 pozycji / 14 aktywnych, stabilne ordynały wyłączonych kanałów, limity ID,
jawne ENABLE 0, HIT wszystkich czterech HDD, niezmieniony STATUS i cztery sloty
STRICT_TRACKS. Dla ośmiu presetów porównują zdarzenia, artykulację i skompilowany
timeline z dodatkową nieaktywną pulą oraz bez niej, wyłącznie offline.
Firmware ma przypięte zależności w [platformio.ini](../firmware/controller/platformio.ini);
zmiana wersji Arduino/LEDC wymaga oddzielnej weryfikacji, nie automatycznej migracji.

Alternatywnie gotowe środowiska testowe:

```sh
docker compose --profile test run --rm --build backend-tests
docker compose --profile test run --rm --build frontend-tests
```

Benchmarki uruchamiaj według zapisu konkretnego badania, z tym samym inventory,
MIDI hash i polityką. Testy deterministyczności, chronologii i wspólnego timeline
nie dowodzą poprawności akustycznej ani termicznej na REAL.
