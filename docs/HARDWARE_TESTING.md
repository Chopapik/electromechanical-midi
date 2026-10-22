# Uruchamianie sprzętu, diagnostyka i awarie

Najpierw [połączenia](HARDWARE_WIRING.md), następnie
[limity i status pomiarów](HARDWARE_DEVICES.md). Poniższa procedura nie została
w całości powtórzona na docelowym zestawie 8 FDD / 4 DVD / 4 HDD / 2 speakery / 6 rejestrów / 6 wykorzystywanych DRV8833.
Testy programowe nie mierzą temperatury, prądu, dźwięku ani pozycji.

## Kontrola bez zasilania urządzeń

1. **Wyłącz/odłącz VM mostków, zasilanie FDD i V_SPK oraz sygnały do
   FDD/DRV/speakerów**, także podczas flashowania. Zidentyfikuj modele modułów,
   piny zasilania, orientację 74HC595 i faktyczne B/C/E obu S8550 PNP speakerów (osobny S8050 NPN steruje ATX).
2. Sprawdź **pin 8 GND każdego z sześciu rejestrów**, ciągłość wspólnej masy, brak zwarć między dodatnimi szynami i masą,
   połączenia szyn płytek stykowych, każdy /OE i /SRCLR oraz łańcuch QH′→SER.
3. Prześledź Q0–Q47 według tabeli w schemacie: 40 wyjść jest przypisanych,
   Q32–Q39 są wolne, HDD używają Q40–Q47. SR5 musi pozostać w kaskadzie.
   Sprawdź, że GPIO27 nie trafiło na DRV3 BIN2 (Q27).
4. Zmierz rezystancje par cewek DVD i HDD. Ustal wartości rezystorów bazowych
   oraz napięcie i prąd speakerów. Nie uruchamiaj nieustalonego obwodu mocy.
5. Zweryfikuj poziomy STEP/DIR i TRACK0 dla konkretnych FDD. Nie podawaj
   podciągania 5 V na GPIO ESP32; każde z ośmiu TRACK0 ma zewnętrzny pull-up 3,3 V. Przy odłączonej logice zidentyfikuj /DS.
6. Zapewnij możliwość natychmiastowego odłączenia zasilania urządzeń oraz
   pomiar prądu i temperatury silników/mostków podczas prób.

## Firmware i sama logika

Zbuduj właściwy target (domyślny target PlatformIO jest inny):

```sh
pio run -d firmware/controller -e esp32
.venv/bin/python scripts/generate_hardware_profiles.py --check
```

Flashowanie przez USB/CP2102 wykonuj wyłącznie przez `/settings` →
**Serwis → Wgraj firmware ESP32** lub wspólną procedurę:

```sh
.venv/bin/python scripts/safe_upload.py
```

Skrypt łączy się z lokalną aplikacją (`--url ws://127.0.0.1:5173/ws`),
wywołuje ten sam DeviceService i nie ma obejścia braku potwierdzenia OFF.
Nie używaj bezpośredniego `pio ... -t upload`. Sekwencja: wyłączność serwisowa →
zatrzymanie odtwarzania i potwierdzone ALL STOP → POWER OFF z dopasowanym tokenem
oraz potwierdzeniem GPIO19 LOW → robocze 1 s oczekiwania → zamknięcie BLE →
sprawdzenie USB → build → ponowne sprawdzenie portu → upload → powrót BLE.
Nie ma automatycznego POWER ON ani autoplay; po flashowaniu backend ponownie
potwierdza OFF. Brak BLE, obsługi POWER lub świeżego ACK przerywa procedurę
**przed buildem/uploadem**, także przy obecnym porcie USB. Błąd builda/uploadu
pozostawia zasilanie logicznie OFF; utrata łączności oznacza UNKNOWN.

