# Architektura i obsługa aplikacji

Katalog i adresacja hosta odpowiadają firmware: **18 urządzeń: 8 FDD, 4 DVD,
4 HDD i 2 speakery**. Aktywnych jest 16: HDD3–4 pozostają w katalogu i firmware,
ale są wyłączone w konfiguracji, aranżacji oraz routerze REAL/VIRTUAL.
FDD5–8 mają `present:true` i `realEnabled:true`.
Kaskada ma sześć rejestrów: Q32–Q39 są wolne, HDD nadal używają Q40–Q47.
Domyślny preset tworzy dwie grupy unisono po cztery FDD. STRICT_TRACKS zachowuje
cztery sloty i wyłącza FDD5–8 w konfiguracji REAL.
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

## Granice modułów i własność stanu

| Obszar | Odpowiedzialność |
| --- | --- |
| [HTTP/WebSocket](../host/web/server.py) | Origin, walidacja komunikatu, serializacja, odpowiedzi i mapowanie błędów |
| [Application](../host/runtime/application.py) | Scenariusze play/pause/stop/seek, wyjście, sesja audio/lab, instalacja planu i delegowanie do serwisu; używalne bez FastAPI |
| [MidiLibrary](../host/web/library.py) | Rozwiązywanie nazwy, jeden importer, walidacja MidiSource, kolizje, zapis i cache metadanych; wyjątki niezależne od HTTP |
| [DeviceRegistry](../host/runtime/registry.py) | Katalog i zwalidowane profile/parametry urządzeń |
| [SpeakerSettingsStore](../host/runtime/speaker_settings.py) | Wczytanie preferencji i atomowy zapis istniejącego JSON; bez decyzji o dopuszczalnych poziomach |
| [Planning pipeline](../host/runtime/planning_pipeline.py) | Dobór i kolejność nazwanych etapów; etapy modyfikują plan, bez połączeń i stanu odtwarzania |
| [PlanningContext](../host/playback/planning_context.py) | Dane potrzebne do wykonania: fizyczne lanes, grupy FDD, łączenie tonów i powiązania artykulacji extras |
| [Wspólne modele alokacji](../host/playback/allocation_models.py) | SourceNote, ManualPin, slot i kandydat; stan slotu należy do pojedynczej alokacji |
| [Przygotowanie alokacji](../host/playback/allocation_input.py) / [operacje](../host/playback/allocation_operations.py) | Deterministyczne nuty źródłowe, duplikaty, priorytet, budżety gate i tworzenie zdarzeń; bez importowania alokatorów |
| [Strategie](../host/playback/arrangement_strategy.py) | Opis bazowego presetu, grup FDD i końcowego refinement; korzysta z kanonicznych ID katalogu, bez importowania implementacji algorytmów |
| [Player](../host/runtime/player.py) / [Router](../host/runtime/router.py) | Odpowiednio zegar/epoka/właściciel wykonania oraz wybór wyjścia/mute |
| [RealOutput / VirtualOutput](../host/runtime/outputs.py) | Własny stan wyjścia, gotowość, wykonanie i bariery STOP; stan logiczny POWER i właściciel Web Audio |
| [DeviceService](../host/runtime/device_service.py) | Wyłączność serwisu, kolejność safe upload i odzyskanie BLE; zmiany stanu wyjścia przez jego operacje |
| [Kontrakty serwisu](../host/runtime/service_models.py) | Rodzaj operacji, ticket generacji, typ statusu firmware i własność odłączonej sesji OTA; bez przechowywania klucza |

Katalog presetów jest w [arrangement_presets.py](../host/arrangement_presets.py).
[Generator](../scripts/generate_preset_catalog.py) tworzy dane i typy używane przez
Settings; kontrola `--check` wykrywa nieodświeżony plik. Walidacja backendu korzysta
z tego samego katalogu. [Kontrakty WS](../host/web/contracts.py) sprawdzają pola
przychodzących komend, a [kontrakty klienta](../web/src/contracts.ts) sprawdzają
odpowiedzi JSON przed przekazaniem ich do stanu lub audio. Kształt poprawnych
komunikatów i ich `requestId` pozostaje zgodny; niepoprawne dane dostają błąd
kontrolera. Typy nie zastępują sprawdzenia stanu sesji, profilu ani Origin.

