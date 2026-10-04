# electromechanical-midi

Odtwarzanie plików MIDI na **mechanicznej stacji dyskietek 3.5"** sterowanej
przez **Arduino Uno**. Dwa interfejsy, jeden silnik odtwarzania:

* **web player** - lokalny odtwarzacz w przeglądarce (play/pause/seek/progress bar),
* **CLI** - `python host/player.py song.mid`.

```
plik .mid
   ↓
Python: MIDI → monofonia → octave folding → timeline (PLAY/STOP)
   ↓
silnik odtwarzania (absolutny timing, seek, pauza, keepalive)
   ↓
USB Serial 115200
   ↓
Arduino Uno           (prosty kontroler wykonawczy: STEP/DIR)
   ↓
stacja dyskietek 3.5" (jedna nuta naraz)

przeglądarka  ↕  HTTP + WebSocket  ↕  backend FastAPI
```

Nie trzeba już przepisywać nut do C++ ani rekompilować firmware dla każdego
utworu. Firmware wgrywa się raz, a utwory wybiera się z plików `.mid`.

**Arduino NIE udaje urządzenia USB MIDI i nie parsuje MIDI.** Dostaje po
Serialu gotową częstotliwość w Hz (`PLAY 196.00`) i ma ją zagrać natychmiast.
Nie zna długości utworu ani pozycji - **seek, pauza i progress bar istnieją
wyłącznie po stronie hosta**.

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
| `host/midi_source.py` | wczytanie MIDI, mapa tempa, nuty, monofonia |
| `host/pitch.py` | MIDI → Hz, octave folding |
| `host/playback/` | timeline (linie FDD + drum) i **silnik**: absolutny timing, play/pause/seek |
| `host/web/` | backend web playera (FastAPI: REST + WebSocket) |
| `host/player.py` | CLI (używa tego samego silnika) |
| `web/` | frontend (React + Vite + TypeScript) |
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
│   ├── player.py               # CLI (cienka warstwa nad silnikiem)
│   ├── midi_source.py          # MIDI: tracki, mapa tempa, nuty, monofonia
│   ├── pitch.py                # MIDI → Hz, octave folding
│   ├── floppy_link.py          # Serial + wykrywanie Arduino
│   ├── playback/
│   │   ├── timeline.py         # nuty -> komendy PLAY/STOP + obsługa pozycji
│   │   └── engine.py           # silnik: play/pause/resume/stop/seek, keepalive
│   ├── web/
│   │   └── server.py           # FastAPI: REST + WebSocket + serwowanie frontendu
│   ├── requirements.txt
│   └── tests/                  # testy bez sprzętu (unittest)
├── web/                        # frontend (React + Vite + TS)
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── App.tsx
│       ├── usePlayer.ts        # WebSocket + stan playera
│       ├── useThrottled.ts     # dławienie suwaków sprzętowych
│       └── components/         # ProgressBar, DrumPanel, PlayerControls...
├── midi/                       # pliki .mid dla playera (tu wrzucasz swoje)
├── scripts/
│   └── dev.sh                  # backend + frontend jednym poleceniem
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
| (VHS drum ICTL przez 100 kΩ) | **D6** |
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

### 4.1. Zależności Pythona (host + backend web)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r host/requirements.txt
```

Zależności: `mido` (parsowanie MIDI), `pyserial` (Serial), `fastapi` +
`uvicorn` (web player), `numpy` (wektorowy render podglądu Virtual Orchestra).

> `numpy` jest opcjonalny w kodzie (jest fallback czysto-pythonowy), ale bez
> niego `WavePreview.render` liczy próbka po próbce i pierwszy `Play` w trybie
> wirtualnym potrafi zamrozić UI na kilkanaście/kilkadziesiąt sekund:
> przykładowa aranżacja 6 urządzeń ≈ 5.9 s vs 0.2 s, duża aranżacja 40 urządzeń
> ≈ 24 s vs 0.9 s.

> Na macOS port Arduino nazywa się zwykle `/dev/cu.usbmodemXXXX`.
> Program wykrywa go sam - nigdzie nie ma zaszytego numeru portu.

### 4.2. Frontend (Node 18+)

```bash
cd web
npm install
```

`npm install` jest potrzebny raz. Dalej wystarczy `./scripts/dev.sh` albo
zbudowany frontend (`npm run build`) serwowany przez backend.

### 4.3. Firmware (PlatformIO)

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

## 5. Web player (przeglądarka)

### 5.1. Tryb dev - jedno polecenie

```bash
./scripts/dev.sh
```

Skrypt uruchamia:

* backend FastAPI na `http://127.0.0.1:8000` (`python -m host.web.server`),
* frontend Vite na `http://127.0.0.1:5173` (proxy `/api` i `/ws` → backend).

Otwórz **http://127.0.0.1:5173**. `Ctrl+C` kończy oba procesy.

Przydatne warianty:

```bash
./scripts/dev.sh --no-hardware     # bez Arduino: PLAY zgłosi brak połączenia
./scripts/dev.sh --fake-hardware   # atrapa Serial: UI gra "na sucho" (demo, testy)
./scripts/dev.sh --port 9000       # inny port backendu
```

### 5.2. Tryb produkcyjny (jeden proces, bez Node)

```bash
cd web && npm run build && cd ..     # raz (albo po każdej zmianie frontendu)
python -m host.web.server            # http://127.0.0.1:8000
```

Backend sam serwuje `web/dist`, więc wystarczy jeden proces i jedna strona.
Jeśli `web/dist` nie istnieje, backend pokaże instrukcję, a API i tak działa.

Opcje backendu:

| Opcja | Znaczenie |
| --- | --- |
| `--host`, `--port` | adres nasłuchu (domyślnie `127.0.0.1:8000`) |
| `--midi-dir` | katalog z plikami `.mid` (domyślnie `midi/`) |
| `--serial-port` | wskaż port Arduino ręcznie (domyślnie autodetekcja) |
| `--no-hardware` | nie łączy się z Arduino |
| `--fake-hardware` | bez Serial, ale silnik gra na atrapie (demo UI) |
| `--min-hz`, `--max-hz` | zakres stacji (domyślnie 130–330 Hz) |
| `--transpose` | tryb składania oktawowego na start (`auto`/`low`/`high`) |
| `--strategy` | strategia akordów (`highest`/`lowest`/`last`) |

### 5.3. Co potrafi UI

```
┌──────────────────────────────────────────────┐
│ Electromechanical MIDI                       │
│ Sail to the Moon                             │
│ Thom Vox                                      │
│                 E3                            │
│              164.81 Hz                        │
│        ⏮      ▶ / ❚❚      ■                   │
│  1:17 ━━━━━━━━●━━━━━━━━━━━━━━━ 4:03          │
│ MIDI     [ Sail to the Moon.mid        ▾ ]   │
│ Track    [ Thom Vox                    ▾ ]   │
│ Transpose[ LOW 130–260 Hz              ▾ ]   │
│ ● Arduino connected                          │
│   /dev/cu.usbmodem14101            Reconnect │
└──────────────────────────────────────────────┘
```

* **Wybór pliku** - lista `.mid` / `.midi` z katalogu `midi/`.
* **Wgrywanie MIDI** - przycisk **＋ Wgraj plik MIDI** albo **przeciągnięcie
  pliku** na pole wyboru. Plik leci `POST /api/files` do katalogu `midi/`
  i od razu staje się aktywnym utworem (bez restartu backendu).
* **Wybór tracku** - z nazwą, liczbą nut i informacją „monofonia / polifonia /
  perkusja”.
* **PLAY / PAUZA / STOP** oraz ⏮ (od początku).
* **Aktualna nuta** (`E3`) i **częstotliwość** (`164.81 Hz`), a w ciszy `REST`.
  Jeśli nuta została złożona oktawowo, UI pokazuje też nutę źródłową.
* **Progress bar** z czasem `1:17 / 4:03`.
* **Transpose** - `AUTO` / `LOW 130–260 Hz` / `HIGH 165–330 Hz`
  (patrz sekcja 9).
* **Status sprzętu** - zielona/czerwona kropka, port, komunikat błędu i
  przycisk **Reconnect** (plus wybór portu, gdy jest ich kilka).
* **VHS Drum** - osobna sekcja z ręcznym sterowaniem bębnem: `Start` / `Stop`,
  status (`Running` / `Stopped` / `Disconnected`), suwak **PWM** (0-255,
  głośność) i suwak **Ton** (20-2000 Hz, wysokość dźwięku). Szczegóły i
  wyniki pomiarów: sekcja 5.6.

### 5.4. Progress bar i seek

* Backend publikuje autorytatywny stan **co ~150 ms**.
* Frontend **interpoluje pozycję lokalnie** (`requestAnimationFrame`), więc
  pasek płynie płynnie, a WebSocket nie jest spamowany 60 razy na sekundę.
* **Przeciąganie** pokazuje tylko lokalny podgląd pozycji - **żadne komendy
  nie lecą do Arduino**.
