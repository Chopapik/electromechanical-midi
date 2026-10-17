# Urządzenia, ograniczenia i kalibracja

Docelowy firmware obsługuje **8 FDD / 6 DVD / 4 HDD / 2 speakery**,
6 rejestrów i 8 DRV8833, ale **host nadal deklaruje 4 FDD, 4 DVD i 14 urządzeń**. Nie rozszerzono aranżacji, profili JSON ani UI.
FDD5–8 oraz DVD5–6 wymagają osobnej kwalifikacji fizycznej i są domyślnie wyłączone.
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

Wszystkie 14 wpisów **hosta** są obecnie włączone; tabela nie deklaruje
obsługi FDD5–8 ani DVD5–6 przez aplikację. `enabled` / `present` deklaruje
inventory; nie jest detekcją przewodów ani pomiarem sprawności. Ordynał lane
jest fizycznym kanałem: usunięcie wpisu nie uprawnia do przesunięcia pozostałych.
Typ `VHS` oraz komendy `VHS`/`VHS2` zachowano dla zgodności obu speakerów.
HDD mają profil brzmienia `WD_CAVIAR_CURRENT`, ale fizyczny
`hardwareProfile: HDD_PERCUSSION`; nie ma wykonawcy tonalnego HDD w tym zestawie.

## Nowe FDD5–8: firmware bez rozszerzenia hosta

| Kanał | TRACK0 | STEP / DIR | Stan po boot |
| --- | ---: | --- | --- |
| FDD5 | GPIO32 | Q8 / Q9 | Wyłączony, bez HOME |
| FDD6 | GPIO33 | Q10 / Q11 | Wyłączony, bez HOME |
| FDD7 | GPIO16 | Q12 / Q13 | Wyłączony, bez HOME |
| FDD8 | GPIO17 | Q14 / Q15 | Wyłączony, bez HOME |

Cztery istniejące kanały mają dotychczas testowaną logikę; nie oznacza to
fizycznego sprawdzenia nowej kaskady i przeniesionych DVD/HDD. Dodatkowe FDD
są jeszcze niepodłączone, a SR6 wymaga oddzielnego testu napięć i propagacji.

Generator nadal dostarcza **cztery** profile FDD. `fddDefaults::profileIndex`
w [rdzeniu C++](../firmware/controller/include/orchestra_core.h) jawnie wybiera
dla FDD5–8 indeks 0: startowo 72 kroki oddalania, 5000 µs zmiany kierunku,
2439 µs minimum STEP. To kopia domyślnych parametrów FDD1 z wygenerowanego
nagłówka, **nie profil zmierzony nowych stacji**. Runtime PROFILE FDD1 nie
zmienia automatycznie pozostałych kanałów. Osobny PROFILE n można nadać ręcznie
przy zatrzymanym kanale po pomiarach. Nie edytuj wygenerowanego nagłówka ręcznie.

FDD5–8 mają ENABLE/HOME/PLAY/STOP oraz obsługę błędów i watchdoga.
Samo ENABLE nie wykonuje HOME. Jawne `FDD ALL HOME` obejmuje wszystkie
**włączone** kanały; po boot są to tylko FDD1–4. STRICT_TRACKS pozostaje
czterokanałowe i odrzuca PLAY FDD5–8, bez indeksowania tablicy czterech tracków.
Zwykłe STATUS zachowuje FDD1–4 i 17 rekordów. `DIAG FDD` pokazuje FDD5–8
w osobnej odpowiedzi diagnostycznej, bez poszerzania transakcji hosta.