Importer zachowuje limit 5 MiB, walidację przez tymczasowy plik MidiSource i
konwencję kolizji `stem-1.mid`, `stem-2.mid`. Kontroler czyta najwyżej limit +1
bajt, a biblioteka wybiera nazwę i zapisuje plik. Wyłączne tworzenie `xb`
chroni istniejące pliki i dowiązania symboliczne, również dangling symlink;
nie nadpisuje celu spoza biblioteki. Błąd zapisu usuwa częściowy nowy plik.
Brak metadanych, uszkodzone MIDI i błędy rozmiaru/nazwy są mapowane na zachowane
statusy HTTP. Nie dodano naprawiania nieprawidłowego MIDI.

`DeviceService` rezerwuje operację pod krótką blokadą serwisu. Gdy potrzeba obu
blokad, kolejność to `player.lock` → `service.lock`; oczekiwanie na Playera ani
POWER/STOP ACK nie trzyma blokady serwisu. ACK audio i heartbeat pozostają poza
kolejką komend i blokadą Playera, aby nie zablokować STOP oczekującego na ACK.
Zmiana wyjścia podczas planowania nadal omija kolejkę całego renderu.
`RealOutput.power()` stosuje wyłącznie potwierdzony wynik GPIO; adapter linku
unieważnia status FDD po OFF i logiczny ATX po braku potwierdzenia.
`VirtualOutput.claim_owner/release_owner` pilnują właściciela: wygasająca sesja
po disconnect nie może wyczyścić nowego właściciela audio.

### Cykl życia serwisu

`_exclusive_operation` rezerwuje i zwalnia operację w jednym zakresie, obejmując
także błąd pierwszego callbacku statusu. Publiczne `busy`, `connecting` i
`operation` zachowują dotychczasowy kontrakt. Ticket niesie rodzaj operacji i
generację recovery; nie stanowi drugiej kopii statusu. `_state` aktualizuje status
i numerowane zdarzenie atomowo, a callback wywołuje po zwolnieniu blokady.

| Przejście | Właściciel i warunek |
| --- | --- |
| idle → operacja | `_exclusive_operation`; brak busy/connecting i niezamknięty serwis |
| idle/retry → connecting | `connect`; aktualna generacja, REAL, brak linku i operacji |
| connecting → link RealOutput | Zgodny boot/STATUS/protokół, POWER STATUS i wymagane OFF; attach potwierdza STOP. Ponowna kontrola generacji/shutdown po ACK. |
| prepare → power_off | Wyłącznie pod player.lock, po potwierdzonym STOP; BLE wymaga także capability OTA i istniejącego klucza |
| power_off → build | Potwierdzone OFF i 1 s; USB oddaje link i sprawdza port, BLE przenosi link z RealOutput do FirmwareSession |
| build → upload/upload_ble | USB ponownie sprawdza ten sam port; BLE czyta obraz i lokalny klucz do podpisu |
| upload → flash_confirmed → reboot_wait | Potwierdzony wynik transferu; flash i recovery mają odrębny stan |
| błąd → failed | Próba STOP, zamknięcie sesji OTA, zwolnienie operacji; bez ponowienia transferu |
| reboot_wait/failed → ble_connect/ble_retry → ready/failed | Tylko recovery połączenia w aktualnej generacji; nigdy automatyczne ON/HOME/PLAY |
| dowolny → shutdown | Unieważnia późne podłączenia/statusy recovery; odmawia nowych operacji |

Firmware USB i BLE przechodzą przez `_prepare_firmware` i `_flash`. Rozgałęzienie
transportu zachowuje różne zasady portu i własności BLE; sama budowa/transfer nie
decydują o POWER ani właścicielu Playera. `FirmwareSession.close` odpowiada za
link OTA odłączony od wyjścia. Klucz jest zmienną lokalną transferu i nie trafia
do statusu ani tej sesji. Awaryjny POWER OFF ma osobną ścieżkę dopuszczającą
próbę OFF po niepotwierdzonym STOP; firmware nie korzysta z tego wyjątku.