* Dopiero **puszczenie** (albo klawisz) wysyła **jeden** `seek`.
* Kliknięcie w pasku = jedno `seek`.
* Klawiatura: `←` / `→` = ±5 s, `Shift`+strzałka = ±30 s, `Home` / `End`.

Seek po stronie hosta oznacza: `STOP` → ustaw playhead → **wznów nutę, która
w tym miejscu trwa** → graj dalej. Dla Arduino to najwyżej `STOP` i
`PLAY <hz>` - nie ma żadnego „SEEK” w protokole.

Przykład: nuta `102.00–103.09 s`. Seek na `102.55 s` natychmiast gra jej
środkiem i kończy ją o `103.09 s` (zweryfikowane na sprzęcie).

### 5.5. Zachowanie przy zmianach w trakcie grania

| Akcja | Zachowanie |
| --- | --- |
| **Play** | od `0` (po STOP) albo od bieżącej pozycji (po pauzie lub seeku) |
| **Pause** | `STOP` do Arduino, playhead zamrożony, stan `paused` |
| **Resume** | wznawia nutę, która w tym miejscu trwa, nowy origin czasu |
| **Stop** | `STOP`, playhead = 0, stan `stopped` |
| **Seek** | `STOP` + natychmiastowe wznowienie nuty w nowym miejscu |
| **Zmiana tracku / transpose / strategii** | timeline liczony od nowa, **pozycja i stan zachowane** - gra dalej od tego samego miejsca |
| **Zmiana pliku** | `STOP`, pozycja 0, stan `stopped` (przewidywalne) |
| **Koniec utworu** | stan `stopped`, playhead na końcu; Play startuje od 0 |

Zmiana tracku zachowuje pozycję (zamiast pauzować) - dzięki temu przełączanie
„Thom Vox ↔ Thom Piano” w trakcie odtwarzania działa jak zmiana instrumentu.

### 5.6. VHS Drum (ręczne sterowanie dodatkowym silnikiem)

Do web playera dołożony jest **jeden sprawny silnik bębna VHS** (PCB VTDMT04D,
driver KA8328D). To na razie **nie jest połączone z MIDI** — to osobny,
ręcznie sterowany instrument.

```
Arduino D6 ──[100 kΩ]── CN5 (ICTL)        CN3 = GND (wspólna masa)
                                          CN6 = +12 V (przez bezpiecznik ~1 A)
```

Sterowanie idzie po istniejącym Serialu, więc Arduino nadal jest tylko
kontrolerem wykonawczym:

| Komenda | Znaczenie | Zakres |
| --- | --- | --- |
| `DRUM <0-255>` | amplituda (wypełnienie PWM) — **głośność**; `0` = stop | 0–255 |
| `DRUMF <hz>` | częstotliwość kluczowania — **wysokość dźwięku**; `0` = tryb DC (zwykły PWM ~976 Hz) | 20–2000 Hz |

Co ustaliliśmy **empirycznie na tym egzemplarzu**:

* silnik rusza od około **24/255** (~9% wypełnienia),
* **wypełnienie zmienia głośność, a nie wysokość** (napęd ma regulowane obroty),
* **wysokość dźwięku steruje `DRUMF`** — sprawdzone od 100 Hz do 1600 Hz:
  każdy krok brzmiał wyżej, a silnik kręcił się przy każdej częstotliwości,
* bęben i stacja dyskietek **grają równocześnie** (kluczowanie bębna idzie
  z wolnego Timer1, więc nie rusza `millis()`/`micros()` ani kroków FDD).

Jak to jest zrobione w firmware: w trybie tonu D6 nie jest już napędzany przez
Timer0 (`analogWrite`), tylko przez przerwanie **Timer1** (CTC, prescaler 8),
które samo przełącza pin. `millis()`, `micros()` i scheduler kroków korzystają
z Timer0 i **nie są przy tym dotykane** — przed wejściem w tryb tonu firmware
czyści tylko bit `COM0A1`, żeby odczepić OC0A od pinu.

#### Drugi głos z MIDI (FDD + VHS Drum)

Bęben może grać **drugi track z tego samego pliku MIDI**, równocześnie z FDD.
To nie są dwa odtwarzacze: obie linie są zmergowane w **jeden timeline**
i grane przez **jeden scheduler z jednym zegarem** (monotonic origin).

```
                ┌──→ FDD   (PLAY/STOP)
MIDI → timeline ┤
   (jeden czas) └──→ DRUM  (DRUM 74 + DRUMF <hz> / DRUM 0)
```

| Ustawienie | Znaczenie |
| --- | --- |
| `VHS Drum Track` | który track gra bęben; **`None`** = bęben tylko ręczny |
| `VHS Drum transpose` | `low` (110–220 Hz), `high` (440–880 Hz) albo `auto` (110–880 Hz) |
| napęd | stały `DRUM 38` (**15%** wypełnienia — mniej szumu mechanicznego) |

**Sprawdzona recepta („melodia + bas”)** — na *Sail to the Moon* to zabrzmiało
rozpoznawalnie:

| Ustawienie | Wartość | Dlaczego |
| --- | --- | --- |
| FDD Track | `Thom Vox` (partia wokalna) | melodia jest najbardziej rozpoznawalna |
| FDD transpose | `auto` | wokal zostaje w swoim rejestrze |
| VHS Drum Track | `Thom Piano` | partia harmoniczna |
| VHS Drum drive | `38` (15%) | stała `DRUM_DRIVE_DEFAULT` w `timeline.py` |
| VHS Drum strategy | `lowest` | daje **linię basową** pod melodią |
| VHS Drum transpose | `low` (110–220 Hz) | jedno okno oktawowe = **zero skoków** |
| start | ~158 s | najdłuższa nuta wokalna (3,3 s) |

Dwie melodie w różnych rejestrach (np. bęben w `high`) brzmią jak dwa
konkurujące głosy — dopiero **melodia + bas** zaczyna brzmieć jak utwór.
Dlatego domyślny tryb bębna to `low`: okno dokładnie jednej oktawy
matematycznie gwarantuje brak skoków oktawowych.

Zasady działania:

* nuta → `DRUMF <hz>` + `DRUM 38` (15%); **`DRUM` wysyłamy tylko raz**, bo przy
  legato zmienia się wyłącznie wysokość (mniej ruchu po Serialu i brak
  restartu timera tonu),
* przerwa → `DRUM 0`,
* nuty stykające się nie dostają `DRUM 0` — dźwięk przechodzi płynnie,
* osobny mapper wysokości: zakres **110–880 Hz** i składanie oktawowe,
  niezależne od zakresu FDD (130–330 Hz),
* monofonizacja: ta sama strategia co dla FDD (`highest`/`lowest`/`last`),
* **seek** wznawia stan **obu** linii (jeśli w danej chwili trwa nuta bębna,
  od razu leci `DRUMF` + `DRUM 74`),
* PLAY/PAUSE/STOP/disconnect/reconnect zawsze robią `STOP` + `DRUM 0`,
* podczas gdy bęben gra z MIDI, **panel ręczny jest zablokowany**
  (`MIDI CONTROLLED`); wraca po pauzie/stopie.

#### Homing: czujnik TRACK0 i awaryjny homing „na ślepo"

Poprawny homing opiera się na czujniku TRACK0. Jeśli czujnik (albo taśma)
przestanie odpowiadać, firmware melduje `ERR HOME_FAILED` i **nic nie da się
grać** — `PLAY` wymaga znanej pozycji głowicy. Dlatego host schodzi po
drabince:

1. `HOME` — normalny homing z czujnikiem (90 kroków),
2. `HOME` × 2 — kolejne pełne budżety kroków w stronę TRACK0,
3. `HOME BLIND` — **homing bez czujnika**: głowica jedzie pełną szerokość
   stacji (95 kroków) do oporu, potem odjeżdża `START_TRACK`. Pozycja jest
   znana „z założenia", więc granie wraca.

Gdy zadziała wariant 3, UI pokazuje żółte ostrzeżenie:

> ⚠ homing NA ŚLEPO: czujnik TRACK0 stacji nie odpowiada (sprawdź taśmę /
> czujnik) — pozycja liczona z dojazdu do oporu

To jest obejście, nie naprawa: przy padniętym czujniku stacja traci
kontrolę pozycji (kontrola `POS_LOST` też nie działa) i dalej gra, ale
warto wymienić taśmę/czujnik.

#### Trzecia linia: HDD perkusja (VCM)

HDD jest instrumentem **uderzeniowym bez wysokości dźwięku**: każda nuta
wybranego tracku = jedno uderzenie. Nadaje się więc do tracku perkusyjnego
(np. `Drums`, kanał 9/10).

```
FDD   (PLAY/STOP)          <- melodia
VHS   (DRUM/DRUMF)         <- bas / druga linia
HDD   (HIT)                <- perkusja
        ^ wszystko z JEDNEGO timeline'u i jednego zegara
```

**Mechanika (ustalona empirycznie w testach strojenia):**

