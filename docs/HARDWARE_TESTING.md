# Uruchamianie sprzętu, diagnostyka i awarie

Najpierw [połączenia](HARDWARE_WIRING.md), następnie
[limity i status pomiarów](HARDWARE_DEVICES.md). Poniższa procedura nie została
w całości powtórzona na fizycznym zestawie podczas porządkowania dokumentacji.
Testy programowe nie mierzą temperatury, prądu, dźwięku ani pozycji.

## Kontrola bez zasilania urządzeń

1. Odłącz VM mostków, zasilanie FDD i V_SPK. Zidentyfikuj modele modułów,
   piny zasilania, orientację 74HC595 i faktyczne B/C/E obu S8050.
2. Sprawdź ciągłość wspólnej masy, brak zwarć między dodatnimi szynami i masą,
   połączenia szyn płytek stykowych, każdy /OE i /SRCLR oraz łańcuch QH′→SER.
3. Prześledź wszystkie Q0–Q39 według tabeli w schemacie; wolne wyjścia zostaw
   niepodłączone. Sprawdź, że GPIO27 nie trafiło na mostek HDD2 (Q27).
4. Zmierz rezystancje par cewek DVD i HDD. Ustal wartości rezystorów bazowych
   oraz napięcie i prąd speakerów. Nie uruchamiaj nieustalonego obwodu mocy.
5. Zweryfikuj poziomy STEP/DIR i TRACK0 dla konkretnych FDD. Nie podawaj
   podciągania 5 V na GPIO ESP32. Przy odłączonej logice zidentyfikuj /DS.
6. Zapewnij możliwość natychmiastowego odłączenia zasilania urządzeń oraz
   pomiar prądu i temperatury silników/mostków podczas prób.

## Firmware i sama logika

Zbuduj właściwy target (domyślny target PlatformIO jest inny):

```sh
pio run -d firmware/controller -e esp32
.venv/bin/python scripts/generate_hardware_profiles.py --check
```

Flashowanie przez USB/CP2102: `/settings` → **Serwis → Wgraj firmware ESP32**,
albo `pio run -d firmware/controller -e esp32 -t upload --upload-port PORT`.
`PORT` zastąp wykrytym portem konkretnej płytki. Sam CP2102 nie dowodzi
poprawności połączeń. Nie flashuj podczas ruchu; DeviceService potwierdza STOP
i przejmuje wyłączne sterowanie. Monitor USB: 115200, 8N1; wyłącz DTR/RTS,
jeśli program monitora resetuje płytkę przy otwarciu.

Uruchom samą logikę. Sprawdź /OE HIGH podczas resetu, potem stan boot
`55 00 00 00 00` rejestrów #1→#5: STEP HIGH, wejścia mostków i nSLEEP LOW.
USB zgłasza `READY protocol=2 board=esp32`; nie oznacza to wykonania HOME.

Do sprawdzenia pojedynczych wyjść służy `DIAG BIT n` (n=0…39).
**Wszystkie urządzenia wykonawcze muszą być odłączone**, także FDD i wejścia
sterowników mogące je uruchomić. Komenda nadpisuje ramkę, w tym STEP i nSLEEP;
mierz wyłącznie logikę. Po diagnostyce zresetuj ESP32 przy nadal odłączonej mocy
i ponownie sprawdź maskę boot. `ALL STOP` wyłącza obsługiwane urządzenia,
ale nie czyści każdego wolnego bitu ustawionego przez DIAG.

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
ALL STOP test1
```

Oczekuj PONG, zapalenia/zgaszenia opcjonalnej LED GPIO27, transakcji STATUS
oraz `STOPPED test1`. STATUS zawiera BEGIN, CTRL, 4 FDD, 4 HDD, 4 SLED,
VHS, VHS2, END (17 rekordów). Powiadomienia są fragmentowane do 20 bajtów:
składaj je do LF, również przy MTU 23. Boot READY jest wysyłane przez USB;
połączenie BLE sprawdza się PING/STATUS. Rekord urządzenia nie dowodzi,
że silnik jest fizycznie podłączony.

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
| DVD | Pary cewek, VM, nSLEEP, swobodny obrót | Kierunek, rampa, zmiana celu bez STOP, prąd i wzrost temperatury |
| HDD | Rezystancja/połączenia cewki, VM, miejsce ruchu ramienia | Pojedynczy HIT, park/settle/strike, brak zakleszczenia i nadmiernego nagrzewania |
| Speaker / FX | Ustalony V_SPK, R_B i pinout S8050 | Każdy kanał osobno, brak sprzęgania częstotliwości, prąd, temperatura i nośna PWM |

Aplikacja konfiguruje profile i ENABLE przed grą. Samo połączenie nie wykonuje
HOME; użyj `/settings` → **Serwis → Homing**. `homed=1` i aktywne TRACK0
to różne stany. `HOME_FAILED` wymaga sprawdzenia czujnika, /DS, DIR i przewodów;
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
ALL STOP test2
```

Każdy kanał ma `ENABLE 0|1`, np. `SLED 1 ENABLE 1`.
Po PLAY zaplanuj STOP; watchdog nie zastępuje skończonej próby przy aktywnych PING.
Nie przesyłaj ręcznie profilu z pominięciem nierozpoznanych parametrów sprzętu.

## Laboratory

`/settings` → **Laboratory → Laboratory · debug** otwiera testy bez MIDI.
Wybierz urządzenie, Hz i czas (0,1–10 s, domyślnie 1 s), potem **Uruchom test**.
HDD wykonuje pojedynczy HIT zamiast tonu. Lab używa tego samego Playera,
Routera i wyjścia; REAL wymaga BLE, profilu i HOME dla FDD. Odrzucone Hz nie
są składane oktawowo. Kończący się test wysyła STOP; **Stop** przerywa wcześniej.
**Wróć do Orkiestry** zamyka sesję bez autoplay.

Aktualny WebSocket ma wyłączną sesję lab; sync odnawia lease 3 s.
Wygaśnięcie lease, utrata sesji lub zmiana właściciela kończy wykonanie.
Nie ma dawnego panelu ocen rezonansu i eksportu historii ocen.
Zapis historycznej próby kontrolera: [pomiary i obserwacje](research/hardware-measurements.md#laboratory).

## Awarie

**Naciśnij STOP.** REAL używa `ALL STOP <token>` i wymaga pasującego
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
| Nieznana fala / drugi speaker | `speaker_waves` / `speaker_fx` w STATUS, aktualność firmware |
| VIRTUAL milczy | Wybrane Output, gest uruchamiający Web Audio, gain/duty 0, Mute, aktywna karta i synchronizacja |

Telemetria `/api/monitor/raw` pokazuje ruch komend; nie jest analizatorem STEP
ani pomiarem prądu. Zapisuj wersję kodu, profil, kanał, zasilanie, czas, temperaturę,
prąd i metodę pomiaru przy każdej nowej kwalifikacji sprzętu.
