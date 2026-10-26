# Baseline refaktoryzacji — API, stan i współbieżność

Audyt statyczny: 2026-10-26. SHA wejściowe:
`ea0b26c5ddad30a9dc5042dbd4e34daf6abdc0f8`; implementacja Adaptive Legato
pochodzi z `a221286`. Przy rozpoczęciu audytu `git status --short` był pusty.
Ten dokument jest częścią **etapu 0** [planu refaktoryzacji](../REFACTORING_PLAN.md).
Nie jest dowodem zakończenia testów całego etapu ani specyfikacją nowego API.
Późniejszą poprawkę par Adaptive Legato należy porównywać jako osobną zmianę
zachowania, z własnym punktem odniesienia.

Źródła: [HTTP/WS](../../host/web/server.py),
[Application](../../host/runtime/application.py),
[Player](../../host/runtime/player.py), [wyjścia](../../host/runtime/outputs.py),
[DeviceService](../../host/runtime/device_service.py),
[Laboratory](../../host/runtime/laboratory.py),
[klient przeglądarki](../../web/src/runtime.ts).
Wszystkie poniższe zachowania potwierdzono przez odczyt tych implementacji;
odtworzenie defektu importera opisano oddzielnie w sekcji 6.

## 1. HTTP

Jawnie zdefiniowane endpointy aplikacji:

| Metoda i ścieżka | Odpowiedź przy sukcesie | Jawne błędy i uwagi |
| --- | --- | --- |
| GET `/api/state` | 200, snapshot aplikacji | Brak własnego mapowania wyjątków |
| GET `/api/firmware/events` | 200, lista do 3000 zdarzeń serwisu | Odczyt aktualnego bufora |
| GET `/api/monitor/raw` | 200, snapshot oraz `commands`, `plan` | Ostatnie do 200 wysłanych linii REAL; `plan` może być `null` |
| GET `/api/plan` | 200, `{report, events, reinforcements}` albo `null` | Pełne zdarzenia planu, nie tylko zagrane |
| GET `/api/timeline` | 200, serializacja timeline albo `null` | Kolejność wykonania tone/hit/stop |
| GET `/api/files` | 200, lista `{name,size,modified}` | `.mid`/`.midi`, posortowane ścieżki; brak katalogu daje `[]` |
| GET `/api/files/{name}` | 200, metadane pliku i ścieżek MIDI | 400 błędna nazwa/wyjście poza katalog; 404 brak pliku; 422 `MidiSourceError` |
| POST `/api/files` | 200, `{name}` | 422 nazwa/rozszerzenie lub błąd parsowania; 413 ponad 5 MiB; brak pola `file` obsługuje FastAPI (422) |
| GET `/settings` | 200, frontend `index.html` | Rejestrowane, jeśli istnieje `web/dist` |
| GET `/*` | Zasoby statyczne `web/dist` | Montowane tylko, jeśli katalog istnieje; zachowanie `StaticFiles(html=True)` |

FastAPI domyślnie udostępnia również `/openapi.json`, `/docs`,
`/docs/oauth2-redirect` i `/redoc`. Wyjątki nieprzechwycone w endpointach
nie mają własnej odpowiedzi domenowej (standardowa obsługa 500 frameworka).

Aktualny upload czyta najwyżej `5*1024*1024+1` bajtów. Bierze
`Path(file.filename or '').name` bez `strip()`, odrzuca pustą nazwę, kropkę na
początku i rozszerzenie inne niż `.mid`/`.midi`. Sprawdza tymczasowy plik przez
`MidiSource` i usuwa go po wyjściu z kontekstu. Kolizje dostają nazwy
`stem-1.mid`, `stem-2.mid` itd., także gdy pierwotny sufiks to `.midi`.
Nie zamieniać tego na konwencję `stem (2).mid` z nieużywanej metody biblioteki.
Zapis docelowy i błędy systemu plików nie mają własnego mapowania HTTP.

## 2. WebSocket `/ws`

Serwer przyjmuje połączenie, nadaje losowy identyfikator sesji i wysyła
`{type:'hello', session}` oraz zapisane zdarzenia firmware. Wiadomości komend
są zwykłymi słownikami; nie istnieje wspólny walidator kształtu JSON.
Brak wymaganych kluczy w komendzie zwykle kończy się tekstem wyjątku `KeyError`.
Niepoprawny JSON lub JSON niebędący obiektem trafia poza zwykłą obsługę błędu
komendy. To zastane zachowanie, nie docelowy kontrakt walidacji.