| parametr | wartość | znaczenie |
| --- | --- | --- |
| `PARK` | 40 ms (D7 LOW + D10 HIGH) | odwozi ramię do parku |
| `SETTLE` | 40 ms | ramię osiada w parku |
| `STRIKE` | 25 ms (D8 LOW + D9 HIGH) | **uderzenie** |

Ramię **nie wraca samo** — dlatego każdy hit zaczyna się od aktywnego
parkowania. Pełny cykl to ~105 ms, więc maksymalna gęstość to ~9,5
uderzenia/s; nuty bliższe niż `HDD_MIN_PERIOD_S = 0,11 s` są zlewane
w jedno uderzenie (akord = jedno uderzenie).

**Jedna nuta, nie cały zestaw.** HDD ma JEDEN dźwięk uderzeniowy, więc
wrzucenie na niego całego tracku perkusyjnego brzmi jak terkot: hi-hat sam
ma ~3,5 uderzenia/s i zagłusza rytm. Dlatego wybiera się **jedną nutę
perkusyjną** (selektor `HDD Note`), np.:

| nuta | nazwa | gęstość w *Jigsaw* | efekt |
| --- | --- | --- | --- |
| 42 | Hi-hat zamk. | 3,56/s | terkot (za gęsto) |
| 51 | Ride | 1,71/s | szum |
| 36 | Stopa | 1,79/s | czytelny puls |
| **40** | **Werbel** | **1,41/s** | **czytelny rytm (2 i 4)** |

Bez filtra *Jigsaw* daje 5,56 uderzenia/s (powyżej możliwości mechaniki),
z filtrem werbla — 1,41/s. Lista dostępnych nut (z licznikami) jest
wyliczana z wybranego tracku i podawana w stanie `hdd.notes`.

**Gęstość.** Sam wybór nuty nie zawsze wystarcza: *Jigsaw* ma 170 BPM,
więc werbel (backbeat na 2 i 4) i tak wypada 1,29 raza na sekundę. Selektor
`HDD Gęstość` dokłada limiter (`hdd_rate`, uderzeń/s):

| ustawienie | werbel w *Jigsaw* |
| --- | --- |
| bez limitu | 1,41/s |
| max 2/s | 1,29/s (bez zmian — uderzenia są rzadsze) |
| max 1/s | 0,64/s (half-time) |
| max 0,5/s | 0,43/s |

Limiter nigdy nie schodzi poniżej limitu mechaniki (cykl park+strike
~105 ms), więc nie da się „przeciągnąć" HDD ponad ~9 uderzeń/s.

**Protokół:** `HIT` = jedno uderzenie (cisza, stan w `STATUS hdd=<0|1>`),
`HDD 0` = awaryjne przerwanie sekwencji. HDD jest niezależny od FDD —
działa nawet gdy stacja nie zrobiła homingu.

**Fail-safe:** `STOP`/`PAUZA`/`seek`/`disconnect`/`shutdown` wysyłają
`HDD 0`, więc żadne uderzenie nie „wisi" po zatrzymaniu.

**Fail-safe:**

* start firmware → `DRUM 0`,
* połączenie / **reconnect** Arduino → `DRUM 0` (bęben nie może ruszyć sam),
* rozłączenie w UI → `DRUM 0`, stan `disconnected`, suwaki zablokowane,
* restart backendu → `DRUM 0` przy pierwszym połączeniu.

W UI suwak PWM jest **dławiony (~80 ms)**, a po puszczeniu zawsze leci wartość
finalna — Serial nie jest zalewany. Backend wysyła dodatkowo `STATUS`, żeby
pokazać `PWM` **potwierdzone przez firmware** (a nie tylko wartość zadaną).

Uwaga: bęben nie jest objęty watchdogiem kroków FDD. Jeśli host zginie
(np. wyjęty kabel), bęben **kręci się dalej** — to świadoma decyzja (ręczne
sterowanie), do zmiany razem z ewentualnym watchdogiem bębna.

### 5.7. Sprzęt: reconnect i awarie

* Port Arduino wykrywany jest automatycznie (po VID/opisie); gdy jest kilka
  kandydatów, UI pozwala wybrać port.
* Po otwarciu portu Uno resetuje się, robi homing i wysyła `READY` - backend
  czeka na to i pokazuje wynik.
* **Play wciśnięty w trakcie homingu nie przepada.** Homing trwa do
  `--ready-timeout` (domyślnie 12 s) i przez cały ten czas nie ma jeszcze
  transportu, więc kiedyś kliknięcie `▶` kończyło się cichym „nic się nie
  stało". Teraz backend zapamiętuje zamiar (`hardware.pendingPlay`), UI pokazuje
  `Arduino: homing…` / `Play jest w kolejce`, a utwór rusza sam po `READY`.
  To dotyczy też **Reconnect** i **Home**.
* **Awaria w trakcie grania** (np. wyjęty kabel) → utwór przechodzi w `paused`
  z komunikatem błędu; playback **nie udaje, że gra dalej w ciszy**.
* Po podłączeniu sprzętu wciśnij **Reconnect** i wznów (`▶`).
* Błędy krytyczne z Arduino (`ERR POS_LOST`, `ERR NOT_HOMED`, `ERR HOME_FAILED`,
  `ERR HOST_TIMEOUT`) przerywają utwór; backend robi wtedy ponowny homing.

---

## 6. API backendu

Podział: **REST** = rzeczy bezstanowe, **WebSocket** = stan czasu
rzeczywistego i sterowanie.

### 6.1. REST

| Metoda | Ścieżka | Opis |
| --- | --- | --- |
| `GET` | `/api/state` | aktualny stan playera (ten sam co po WebSocketcie) |
| `GET` | `/api/files` | lista plików `.mid` z katalogu `midi/` |
| `GET` | `/api/files/{name}` | metadane: długość, zmiany tempa, lista tracków |
| `POST` | `/api/files` | **wgranie pliku MIDI** (`multipart/form-data`, pole `file`) |
| `GET` | `/api/ports` | dostępne porty szeregowe + aktualny |
| `GET` | `/api/config` | tryby transpozycji, strategie, zakres Hz |

Metadane pliku zawierają dla każdego tracku: `index`, `name`, `noteCount`,
`channels`, `isDrums`, `polyphonic` (czy cokolwiek brzmi jednocześnie).

### 6.2. WebSocket `/ws`

Po połączeniu serwer od razu wysyła stan, a potem publikuje go cyklicznie
(~150 ms, a gdy nic się nie zmienia - co 1 s jako heartbeat).

```jsonc
// serwer -> klient
{ "type": "state", "state": {
    "state": "playing",          // "stopped" | "playing" | "paused"
    "position": 126.47,
    "duration": 241.38,
    "file": "song.mid",
    "track": 3,
    "trackName": "Thom Vox",
    "midiNote": 52,
    "noteName": "E3",
    "sourceNote": 64,            // nuta z pliku (przed złożeniem oktawowym)
    "frequency": 164.81,
    "transpose": "low",
    "strategy": "highest",
    "range": { "minHz": 130, "maxHz": 330 },
    "stats": { "notes": 84, "folded": 80, "skipped": 0, "playCommands": 84 },
    "hardware": { "connected": true, "port": "/dev/cu.usbmodem14101",
                  "label": "Arduino", "error": null, "log": [] },
    "drum": {
      "value": 100,        // zadane PWM (0-255); 0 = stop
      "output": 100,       // potwierdzone przez firmware (STATUS); null = brak
      "toneHz": 300,       // 0 = tryb DC, inaczej wysokosc dzwieku
      "lastValue": 100,    // pamiec do przycisku Start
      "running": true,
      "connected": true,
      "minHz": 20,
      "maxHz": 2000
    }
} }

{ "type": "error", "message": "opis problemu" }   // np. zła akcja / brak pliku
```

```jsonc
// klient -> serwer
{ "action": "play" }  { "action": "pause" }  { "action": "resume" }  { "action": "stop" }
{ "action": "seek", "position": 120.0 }
{ "action": "set_file", "file": "song.mid", "track": 3 }
{ "action": "set_track", "track": 3 }
{ "action": "set_transpose", "mode": "low" }
{ "action": "set_strategy", "strategy": "highest" }
{ "action": "set_drum", "value": 100 }        // PWM bebna 0-255 (0 = stop)
{ "action": "start_drum" }                    // start z ostatniej niezerowej wartosci
{ "action": "stop_drum" }                     // DRUM 0
{ "action": "set_drum_tone", "hz": 300 }      // wysokosc bebna (0 = tryb DC)
{ "action": "set_drum_track", "track": 2 }    // drugi glos z MIDI (null = brak)
{ "action": "set_drum_transpose", "mode": "high" }   // low/high/auto
{ "action": "set_drum_strategy", "strategy": "highest" }
{ "action": "set_hdd_track", "track": 8 }    // track perkusji HDD (null = brak)
{ "action": "set_hdd_note", "note": 40 }     // jedna nuta perkusyjna (null = wszystkie)
{ "action": "set_hdd_rate", "rate": 1 }      // max uderzen/s (null = bez limitu)
{ "action": "reconnect", "port": "/dev/cu.usbmodem14101" }   // port opcjonalny
{ "action": "disconnect" }
{ "action": "snapshot" }                                       // wymuś odświeżenie
```