Testy [cyklu życia](../host/tests/test_service_lifecycle.py) obejmują bariery
wątkowe, callbacki i spóźnione wyniki. Zamrożone 11 śladów sprzed refaktoryzacji
sprawdza komendy, kolejność efektów i zdarzenia USB/BLE przy sukcesie i błędach.
Osobne regresje dotyczą błędu callbacku pozostawiającego busy i shutdown podczas
ACK; nie są zmianą protokołu ani dowodem elektrycznego bezpieczeństwa.

### Planowanie i wykonanie

[MidiSource](../host/midi_source.py) parsuje nuty, tempo, metrum, programy,
kontrolery i lyrics. [Runtime Arranger](../host/runtime/arranger.py) przekazuje
planowanie do [pipeline'u](../host/runtime/planning_pipeline.py), a AUTO korzysta
z [alokatora sprzętowego](../host/playback/hardware_arranger.py):
normalizacja duplikatów, role i kandydaci, zajętość oraz profile, artykulacja,
rezerwacje dodatkowe i walidacja. Kolejność refinements wewnątrz alokatora
zależy od presetu; [algorytmy](ARRANGEMENT.md) są opisane w jednym miejscu.

Pipeline ma kolejność: `allocate_backbone` → `resolve_expression` →
`enforce_fdd_limits` → opcjonalne `recover_voices` z ponowną walidacją →
`finish_articulation`. `ArrangementStrategy` odróżnia wybrany preset od
współdzielonej alokacji Expressive; nie zmienia tymczasowo konfiguracji
użytkownika. STRICT_TRACKS zachowuje osobną ścieżkę. Modele urządzeń i profili
są w neutralnym [device_models.py](../host/playback/device_models.py);
`playback.virtual` zachowuje importy zgodności dla historycznych CLI/podglądu.

Runtime dodaje ekspresję tonalną i artykulację HDD, po czym wykonuje wspólny
pass ograniczania ataków FDD. Universal ma po nim dodatkowe odzyskiwanie głosów,
podobnie jak 2×4 Unisono i FDD Expressive. Expressive rezerwuje cztery logiczne
głosy w parach FDD1–2, 3–4, 5–6, 7–8, dobiera rytmiczne gate'y i opcjonalne
krótsze kopie akcentów; omija eksperyment stałych 200 ms tylko we własnym AUTO.
Recovery dla obu presetów grupowych nie dodaje niezależnych nut FDD.
Odzyskiwanie sprawdza pełną chronologię każdej nowej rezerwacji. Kolejny etap ustawia
[rejestr DVD 200–800 Hz](../host/playback/dvd_register.py), preferując +1 oktawę
całych fraz, bez zmiany rezerwacji i liczby nut. Ponownie sprawdza chronologię DVD.
Wariant A/B `fdd_expressive_solo` planuje pełne Expressive, a następnie usuwa
wyłącznie kopie `FDD_ACCENT`, przelicza indeksy sidecarów i ponownie sprawdza
chronologię FDD. Nie wykorzystuje zwolnionych miejsc do doboru innych nut.
`fdd_legato` korzysta z tego samego tła, po czym przeorganizowuje wyłącznie
pierwotne nuty FDD: stabilne napędy na frazę, łączenie powtórzeń i redukcja
szybkich zmian. Następnie wolne stacje w parach wzmacniają mocne fragmenty
kopiami przebiegu legato (`FDD_LEGATO_REINFORCEMENT`). Decyzja wynika z ataków
źródłowych, także powtórzeń scalonych w długi ton. Dodatkowe rezerwacje
zachowują wszystkie przyszłe główne nuty. Ponownie sprawdza pełną chronologię
i odświeża stany FDD.
Adaptive Legato używa tego samego tła i lokalnej ochrony ataków. Każdy zachowany
głos ma stałą parę FDD1–2, 3–4, 5–6 lub 7–8 o identycznym pitch/start/gate
(`FDD_PAIR_UNISON`), także w spokojnych fragmentach. Brak partnera, wyłączone
unisono lub weto mechaniczne pozostawiają głos bez kopii.
`PerformancePlan` zawiera
źródłowe dane, wykonane zdarzenia, pominięcia z powodami, extras i sidecary ekspresji.
Nie jest jeszcze kolejką transportową.

Wewnętrzny `PlanningContext` nie jest raportem `hardware`. Grupy FDD i flaga
`join_fdd_tones` trafiają do wykonania bez odczytywania diagnostyki.
Reinforcement ma deterministyczne powiązanie `extra-event:N` z artykulacją,
zachowane przy filtrowaniu i zastępowaniu zdarzeń. Publiczne `extra:N` pozostaje
projekcją zgodności raportu/API; starsze wejścia można jednokrotnie zaadaptować.
Usunięcie słownika diagnostycznego nie zmienia zachowania kompilatora.

[compile_plan](../host/runtime/compiler.py) tworzy uporządkowany
`ExecutionTimeline`: tone/hit/stop ze stabilnym `device_id`. Stykające się tony
nie mają pośredniego STOP; dla DVD i jawnego `join_fdd_tones` tolerancja
błędu float granicy wynosi 1 ns.
Rzeczywiste przerwy nadal generują STOP. Liczenie STOP i ciągłych odcinków pracy
musi korzystać z tej warstwy, obejmując również dodatkowe głosy.
W VIRTUAL nowy preset utrzymuje jeden zapętlony podgląd mechaniczny przez
stykające się nuty danej stacji i skokowo zmienia jego wysokość. Pauza, STOP,
mute i zmiana epoki przerywają głos. Ten model nie jest kalibracją akustyczną.

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
Przygotowanie urządzeń jest potwierdzaną transakcją bramki `GATEWAY CONFIG`,
zakończoną przed uruchomieniem zegara utworu. Przyjmuje wyłącznie ograniczony
zestaw komend konfiguracji, bez PLAY, HOME, HIT, AMP/FREQ i POWER.
Każde okno BLE nadal wymaga ACK w 250 ms. Muzyka zachowuje asynchroniczny
strumień: samo `sendall()` do bramki oznacza zakolejkowanie, a bramka czeka na
ACK wykonania i łączy już należne komendy bez oczekiwania na przyszłe nuty.
Potwierdzenie przygotowania jest wysyłane między kompletnymi liniami STATUS.
Konfiguracja wysyła FDD5–8 PROFILE/ENABLE, pobiera atomowy `DIAG FDD`, a
automatyczny homing TRACK0 czeka na potwierdzenie FDD5–8 przed PLAY.
Domyślnie HDD1–2 dostają ENABLE 1 i wykonują HIT; HDD3–4 pozostają wyłączone.
Registry oraz `bind_devices(..., 2)` liczą ordynały również wyłączonych pozycji,
więc wyłączenie FDD1 nie przenosi FDD2 na kanał 1. OrchestraLink sprawdza
osobne granice FDD 1–8, SLED 1–4 i HDD 1–4, odrzucając także ID typu bool.
Wymaga `board=esp32`, protocol 2, `ready=1`, `stop_ack=1`, `hardware_profiles=1`
oraz capabilities potrzebnych planowi (m.in. `dvd_continuous`, `speaker_fx`,
`speaker_waves`, `strict_tracks`). Konfigurację potwierdza kompletna transakcja
STATUS. Firmware zachowuje 17 rekordów STATUS z FDD1–4; host atomowo scala
osobną transakcję `DIAG FDD` dla FDD5–8, bez zwiększania limitu 20 linii
podstawowego STATUS. Cztery DVD są raportowane przez STATUS. FDD wymagają
potwierdzonego HOME. Jawny Play w REAL przygotowuje automatycznie
niewyciszone FDD użyte w planie, jeśli nie mają odniesienia; Player czeka bez
przesuwania zegara utworu, pozostawiając STOP dostępny. STATUS nie jest wysyłany
ponownie przed zakończeniem poprzedniej transakcji. Dopiero pełne potwierdzenie
homingu pozwala zacząć nuty; błąd/timeout nie wznawia odtwarzania. Boot/reconnect
same nie wykonują HOME ani Play. W Laboratory każde Uruchom dla REAL FDD wykonuje HOME tylko wybranej stacji,
czeka na świeży STATUS lub DIAG FDD z potwierdzonym TRACK0 i dopiero uruchamia ton.
USB służy flashowaniu i diagnostyce.

VIRTUAL odbiera ten sam timeline, z wyprzedzeniem 150 ms względem czasu
wykonania (REAL bez takiego lookahead). [virtualOutput.ts](../web/src/virtualOutput.ts)
synchronizuje zegar i epoki; [mechanicalAudio.ts](../web/src/mechanicalAudio.ts)
syntezuje dźwięk proceduralnie. Nie parsuje MIDI i nie układa drugiej aranżacji.
Velocity/CC i obwiednia modelu audio nie są fizyczną regulacją amplitudy FDD/DVD.
Utrata synchronizacji wycisza audio; brzmienie, poziom i rezonanse wymagają
osobnej kalibracji wobec urządzeń.

Frontendowy [useRuntime](../web/src/runtime.ts) składa klienta komunikacji,
proces importu, historię firmware i pojedynczy silnik audio. Jego moduły:
[RuntimeClient](../web/src/runtimeClient.ts) zarządza WebSocket, reconnect,
heartbeat i oczekującymi `requestId`; [MidiImportProcess](../web/src/midiImport.ts)
prowadzi STOP z ACK → upload → `set_file` z ACK; [FirmwareEvents](../web/src/firmwareEvents.ts)
utrzymuje historię UI. Zwykłe wysłanie komendy nadal różni się od oczekiwania
na ACK. Zamknięcie klienta odrzuca oczekujące żądania i anuluje jego timery,
a odmontowanie kończy import i audio. Firmware upload/recovery wykonuje backend.

[DeviceService](../host/runtime/device_service.py) po potwierdzonym STOP
przejmuje wyłączne sterowanie na czas USB uploadu, homingu lub operacji POWER.
Nie ma resetowania kontrolera przez BLE. STOP/ACK, watchdog i postępowanie
przy niepewnym stanie opisuje [procedura awarii](HARDWARE_TESTING.md#awarie).

Laboratorium ma niezależne zadania kanałów w
[Laboratory](../host/runtime/laboratory.py), wykonywane przez istniejący tick Playera
oraz Router. Nie ładuje nowego timeline przy każdym starcie, więc drugi kanał
nie zatrzymuje pierwszego. Komendy nadal są `ExecutionCommand`; wyjścia i STOP
pozostają wspólne. Serwis/POWER OFF unieważniają zadania przez Player.invalidate.
Stan `laboratory.active` zawiera aktualne Hz, modulację, czas i pozostały limit;
`lab_test`, `lab_update`, `lab_stop` wymagają właściciela sesji lab. VIRTUAL
używa krótkiej odnawianej dzierżawy audio bez ponownych ataków. Mechaniczny model
lab używa zapętlenia bufora z playbackRate; model utworów MIDI pozostaje bez zmian.
Przeglądarka zachowuje ustawienia osobno dla każdego urządzenia, także wyłączonego,
a zapisane ustawienia urządzeń usuniętych z katalogu są automatycznie czyszczone.
[Szczegółowa obsługa i ograniczenia](HARDWARE_TESTING.md#laboratory).

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
| `/settings` → Brzmienie PC Speaker | Gain VIRTUAL i modulacja prostokąta REAL + VIRTUAL osobno dla dwóch speakerów |
| `/settings` → Zasilanie ATX | Ręczne ON/OFF, stan logiczny i potwierdzenie ON |
| `/settings` → Serwis | Wgraj firmware ESP32, Homing |
| `/settings` → Laboratory | Lista i panel urządzenia, równoległe testy, odliczanie lub ∞ Do STOP |

Aplikacja zawsze startuje w REAL, nawet offline. Wybór presetu jest sesyjny:
restart odczytuje `parameters.arrangementPreset` z JSON (obecnie `instrument_roles_unison4`).
Zmiana presetu potwierdza STOP, przebudowuje plan i zwiększa rewizję,
bez autoplay. Podczas przygotowywania nowego pliku MIDI przełącznik REAL/VIRTUAL
pozostaje dostępny i nie czeka w kolejce za obliczaniem aranżacji. Zmiana nadal
przechodzi przez Player/Router i potwierdzony STOP; zajęty serwis blokuje ją,
a zakończenie wczytywania nie przywraca starego wyjścia ani nie uruchamia gry.
Inventory/profil zmieniasz w JSON, potem przebudowujesz aplikację;
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

### Aktualizacje firmware przez BLE

Oba transporty aktualizacji należą do `DeviceService`: `firmware` oznacza USB,
`firmware_ble` oznacza BLE OTA. Wspólny początek to wyłączność serwisu, zatrzymanie
odtwarzania, skorelowane STOP i POWER OFF oraz 1 s oczekiwania. USB zwalnia BLE;
OTA zachowuje połączenie, lecz odłącza je od RealOutput, aby heartbeat i komendy
muzyczne nie mieszały się z transferem. WebSocket laptop–backend nadal przesyła
postęp. Nie potrzeba drugiego połączenia BLE ani Wi-Fi.

Pierwszy build przez serwis tworzy prywatny klucz ECDSA P-256 w
`ORCHESTRA_OTA_KEY` (Compose: `/app/settings/ble-ota-key` w trwałym wolumenie).
Wygenerowany nagłówek `.generated/ble_ota_key.h` zawiera wyłącznie klucz publiczny.
Oba pliki są wyłączone z Git i kontekstu Docker. Utrata klucza prywatnego wymaga
ponownego provisioningu przez USB; nie generujemy zastępczego klucza przy próbie
BLE. Samodzielny build PlatformIO bez nagłówka pozostawia OTA wyłączone.

Charakterystyki NUS `...0005` (control/notify) i `...0006` (data) realizują osobny
protokół binarny. ESP32 wydaje losowy challenge 16 B; host podpisuje challenge,
rozmiar i SHA-256 obrazu. Manifest ma 100 B: uint32 LE, SHA-256 32 B i podpis
ECDSA r||s 64 B. Publiczny klucz i podpis obrazu mogą być widoczne w transmisji;
klucz prywatny nie trafia do firmware ani do radia. Transfer nie zapewnia
poufności samego obrazu ani sprzętowego Secure Boot.

Po poprawnej autoryzacji i potwierdzeniu logicznego ATX OFF firmware blokuje
komendy ruchu/POWER ON na USB i NUS. Callback tylko kolejkuje bajty; zapis Flash
wykonuje loopTask. Okno zawiera najwyżej 6 ramek przy 8 miejscach RX; każde ma
offset, a ostatnia ramka okna wymaga potwierdzenia liczby zapisanych bajtów.
Nie ma automatycznych powtórzeń. Timeout OTA wynosi 10 s na odpowiedź/bezczynność,
cały transfer jest ograniczony do 900 s; nie zmienia to progu 250 ms dla muzyki.

Zapis obejmuje wyłącznie nieaktywną partycję aplikacji. Default ESP32 layout ma
`ota_0`/`ota_1` po `0x140000` B i `otadata`; bootloader, NVS i tabela partycji
pozostają bez zmian podczas BLE OTA. END sprawdza pełne SHA-256 i obraz ESP32,
COMMIT dopiero wybiera partycję, odsyła ACK i planuje restart po 500 ms. Przerwanie
przed COMMIT nie wybiera nowej aplikacji. Brak ACK po COMMIT oznacza niepewny
wynik; nie ponawiamy uploadu. Zwykły reconnect weryfikuje protokół i POWER OFF,
nie przywraca ATX ON ani utworu. Automatyczny rollback po błędzie uruchomienia
aplikacji nie jest włączony przez tę implementację; USB pozostaje drogą naprawy.

[Uruchamianie i ograniczenia OTA](HARDWARE_TESTING.md#aktualizacja-firmware-przez-ble).

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

Nowe firmware udostępnia obok NUS RX/TX charakterystykę notify
`6E400004-B5A3-F393-E0A9-E50E24DCCA9E` dla barier `SYNC <token>` →
`SYNCED <token>`. Host najpierw sprawdza jej obecność i potwierdza pustą barierę.
Następnie wysyła ograniczoną grupę pełnych komend przez write without response,
dopisuje SYNC i czeka na właściwy token przed następną grupą. Potwierdzenie
powstaje w loopTask po parsowaniu wcześniejszych bajtów, nie w callbacku GATT.
To usuwa oczekiwanie na ATT Write Response w CoreBluetooth; **nie oznacza**
potwierdzenia poprawności każdej komendy, ukończenia ruchu ani pomiaru napięcia.
ERR oraz osobne STOPPED/POWER nadal przechodzą przez istniejący parser NUS.

ACK ma osobną, ograniczoną kolejkę i pierwszeństwo między fragmentami STATUS.
Nie rozcina linii NUS, nie dotyka GPIO i nie odświeża watchdoga. Jedna grupa
zajmuje najwyżej sześć fragmentów ATT przy każdym MTU, poniżej ośmiu miejsc RX. Utrata
pakietu przez RX overflow unieważnia kolejne ACK do reconnect. Brak zgodnego ACK
przerywa sesję; nie ma automatycznego ponawiania komend muzycznych. Pozostają
limit wieku 250 ms, priorytet STOP, watchdog i brak odtwarzania po reconnect.

Starszy firmware bez nowej charakterystyki używa dotychczasowych zapisów ATT
z odpowiedzią. Bramka loguje `delivery=execution-ack` lub `att-response (legacy)`.
Sama aktualizacja kontenera nie aktywuje nowego transportu w ESP32: potrzebne
są osobno autoryzowany safe upload i restart natywnej bramki. Charakterystyka
obecna, ale niedziałająca, kończy połączenie błędem zamiast cichego fallbacku.
[Diagnoza i zakres weryfikacji](research/ble-overrun-diagnosis.md).

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
.venv/bin/python scripts/generate_preset_catalog.py --check
.venv/bin/python scripts/check_architecture.py
pio run -d firmware/controller -e esp32
```

Zainstaluj `httpx` w środowisku testowym dla testów API; testy natywnego rdzenia
C++ potrzebują lokalnego kompilatora. `npm ci` instaluje frontendowe zależności.
Generator z `--check` sprawdza zgodność bez zapisywania konfiguracji/nagłówka.
[Testy pojemności backendu](../host/tests/test_backend_capacity.py) sprawdzają
18 pozycji / 16 aktywnych w planowaniu, stabilne ordynały kanałów, limity ID,
bramkę `realEnabled`, pełny cykl DIAG/HOME/PLAY FDD8 na atrapach, HIT wszystkich
czterech HDD po jawnym włączeniu w teście, niezmieniony STATUS i cztery sloty
STRICT_TRACKS. Testy presetów, w tym FDD Expressive, sprawdzają dozwolone kanały wykonawcze.
[Testy dwóch HDD](../host/tests/test_two_hdd.py) obejmują domyślnie nieaktywne
HDD3–4, filtrowanie gotowości i komend routera, ochronę głównego rytmu oraz
wspólny limit 8 HIT/s, wyłącznie offline.
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

## Kontrola granic i ograniczenia refaktoryzacji

[check_architecture.py](../scripts/check_architecture.py) używa wyłącznie AST i
`symtable`, bez importowania aplikacji. Obejmuje moduły runtime/web/playback
oraz MidiSource, pitch i katalog presetów: wykrywa niezdefiniowane odwołania
globalne, wildcard imports i wybrane niedozwolone importy między warstwami.
Nie zastępuje analizy przepływu, typów, dynamicznych importów ani testów
współbieżności. Nie wykrywa wszystkich lokalnych odczytów przed przypisaniem.

Pozostawiony wyjątek granic jest jawny: `universal_recovery` importuje dokładnie
`runtime.compiler.compile_plan` do diagnostycznego fingerprintu szkieletu.
Guard dopuszcza tylko tę istniejącą zależność, bez ogólnego zezwolenia na importy
runtime w planowaniu. Historyczny eksport `VirtualDeviceInstance` z virtual i
publiczne sidecary `extra:N` pozostają adapterami zgodności; nie są drugim modelem
urządzeń ani osobną artykulacją.

Porównania [baseline'u](research/refactoring-baseline.md),
[końcowy raport weryfikacji](../reports/refactoring-verification-2026-10-26.json)
i [plan wykonania etapów](REFACTORING_PLAN.md) dokumentują zgodność poleceń
offline. Czyste przenosiny kodu nie zmieniają MIDI, harmonogramów ani firmware.
Osobne naprawy granicy importu plików i przeplotów sesji/blokad mają własne testy;
nie należy ukrywać ich jako zmian muzycznych lub nowych zabezpieczeń sprzętowych.
Oprogramowanie nadal nie mierzy temperatury, prądu ani zaniku napięcia ATX.