### Komendy przyjmowane od klienta

`requestId` jest opcjonalny i przepisywany do zwykłego ACK/błędu. Pola inne niż
wymienione nie mają ogólnej walidacji. Domyślne wartości poniżej pochodzą z kodu.

| `action` | Pola | Operacja i ograniczenia |
| --- | --- | --- |
| `set_file` | `file` | `library.resolve` → `runtime.load`; obliczenie poza blokadą Playera, instalacja planu pod nią |
| `arrangement_preset` | `preset` | STOP przed planowaniem; w razie błędu przywrócenie poprzedniego identyfikatora presetu |
| `play` | — | Zajmuje sesję Web Audio w VIRTUAL; wybiera orkiestrę, następnie `Player.play()` |
| `pause` | — | STOP z zachowaniem pozycji, potem stan `paused` |
| `stop` | — | Unieważnienie epoki i potwierdzony STOP; po sukcesie pozycja 0 |
| `seek` | `position` | Skończona liczba, bool odrzucony; ograniczenie do długości; STOP przed zmianą czasu |
| `output` | `mode` | `REAL`/`VIRTUAL`; przechodzi poza `command_lock`, nadal używa blokady Playera i STOP |
| `mute` | `deviceId`, `muted` | Wymaga znanego ID i bool; STOP urządzenia także przy błędzie pozostawia mute włączone |
| `speaker_waveform` | `deviceId`, `waveform` | Registry dopuszcza tylko `pulse` i tylko speakery |
| `speaker_volume` | `deviceId`, `output`, `value` | REAL: całkowite 0–128; VIRTUAL: 0–2,5; bool/nieskończoność odrzucone |
| `lab_enter` | — | Wyłączny właściciel sesji laboratorium; STOP poprzedniego wykonania |
| `lab_leave` | — | Oddaje laboratorium i przywraca timeline orkiestry |
| `lab_test` | `deviceId`; `hz=200`, `duration=1`, `modulation` opcjonalne | Wymaga właściciela lab; `duration:null` daje grę ciągłą, poza HDD; REAL FDD przechodzą homing konkretnego kanału |
| `lab_update` | Jak `lab_test` | Wymaga aktywnego testu tonalnego; zachowuje jego pierwotny czas końca |
| `lab_stop` | `deviceId` | STOP wskazanego kanału; błąd powoduje próbę STOP całości |
| `service` | `operation`, `confirmed` opcjonalne | `home`, `firmware`, `power_on`, `power_off`, `power_status`; `reset` jawnie niedostępny; `power_on` wymaga `confirmed is True` |
| `audio_error` | `epoch`, `message` opcjonalne | Tylko bieżący właściciel VIRTUAL i bieżąca epoka: STOP, błąd `Web Audio: …` do 250 znaków szczegółu |
| `audio_ack` | `token` | Obsługiwane natychmiast, poza `command_lock`; potwierdza anulowanie wyłącznie dla właściciela tokenu |
| `sync` | `sent` | Obsługiwane natychmiast; odnawia lease lab i odsyła zegar; nie ma zwykłego ACK |

Presety akceptowane w punkcie odniesienia: `balanced`, `fdd_quality`,
`dvd_lead_low_fdd`, `fdd_quality_adaptive`, `instrument_roles`,
`instrument_roles_unison`, `instrument_roles_duet`, `instrument_roles_unison4`,
`fdd_expressive`, `fdd_expressive_solo`, `adaptive_legato`, `fdd_legato`, `universal`.

Przed zwykłą komendą sprawdzane jest `service.busy`. Dla serwisu POWER/firmware
zajęty `command_lock` daje natychmiastowy błąd. Pozostałe komendy czekają na tę
blokadę, z wyjątkiem `output`. Drugi test `service.busy` następuje wewnątrz
wykonania; przy `output` także po wejściu pod blokadę Playera.

POWER i firmware wymagają `Origin` o schemacie http/https, hostname
`localhost`/`127.0.0.1`/`::1`, a `origin.netloc` musi być równy nagłówkowi Host.
Ten warunek nie obejmuje pozostałych komend ani samego przyjęcia WebSocketu.
Nie zastępować go twierdzeniem o ogólnej autoryzacji całego API.

### Wiadomości serwera i błędy