Szybkie sprawdzenie z terminala:

```bash
curl -s localhost:8000/api/state | python -m json.tool
curl -s localhost:8000/api/files | python -m json.tool
```

---

## 7. Uruchomienie (CLI)

CLI korzysta z **tego samego silnika** co web player (`host/playback/`), więc
timing, monofonia i transpozycja zachowują się identycznie. Różnica to brak
seek/pauzy - CLI gra utwór od początku do końca.

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

## 8. Protokół Serial

Tekstowy, 115200 8N1, linie zakończone `\n`.

| Komenda hosta | Odpowiedź Arduino |
| --- | --- |
| `PING` | `PONG` |
| `PLAY <hz>` | *(cisza - patrz niżej)* |
| `STOP` | *(cisza - patrz niżej)* |
| `HOME` | `OK`, a po dojechaniu `READY` |
| `DRUM <0-255>` | *(cisza)* PWM bębna VHS; `0` = stop (patrz sekcja 5.6) |
| `DRUMF <hz>` | *(cisza)* częstotliwość kluczowania = wysokość dźwięku; `0` = tryb DC (sekcja 5.6) |
| `STATUS` | `STATUS track=.. dir=.. homed=.. playing=.. track0=.. hz=.. drum=.. drum_out=.. drumf=..` |
| cokolwiek innego | `ERR UNKNOWN_CMD` |

Możliwe błędy: `ERR NOT_HOMED` (brak homingu), `ERR BUSY` (trwa homing/odjazd),
`ERR FREQ_RANGE` (częstotliwość poza `MIN_PLAY_HZ`..`MAX_PLAY_HZ`),
`ERR MISSING_FREQ`, `ERR BAD_FREQ`, `ERR HOME_FAILED`, `ERR POS_LOST`
(utrata pozycji - host robi ponowny homing), `ERR HOST_TIMEOUT` (watchdog: host
przestał się odzywać), `ERR MISSING_PWM`, `ERR BAD_PWM`, `ERR PWM_RANGE`,
`ERR MISSING_DRUMF`, `ERR BAD_DRUMF`, `ERR DRUMF_RANGE`
(sterowanie bębnem VHS), `ERR LINE_TOO_LONG`, `ERR UNKNOWN_CMD`.

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

## 9. Automatyczne składanie oktawowe (octave folding)

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

## 10. Monofonia (jedna stacja = jedna nuta)

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

## 11. Timing

Cały timing liczy host, a Arduino tylko wykonuje. Silnik
(`host/playback/engine.py`) działa w osobnym wątku i:

* korzysta z **zegara monotonicznego** (`time.monotonic()`),
* trzyma **absolutny origin**: `origin = monotonic() - pozycja`, a czas każdej
  komendy to `origin + czas eventu`,
* śpi do konkretnej chwili (`sleep` + krótkie aktywne doczekanie ostatnich
  1.5 ms), a nie „przez czas trwania nuty”,
* **seek przestawia origin**, a nie przesuwa kolejnych opóźnień - dlatego
  po seeku dryf nadal się nie kumuluje,
* wysyła `PING` (keepalive) tylko wtedy, gdy przez ~1 s nie poszła żadna
  komenda - dzięki temu długie nuty nie wyzwalają watchdoga w Arduino.

Dzięki temu opóźnienia Serial **nie kumulują się** - każde opóźnienie
przesuwa tylko jedną komendę, a nie cały utwór. Zmierzony dryf:

| Test | Zaplanowane | Rzeczywiste | Dryf |
| --- | --- | --- | --- |
| `range-test.mid` (73 nuty), CLI | 9.125 s | 9.125 s | **0 ms** |
| to samo, `--no-busy-wait` | 9.125 s | 9.130 s | +5 ms (stały, nie narasta) |
| `test.mid` track 1, na sprzęcie | 16.873 s | 16.877 s | +4 ms całości |
| `test.mid` track 1, web player + FDD | 16.873 s | 16.873 s | 0 ms |

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

## 12. Bezpieczeństwo mechaniki

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

## 13. Aktualne ograniczenia

* **Jedna stacja = jedna nuta naraz.** Akordy są redukowane do pojedynczej
  linii (patrz sekcja 10).
* Jedna stacja obsługiwana jednocześnie (`FloppyDrive drive` w firmware).
* Zakres 130-330 Hz; poza nim trzeba zmienić `--min-hz` / `--max-hz`
  (świadomie) albo liczyć się z gubieniem kroków.
* Głowica cały czas jeździ - długie nuty to kilka przejazdów po ścieżkach,
  co słychać jako zmianę barwy.
* Firmware nie wie nic o nutach MIDI: wysokość musi przyjść jako Hz.
* **Web player** jest lokalny i jednodostępowy (bez logowania i bazy danych).
  Stan jest jeden dla wszystkich kart przeglądarki - dwie karty to ten sam
  odtwarzacz, a nie dwa niezależne.
* Wgrywanie MIDI z przeglądarki zapisuje pliki **na stałe** w katalogu `midi/`
  (limit 5 MB); przy kolizji nazw powstaje `nazwa (2).mid`, nic nie jest
  nadpisywane. Walidacja: plik musi być czytelnym MIDI.
* Wybór strategii akordów jest w API (`set_strategy`), ale nie ma go w UI.
* **VHS Drum jest sterowany wyłącznie ręcznie** - nie ma jeszcze żadnego
  powiązania z MIDI (żadnego `MIDI → drum`, `velocity → drum`,
  `BPM → drum`, beat sync). To kolejny etap.

Świadomie **nie** zaimplementowano: ESP32, Wi-Fi, MQTT, VFD, HDD, DVD, VHS,
wielu instrumentów naraz, logowania, Dockera i chmury.

---

## 14. Rozszerzanie na wiele instrumentów

Kod jest tak ułożony, żeby nie trzeba było przepisywać logiki:

* **Firmware**: cała obsługa jednej stacji siedzi w klasie `FloppyDrive`
  (homing, licznik pozycji, generowanie kroków). Wystarczy `FloppyDrive
  drives[N]` z różnymi pinami i wybór stacji w `handleCommand()`.
* **Host**: `FloppyLink` wysyła komendy jako tekst, a harmonogram to lista
  `Command` z osią czasu - dodanie drugiego instrumentu to druga instancja
  linku i rozdzielenie komend po urządzeniu.

---

## 15. Testy

Wszystkie testy działają bez sprzętu (Serial jest zamockowany).

**Backend / host** (185 testów):

```bash
python -m unittest discover -s host/tests -t host/tests -v
```

* `test_pitch.py` - konwersje MIDI↔Hz, składanie oktawowe (wszystkie 128 nut,
  tryby `auto`/`low`/`high`),
* `test_midi_source.py` - mapa tempa ze zmianami BPM, redukcja do monofonii,
  scalanie unisono, nuty bez `NOTE_OFF`,
* `test_player.py` - budowanie harmonogramu `PLAY`/`STOP`, artykulacja,
  walidacja CLI,
* `test_engine.py` - **seek** (w ciszę, w środek nuty, w trakcie grania i
  pauzy), pauza/wznowienie, stop, zmiana tracku i transpozycji, anulowanie
  starego planu, brak dryfu, rozłączenie sprzętu, keepalive, wyścigi
  (wielowątkowe młotkowanie play/pause/seek),
* `test_web.py` - REST, WebSocket, sterowanie, bezpieczeństwo ścieżek plików,
  wielu klientów = jeden stan, sterowanie bębnem VHS i perkusją HDD przez
  WebSocket, wgrywanie plików MIDI (walidacja, kolizje nazw, limit rozmiaru).

**Frontend** (40 testów, vitest + jsdom):

```bash
cd web
npm test           # testy
npm run typecheck  # sama kontrola typów
npm run build      # typecheck + build produkcyjny
```

Testy frontendu sprawdzają m.in., że **przeciąganie paska nie wysyła niczego**,
a po puszczeniu leci **dokładnie jeden** `seek`, oraz że stan z WebSocketa
trafia na ekran (nuta, Hz, status sprzętu).

**Firmware**:

```bash
pio run -d firmware/floppy
```

---

## 16. Rozwiązywanie problemów

