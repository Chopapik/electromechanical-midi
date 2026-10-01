# electromechanical-midi

Odtwarzanie plików MIDI na **mechanicznej stacji dyskietek 3.5"** sterowanej
przez **Arduino Uno**.

```
plik .mid
   ↓
host/player.py        (Python: MIDI, timing, transpozycja)
   ↓
USB Serial 115200
   ↓
Arduino Uno           (prosty kontroler wykonawczy: STEP/DIR)
   ↓
stacja dyskietek 3.5" (jedna nuta naraz)
```

Nie trzeba już przepisywać nut do C++ ani rekompilować firmware dla każdego
utworu. Firmware wgrywa się raz, a utwory wybiera się z plików `.mid`.

**Arduino NIE udaje urządzenia USB MIDI i nie parsuje MIDI.** Dostaje po
Serialu gotową częstotliwość w Hz (`PLAY 196.00`) i ma ją zagrać natychmiast.

---

## 1. Jak to działa

Stacja dyskietek nie ma głośnika - dźwięk powstaje w wyniku **kroków głowicy**.
Jeden impuls `/STEP` to jeden "klik", a częstotliwość tych klików to wysokość
dźwięku. Dlatego:

* wysokość nuty = **tempo kroków** (okres w mikrosekundach),
* głowica cały czas jedzie, więc co jakiś czas **zawraca**
  (`MIN_TRACK` ↔ `MAX_TRACK`),
* **zawracanie nie zmienia wysokości dźwięku** - zmienia się tylko kierunek,
  tempo kroków zostaje takie samo.

Podział odpowiedzialności:

| Warstwa | Odpowiada za |
| --- | --- |
| `host/player.py` | wczytanie MIDI, tempo, monofonia, octave folding, **cały timing** |
| `firmware/floppy` | odbiór komend, homing, licznik pozycji, generowanie kroków, STOP |

Firmware **nie ma pojęcia o długości nuty** - to host wysyła `PLAY` i `STOP`
w odpowiednich momentach.

---

## 2. Struktura repozytorium

```
electromechanical-midi/
├── firmware/
│   └── floppy/                 # projekt PlatformIO (Arduino Uno)
│       ├── platformio.ini
│       └── src/main.cpp
├── host/
│   ├── player.py               # CLI + harmonogram + timing
│   ├── midi_source.py          # MIDI: tracki, mapa tempa, nuty, monofonia
│   ├── pitch.py                # MIDI → Hz, octave folding
│   ├── floppy_link.py          # Serial + wykrywanie Arduino
│   ├── requirements.txt
│   └── tests/                  # testy bez sprzętu (unittest)
├── midi/
│   ├── test.mid                # przykładowy utwór (melodia + akordy)
│   └── range-test.mid          # chromatyka C1-C7 (test składania oktawowego)
└── README.md
```

---

## 3. Pinout (aktualny, sprawdzony sprzętowo)