| `type` | Pola / semantyka |
| --- | --- |
| `hello` | `session`; identyfikator właściciela połączenia |
| `state` | `state`; broadcast po snapshot/expire z przerwą 50 ms (nie gwarantowane 20 Hz) |
| `ack` | `requestId`, `state`; po zakończeniu operacji; nie oznacza, że utwór skończył homing lub że firmware odzyskało BLE |
| `error` | `requestId`, `message`; tekst wyjątku, bez pola kodu domenowego |
| `sync` | `sent`, `serverTime` z `time.monotonic()` |
| `audio` | `owner`, `commands`, `epoch`, `origin`, `serverTime` |
| `audio_cancel` | `owner`, `token`, `deviceId`, `epoch`; pełne anulowanie ma epokę, anulowanie kanału `null` |
| `firmware_event` | `seq`, `kind:'status'/'log'`; status: `stage,flash,ble,progress,error`; log: `line` |

Na WS nie ma kodów HTTP błędów ani globalnych stabilnych kodów biznesowych.
Przykłady niezmienianych tekstów: `Unknown action`, `Unknown arrangement preset`,
`Unknown output`, `Invalid position`, `DeviceService jest zajęty`,
`Web Audio jest używane przez inną przeglądarkę`,
`Sterowanie ATX i upload wymagają lokalnego połączenia z poprawnym Origin`.
Błędy `lab_test`/`lab_update`/`lab_stop` dostają prefiks
`<nazwa urządzenia> · <uruchomienie testu/zmiana parametrów/zatrzymanie testu>: `.
Szczegóły profilu i `ERR …` firmware są przenoszone w tekście, np.
`OUTSIDE_MUSICAL_RANGE`, `ERR HOME_FAILED FDD=7`. Ich prezentację przekształca
[laboratoryErrors.ts](../../web/src/laboratoryErrors.ts), zachowując nieznane kody.

Stan Playera: `stopped`, `playing`, `paused`; właściciel: `orchestra`, `lab`,
`service`. Homing ma osobną flagę. Logiczne zasilanie: `ON`, `OFF`, `UNKNOWN`,
`UNAVAILABLE`, zawsze `measured:false`. Etapy serwisu występujące w kodzie:
`idle`, `prepare`, `power_off`, `build`, `upload`, `flash_confirmed`,
`reboot_wait`, `ble_connect`, `ble_retry`, `ready`, `failed`.

## 3. Własność stanu i istniejące naruszenia granic

| Obszar | Główny stan | Faktyczni piszący / ochrona |
| --- | --- | --- |
| Serwer | `peers`, `peer_locks`, `tasks`, `loop` | Pętla asyncio; osobna blokada wysyłania per peer, wspólna blokada zwykłych komend |
| Application | `source`, `plan`, `timeline`, `revision` | `load`, `set_preset`; instalacja pod `player.lock`; snapshot składa kilka osobnych odczytów |
| Registry | `document`, `devices`, `by_id`, profile, preferencje | Application ustawia preset; registry zapisuje preferencje; planowanie czyta registry; brak własnej blokady |
| Player | timeline/lanes, czas, pozycja, indeks, epoka, stan, owner, homing, błąd i liczniki opóźnień | Głównie `threading.RLock`; Laboratory oraz DeviceService także bezpośrednio ustawiają wybrane pola |
| Router | `mode`, `muted` | Player używa blokady; sam Router nie posiada blokady |
| RealOutput | link, active/unknown/error/configured, homing, aktywne speakery, bufor sent | Głównie operacje pod Playerem; DeviceService ustawia także bezpośrednio link, konfigurację, pola i kolekcje; `power_state()` przy odczycie mutuje `power_seen` |
| VirtualOutput | owner, epoch, active, pending anulowania | `pending` ma własną blokadę; owner/active zmienia również kontroler i disconnect; ACK przychodzi niezależnie od Playera |
| Laboratory | session, lease, jobs, history, home_query | Zwykle `player.lock`; `touch()`/`require_session()` nie biorą własnej blokady; Application i serwer resetują session |
| DeviceService | busy/connecting, operation, błędy, ports, generation, events i firmware_state | Własna `Lock` i Event; część pól zmieniana poza blokadą; `run` i wątek recovery/połączenia |
| OrchestraLink | parser, device_status/controller_status, generations, bufor | Odczyt i aktualizacje przez `poll_lines`; DeviceService `_power()` również bezpośrednio zmienia statusy FDD i ATX |
| MidiLibrary | directory i cache metadanych | Endpointy sync/threadpool; cache bez blokady; importer endpointu osobno wybiera nazwę/zapis |
| Frontend runtime | WebSocket, requests, sesja, latest state, audio, uploadBusy, firmware sequence | Jeden hook; `VirtualOutput` utrzymywany w ref; efekty/cleanup sterują połączeniem i audio |
| PerformancePlan | events, reinforcements, policy, hardware, execution_articulation | Kolejne transformacje modyfikują jeden plan; raport `hardware` bywa wejściem algorytmu i kompilatora |