| Objaw | Przyczyna / rozwiązanie |
| --- | --- |
| `nie widze zadnego portu szeregowego` | sprawdź kabel USB i czy Serial Monitor / `pio device monitor` nie zajmuje portu |
| `nie moge otworzyc /dev/...` | port zajęty - zamknij Arduino IDE / PlatformIO Monitor |
| brak `READY` po otwarciu portu | stacja bez zasilania, źle podłączony `/TRACK0` lub `ERR HOME_FAILED` |
| `ERR HOME_FAILED` | napęd nie odpowiada: brak zasilania stacji, odłączona taśma albo czujnik `/TRACK0`. Sprawdź `STATUS` - pole `track0` powinno zmienić się na 1, gdy głowica dojedzie do TRACK0 |
| po `Ctrl+C` głowica stoi | to normalne - `STOP` zatrzymuje kroki, głowica zostaje na miejscu |
| gubi kroki / brzydki dźwięk | zjedź niżej: `--max-hz 300` albo `--transpose low` |
| dźwięk przerywany w szybkich nutach | `--no-busy-wait` zamień na domyślne (busy-wait) na maszynie obciążonej innymi procesami |

### Web player

| Objaw | Przyczyna / rozwiązanie |
| --- | --- |
| `Brak połączenia z backendem` w UI | backend nie działa - uruchom `python -m host.web.server` (albo `./scripts/dev.sh`) |
| strona pokazuje „Brak zbudowanego frontendu” | uruchom `cd web && npm run build` albo używaj Vite dev (`npm run dev`) |
| UI działa, ale `PLAY` nic nie robi | tryb `--no-hardware`; uruchom backend bez tej flagi albo z `--fake-hardware` do demo |
| `Arduino disconnected` mimo podłączonego kabla | port zajęty przez inny program (Serial Monitor) albo `ERR HOME_FAILED` - patrz wyżej |
| po `Reconnect` nadal brak `READY` | napęd nie odpowiada mechanicznie; sprawdź zasilanie stacji i taśmę |
| pasek stoi, choć stan to `playing` | brak interpolacji? sprawdź konsolę przeglądarki; backend i tak wysyła stan co ~150 ms |
| `seek` nie działa na bardzo krótkich utworach | pozycja jest klamrowana do długości timeline |
| zmiany frontendu nie widać | w trybie produkcyjnym po zmianach uruchom `npm run build` (Vite dev przeładowuje sam) |

---

## Auto Arranger (domyślny przepływ)

### Semantyczna klasyfikacja tracków

Kolejność: `MidiSource → normalizacja dubli → klasyfikacja semantyczna → wybór leadu/basu → allocator → PerformancePlan`. Klasyfikator w `host/playback/semantic.py` nadaje każdej partii rolę `VOCAL`, `BACKING_VOCAL`, `BASS`, `GUITAR`, `KEYS`, `STRINGS`, `PAD_SYNTH`, `PERCUSSION` albo `OTHER`. Raport aranżacji zawiera `trackClassification` z wynikiem każdej roli, pewnością, rodziną GM i powodami; zakładka **ARRANGEMENT** pokazuje je także w inspectorze nuty. Wyniki to jawne sumy wag, a nie prawdopodobieństwa.

| Sygnał | Punkty |
| --- | --- |
| nazwa wokalu/basu | `+0.72` do wskazanej roli |
| nazwa innej rozpoznanej roli | `+0.68` |
| nazwa chórku / dodatkowego głosu | `+0.78 BACKING_VOCAL` |
| `melody` / `solo` w nazwie | `+0.08 VOCAL` |
| rodzina GM Bass | `+0.45 BASS` |
| inna rozpoznana rodzina GM | `+0.18` do odpowiedniej roli |
| kanał perkusyjny MIDI | `+1.00 PERCUSSION` |
| monofonia co najmniej 80% | `+0.07 VOCAL`, `+0.04 BACKING_VOCAL`; przy niskich nutach `+0.04 BASS` |
| średnia wysokość 48–84 / nie wyższa niż 55 | `+0.06 VOCAL` / `+0.12 BASS` |
| co najmniej 30% małych interwałów / średni czas nuty 0.1–0.8 s | `+0.04 VOCAL` / `+0.02 VOCAL` |
| polifonia co najmniej 1.5 | `+0.04 GUITAR`, `KEYS`, `STRINGS` |
| zbieżność co najmniej 25% nut z tekstem w oknie ±120 ms | do `+0.50 VOCAL`, `+0.10 BACKING_VOCAL`, proporcjonalnie do zbieżności 75% |

Niska partia z GM Bass odejmuje `0.35` od punktów `VOCAL`. Bazowy wynik `OTHER` to `0.25`; rola musi osiągnąć `0.55`, inaczej pozostaje `OTHER`. Pewność to wynik zwycięskiej roli ograniczony do `1.00`. `VOCAL` przejmuje lead tylko przy pewności co najmniej `0.75` i przewadze co najmniej `0.12` nad innymi rolami; w przeciwnym razie działa dotychczasowa heurystyka. Pewny `BASS` i `PERCUSSION` są wyłączone z jej kandydatów. Po wyborze leadu tylko jego nuty mają dostęp do VHS; pozostałe partie tonalne korzystają z FDD/DVD, a perkusja z HDD.

MIDI → analiza → **voice allocator** → **Performance Plan** → Virtual Orchestra
(a później ten sam plan → hardware scheduler).

Użytkownik wrzuca plik MIDI i naciska Play. **Nie musi przygotowywać żadnego
JSON-a**, wybierać pitchy ani ręcznie rozdzielać akordów. Orkiestra domyślna v1
to 3 × FDD + 1 × VHS + 3 × HDD VCM (7 urządzeń), bez Arduino gra to Virtual
Orchestra.

### Dlaczego to powstało

Poprzedni model przypisywał konkretny pitch do konkretnego urządzenia na stałe.
Pojedynczy FDD/VHS jest monofoniczny, więc nuta skierowana do zajętego
urządzenia była **odrzucana, mimo że inne kompatybilne urządzenie stało puste**.
Na tym samym pliku i tej samej 7-urządzeniowej orkiestrze
(`.venv/bin/python scripts/benchmark.py`):

| | static (dawny routing) | auto (pula głosów) |
| --- | --- | --- |
| zagrane | 2890 | **5344** (+85%) |
| drop rate | 61.3% | **28.4%** |
| reassigned | 0 | 3805 |
| delayed | 0 | 247 (śr. 15 ms) |
| arpeggiated | 0 | 19 |
| voice steals | 0 | 48 |
| **lead preservation** | – | **310/310 = 100%** |
| **non-lead events na VHS** | – | **0** |
| VHS utilization | – | 0.61 (dedykowany) |
| wykorzystanie FDD | – | 0.69–0.71 (równomiernie) |

Podział pul kosztował ~7% zagranych nut (5730 → 5344) względem wspólnej puli,
ale VHS przestał przełączać się między wokalem, basem i harmonią. Świadoma
wymiana: czysta linia melodyczna zamiast kilku dodatkowych harmoniach nut.

### Warstwy

| plik | odpowiedzialność |
| --- | --- |
| `playback/analysis.py` | profil tracków, detekcja lead/bas, role nut |
| `playback/capabilities.py` | co potrafi typ urządzenia (tonalne/perkusyjne, monofonia, zakres, cykl) |
| `playback/orchestra.py` | konfiguracja orkiestry + polityka (preset `BALANCED`) |
| `playback/allocator.py` | **voice allocator** → decyzje, timing, overflow policies |
| `playback/performance.py` | `PerformancePlan` + raport (jedno źródło prawdy) |
| `playback/virtual.py` | `render_plan()` – wykonuje plan, **nie decyduje ponownie** |

`VirtualOrchestra.render_plan(plan)` symuluje mechanikę (kroki, travel,
zawracanie, cykl uderzenia) i produkuje zdarzenia audio oraz komendy sprzętowe.
Nie ma tam ani jednego „dropu z powodu polifonii” – plan już rozstrzygnął, co
gra. Dzięki temu wirtualizacja i sprzęt nie mogą się rozjechać.

### Podstawowy invariant

> Nuta nie może dostać DROP tylko dlatego, że jej *preferowane* urządzenie jest
> zajęte, jeśli istnieje inne kompatybilne, wolne i zdolne ją zagrać urządzenie.

Kolejność ratowania nuty:

1. wolne preferowane urządzenie → `ACCEPTED`
2. wolne inne kompatybilne → `REASSIGNED`
3. zwalnia się w oknie `maxMicroDelayMs` → `DELAYED`
4. zwalnia się w oknie `maxArpeggioMs` → `ARPEGGIATED`
5. głos słabszej nuty (grającej ≥ minimalną nutę) → `STOLEN` / `SHORTENED`
6. dopiero teraz → `DROPPED`

`REASSIGNED`, `DELAYED`, `ARPEGGIATED`, `STOLEN`, `SHORTENED` to jawne wyniki
widoczne w inspektorze nuty i w raporcie.

### Mechaniczna artykulacja FDD (legato)

MIDI gitary to często bardzo krótkie nuty: szarpnięcie struny plus naturalne
wybrzmienie instrumentu. Stacja dyskietek **nie ma naturalnego decayu** — jeśli
zagramy literalnie 62 ms i STOP, słychać `puk, cisza, puk, cisza`. Muzyka
przestaje się nieść, mimo poprawnych onsetów.

`playback/articulation.py` dodaje warstwę **wykonawczą**: rozdziela
`sourceDuration` (co jest w MIDI) od `performedDuration` (co zagra mechanika).

