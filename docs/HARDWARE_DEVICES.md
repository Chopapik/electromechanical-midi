# Urządzenia, ograniczenia i kalibracja

Bieżące wartości pochodzą z lokalnego kodu i konfiguracji, także commitów
niewysłanych na serwer. Kolejność źródeł: aktywne urządzenia w
[devices.json](../config/devices.json), połączone profile
[theoretical.json](../config/hardware-profiles/theoretical.json) i
[instances.json](../config/hardware-profiles/instances.json), interpretacja w
[hardware_profiles.py](../host/playback/hardware_profiles.py), następnie
[stałe wykonawcze firmware](../firmware/controller/include/hardware_profiles_generated.h).
Osobno istnieją profile brzmienia; ich nazwa nie określa fizycznego sterownika.
Połączenia i napięcia są opisane wyłącznie w [schemacie](HARDWARE_WIRING.md).

## Inventory i identyfikatory

| Urządzenia | ID / lane | Wykonawca i rola |
| --- | --- | --- |
| FDD1–4 | `fdd-1`…`fdd-4`, `fdd:1`…`fdd:4` | STEP/DIR, monofoniczne głosy tonalne |
| DVD1–4 | `DVD_STEPPER_1`…`DVD_STEPPER_4`, `sled:1`…`sled:4` | DRV8833, dwie cewki, pełny krok, ciągły obrót |
| PC Speaker | `vhs-1`, `drum:1` | GPIO25, główny wokal/lead |
| PC Speaker FX | `pc-speaker-fx`, `drum:2` | GPIO26, tonalne ozdobniki i rezerwa zależna od presetu |
| HDD1–4 | `hdd_vcm-1`…`hdd_vcm-4`, `hdd:1`…`hdd:4` | DRV8833, perkusyjny HIT |

Wszystkie 14 wpisów są obecnie włączone. `enabled` / `present` deklaruje
inventory; nie jest detekcją przewodów ani pomiarem sprawności. Ordynał lane
jest fizycznym kanałem: usunięcie wpisu nie uprawnia do przesunięcia pozostałych.
Typ `VHS` oraz komendy `VHS`/`VHS2` zachowano dla zgodności obu speakerów.
HDD mają profil brzmienia `WD_CAVIAR_CURRENT`, ale fizyczny
`hardwareProfile: HDD_PERCUSSION`; nie ma wykonawcy tonalnego HDD w tym zestawie.

## Jak czytać dowody

`FACT` może oznaczać fakt o konfiguracji lub kodzie. Nie oznacza automatycznie
pomiaru silnika. `MEASURED` trzeba czytać wraz z metodą, badaną instancją,
warunkami i niepewnością; `DERIVED` to wynik obliczenia, `HYPOTHESIS` to założenie.
Brak danych (`null`, UNKNOWN) nie jest zerem ani dowodem braku ograniczenia.
Dane referencyjnego modelu producenta nie identyfikują odzyskanego egzemplarza.
[Rejestr obserwacji i pomiarów](research/hardware-measurements.md) oddziela
wyniki testów od aktualnej polityki muzycznej.

## FDD: trzy różne zakresy

| Warstwa | Bieżąca wartość dla FDD1–4 | Co oznacza |
| --- | --- | --- |
| Aranżacja | Transpozycja −12, preferowane 100–205 Hz | Zapisany eksperyment odsłuchowy; wszystkie presety i STRICT_TRACKS |
| Profil sprzętowy | `musicalHz` 100–410 Hz | Dopuszczenie przez model hosta, także testy lab; dolna granica eksperymentalna |
| Firmware, wejście PLAY | 40–500 Hz | Zakres poprawnej komendy, nie gwarancja osiągalnej częstotliwości |
| Firmware, impulsy STEP | Minimalny odstęp 2439 µs ≈ 410 kroków/s | Osobny limit wykonania, również przy komendzie 500 Hz |
| Metadane FDD1 | `stableHz` 130–410 Hz | Górny punkt z testu; 130 Hz zachowane w metadanych, nie zmierzony próg dolny |
| Ataki nut | Minimum 120 ms między NOTE_ON na stację | Muzyczne ograniczenie zmian nut, niezależne od częstotliwości STEP |