To inwentaryzacja zastanej własności, a nie deklaracja bezpieczeństwa wszystkich
odczytów. Nie rozwiązywać tych granic przez zastąpienie wszystkiego jedną blokadą.

## 4. Blokady i bariery potwierdzeń

1. **Zwykła komenda:** asyncio `command_lock` → `asyncio.to_thread(perform)` →
   najczęściej `player.lock` → Router/Output/transport. Po wyjściu spod
   `command_lock` pobierany jest snapshot i wysyłany ACK pod `peer_locks[peer]`.
   ACK i kolejne broadcasty mogą odzwierciedlać późniejszy stan; nie są dziennikiem
   atomowych zmian jednej komendy.
2. **Planowanie:** `load()` czyta MIDI, aranżuje i kompiluje przed `player.lock`.
   Zmiana `output` omija `command_lock`, więc może przerwać bieżące wyjście w tym
   czasie. `set_preset()` przeciwnie, trzyma `player.lock` podczas planowania.
3. **STOP VIRTUAL:** Player trzyma swoją blokadę; `VirtualOutput.cancel()`
   rejestruje token pod własną blokadą, emituje anulowanie i czeka najwyżej 1,5 s
   poza blokadą `pending`. Receiver musi przyjąć `audio_ack` bez czekania na
   `command_lock` ani `player.lock`. Klient zatrzymuje audio przed wysłaniem ACK.
4. **STOP REAL:** token w `ALL STOP <token>` → dokładne `STOPPED <token>`
   w ciągu 2 s. Brak potwierdzenia utrzymuje `unknown` i nie daje sukcesu STOP.
   Samo wysłanie `ALL STOP` na starym firmware nie jest potwierdzeniem.
5. **POWER:** token i przejściowe `atx=UNKNOWN` → zgodny stan i GPIO19 w dokładnej
   odpowiedzi w ciągu 2 s. Nie jest to pomiar napięcia.
6. **Konfiguracja REAL:** wysłanie profili/ENABLE → `STATUS` i w razie potrzeby
   `DIAG FDD` → wzrost obu wymaganych generation, do 3 s. Sam zapis BLE nie
   potwierdza wykonania konfiguracji.
7. **Auto-homing orkiestry:** `ready()` konfiguruje, potwierdza STOP i wysyła HOME
   brakujących FDD, potem oddaje sterowanie (`False`). Player ma flagę homing,
   a kolejne ticki pytają o status (co najmniej 200 ms między zapytaniami);
   10 s limitu. Nie uruchamia tonu przed potwierdzeniem. Laboratorium ma osobny
   stan zapytania i sprawdza również `track0=1` konkretnej stacji.
8. **Serwis:** krótko `service.lock` ustawia busy/operation/generation, następnie
   zwalnia ją; oczekiwanie `_connect_done` do 25 s; `player.lock` → wybór ownera
   service/STOP. Firmware: potwierdzony STOP → POWER OFF → 1 s czekania →
   zamknięcie BLE → poza Playerem skan USB/build/ponowny skan/upload → recovery.
   Brak STOP/OFF kończy tę procedurę bez uploadu. `power_off` ma osobną ścieżkę:
   po błędzie STOP nadal próbuje potwierdzić OFF.
9. **Połączenie/recovery:** `service.lock` chroni warunki startu/commit linku.
   Handshake PING/STATUS zachodzi poza nią; przy commit połączenia kod bierze
   `service.lock` → `player.lock` → POWER STATUS/(po uploadzie) OFF → attach/STOP.
   Nie ma automatycznego POWER ON ani wznowienia.
10. **BLE:** `BleBytes` ma blokadę zapisu asyncio obejmującą wszystkie fragmenty
    jednej paczki i potwierdzane GATT writes; wywołujący wątek czeka na zapis do
    2 s. Gateway ma własną blokadę zapisu. To inna bariera niż protokołowe ACK.