```
Allocator → PerformancePlan (sourceDuration)
          → articulation pass (performedDuration)
          → Virtual Orchestra / hardware scheduler
```

Pass żyje **między allokatorem a rendererem**, więc wirtualizacja i przyszły
sprzęt dostają dokładnie tę samą długość wykonawczą. Renderer nie podejmuje
żadnych nowych decyzji.

#### Algorytm

```
desiredEnd   = max(sourceEnd, start + preferredMechanicalSustain)
desiredEnd   = min(desiredEnd, sourceEnd + maxSustainExtension)
limit        = nextAssignedNoteStart − releaseGap      (na TYM SAMYM urządzeniu)
performedEnd = min(desiredEnd, limit)
performedEnd = max(performedEnd, sourceEnd)            (nigdy nie skracamy)
```

* **NOTE_ON / `actual_start` nigdy się nie zmienia** — groove zostaje.
* `releaseGap` rośnie do artykulacji mechanicznej (12 ms) przy powtórce tego
  samego pitchu, żeby dwie nuty nie zlały się w jedną ciągłą.
* Zdarzenia `SHORTENED` są pomijane — sustain nie cofa decyzji schedulera.
* Tylko urządzenia z `capability.articulation == 'sustain'` (FDD). VHS, HDD,
  solenoid i stepper mają `'none'`.
* Zmiana jest **adaptacyjna**: przy gęstym riffie (mediana przerwy 19 ms) nuta
  wydłuża się o ~16 ms; tam, gdzie jest 260 ms miejsca, dochodzi do 190 ms.
  Długie nuty (≥ `preferred`) zostają 1:1.

#### Parametry (`BALANCED`)

| parametr | wartość |
| --- | --- |
| `preferredMechanicalSustainMs` | 190 |
| `minMechanicalSustainMs` | 120 |
| `releaseGapMs` | 3 |
| `maxSustainExtensionMs` | 200 |
| `mechanicalSustain` | `true` (wyłącznik A/B) |

#### Benchmark Creep

| metryka | przed | po |
| --- | --- | --- |
| played / dropped | 4344 / 181 | 4344 / 181 (bez zmian) |
| accompaniment continuity | 0,371 | **0,661** |
| long gaps > 150 ms | 237 | **20** |
| total silence | 68,0 s | **41,5 s** |
| planned coverage | 0,709 | **0,823** |
| FDD coverage | 0,371 | **0,665** |
| mean performed duration | 61,5 ms | **107,8 ms** |

Kontrola `2+2=5`: liczba zdarzeń, NOTE_ON (bit w bit), decyzje allokatora
(urządzenie/wynik/rola) i `sourceDuration` **identyczne**; zmieniają się
wyłącznie długości na FDD. Ten utwór też zyskuje: continuity 0,843 → 0,942,
cisza 14,0 s → 6,9 s.

### Normalizacja źródeł: double-tracking

Realne pliki MIDI często zawierają tę samą partię zagraną dwa razy — `Guitar 1`
i `Guitar Dub`, stereo-duble, warstwy przesunięte o kilka–kilkadziesiąt ms. Dla
syntezatora to normalna technika producencka. Dla monofonicznej orkiestry
mechanicznej to **fałszywa polifonia**: dwa głosy walczą o te same FDD, choć
muzycznie to jedna partia.

`playback/duplicates.py` wykrywa takie pary i zamienia surowe tracki na
**partie logiczne**:

```
MidiSource → detect() → DuplicateReport
           → normalize() → NormalizedSource (partie logiczne)
           → analysis → allocator → PerformancePlan
```

Detekcja **nie używa nazw ani numerów tracków** — liczy się wyłącznie struktura
nut. Nazwa trafia tylko do raportu.

#### Algorytm

1. **Odsiew wstępny** — tylko tracki tonalne (perkusji nie deduplikujemy),
   ≥ 8 nut, stosunek liczby nut ≥ 0,60.
2. **Estymacja offsetu** — histogram `b.start − a.start` po parach *tego samego
   pitchu* w oknie ±250 ms, ziarno 1 ms; bierze się najgęstszy bin i uściśla
   medianą wokół szczytu. Histogram, nie średnia: kilka brakujących nut albo
   ornament nie przesuwa wyniku.
3. **Dopasowanie** — z offsetem, każda nuta A szuka najbliższej nuty B o tym
   samym pitchu w oknie ±40 ms; każda nuta B użyta najwyżej raz.
4. **Metryki** — `matchingRatio` (względem większego tracku), `pitchAgreement`,
   `medianOffset`, `offsetMad`, `durationSimilarity`, `velocitySimilarity`,
   `countRatio`, `confidence`.
5. **Werdykt** — `EXACT_DUPLICATE` / `NEAR_DUPLICATE` / `DIFFERENT`.
6. **Grupowanie** — spójne składowe po parach duplikatów, a potem **weryfikacja
   każdego członka względem primary** (łańcuch A~B~C nie skleja A z C).

| próg | EXACT | NEAR |
| --- | --- | --- |
| matchingRatio | ≥ 0,99 | ≥ 0,90 |
| offset MAD | ≤ 8 ms | ≤ 30 ms |
| durationSimilarity | ≥ 0,90 | ≥ 0,75 |
| velocitySimilarity | ≥ 0,90 | ≥ 0,55 |

Primary wybierany jest deterministycznie: większa liczba nut, potem wcześniejszy
indeks. Dub nie zużywa drugiego mechanicznego głosu — partia logiczna ma nuty
primary, a pełna metadana źródłowa (`sourceTracks`, `duplicateGroupId`,
`duplicateConfidence`, offsety) zostaje w planie i w raporcie.

Zasada bezpieczeństwa: **wolimy nie połączyć prawdziwego dubla niż źle skleić
dwie różne partie**. Przykłady false-positive protection: `C-E-G` vs `E-G-B`
(2/3 zgodności), ta sama linia o oktawę wyżej, ten sam rytm z innym pitchsem,
gęsty niezależny track. Na 15 plikach w `midi/` detektor znajduje grupy
**wyłącznie w Creep**.

#### Benchmark Creep

| metryka | przed | po |
| --- | --- | --- |
| tonal events | 5793 | 3259 |
| accompaniment demand | 2393 s | **1345 s** |
| demand / 3×FDD capacity | 3,40 | **1,91** |
| dropped | 1411 | **181** |
| drop rate | 20,0% | **4,0%** |
| delayed + arpeggiated | 2933 | **711** |
| długie dziury (>150 ms) | 237 | 237 |
| orchestra silent | 64,9 s | 68,0 s |
| planned coverage | 0,722 | 0,709 |

Kontrola `2+2=5` (0 grup): wszystkie metryki **bit w bit identyczne** przed i po.

### VHS = DEDICATED_LEAD_ONLY

VHS **nie należy do puli tonalnej**. Urządzenia tonalne dzielą się na dwie
rozłączne pule:

| pula | urządzenia | role |
| --- | --- | --- |
| **lead** | VHS | wyłącznie wykryty lead / vocal |
| **accompaniment** | FDD1–3 | bas, gitary, harmonia, chord tones |

To jest **twarda kwalifikacja, nie punktacja**. VHS nie występuje na liście
kandydatów akompaniamentu (`DeviceCapability.accepts()`), więc nie da się go
wybrać, nie może być fallbackiem dla zajętych FDD, nie może ratować
`DROPPED` nut akompaniamentu, nie może dostać nuty przez `REASSIGNED` i nie
może zostać obrabowany przez voice steal akompaniamentu. Gdy lead milczy,
**VHS pozostaje cichy** – świadomie, mimo że stoi bezczynnie.

Ścieżka leadu ma własne reguły (`_allocate_lead`): brak arpeggio, brak
reassignmentu do FDD, `leadMaxMicroDelayMs` = 12 ms. Gdy dwie nuty leadu na
siebie nachodzą, poprzednia jest **skracana**, żeby melodia szła dalej —
nigdy nie oddajemy jej na FDD.

Budżety długości nut liczone są **osobno dla każdej puli** (`maxNoteSeconds`
dla akompaniamentu, `leadMaxNoteSeconds` dla leadu), więc akompaniament nie
zjada pojemności zarezerwowanej dla melodii.

Raport zawiera sekcję `lead` (requested / played / dropped / preservation)
oraz `leadDevices` z licznikiem `nonLeadEvents` — invariant
**`assignedDevice == VHS ⇒ role == LEAD`** jest widoczny w API i w UI, a
testy pilnują, że wynosi dokładnie `0`. Ręczna reguła wskazująca VHS dla
basu/harmonii jest ignorowana.

### Detekcja lead / bas

Lead wybierany jest heurystycznie (bez twardych założeń o trackach): monofonia,
wyższy rejestr, dłuższe nuty, głośność, ciągłość melodii (małe interwały),
gęstość, a nazwa tracku to **wyłącznie słaba podpowiedź**. Dla polifonicznego
tracku za linię melodiczną uznawany jest górny głos. Gdy wynik jest zbyt płaski
(`leadConfidence`), lead nie jest chroniony na siłę.