**Pierwsze wdrożenie:** starszy firmware nie zna POWER, więc normalny upload
zostanie odmówiony. Potrzebna jest osobno zatwierdzona ręczna procedura bootstrapu,
z fizycznie wyłączonym/odłączonym ATX, odłączonymi obciążeniami/sygnałami i oceną
[domen zasilania](HARDWARE_WIRING.md#sterowanie-atx-przez-ps_on).
Nie traktuj samej deklaracji GPIO LOW ani upływu 1 s jako pomiaru napięcia.
Nie dodano przycisku ani flagi omijającej tę blokadę. Zasady pracy narzędzi:
[AGENTS.md](../AGENTS.md). Monitor USB: 115200, 8N1; wyłącz DTR/RTS,
jeśli program monitora resetuje płytkę przy otwarciu.

### ATX: protokół i testy logiczne

Na USB i BLE dostępne są `POWER ON`, `POWER OFF`, `POWER STATUS`.
Odpowiedzi: `POWER ON gpio19=1`, `POWER OFF gpio19=0`,
`POWER STATUS ON gpio19=1` albo `POWER STATUS OFF gpio19=0`.
Opcjonalny dziesiętny token (1–10 cyfr) jest powtarzany jako `token=...`;
backend wymaga dokładnego dopasowania tokenu, stanu i poziomu GPIO.
STATUS CTRL ma dodatkowe `atx=ON/OFF`, nadal w tej samej 17-liniowej transakcji.
OFF blokuje PLAY/HOME/HIT i AMP/FREQ obu speakerów, również aliasy protokołu;
STOP, konfiguracja, status i odłączona diagnostyka pozostają dostępne.
ALL STOP i watchdog zatrzymują instrumenty, lecz nie przełączają ATX.

Testy offline są w [test_atx_power.py](../host/tests/test_atx_power.py),
[test_esp32_firmware.py](../host/tests/test_esp32_firmware.py),
[test_esp32_protocol.py](../host/tests/test_esp32_protocol.py),
[test_esp32_ble_adapter.py](../host/tests/test_esp32_ble_adapter.py) oraz
[atxPower.test.tsx](../web/src/atxPower.test.tsx). Testują logiczny stan,
transport, blokady i sekwencję uploadu; nie testują elektrycznie zasilacza,
tranzystora, zaniku napięcia ani domen zasilania. Nie uruchamiaj obciążeń jako
części tych testów. Fizyczne testy wymagają osobnej decyzji użytkownika.

Uruchom samą logikę: **ESP32 z USB, rejestry z 3,3 V ATX, wspólna masa**.
Nie łącz dodatnich szyn ATX i zasilanej USB płytki ESP32, także pinów 3V3/5V/VIN.
Sprawdź /OE podciągnięte 10 kΩ do 3,3 V i HIGH podczas resetu, potem stan boot
**`55 55 00 00 00 00`** SR1→SR6: STEP FDD1–8 HIGH, pozostałe Q LOW.
SR6 jest na końcu kaskady, za SR5; jego bajt wysyłany jest jako pierwszy.
/OE wyłącza wyjścia logiczne, nie moc mostków.
USB zgłasza `READY protocol=2 board=esp32`; nie oznacza to wykonania HOME.

Do sprawdzenia pojedynczych wyjść służy `DIAG BIT n` (n=0…47).
**Wszystkie urządzenia wykonawcze muszą być odłączone**, także FDD i wejścia
sterowników mogące je uruchomić. Komenda nadpisuje całą ramkę, także STEP i wejścia mostków;
mierz wyłącznie logikę. Po diagnostyce zresetuj ESP32 przy nadal odłączonej mocy
i ponownie sprawdź maskę boot. `ALL STOP` wyłącza obsługiwane urządzenia,
ustawia STEP HIGH i wejścia wszystkich mostków DVD/HDD LOW, także Q40–Q47 HDD. Zachowuje stan DIR,
więc dopiero reset przywraca całą maskę startową; żadna z tych komend
nie jest odłączeniem napięcia VM.

### Pomiary sześciu rejestrów bez obciążeń

Zgłoszony brak pinu 8 GND rejestrów powodował wcześniej nieprawidłowe napięcia
i niestabilną logikę. Po poprawce pin 15 pięciu starych układów dawał LOW ≈0 V,
HIGH ≈3,41 V. To tylko wskazany pomiar użytkownika, bez kwalifikacji innych
wyjść i bez pomiaru SR6. Najpierw potwierdź GND i VCC każdego z sześciu układów.

| Rejestr | QA, pin 15 DIP-16 | Komenda HIGH |
| --- | --- | --- |
| SR1 | Q0 | `DIAG BIT 0` |
| SR2 | Q8 | `DIAG BIT 8` |
| SR3 | Q16 | `DIAG BIT 16` |
| SR4 | Q24 | `DIAG BIT 24` |
| SR5 | Q32 | `DIAG BIT 32` |
| SR6 — nowy, ostatni | Q40 | `DIAG BIT 40` |

Mierz względem wspólnej masy; wybrane QA powinno być HIGH, pozostałe LOW.
Przełącz wybrany bit na inny, aby sprawdzić również LOW danego pinu. Następnie
sprawdź kolejno **wszystkie Q0–Q47**, właściwe piny QA–QH i brak przesunięcia
bajtów. Nie zakładaj identycznego wyniku dla SR6 na podstawie pięciu starych.
Po pomiarach zresetuj samą logikę i potwierdź maskę startową. Obciążenia
podłączaj dopiero po przejściu tych kontroli, przy ponownie odłączonym zasilaniu.


## BLE bez silników

Jedna płytka obsługuje USB i BLE tym samym dispatcherem. Nie ma osobnego
firmware testowego. Nazwa reklamowa: **Electromechanical-MIDI**.

| Endpoint | UUID | Kierunek |
| --- | --- | --- |
| Service | `6E400001-B5A3-F393-E0A9-E50E24DCCA9E` | Nordic UART Service |
| RX | `6E400002-B5A3-F393-E0A9-E50E24DCCA9E` | Write / Write Without Response do ESP32 |
| TX | `6E400003-B5A3-F393-E0A9-E50E24DCCA9E` | Notify z ESP32 |

Wyłącz aplikację/bramkę zajmującą połączenie przed testem klientem GATT.
Obsługiwany jest jeden klient BLE. Subskrybuj TX przed wysłaniem komendy do RX.
Komendy są ASCII zakończonym rzeczywistym LF (0A), nie dwoma znakami `\n`.
Przykład `PING` z LF w hex: `50 49 4E 47 0A`.

```text
PING
TEST ON
TEST STATUS
TEST OFF
STATUS
ALL STOP 1001
```

Oczekuj PONG, zapalenia/zgaszenia opcjonalnej LED GPIO27, transakcji STATUS
oraz `STOPPED 1001`. STATUS zawiera BEGIN, CTRL, 4 FDD, 4 HDD, 4 SLED,
VHS, VHS2, END (17 rekordów). Powiadomienia są fragmentowane do 20 bajtów:
składaj je do LF, również przy MTU 23. Boot READY jest wysyłane przez USB;
połączenie BLE sprawdza się PING/STATUS. Rekord urządzenia nie dowodzi,
że silnik jest fizycznie podłączony. FDD5–8 celowo nie są dodawane do STATUS:
bufor hosta ma limit 20 linii, a poszerzenie obecnych 17 dałoby 21.
Wyślij osobno `DIAG FDD`: odpowiedź `DIAG FDD BEGIN`, cztery rekordy
`DIAG FDD 5`…`DIAG FDD 8`, `DIAG FDD END` pokazuje enabled/HOME/PLAY/TRACK0
nowych kanałów bez mieszania ich ze STATUS. STATUS zawiera wszystkie cztery DVD.
Używaj klienta diagnostycznego
przy zatrzymanej aplikacji, aby nie współdzielić sterowania.

USB i BLE mają osobne bufory linii do 95 bajtów. `ERR LINE_TOO_LONG`,
`ERR RX_OVERFLOW` lub `ERR TX_OVERFLOW` oznaczają problem protokołu/kolejki,
nie gotowość do dalszego ruchu. W trakcie ręcznych prób wysyłaj PING co sekundę;
watchdog po 3 s bez komend wyłącza urządzenia. Dwa transporty sterują tym
samym sprzętem: nie uruchamiaj równocześnie ręcznych testów i playera.

## Pierwsze próby urządzeń

Podłączaj i kwalifikuj pojedynczy kanał przy odłączonym zasilaniu, a następnie
uruchamiaj skończone próby z ograniczonym prądem. Nie zaczynaj od całej orkiestry.

| Urządzenie | Sprawdzenie przed grą | Obserwacje w próbie |
| --- | --- | --- |
| FDD | /DS, TRACK0 aktywne LOW i właściwy kanał; jawny HOME | Czy dochodzi do TRACK0, odsuwa się, nie uderza w koniec, nie gubi odniesienia |
| DVD | Pary cewek, VM 5 V, stan wejść mostków, swobodny obrót, kontakt termiczny z elementem odbierającym ciepło (np. metalową obudową VHS) | Kierunek, rampa, zmiana celu bez STOP, prąd i temperatura silnika/sterownika/obudowy |
| HDD | Rezystancja/połączenia cewki, VM 5 V, miejsce ruchu ramienia, odprowadzanie ciepła do obudowy | Pojedynczy HIT, park/settle/strike, brak zakleszczenia, prąd i temperatura cewki/sterownika/obudowy |
| Speaker / FX | Zgłoszone 3,3 V ATX, baza 330 Ω, pull-up 10 kΩ, szeregowo 56 Ω (moc rezystora do potwierdzenia); pinout S8550 do sprawdzenia | Każdy kanał osobno, brak sprzęgania częstotliwości, prąd, temperatura i nośna PWM |

Praca DVD/HDD przy 5 V z chłodzeniem jest aktualnym zgłoszeniem użytkownika.
Przy odtwarzaniu tego montażu zapisz czas próby, temperaturę otoczenia i części,
prąd oraz sposób mocowania do obudowy. Metalowy case VHS może być jednocześnie
elementem odprowadzania ciepła i pudłem rezonansowym; ocena brzmienia nie zastępuje
sprawdzenia temperatury.

**FDD5–8 są zadeklarowane jako podłączone i aktywne w planowaniu, VIRTUAL oraz
REAL (`realEnabled:true`, `present:true`).** Parametry fallbacku nie zastępują
indywidualnej kontroli TRACK0, /DS, poziomów, ruchu i parametrów. Jawny
`FDD n ENABLE 1` nie wykonuje HOME; dopiero osobny
`FDD n HOME` rozpoczyna ruch. `FDD ALL HOME` obejmuje też nowe kanały, jeśli
wcześniej zostały ręcznie włączone. Nie używaj tej komendy zamiast testu jednej
nowej stacji. Dodatkowe kanały są dostępne w VIRTUAL UI, Laboratory i REAL;
normalne PLAY wymaga ich potwierdzenia przez `DIAG FDD` i homing TRACK0.

DVD1–4 zajmują Q16–Q31 na DRV1–4. HDD1–4 zachowują **DRV7–8 / Q40–Q47**.
Q32–Q39 są wolne i nie mogą być podłączone do urządzeń wykonawczych.
Sprawdź cztery własne profile DVD oraz odrzucanie ID poza zakresem 1–4.

Aplikacja konfiguruje profile i ENABLE **FDD1–8 oraz DVD1–4** przed grą. Samo połączenie nie wykonuje
HOME. Przy jawnym **Play** w REAL aplikacja automatycznie wysyła HOME do
niewyciszonych FDD potrzebnych w planie, które nie mają potwierdzonego `homed=1`.
Czeka na kompletny STATUS z `homed=1, homing=0`, dopiero potem uruchamia zegar
utworu i nuty. Już skalibrowane FDD nie są ponownie parkowane. STOP przerywa
przygotowanie; błąd czujnika/transportu lub timeout nie uruchamia muzyki.
ATX musi być wcześniej włączony przez użytkownika; Play nie włącza go automatycznie.
VIRTUAL nie wykonuje homingu. Laboratory automatycznie wykonuje HOME wybranej FDD po kliknięciu Uruchom w REAL.
Ręczne parkowanie pozostaje w `/settings` → **Serwis → Homing TRACK0**
(obejmuje wszystkie włączone stacje). `homed=1` i aktywne TRACK0 to różne stany. `HOME_FAILED` wymaga sprawdzenia czujnika, /DS, DIR i przewodów;
nie ponawiaj bez końca uderzającej w ogranicznik karetki.

Ręczne komendy diagnostyczne (najpierw poprawny profil/ENABLE; podane Hz są
przykładami składni, a nie kwalifikacją nieznanego silnika):

```text
FDD 1 HOME
FDD 1 PLAY 130.81
FDD 1 STOP
SLED 1 PLAY 220.00
SLED 1 PLAY 330.00
SLED 1 STOP
HDD 1 HIT
HDD 1 STOP
VHS AMP 50
VHS FREQ 440.00
VHS STOP
VHS2 ENABLE 1
VHS2 AMP 50
VHS2 FREQ 830.61
VHS2 STOP
ALL STOP 1002
```

Każdy kanał ma `ENABLE 0|1`, np. `SLED 1 ENABLE 1`.
Po PLAY zaplanuj STOP; watchdog nie zastępuje skończonej próby przy aktywnych PING.
Nie przesyłaj ręcznie profilu z pominięciem nierozpoznanych parametrów sprzętu.

## Laboratory

`/settings` → **Laboratory → Laboratory · debug** otwiera testy bez MIDI.
Po lewej jest lista urządzeń, po prawej panel wybranego kanału. Nie ma kart
orkiestry. Częstotliwość ustawisz suwakiem, polem Hz, skrótem nuty lub przyciskami
±półton / ±oktawa. Ustawienia każdego urządzenia zapisują się lokalnie w przeglądarce;
zmiana zaznaczenia, wyjście i odświeżenie nie kasują parametrów i nie uruchamiają testów.

Wybierz **Odliczanie** (0,1–3600 s, domyślnie 5 s) lub **∞ Do STOP**, potem
**Uruchom**. Przejdź do kolejnego urządzenia i uruchom je niezależnie: wcześniejszy
kanał nadal gra. W REAL każda FDD przed testem otrzymuje własne STOP i HOME.
Panel pokazuje oczekiwanie na TRACK0; wymagany jest świeży, kompletny STATUS
(FDD1–4) lub DIAG FDD (FDD5–8), enabled=1, homed=1, homing=0 i track0=1.
Czas testu zaczyna się po potwierdzeniu homingu. STOP działa również podczas
oczekiwania. Błąd, utrata połączenia lub timeout 10 s przerywa sesję bez
późniejszego automatycznego startu. Aktualizacja Hz podczas testu nie wykonuje
ponownego HOME. VIRTUAL i inne rodziny nie otrzymują HOME.
Lista pokazuje aktualne Hz i czas. Stopka sygnalizuje homing wybranych FDD;
błędy uruchomienia, zmiany parametrów i zatrzymania zawierają nazwę urządzenia.
Mapuje znane błędy firmware, odrzucenia profilu, restart ESP32 i opóźnienia BLE
na opisy po polsku. Przy błędzie HOME/timeout pokazuje opis TRACK0. Surowy
komunikat pozostaje w rozwijanych szczegółach; nieznane kody nie są ukrywane.
Brak potwierdzenia STOP pozostaje osobnym ostrzeżeniem, niezależnie od opisu błędu. **Stop [urządzenie]** zatrzymuje
wybrany kanał; **Zatrzymaj wszystko** przerywa całą sesję. **Orkiestra** kończy testy
bez autoplay. Zmiana czasu dotyczy kolejnego uruchomienia, nie wydłuża aktywnego testu.

**Vibrato** moduluje częstotliwość sinusoidalnie, **Przemiatanie** trójkątnie.
To modulacja wysokości tonu, nie nowy przebieg elektryczny speakera: oba PC Speakery
nadal generują wyłącznie prostokąt z regulowanym wypełnieniem. Pole Hz i modulacja
aktualizują aktywny test po 250 ms bez zmian suwaka. Zakres całej modulacji musi
mieścić się w jednym dozwolonym paśmie profilu; nie składamy Hz oktawowo.
Dla ciągłego DVD obowiązuje istniejący zakres wykonawczy profilu/protokołu,
nie muzyczny sufit aranżera 600 Hz. Dostępny zakres nie oznacza bezpieczeństwa
termicznego, mechanicznego ani potwierdzonego brzmienia.

HDD wykonuje tylko pojedynczy HIT z czasami i odstępami profilu, bez opcji ciągłej
lub modulacji. REAL wymaga BLE, logicznego ATX ON, aktywnego profilu, braku Mute
oraz wcześniej potwierdzonego HOME dla FDD. Lab nie włącza ATX ani nie wykonuje
automatycznie homingu.

Lab używa tego samego Playera, Routera i wyjścia. Każdy kanał ma własny termin;
wspólna pętla wysyła zmiany maksymalnie co 100 ms, w jednym batchu, bez nadrabiania
zaległych próbek. Stały ton REAL nie wymaga ponawiania PLAY. VIRTUAL odnawia
krótkie, maksymalnie 0,5-sekundowe odcinki bez ponownego ataku oscylatora.
Podgląd mechaniczny lab zapętla krótki fragment modelu i zmienia playbackRate:
przy zmianie Hz zmieniają się także rezonanse modelu. To przybliżenie do odsłuchu
połączenia częstotliwości, nie pomiar ani kalibracja rzeczywistego urządzenia.
Zwykłe odtwarzanie MIDI zachowuje dotychczasowy model dźwięku.

Wyłączna sesja lab ma lease 3 s odnawiany przez WebSocket sync. Wygaśnięcie lease,
utrata sesji/BLE, błąd wykonania, POWER OFF, zmiana wyjścia/właściciela i globalny
STOP kasują aktywne testy. Ponowne połączenie nie wznawia dźwięku. STOP globalny
zachowuje istniejące potwierdzenie kontrolera; brak ACK pozostaje błędem, nie sukcesem.
**∞ oznacza brak terminu aplikacyjnego, nie kwalifikację do nienadzorowanej pracy.**
Nadzoruj sprzęt i temperaturę; watchdog komunikacji nie mierzy przegrzania.
Nie ma dawnego panelu ocen rezonansu i eksportu historii ocen.
Zapis historycznej próby kontrolera: [pomiary i obserwacje](research/hardware-measurements.md#laboratory).

## Awarie

**Naciśnij STOP.** REAL używa `ALL STOP <token>` (token to 1–10 cyfr) i wymaga pasującego
`STOPPED <token>` w ciągu 2 s. Brak ACK oznacza niepotwierdzony stan sprzętu;
rozłączenie BLE samo nie jest potwierdzeniem zatrzymania. Gdy ruch trwa,
pojawia się zapach/nadmierne grzanie lub nie można potwierdzić STOP,
odłącz zasilanie urządzeń wykonawczych. Sprawdź przyczynę przed ponownym
zasileniem; po utracie odniesienia FDD wykonaj HOME.

STOP omija mute, usuwa stare komendy PLAY i wyłącza fazy DVD/HDD oraz oba
speakery. Dostarczenie przez BLE ma opóźnienie transportu; nie jest to
sprzętowy przycisk odcinający moc. Watchdog firmware 3 s stanowi dodatkowe
zabezpieczenie utraty komend hosta, bez nadzoru termicznego.
Po reconnect aplikacja potwierdza STOP, nie robi HOME i nie wznawia utworu.
VIRTUAL anuluje kolejki/epokę i wycisza audio po utracie synchronizacji.

## Diagnoza w aplikacji

| Objaw | Gdzie sprawdzić |
| --- | --- |
| REAL niedostępne | Natywna bramka BLE, uprawnienia Bluetooth, `/api/state`, brak innego klienta GATT |
| Brak części urządzeń | `config/devices.json`, capability firmware, Mute, mapowanie fizycznej lane |
| FDD zablokowane | HOME i TRACK0, błędy w `/api/firmware/events` |
| Nuta pominięta / skrócona | `/api/plan` i Settings → Aranżacja → Arrangement · PerformancePlan; powód decyzji, nie tylko statystyka |
| STOP pomiędzy tonami DVD | `/api/timeline`: rzeczywista przerwa, źródłowa fraza, ograniczenie sustainu, zmiana partii lub rezerwacja |
| 130 Hz zamiast 260 Hz FDD | Obecna transpozycja −12 i zakres 100–205 Hz; patrz [zakresy](HARDWARE_DEVICES.md#fdd-trzy-różne-zakresy) |
| Drugi speaker / przebieg | `speaker_fx` w STATUS; obsługiwany tylko `pulse`, `speaker_waves=0` |
| VIRTUAL milczy | Wybrane Output, gest uruchamiający Web Audio, gain/duty 0, Mute, aktywna karta i synchronizacja |

Telemetria `/api/monitor/raw` pokazuje ruch komend; nie jest analizatorem STEP
ani pomiarem prądu. Zapisuj wersję kodu, profil, kanał, zasilanie, czas, temperaturę,
prąd i metodę pomiaru przy każdej nowej kwalifikacji sprzętu.

## Weryfikacja zmiany mapy

Procedura offline (bez flashowania i obciążeń):

```sh
PYTHONPATH=host:host/tests .venv/bin/python -m unittest \
  test_esp32_firmware test_esp32_protocol test_esp32_ble_adapter \
  test_fdd_firmware_open_loop test_firmware test_firmware_flow test_orchestra_link -q
pio run -d firmware/controller -e esp32
.venv/bin/python scripts/generate_hardware_profiles.py --check
```

Testy w `host/tests/test_esp32_firmware.py`, `test_esp32_protocol.py` i
`test_esp32_ble_adapter.py` kompilują produkcyjny C++ z atrapami czasu/GPIO,
Arduino/NimBLE/FreeRTOS. Pozostałe sprawdzają m.in. rdzeń UNO i kompatybilność
hosta z atrapami transportu/uploadu; nie są próbami fizycznymi.

### Kontrole bieżącej mapy

Weryfikacja programowa konfiguracji 8 FDD / 4 DVD / 4 HDD obejmuje:

- 40 przypisanych Q (16 FDD, 16 DVD, 8 HDD) oraz osiem wolnych Q32–Q39.
  Brak nakładających się przypisań; HDD pozostają na Q40–Q47.
- Sześciobajtową ramkę SPI i boot SR1→SR6 `55 55 00 00 00 00`.
- Cztery profile DVD indeksowane bez dodatkowego fallbacku; odrzucanie
  identyfikatorów poza zakresem 1–4 przez host, rdzeń C++ i transport USB/BLE.
- STOP, POWER OFF i watchdog dla wszystkich urządzeń, w tym zerowanie wolnych Q.
- STATUS z 17 rekordami oraz osobną diagnostykę FDD; DIAG BIT obejmuje Q0–Q47
  i jest przeznaczone wyłącznie do prób z odłączonymi obciążeniami.
- Zgodność wygenerowanego nagłówka profili i kompilację PlatformIO ESP32.

To zakres kontroli offline, nie wynik pomiaru elektrycznego ani akustycznego.
Obserwacja LOW ≈0 V / HIGH ≈3,41 V dotyczy wybranych wyjść pięciu rejestrów po
naprawie GND; nie potwierdza wszystkich Q ani pozostałych elementów instalacji.

Weryfikacja offline z 2026-10-22 dla bieżącej mapy czterech DVD:

- 759 testów backendu, w tym produkcyjnego C++, protokołu i adaptera ESP32/BLE.
- 122 testy frontendu oraz poprawny build TypeScript/Vite.
- 58 przypadków rdzenia i protokołu C++ z UndefinedBehaviorSanitizer.
- Kompilacja PlatformIO ESP32: RAM 39 180 B, flash 618 469 B;
  sprawdzenie wygenerowanego nagłówka profili bez rozbieżności.
- Pełna biblioteka `/Users/krzysztof/Music/MIDI`: 134/134 pliki, bez błędów,
  identyczne skróty wejściowych MIDI i skompilowanych harmonogramów jak w
  [poprzednim benchmarku](../reports/library-8fdd-experiment.json),
  preset `instrument_roles_unison4`. Zero konfliktów mechanicznych, nakładających
  się nut, naruszeń minimalnego odstępu ataków FDD i rozbieżności grup unisono.
- Przebudowany kontener `orchestra` zdrowy; API publikuje 18 urządzeń,
  w tym cztery DVD. Nie wykonywano uploadu ani prób na fizycznych urządzeniach.

Wyniki kolejnych prób zapisuj wraz z wersją kodu i warunkami pomiarów.

### Sprawdzenie polaryzacji speakerów S8550 PNP

Przed odsłuchem zweryfikuj połączenia z [aktualnym schematem](HARDWARE_WIRING.md#dwa-pc-speakery).
Przy zatrzymanym odtwarzaniu GPIO25 i GPIO26 powinny mieć HIGH względem GND,
także po STOP, watchdogu i logicznym POWER OFF, gdy ESP32 pozostaje zasilone.
HIGH wyłącza PNP; nie jest pomiarem zaniku napięcia ATX.
Oscyloskopem sprawdź osobno oba kanały: pulse 440 Hz i AMP 50 powinien dawać
LOW przez 50/256 okresu, HIGH przez resztę. Innych przebiegów nie obsługujemy. Boot/reset wymaga również sprawdzenia
stanów przejściowych i działania pull-upów; testy C++ nie mierzą GPIO.
Nie podłączaj wejścia pomiarowego do obciążenia bez sprawdzenia jego zakresu.