Wątek Playera próbuje tick co 10 ms; REAL PING po upływie 300 ms w `poll()`.
VIRTUAL ma lookahead 150 ms i okno przygotowania 120 ms; komendy źródłowe są
wspólne. `sync` klienta co 200 ms odnawia lease laboratorium 3 s.
Disconnect właściciela VIRTUAL próbuje STOP, czeka dalsze 600 ms na wygaśnięcie
heartbeat audio, potem czyści owner/active. Te opóźnienia nie są nowymi limitami.

## 5. Ryzyka wymagające zachowania lub osobnych testów

- **Przetwarzanie ACK musi pozostać poza kolejką komend.** Przeniesienie go pod
  `command_lock` spowodowałoby czekanie STOP na ACK zablokowany przez ten STOP.
- **Odwrotna kolejność blokad jest widoczna statycznie:** commit BLE bierze
  service → player; przygotowanie firmware trzyma Playera i wywołuje
  `_state()`/`_event()` z blokadą service. `busy`/`connecting` ograniczają obecne
  ścieżki. Nie odtworzono deadlocku i nie należy twierdzić, że występuje, ale
  refaktoryzacja musi sprawdzić te przeploty i unikać nowych odwróceń.
- **Snapshot nie jest transakcją całej aplikacji.** Odczyt Playera i serwisu jest
  osobno blokowany, a dane Application/registry/linku mogą zmienić się pomiędzy.
- **Planowanie może trwać podczas zmiany wyjścia.** To celowe zachowanie,
  chronione przez `test_output_during_planning`; nie blokować go całym renderem.
- **Własność VIRTUAL i lab jest rozproszona.** Disconnect, stary owner,
  wygaśnięcie lease, błąd ACK i nowe połączenie wymagają testów z dwiema sesjami.
- **Upload HTTP nie jest pod `command_lock`.** Wybór wolnej nazwy i zapis nie są
  atomowym zarezerwowaniem ścieżki; ryzyko równoczesnych importów to obserwacja
  statyczna, nie odtworzony przypadek utraty danych.
- **Granica typów WS jest słaba.** `requestId` i wartości są przyjmowane bez
  wspólnego schematu. Typ TypeScript nie waliduje odpowiedzi JSON w przeglądarce.
- **Frontend ma różne semantyki wysyłania.** `send()` zwykle nie czeka na ACK;
  `command()` dla STOP/upload/load czeka do 120 s. Nie scalać ich bez zachowania
  obsługi anulowania, błędów, timeoutu i unlock Web Audio.
- **Raport steruje wykonaniem.** Legato czyta grupy z `hardware.fddExpressive`,
  compiler rozpoznaje łączenie FDD przez `hardware.fddLegato`; artykulacja extras
  używa `extra:N`. Usunięcie diagnostyki lub zmiana kolejności extras może zmienić
  muzykę mimo braku edycji algorytmu.

## 6. Potwierdzone defekty i zakres weryfikacji tego audytu

Odtworzono offline bez aplikacji i sprzętu:

```sh
PYTHONPATH=host .venv/bin/python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
from web.library import MidiLibrary
with TemporaryDirectory() as root:
    try:
        MidiLibrary(Path(root)).save_upload('test.mid', b'MThd')
    except Exception as exc:
        print(type(exc).__name__ + ': ' + str(exc))
PY
```

Wynik: `NameError: name 'MAX_UPLOAD_BYTES' is not defined`. Metoda dodatkowo
odwołuje się do niezaimportowanych `mido` i `io`. Działający endpoint POST
implementuje odrębną ścieżkę i nie wywołuje tej metody. To znany defekt do
naprawy w etapie 1; nie przyjmować nieużywanej ścieżki jako baseline API.

Ten audyt nie uruchamiał pełnych testów hosta/frontendu, builda, korpusu MIDI ani
kontenera. Wyniki tych bramek i manifesty porównawcze muszą pochodzić z raportu
wykonania etapu 0. Istnienie testu nie jest równoznaczne z zaliczeniem go:
`test_runtime`, `test_output_during_planning`, `test_atx_power`,
`test_firmware_flow`, `test_laboratory`, `test_auto_homing`,
`test_safe_upload`, `test_speaker_volume` są wskazówkami do weryfikacji.
Nie wykonywano uploadu ESP32, POWER ON ani ruchu urządzeń.