VHS preferuje lead, ale gdy FDD są zajęte, przejmie harmonię – byle nie
dropować. Bas jest wykrywany po najniższym rejestrze i chroniony priorytetem.

### Pule perkusyjne

Trzy HDD to pula, nie przypisanie „kick → HDD1”. Preferencja wynika z klasy
brzmienia (stopa / werbel / blachy), ale gdy preferowany młotek jest zajęty,
uderzenie idzie na **dowolny wolny**. Drop dopiero gdy wszystkie trzy są zajęte
dłużej niż okno micro-delayu.

### Budżet długości nuty

Monofoniczna orkiestra ma skończoną przepustowość: N głosów × długość utworu.
Gdy suma długości nut ją przekracza, część materiału **musi** wypaść – chyba że
skrócimy nuty, tak jak robi to każdy instrument monofoniczny grający akordy.
Allocator liczy budżet sam (`tonalOverflow: "adaptive"`), a `capacitySafety`
(domyślnie 1.15) przechyla kompromis: **niżej = mniej dropów, rzadsza
faktura; wyżej = gęściej, więcej dropów**.

### Raport

`GET /api/report` (oraz `report` w `GET /api/arrangement`) zwraca:

* `requested / played / dropped / dropRate / retention`,
* `onTime / reassigned / delayed / arpeggiated / stolen / shortened / folded`,
* `meanDelayMs / maxDelayMs`,
* osobno dla tonalnych i perkusyjnych,
* per urządzenie: `notes`, `activeTime`, `utilization`.

### Arrangement JSON to teraz override, nie wejście

Zapisany `<nazwa>.orchestra.json` obok pliku MIDI jest wczytywany jako
**opcjonalny override** (reguły stają się *preferencjami* allocatora, nie
przybiciem na stałe). Brak pliku = czysta auto-aranżacja. `Save`/`Export`
zapisują orkiestrę + politykę + ewentualne ręczne reguły – bez tysięcy
przypisań nuta-po-nucie, bo plan jest deterministyczny.

## Virtual Orchestra (pierwszy etap)

Uruchom backend i frontend jak wyżej, np. `./scripts/dev.sh`, a następnie wczytaj MIDI. W sekcji **Virtual Orchestra** wybierz **ADD DEVICE**, ustaw tracki i włącz **Virtual hardware output**. Odtwarzanie działa bez Arduino. Zapisane składy są trzymane w `midi/.virtual-orchestra-presets.json`; przywraca je lista **Load preset**. Edycja urządzeń podczas Play zachowuje pozycję i stan odtwarzania: dotychczasowy podgląd gra do chwili przygotowania nowego audio, które zostaje podmienione w bieżącej pozycji.
Zielona dioda w prawym górnym rogu każdej karty pokazuje, że dana instancja jest aktywna w bieżącej pozycji odtwarzania. Długie nuty świecą przez czas trwania, a uderzenia dają krótki błysk obejmujący pracę mechanizmu. Pauza i stop gaszą wszystkie diody.

Dane MIDI oraz czasy nut pochodzą z istniejących `MidiSource` i `TempoMap`; istniejący `PlaybackEngine` nadal steruje play, pause, seek i stop. Model mechaniczny w `host/playback/virtual.py` przyjmuje nuty i wydaje decyzje accept/fold/drop, aktualizuje pozycję oraz statystyki, a dopiero zaakceptowane zdarzenia trafiają do renderera. Realny tor Serial pozostaje dostępny po wyłączeniu trybu wirtualnego. Pole `mode` w instancji jest zarezerwowane dla przyszłego adaptera hybrydowego; pierwsza wersja przyjmuje tylko `virtual`.

Profile są serializowane z pochodzeniem każdej wartości (`RESEARCHED`, `ESTIMATED`, `UNKNOWN`). `FDD_CURRENT`, `VHS_CURRENT` i `WD_CAVIAR_CURRENT` opisują **ten konkretny** kod firmware i hosta. `DVD_REFERENCE`, `STEPPER_REFERENCE` i `SOLENOID_REFERENCE` jawnie pozostawiają niezmierzone granice jako `UNKNOWN`; symulator nie odrzuca nut na podstawie nieznanych granic. Wartości 40/40/25 ms są tylko profilem bieżącego HDD. Te profile należy skalibrować dla prawdziwych urządzeń przed traktowaniem wyników jako przewidywań fizycznych.
Każda instancja może mieć własne nadpisania parametrów wraz z provenance i notatką źródłową. W UI są pod rozwijanym **Device profile**.

Renderer generuje przybliżony stereofoniczny WAV po stronie Pythona i na macOS odtwarza go przez systemowy `afplay`. `pyo` nie jest zainstalowane w obecnym środowisku Python 3.14, więc nie jest obowiązkową zależnością; interfejs `WavePreview` można zastąpić później backendem `pyo` lub PortAudio. Audio zawiera impulsy kroków, zdarzenia zawracania, prosty rezonans, uderzenia HDD/solenoidu i ton silnika VHS. Rezonatory i krzywa velocity są przybliżeniami do odsłuchu orkiestracji. Nie ma jeszcze próbek SFZ, artykulacji HDD, wzajemnych blokad zasobów ani modelu przyspieszenia silnika.

Testy: `.venv/bin/python -m unittest discover -s host/tests`, `cd web && npm test && npm run build`. Mechanikę można testować bez urządzenia audio.

## Song Arrangement Editor

Po wczytaniu MIDI otwórz zakładkę **ARRANGEMENT**. Edytor ładuje zapisany `<nazwa>.orchestra.json`, jeśli istnieje; w przeciwnym razie inicjalizuje aranżację z istniejącego składu Virtual Orchestra. Pokazuje wszystkie nuty pochodzące z `MidiSource`. W zakładce **ORCHESTRA** dodaj urządzenia i ustaw ich profile oraz miks; w **ARRANGEMENT** przypisz do nich źródła MIDI. Transport u góry strony, seek i playhead korzystają z tego samego `PlaybackEngine` co dotychczas. Edycja reguł podczas Play zachowuje pozycję i stan odtwarzania, a nowy podgląd audio jest podmieniany po przygotowaniu. Zakładka zajmuje całą szerokość okna, a piano roll automatycznie przewija się za playheadem podczas Play.

Dioda przy urządzeniu w **ORCHESTRA** świeci podczas Play, gdy to urządzenie faktycznie wykonuje przyjętą nutę lub uderzenie. Krótkie uderzenia są podtrzymane na ekranie przez 250 ms, żeby były widoczne między aktualizacjami WebSocket. Po Stop/Pause diody gasną; Mute i Solo wpływają na to, które urządzenia są słyszalne i sygnalizowane.

Piano roll ma przewijanie czasu i wysokości, zoom poziomy oraz trzy widoki: źródło MIDI, urządzenie docelowe i wynik symulacji. Pasek po lewej stronie nuty oznacza track, obramowanie oznacza urządzenie. `UNASSIGNED` to nuta bez urządzenia po routingu; `DROPPED` to nuta skierowana do urządzenia, ale odrzucona przez jego model mechaniczny. Statusy mają również symbole i wzory. Kliknięcie nuty pokazuje źródło, regułę, urządzenie, artykulację, wynik, przyczynę odrzucenia, zagrany pitch po złożeniu oktawowym i czas zwolnienia zajętego urządzenia.

Reguły obsługują `track`/`tracks`, `channel`/`channels`, `includeNotes`, `excludeNotes`, `noteRange`, `velocityRange` oraz transformacje `gate`, `transpose`, `octaveFold`, `strategy`. Jedna nuta może trafić do wielu urządzeń. Reguła obejmująca dokładnie jeden pitch w jednym tracku ma pierwszeństwo przed ogólną regułą tracku; dzięki temu lista perkusyjna może wyłączyć hi-hat lub skierować werbel do innego urządzenia bez usuwania ogólnego routingu. Artykulacja jest zapisywana jako metadane i widoczna w inspektorze; obecny renderer audio nie tworzy jeszcze jej wariantów.

**Save Arrangement** zapisuje obok MIDI plik `<nazwa>.orchestra.json` w katalogu `midi/`. **Load Arrangement** odczytuje ten plik. Import/eksport pozwalają przenieść JSON jako osobny plik. Backend sprawdza `schemaVersion`, nazwę i SHA-256 MIDI oraz indeksy i nazwy tracków. Przy niezgodności import pokazuje mapowanie tracków do aktualnego pliku przed zastosowaniem. Format wersji 1:

**Import jest wspólny dla wszystkich zakładek.** Przycisk *Import Arrangement JSON* siedzi w nagłówku obok zakładek, więc ten sam plik wczytasz z **PLAYER**, **ORCHESTRA** i **ARRANGEMENT** — nie ma osobnego dokumentu „dla sprzętu” i „dla wirtualizacji”. Import nie przełącza też na siłę na wirtualizację: o wyjściu decyduje pole `mode` każdej instancji, a nie zakładka.