| FDD (3.5") | Arduino Uno |
| --- | --- |
| pin 18 `DIR` | **D2** |
| pin 20 `/STEP` | **D3** |
| pin 26 `/TRACK0` | **D4** |
| Drive Select | **D5** |
| GND | **GND** |

Ustalenia dla tej konkretnej stacji:

| Sygnał | Znaczenie |
| --- | --- |
| `DIR HIGH` | ruch w stronę TRACK0 |
| `DIR LOW` | ruch od TRACK0 |
| `/TRACK0` | aktywne **LOW** (`INPUT_PULLUP`) |
| `/STEP` | aktywne **LOW** (impuls ~30 µs) |
| Drive Select | aktywne **LOW** (stacja cały czas wybrana) |

Programowy licznik pozycji: `0 = TRACK0`, bezpieczny zakres
`MIN_TRACK = 4` … `MAX_TRACK = 72`.

---

## 4. Instalacja

### 4.1. Zależności Pythona (host)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r host/requirements.txt
```

Zależności: `mido` (parsowanie MIDI) i `pyserial` (Serial).

> Na macOS port Arduino nazywa się zwykle `/dev/cu.usbmodemXXXX`.
> Program wykrywa go sam - nigdzie nie ma zaszytego numeru portu.

### 4.2. Firmware (PlatformIO)

```bash
# instalacja PlatformIO (jeśli nie ma)
python3 -m pip install platformio

# kompilacja dla Arduino Uno
pio run -d firmware/floppy

# wgranie na płytkę
pio run -d firmware/floppy --target upload

# podgląd Serial (opcjonalnie)
pio device monitor -d firmware/floppy
```

W VS Code: **Open Folder → `firmware/floppy`** i użyj przycisków
PlatformIO (Build / Upload / Monitor).

Firmware zajmuje ok. **6.9 kB flash (21%)** i **299 B RAM (15%)** Arduino Uno,
więc zostaje dużo miejsca na rozbudowę.

`platformio.ini`:

```ini
[platformio]
default_envs = uno

[env:uno]
platform = atmelavr
board = uno
framework = arduino
monitor_speed = 115200
```

---

## 5. Uruchomienie

```bash
# 1. wypisz tracki w pliku
python host/player.py midi/test.mid --list-tracks

# 2. tryb interaktywny: wybór tracku z listy
python host/player.py midi/test.mid

# 3. od razu wybrany track
python host/player.py midi/test.mid --track 1

# 4. bez sprzętu - tylko sprawdź, co zostałoby wysłane
python host/player.py midi/test.mid --track 1 --dry-run
```

Przykładowy przebieg:

```
MIDI: test.mid

Tracks:
[0] Tempo - 0 nut  (brak nut)
[1] Melody - 30 nut - kanal 1
[2] Chords - 24 nut - kanal 1

Select track: 1

Serial:
Arduino (www.arduino.cc) @ /dev/cu.usbmodem14101

Transpose mode:
AUTO

Range:
130-330 Hz

Utwor: 16.87 s (1 zmian tempa z pliku MIDI)
Nut: 30 (zlozone oktawowo: 0, pominiete: 0)

Press ENTER to play
Press Ctrl+C to stop
```

Po otwarciu portu Arduino resetuje się, robi **homing** i wysyła `READY` -
host czeka na to, zanim zacznie grać.

### Opcje CLI

| Opcja | Znaczenie |
| --- | --- |
| `--track N` | który track odtworzyć (bez tego pyta interaktywnie) |
| `--list-tracks` | wypisz tracki i zakończ |
| `--list-ports` | wypisz porty szeregowe i zakończ |
| `--port PORT` | wskaż port ręcznie (domyślnie autodetekcja) |
| `--baud N` | prędkość Serial (domyślnie 115200) |
| `--min-hz`, `--max-hz` | zakres stacji (domyślnie 130-330) |
| `--transpose auto\|low\|high` | tryb składania oktawowego |
| `--strategy highest\|lowest\|last` | co zrobić z akordem |
| `--gate (0, 1]` | jaka część nuty ma zabrzmieć (staccato) |
| `--no-wait` | nie czekaj na czas - **tylko z `--dry-run`** |
| `--loop` | powtarzaj w nieskończoność |
| `--dry-run` | bez sprzętu (symulacja + wypis harmonogramu) |
| `--print-schedule` | wypisz harmonogram przed grą |
| `--no-busy-wait` | mniej dokładny zegar, ale bez zajmowania CPU |
| `-y`, `--yes` | nie czekaj na ENTER |
| `-v`, `--verbose` | pokaż każdą wysłaną komendę |

---

## 6. Protokół Serial

Tekstowy, 115200 8N1, linie zakończone `\n`.

| Komenda hosta | Odpowiedź Arduino |
| --- | --- |
| `PING` | `PONG` |
| `PLAY <hz>` | *(cisza - patrz niżej)* |
| `STOP` | *(cisza - patrz niżej)* |
| `HOME` | `OK`, a po dojechaniu `READY` |
| `STATUS` | `STATUS track=.. dir=.. homed=.. playing=.. track0=.. hz=..` |
| cokolwiek innego | `ERR UNKNOWN_CMD` |

Możliwe błędy: `ERR NOT_HOMED` (brak homingu), `ERR BUSY` (trwa homing/odjazd),
`ERR FREQ_RANGE` (częstotliwość poza `MIN_PLAY_HZ`..`MAX_PLAY_HZ`),
`ERR MISSING_FREQ`, `ERR BAD_FREQ`, `ERR HOME_FAILED`, `ERR POS_LOST`
(utrata pozycji - host robi ponowny homing), `ERR HOST_TIMEOUT` (watchdog:
host przestał się odzywać), `ERR LINE_TOO_LONG`, `ERR UNKNOWN_CMD`.

**Dlaczego `PLAY`/`STOP` nie odpowiadają `OK`?**
Host wysyła nuty asynchronicznie i nie czyta portu w trakcie gry. Gdyby Arduino
odpowiadało na każdą nutę, bufor TX (64 B) zapełniłby się, `Serial.println()`
zablokowałoby pętlę i timing kroków by się rozjechał. Odpowiedzi `OK` dla
`PLAY`/`STOP` można włączyć stałą `ACK_PLAY_STOP = true` w `main.cpp`, jeśli
host faktycznie czyta port.

Firmware sprawdza `ERR` tylko wtedy, gdy host sam zechce - odczyt jest
nieblokujący.

### Diagnostyka `STATUS`

```
STATUS track=10 dir=away homed=1 playing=1 track0=0 hz=196.00
```

| Pole | Znaczenie |
| --- | --- |
| `track` | programowy licznik ścieżek (0 = TRACK0) |
| `dir` | `away` = od TRACK0, `toward` = w stronę TRACK0 |
| `homed` | 1 = pozycja pewna (po udanym homingu) |
| `playing` | 1 = generuje kroki |
| `track0` | **surowy stan czujnika** `/TRACK0` (1 = głowica na TRACK0) |
| `hz` | aktualnie grana częstotliwość |

`track0` to najszybszy sposób sprawdzenia sprzętu: jeśli po `HOME` pole
`track0` nigdy nie zmienia się na 1, to napęd nie dojeżdża do TRACK0
(brak zasilania, odłączona taśma, uszkodzony czujnik) - nie problem firmware.

---

## 7. Automatyczne składanie oktawowe (octave folding)

Każda nuta jest sprowadzana do zakresu stacji **wyłącznie przesunięciem
o całe oktawy** - klasa wysokości dźwięku (C, C#, D…) nigdy się nie zmienia.

```
523.25 Hz (C5)  →  261.63 Hz (C4)     -1 oktawa
 65.41 Hz (C2)  →  130.81 Hz (C3)     +1 oktawa
440.00 Hz (A4)  →  220.00 Hz (A3)     -1 oktawa
```

### Tryby

| Tryb | Zasada | Efekt |
| --- | --- | --- |
| `auto` *(domyślny)* | nuta zostaje, jeśli mieści się w zakresie; inaczej najbliższa oktawa | zgodny z przykładem `523 → 261.5`; **melodia przechodząca przez granicę 330 Hz może mieć skok o oktawę** |
| `low` | zawsze najniższa oktawa z zakresu (**130-260 Hz**) | melodia bez skoków, wszystko niżej |
| `high` | zawsze najwyższa oktawa z zakresu (**165-330 Hz**) | melodia bez skoków, wszystko wyżej |

Dlaczego to ma znaczenie: przy zakresie szerszym niż oktawa (330/130 = 2.54)
granica "zostaje / spada o oktawę" wypada na 330 Hz. W trybie `auto`
`E4 = 329.6 Hz` zostaje, a `F4 = 349.2 Hz` spada do `174.6 Hz` - słychać skok.

Tryby `low` i `high` wybierają dla każdej nuty tę samą, **dokładnie
jednooktawową** część zakresu. W takim oknie każda klasa wysokości ma
dokładnie jedną reprezentację, więc odległości między nutami są zachowane
i melodia nie ma skoków - jest tylko przesunięta w dół albo w górę.

```bash
# melodia: najlepiej bez skoków
python host/player.py midi/test.mid --track 1 --transpose low

# sprawdzenie całego zakresu MIDI (C1-C7)
python host/player.py midi/range-test.mid --track 0 --transpose low
```

### Gdy nuta nie mieści się w zakresie

Przy 130-330 Hz (ponad oktawa) **każda** nuta MIDI ma swoją oktawę w zakresie,
więc `in_range` jest zawsze prawdziwe. Gdyby jednak zakres był węższy niż
oktawa (np. `--min-hz 100 --max-hz 130`), dla części nut nie istnieje dobra
oktawa. Wtedy program:

* wybiera oktawę **najbliższą zakresowi**,
* wypisuje ostrzeżenie `UWAGA: N nut nie mieści się w zakresie`,
* liczy je w podsumowaniu (`wyslane 130.8-246.9 Hz`).

---

## 8. Monofonia (jedna stacja = jedna nuta)

Po wczytaniu tracku wszystkie nuty są redukowane do ciągu nut rozłącznych
w czasie. Strategię wybiera `--strategy`:

| Strategia | Zasada |
| --- | --- |
| `highest` *(domyślna)* | gra najwyższą nutę akordu (zwykle linia melodyczna) |
| `lowest` | gra najniższą nutę (linia basu) |
| `last` | gra nutę z ostatniego `NOTE_ON` |

Dodatkowo:

* **nuty tej samej wysokości, które na siebie nachodzą** (np. piano + smyczki)
  są scalane w jeden ciągły dźwięk,
* **przytrzymany dźwięk nie jest cięty** przez inne nuty grające pod nim -
  dopóki wybrana wysokość się nie zmienia, trwa jeden odcinek. Bez tego
  każda nuta towarzysząca zamykałaby odcinek i wstawiała 12 ms przerwę
  w środku trzymanej nuty,
* **nuty tylko stykające się** (koniec = początek) zostają osobne, żeby
  powtórka tej samej nuty była słyszalna. Przy powtórce host wysyła `STOP`
  **12 ms przed** początkiem kolejnej nuty (`ARTICULATION_S`) i `PLAY` w jej
  początku. Samo `STOP`+`PLAY` w tej samej chwili nic nie daje - obie komendy
  docierają do Arduino razem, głowica nie zdąży się zatrzymać i słychać jedną
  ciągłą nutę. Powtórka jest więc krótsza o 12 ms (2% typowej ćwierćnuty),
* nuty krótsze niż 10 ms są pomijane (mechanika i tak ich nie zagra) - licznik
  `pominiete` w podsumowaniu.

Nową strategię dodaje się w jednym miejscu - `STRATEGIES` w
`host/midi_source.py` (funkcja `active -> index`).

---

## 9. Timing

Cały timing liczy host, a Arduino tylko wykonuje. Host:

* korzysta z **zegara monotonicznego** (`time.monotonic()`),
* wylicza czas każdej komendy **względem absolutnego startu odtwarzania**,
* śpi do konkretnej chwili (`sleep` + krótkie aktywne doczekanie ostatnich
  1.5 ms), a nie "przez czas trwania nuty".

Dzięki temu opóźnienia Serial **nie kumulują się** - każde opóźnienie
przesuwa tylko jedną komendę, a nie cały utwór. Zmierzony dryf:

| Test | Zaplanowane | Rzeczywiste | Dryf |
| --- | --- | --- | --- |
| `range-test.mid` (73 nuty) | 9.125 s | 9.125 s | **0 ms** |
| to samo, `--no-busy-wait` | 9.125 s | 9.130 s | +5 ms (stały, nie narasta) |
| `test.mid` track 1, na sprzęcie | 16.873 s | 16.877 s | +4 ms całości |

To dryf **harmonogramu hosta**, mierzony na jego zegarze. Dochodzi do tego
stałe opóźnienie transmisji USB (~1-3 ms), którego ten pomiar nie obejmuje -
ono przesuwa cały utwór, ale się nie kumuluje.

Tempo jest brane z pliku MIDI (`set_tempo` z **wszystkich** tracków, także
zmiany tempa w trakcie utworu). Nie ma założonego stałego BPM.

Arduino pilnuje kroków własnym harmonogramem (`micros()`, `nextStepUs += okres`),
więc drobne opóźnienia Serial nie zmieniają wysokości granych nut. Zmiana
wysokości w trakcie grania (legato) też nie czeka pełnego starego okresu -
nowy okres jest od razu uwzględniany.

---

## 10. Bezpieczeństwo mechaniki

* Firmware prowadzi programowy licznik ścieżek i **zawraca przed końcami**
  (`MIN_TRACK = 4`, `MAX_TRACK = 72`). Dopóki licznik zgadza się
  z rzeczywistością, głowica nie wjedzie w prowadnicę. Ponieważ jedynym
  czujnikiem jest TRACK0, utrata kroków **w stronę MAX_TRACK jest
  niewykrywalna** - licznik byłby wtedy zaniżony. Dlatego przy graniu warto
  obserwować, czy dźwięk nie zaczyna „gubić" kroków.
* `MIN_PLAY_HZ = 40`, `MAX_PLAY_HZ = 500` oraz twardy limit
  `MIN_STEP_INTERVAL_US = 1000` (max 1000 kroków/s) w firmware to bezpieczniki
  na wypadek błędnej komendy albo lawiny komend.
* **Watchdog**: jeśli host przestanie się odzywać na dłużej niż
  `HOST_TIMEOUT_MS = 3000` (awaria, wyjęty kabel USB), firmware sam zatrzymuje
  kroki i zgłasza `ERR HOST_TIMEOUT`. Host podtrzymuje łącze wysyłając `PING`
  co 1 s przy długich nutach i przerwach, więc normalne długie nuty nie
  są przerywane.
* **Detekcja utraty pozycji**: jeśli w trakcie grania czujnik `/TRACK0` jest
  aktywny, a programowy licznik twierdzi, że jesteśmy znacznie dalej niż
  `MIN_TRACK`, to znaczy że głowica zgubiła kroki. Wymagane są 3 aktywne
  odczyty z rzędu (filtr na glitch), po czym firmware zatrzymuje granie
  i wysyła `ERR POS_LOST`; host przerywa utwór i **sam robi ponowny homing**.
  Margines (`POSITION_LOSS_MARGIN = 6`) chroni przed fałszywym alarmem, gdy
  czujnik ma szerszą strefę niż jedna ścieżka. Jeśli Twoja stacja ma wyraźnie
  szeroką strefę TRACK0, zwiększ tę stałą albo wyłącz wykrywanie
  (`DETECT_POSITION_LOSS = false`).
* `HOME` można wysłać w każdej chwili - także w trakcie grania.

Mechanicznie najlepiej brzmi **130-330 Hz** (stąd `COMFORT_MIN_HZ` /
`COMFORT_MAX_HZ`). Okolice 440 Hz są jeszcze możliwe, wyżej głowica gubi kroki.

---

## 11. Aktualne ograniczenia

* **Jedna stacja = jedna nuta naraz.** Akordy są redukowane do pojedynczej
  linii (patrz sekcja 8).
* Jedna stacja obsługiwana jednocześnie (`FloppyDrive drive` w firmware).
* Zakres 130-330 Hz; poza nim trzeba zmienić `--min-hz` / `--max-hz`
  (świadomie) albo liczyć się z gubieniem kroków.
* Głowica cały czas jeździ - długie nuty to kilka przejazdów po ścieżkach,
  co słychać jako zmianę barwy.
* Brak GUI - jest CLI.
* Firmware nie wie nic o nutach MIDI: wysokość musi przyjść jako Hz.

Świadomie **nie** zaimplementowano: ESP32, Wi-Fi, MQTT, VFD, HDD, DVD, VHS,
wielu instrumentów naraz.

---

## 12. Rozszerzanie na wiele instrumentów

Kod jest tak ułożony, żeby nie trzeba było przepisywać logiki:

* **Firmware**: cała obsługa jednej stacji siedzi w klasie `FloppyDrive`
  (homing, licznik pozycji, generowanie kroków). Wystarczy `FloppyDrive
  drives[N]` z różnymi pinami i wybór stacji w `handleCommand()`.
* **Host**: `FloppyLink` wysyła komendy jako tekst, a harmonogram to lista
  `Command` z osią czasu - dodanie drugiego instrumentu to druga instancja
  linku i rozdzielenie komend po urządzeniu.

---

## 13. Testy

Testy hosta nie wymagają sprzętu ani Arduino:

```bash
python -m unittest discover -s host/tests -t host/tests -v
```

Sprawdzają: konwersje MIDI↔Hz, składanie oktawowe (wszystkie 128 nut,
tryby `auto`/`low`/`high`), mapę tempa ze zmianami BPM, redukcję do monofonii,
scalanie unisono i budowanie harmonogramu `PLAY`/`STOP`.

Kontrola składni:

```bash
python -m compileall -q host
```

Firmware kompiluje się dla `uno`:

```bash
pio run -d firmware/floppy
```

---

## 14. Rozwiązywanie problemów

| Objaw | Przyczyna / rozwiązanie |
| --- | --- |
| `nie widze zadnego portu szeregowego` | sprawdź kabel USB i czy Serial Monitor / `pio device monitor` nie zajmuje portu |
| `nie moge otworzyc /dev/...` | port zajęty - zamknij Arduino IDE / PlatformIO Monitor |
| brak `READY` po otwarciu portu | stacja bez zasilania, źle podłączony `/TRACK0` lub `ERR HOME_FAILED` |
| `ERR HOME_FAILED` | napęd nie odpowiada: brak zasilania stacji, odłączona taśma albo czujnik `/TRACK0`. Sprawdź `STATUS` - pole `track0` powinno zmienić się na 1, gdy głowica dojedzie do TRACK0 |
| po `Ctrl+C` głowica stoi | to normalne - `STOP` zatrzymuje kroki, głowica zostaje na miejscu |
| gubi kroki / brzydki dźwięk | zjedź niżej: `--max-hz 300` albo `--transpose low` |
| dźwięk przerywany w szybkich nutach | `--no-busy-wait` zamień na domyślne (busy-wait) na maszynie obciążonej innymi procesami |