**Blokada poza zakresem zadania:** pełne osiem głosów w aplikacji wymagałoby
zmian registry/ordynałów, inventory i profili, limitów ID transportu,
alokacji/STRICT_TRACKS, parsowania lub kontraktu STATUS oraz testów hosta/UI.
Konkretnie [registry](../host/runtime/registry.py) ogranicza rodzinę FDD do 4,
[OrchestraLink](../host/orchestra_link.py) przyjmuje ID FDD tylko 1–4,
a [STRICT_TRACKS](../host/playback/strict_tracks.py) wymaga czterech slotów. Samo dodanie wpisów JSON nie wystarczy.
Wariant do osobnego wdrożenia: jawne poszerzenie całego kontraktu hosta do ośmiu
FDD z indywidualnymi profilami, po kwalifikacji sprzętu. W tym zadaniu tego nie zrobiono.

## Nowe DVD5–6: firmware i fallback czterech profili

| Kanał | Wyjścia | Moduł | Stan po boot |
| --- | --- | --- | --- |
| DVD5 / SLED 5 | Q32–Q35 | DRV5, oba mostki | Wyłączony, bez ruchu |
| DVD6 / SLED 6 | Q36–Q39 | DRV6, oba mostki | Wyłączony, bez ruchu |

Generator i nagłówek wciąż zawierają **tylko DVD1–4**. Jawny
`sledDefaults::profileIndex` w C++ wybiera dla DVD5–6 indeks **3 (DVD4)**:
`travelSteps=0`, przyspieszenie 5000 kroków/s², `pitchRatio=1,0`, bez aktywnych
pasm częstotliwości. To tymczasowe parametry wykonawcze, nie pomiary nowych
silników ani potwierdzony bezpieczny zakres. Nie przenosimy hipotezy tunera 0,5
z DVD1–3 na nowe egzemplarze. Ustal ratio, prąd, temperaturę i swobodę obrotu
indywidualnie przed ruchem. Nie zmieniono generatora ani wygenerowanego pliku.

Fallback obejmuje **każdy odczyt tablic profili DVD**, także sprawdzenie pasm
w `sledFrequencyAllowed`. Indeksy sprzętowe 4/5 nigdy nie trafiają bezpośrednio
do czteroelementowych tablic. Runtime PROFILE DVD4 nie zmienia DVD5/6;
osobny PROFILE nowego kanału jest dopuszczony przy zatrzymaniu, tak jak dla DVD1–4.

Komendy `SLED 5/6 ENABLE`, `PROFILE`, `DIR`, `PLAY`, `STOP` używają istniejącej
rampy i zasad. ENABLE sam nie uruchamia ruchu. ALL STOP i watchdog obejmują
sześć DVD oraz cztery HDD na Q40–Q47. Czterokanałowy STRICT_TRACKS blokuje
PLAY wszystkich DVD. Status nowych kanałów pokazuje osobne **`DIAG SLED`**;
zwykłe STATUS nadal zawiera tylko DVD1–4 i ma 17 rekordów.

Host/registry, limity ID OrchestraLink, inventory, profile i aranżacja pozostają
przy czterech DVD. UI i Laboratory nie sterują DVD5–6. Ich automatyczna aranżacja
wymagałaby osobnego rozszerzenia kontraktu hosta po kwalifikacji fizycznej.
Nie obchodzimy tego przez wpisy JSON, fałszywe lane ani dodatkowe rekordy STATUS.

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
DVD4 1,0; DVD5–6 tymczasowo także 1,0 przez fallback DVD4, bez nowego pomiaru. Dla 200 Hz są to odpowiednio 400 lub 200 kroków/s.
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

## Mostki bez sterowania nSLEEP

Firmware nie ma `map::sleep`, `wake()` ani zastępczego wyjścia usypiania.
Moduły według użytkownika pracowały z niepodłączonym pinem, ale nie ustalono
ich wariantu i wewnętrznych połączeń. Ta obserwacja nie jest zweryfikowanym
zabezpieczeniem układów mocy. STOP sprowadza wejścia mostków do LOW (coast),
a nie odłącza VM. Przy flashowaniu i diagnostyce logiki wyłącz/odłącz moc
silników i sygnały do urządzeń. SR6 steruje HDD1–4; wszystkie 48 Q jest zajęte.
Brak sterowania nSLEEP nie jest zabezpieczeniem przed ruchem.

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