`mode` instancji ma trzy wartości:

| `mode` | Symulacja i piano roll | Podgląd audio (WAV) | Fizyczne linie Serial |
| --- | --- | --- | --- |
| `virtual` | tak | tak | nie |
| `real` | tak (diagnostyka) | nie | tak |
| `hybrid` | tak | tak | tak |

Sprzęt ma dokładnie jedną linię FDD, jedną bębna VHS i jedną HDD, więc dla każdej linii wybierana jest **pierwsza** instancja `real`/`hybrid` (kolejność w `devices`). Pozostałe trafiają do sekcji *Hardware lanes* w zakładce **ORCHESTRA** jako `LANE_TAKEN` — zamiast być po cichu zignorowane. Komendy sprzętowe (`PLAY`/`STOP`, `DRUM`/`DRUMF`, `HIT`) powstają z tych samych zaakceptowanych zdarzeń, które widzi symulacja (`host/playback/hardware.py`), więc sprzęt nie zagra niczego, czego piano roll nie pokazuje jako `ACCEPTED`/`FOLDED`/`DELAYED`. `mute` i `solo` wyciszają także sprzęt. Gdy Arduino nie jest podłączone, `GET /api/state` zwraca `arrangementHardware.active` (aranżacja kieruje na linie) i `.connected: false`; linie czekają w planie i ruszają po podłączeniu.


Przykład do odsłuchu: [`midi/0087-09-radiohead_2007-jigsaw_falling_into_place.orchestra.json`](midi/0087-09-radiohead_2007-jigsaw_falling_into_place.orchestra.json). Wybierz odpowiadający mu MIDI bez dopisku `(2)` lub `(3)`, a potem otwórz **ARRANGEMENT**. Przykład przypisuje wokal i gitarę do dwóch FDD, bas do VHS, stopę/werbel do HDD, talerze do solenoidu i smyczki do steppera; hi-hat 42 pozostaje nieprzypisany. To demonstracja routingu, nie skalibrowana recepta dla fizycznych urządzeń.

```json
{
  "schemaVersion": 1,
  "name": "My arrangement",
  "midi": {
    "file": "song.mid",
    "sha256": "<SHA-256 MIDI>",
    "tracks": [{ "index": 0, "name": "Drums" }]
  },
  "devices": [{
    "id": "hdd-1", "type": "HDD_VCM", "name": "HDD #1",
    "profile": "WD_CAVIAR_CURRENT", "mode": "virtual",
    "volume": 0.6, "pan": 0, "gate": 1, "transpose": 0
  }],
  "rules": [{
    "id": "kick-to-hdd",
    "source": { "track": 0, "includeNotes": [36] },
    "destination": { "deviceId": "hdd-1" },
    "transform": { "gate": 1, "transpose": 0, "octaveFold": true, "strategy": "first" },
    "articulation": "LEFT_HARD"
  }]
}
```

`devices` zawiera także pozostałe pola instancji z Virtual Orchestra, w tym `role`, `mode`, `mute`, `solo` i `overrides`. To one przechowują parametry miksu i profilu. Backend interpretuje JSON przez `host/playback/arrangement.py`, przekazuje wybrane nuty do istniejącego `VirtualOrchestra.simulate`, a wynik udostępnia przez `GET /api/arrangement`; zapis, odczyt i aktualizacja mają endpointy pod tym samym prefiksem. Browser tylko rysuje otrzymane nuty i wysyła edycje. Starsze kontrolki HDD w **PLAYER** nadal obsługują dotychczasowy tryb real hardware (bez aranżacji); gdy aranżacja jest wczytana, routing obu wyjść pochodzi z jej reguł i pola `mode`.

Piano roll używa cienkiego renderera Canvas bez nowego parsera MIDI ani zegara odtwarzania. Oceniono [react-piano-roll](https://github.com/PlayfulCreations/react-piano-roll), [@minagishl/react-piano-roll](https://www.npmjs.com/package/%40minagishl/react-piano-roll), [tween-midi-editor](https://github.com/tuomashatakka/tween-midi-editor) i [@tonejs/midi](https://www.npmjs.com/package/%40tonejs/midi). Gotowe edytory dodają własne odtwarzanie lub model MIDI i utrudniają niestandardowe kolory, wielokierunkowy routing oraz diagnostykę pojedynczej nuty; ostatnia biblioteka jest parserem, który powielałby `MidiSource`. Canvas rysuje tylko nuty widoczne w oknie, więc duży plik nie tworzy tysięcy elementów DOM. Loop range, fizyczny/hybrid adapter routingu i faktyczne warianty artykulacji pozostają kolejnym etapem.

## Eksperyment: cztery dodatkowe głosy DVD

Domyślna testowa orkiestra ma teraz 3 FDD, 4 wirtualne `DVD_SLED`, 1 VHS i 3 HDD. DVD mają profil `DVD_REFERENCE` z nieznanym zakresem fizycznym, tryb `virtual` i głośność `0.2`; nie dodano sterowania fizycznymi napędami. FDD mają pierwszeństwo dla akompaniamentu, a DVD przejmują nuty, gdy FDD są zajęte. VHS pozostaje urządzeniem wyłącznie dla leadu, HDD wyłącznie dla perkusji. W zakładce **ORCHESTRA** można nadal dodawać, usuwać i zapisywać poszczególne instancje; te zmiany trafiają do `OrchestraConfig` używanego przez Auto Arrangera.

Porównanie 7 urządzeń (bez DVD) z 11 urządzeniami na tych samych znormalizowanych plikach MIDI:

```sh
.venv/bin/python scripts/benchmark_dvd.py
```

Wyniki z dostępnych lokalnie utworów są w [`benchmarks/dvd-7-vs-11.json`](benchmarks/dvd-7-vs-11.json). Zawierają drop rate, ciągłość, ciszę tonalną oraz liczbę nut i wykorzystanie każdego DVD. Istniejący zapisany JSON Jigsaw jest ręcznym override po wczytaniu tego konkretnego pliku; benchmark celowo mierzy czysty Auto Arranger bez tego override.

### Eksperyment A/B: dynamiczne reinforcement DVD

W **ORCHESTRA → DVD mode** wybierz `4x DVD independent` lub `4x DVD + dynamic reinforcement`. Oba ustawienia dają allocatorowi te same cztery niezależne DVD i tę samą politykę. Po zakończeniu alokacji i artykulacji mały pass szuka wolnych odcinków każdego DVD. Gdy w tym czasie inne DVD gra nutę, dodaje jej akustyczny dubel na wolnym napędzie. Kandydatów porządkuje istniejący score priority (rola, velocity i długość). Jeden głos dostaje najwyżej jeden dubel w danym odcinku. Dubel kończy się przed następną zwykłą nutą na docelowym DVD. Dodatki są zapisane osobno w `PerformancePlan.reinforcements`, więc nie zmieniają zwykłych decyzji ani liczników `played`/`dropped`.

Ustawienie zapisuje się jako `dvdMode: "independent" | "reinforcement"` w konfiguracji orkiestry i presetach. Poszczególne DVD zachowują osobne diody i raporty. Zmiana trybu przebudowuje plan z zachowaniem pozycji odtwarzania.

Benchmark unikalnych MIDI można powtórzyć komendą:

```sh
.venv/bin/python scripts/benchmark_dvd_reinforcement.py --midi-dir /ścieżka/do/katalogu/midi
```

Wynik: [`benchmarks/dvd-reinforcement.json`](benchmarks/dvd-reinforcement.json). Z 26 dostępnych plików wybrano 15 unikalnych według SHA-256. Każdy z nich został znormalizowany tylko raz. Skrypt wymaga identycznych zwykłych zdarzeń, urządzeń, polityki i metryk alokacji w obu wariantach; rozbieżność kończy benchmark błędem. `dvdDoublingPercentOfNormalWork` to czas pracy dodatkowych napędów podzielony przez zwykły czas pracy DVD, a wykorzystanie pojedynczego DVD uwzględnia zwykłe nuty i duble.

| 15 unikalnych MIDI | 4 DVD independent | 4 DVD + reinforcement |
| --- | ---: | ---: |
| nuty tonalne: requested / played / dropped | 51 195 / 47 737 / 3 458 | 51 195 / 47 737 / 3 458 |
| drop rate | 6,75% | 6,75% |
| zdarzenia / łączny czas reinforcement | 0 / 0 s | 8 849 / 1 404,964 s |
| czas pracy DVD z doublingiem | 0% | 30,28% |
| wykorzystanie DVD1 / DVD2 / DVD3 / DVD4 | 36,60% / 35,87% / 31,96% / 31,66% | 49,98% / 45,05% / 41,13% / 41,15% |

Zwykłe przypisania i dropy są identyczne dla każdego pliku. Te wyniki dotyczą symulowanego podglądu akustycznego; rzeczywisty przyrost głośności napędów wymaga pomiaru sprzętowego.