`COMFORT_MIN_HZ=200` / `MAX=410` w [pitch.py](../host/pitch.py) to ogólny
fallback. Aktywne preferencje urządzeń go zawężają do 100–205 Hz po transpozycji.
Dlatego wykonane 130,81 Hz lub ~196 Hz są zgodne z bieżącą konfiguracją.
Przykład: wcześniej wykonywane C4 261,63 Hz staje się C3 130,81 Hz.
Folding przesuwa o całe oktawy, nie przycina nuty do wartości granicznej.
Źródłowy pitch MIDI pozostaje zapisany osobno od `played_hz`.
Dodatkową próbę obniżenia w DVD Lead opisuje [aranżacja](ARRANGEMENT.md#presety).

Wykonanie: aktywne LOW STEP o szerokości 30 µs; zmiana DIR z czasem ustalenia
5 ms. Roboczy limit oddalania to 72 kroki. Fizyczne TRACK0 jest jedynym odniesieniem:
resetuje `awaySteps`; ruch do TRACK0 nie jest odliczaniem pozycji z powrotem.
HOME ma timeout 2 s i okres kroku 5 ms. Boot i reconnect nie wykonują HOME.
Po utracie odniesienia wykonaj jawny HOME; telemetria nie jest enkoderem.
Wartości wspólne czterem stacjom nie oznaczają indywidualnej kalibracji każdej.
Długie gate'y i powroty karetki nadal mogą wpływać na brzmienie.

## DVD stepper

W aktywnym trybie ciągłym `travelSteps=0`, bez limitu drogi i bez whitelisty
pasm. `−1` oznacza nieznany profil, nie ciągły obrót. Aranżacja ma niezależny
sufit **600 Hz akustycznych**, składając wyższe nuty o oktawy. Lab nie stosuje
tego foldingu i nie daje przez to uprawnienia do dowolnie wysokich testów.

`pitchRatio = acousticHz / stepsPerSecond`: DVD1–3 mają 0,5 (hipoteza tunera),
DVD4 1,0. Dla 200 Hz są to odpowiednio 400 lub 200 kroków/s.
Host i firmware przeliczają ten sam profil; komenda PLAY zawiera akustyczne Hz.
Rampa wynosi 5000 kroków/s² (założenie robocze). `Sled::play()` zmienia
cel bez zatrzymania; STOP natychmiast wyłącza fazy, bez rampy hamowania.
Sustain wykorzystuje tę istniejącą rampę, nie nowy sterownik.

Minimalny okres timera 100 µs oznacza granicę reprezentacji 10 000 kroków/s;
nie jest zakwalifikowanym zakresem muzycznym ani mechanicznym. Licznik pozycji
jest względnym, nasycanym licznikiem komend bez czujnika położenia.
Ciągły obrót zakłada mechanicznie swobodny wirnik; oś ze śrubą i karetką
mogłaby uderzyć w koniec drogi. Sprawdź faktyczną konstrukcję przed ruchem.
Nie ma termicznego limitu długości frazy ani czujnika temperatury.
Proponowane zasilanie silników i brak kwalifikacji ciągłej pracy:
[schemat zasilania](HARDWARE_WIRING.md#zasilanie).

## HDD VCM

Fizyczny cykl: **40 ms Park → 40 ms Settle → 4 ms Strike → coast**, razem 84 ms.
Zajęty kanał odrzuca HIT (`ERR BUSY`), bez ukrytej kolejki.
Profil hosta dodatkowo modeluje gęstość: nominalny odstęp 200 ms,
ciągłe 5 hitów/s i burst 10 hitów/s w oknie 500 ms są założeniami, nie ratingiem
cewki. Kolejność faz i czas impulsu pochodzą z firmware; parametry brzmienia
wirtualnego nie zmieniają czasu fizycznego uderzenia.

Artykulacja MIDI (soft/medium/hard/double/buzz) opisuje proceduralny dźwięk;
nie dowodzi identycznego gestu fizycznego. Nie ma pomiaru prądu, siły uderzeń,
wychylenia ani trwałości ograniczników. Nie wyznaczono bezpiecznego prądu
szczytowego lub czasu ciągłej pracy. Dawny szkic pojedynczej cewki nie kwalifikuje
czterech obecnych urządzeń. Wyniki: [HDD VCM](research/hardware-measurements.md#hdd-vcm).

## PC Speaker i PC Speaker FX

Główny speaker ma `transpose: +12`, FX `0`, przed foldingiem profilu.
Profil hosta `VHS` dopuszcza 20–2000 Hz; protokół ma szerszy zakres pulse do
20 kHz i pozostałych fal do 2 kHz. Granice protokołu nie są pomiarem akustycznym.
LEDC kanały 0 i 2 mają osobne timery; kanał 1 współdzieliłby timer z kanałem 0.

`/settings` → **Brzmienie PC Speaker**: osobny gain VIRTUAL i wybór fali dla
każdego głośnika. Fala `pulse`, `sine`, `triangle`, `sawtooth` jest wspólna
REAL/VIRTUAL. W pulse suwak `realAmplitude` 0–128 daje duty 0–50% przez
`AMP/256`; **AMP 50 = 19,53125% duty**, a nie 50% głośności.
Duty 50% daje prostokąt symetryczny; mniejsze wypełnienie zmienia barwę i poziom,
więc fizyczna głośność i kształt impulsu nie są niezależnymi regulatorami.
VIRTUAL 0–100% mapuje gain 0–2,5 (dawny gain 1 odpowiada 40% nowej skali).
Zapisane ustawienia użytkownika mogą zastępować wartości początkowe.

Pulse VIRTUAL to pasmoograniczony szereg 64 harmonicznych. Pozostałe fale REAL
używają PWM 40 kHz, aktualizowanego co 50 µs (20 kHz). To modulacja impulsów
przez S8050, nie analogowy DAC. Filtracja nośnej, obciążenie i mechanika głośnika
wpływają na słyszany przebieg; identyczny wybór generatora nie oznacza zmierzonej
identyczności dźwięku REAL/VIRTUAL. STOP i próbki synchronizuje wspólny mutex,
aby spóźniona próbka nie przywróciła wyjścia.

Obsługa drugiego kanału wymaga `speaker_fx=1`, nowych fal `speaker_waves=1`.
Niezgodny firmware blokuje wymagającą ich grę REAL; aplikacja nie flashuje
samoczynnie. Sposób podłączenia i nieznane elementy mocy:
[dwa speakery](HARDWARE_WIRING.md#dwa-pc-speakery).

## Walidacja i bezpieczeństwo

Model ocenia długość/minimum cykli, przejścia częstotliwości, zajętość,
chronologię ruchu, zawrócenia i gęstość hitów. `OUTSIDE_MUSICAL_RANGE`, braki
profilu i konflikty nie są wykryciem awarii fizycznego czujnika.
Zmienione gate'y i nowe kopie trzeba oceniać wraz z przyszłymi rezerwacjami.

Najdłuższe ciągłe wykonanie DVD w benchmarku Universal wyniosło **366,997 s**;
to wynik harmonogramu, nie pozytywny test termiczny. Brak kodowego limitu czasu
nie oznacza możliwości nieograniczonej pracy sprzętu. Watchdog chroni przed
utratą komend hosta, nie przed przegrzaniem przy poprawnie działającym hoście.
Procedury STOP i odłączania mocy są w [testach](HARDWARE_TESTING.md#awarie).
