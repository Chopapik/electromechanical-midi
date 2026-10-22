# Urządzenia, ograniczenia i kalibracja

Firmware i host obsługują **18 urządzeń: 8 FDD / 4 DVD / 4 HDD / 2 speakery**,
6 rejestrów i 6 wykorzystywanych DRV8833 (oznaczenia DRV1–4 i DRV7–8).
Wszystkie wpisy są aktywne w planowaniu, VIRTUAL i REAL.
FDD5–8 są zadeklarowane jako podłączone. Q32–Q39 pozostają wolne;
HDD zachowują Q40–Q47, bez zmiany istniejącego okablowania.
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
| FDD5–8 | `fdd-5`…`fdd-8`, `fdd:5`…`fdd:8` | Aktywne w aranżacji, VIRTUAL i REAL; parametry wykonawcze z fallbacku firmware |
| DVD1–4 | `DVD_STEPPER_1`…`DVD_STEPPER_4`, `sled:1`…`sled:4` | DRV8833, dwie cewki, pełny krok, ciągły obrót |
| PC Speaker | `vhs-1`, `drum:1` | GPIO25, główny wokal/lead |
| PC Speaker FX | `pc-speaker-fx`, `drum:2` | GPIO26, tonalne ozdobniki i rezerwa zależna od presetu |
| HDD1–4 | `hdd_vcm-1`…`hdd_vcm-4`, `hdd:1`…`hdd:4` | DRV8833, perkusyjny HIT |

Aktywne jest wszystkich 18 wpisów.
FDD5–8 mają `enabled:true`, `realEnabled:true` i `present:true`. `enabled` oznacza udział
w aranżacji i VIRTUAL, `realEnabled` dopuszczenie transportu REAL, a `present`
w metadanych profili
obecność zadeklarowaną na podstawie potwierdzenia fizycznego, bez automatycznej
detekcji przewodów ani sprawności. Parametry
wykonawcze 72/5/2439 są oznaczone jako niskiej pewności fallback firmware,
a nie indywidualne pomiary. Sam profil
nie kwalifikuje urządzenia. Włączenie wpisu nie zastępuje procedury pomiarowej.
Ordynał lane jest fizycznym kanałem; pozycje wyłączone też zajmują swój numer.
Typ `VHS` oraz komendy `VHS`/`VHS2` zachowano dla zgodności obu speakerów.
HDD mają profil brzmienia `WD_CAVIAR_CURRENT`, ale fizyczny
`hardwareProfile: HDD_PERCUSSION`; nie ma wykonawcy tonalnego HDD w tym zestawie.

## FDD5–8: adresacja i obsługa

| Kanał | TRACK0 | STEP / DIR | Stan po boot |
| --- | ---: | --- | --- |
| FDD5 | GPIO32 | Q8 / Q9 | Wyłączony, bez HOME |
| FDD6 | GPIO33 | Q10 / Q11 | Wyłączony, bez HOME |
| FDD7 | GPIO16 | Q12 / Q13 | Wyłączony, bez HOME |
| FDD8 | GPIO17 | Q14 / Q15 | Wyłączony, bez HOME |

FDD5–8 są zadeklarowane jako podłączone. Profil i potwierdzenie programowe
nie zastępują indywidualnego sprawdzenia połączeń, napięć i propagacji sygnałów.

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

[Registry](../host/runtime/registry.py), inventory i [OrchestraLink](../host/orchestra_link.py)
znają osiem kanałów FDD. Host wysyła FDD5–8 PROFILE/ENABLE, atomowo scala
`DIAG FDD`, wykonuje potwierdzony homing TRACK0 i dopiero potem dopuszcza PLAY.
[STRICT_TRACKS](../host/playback/strict_tracks.py) nadal ma cztery sloty.
Normalny STATUS nie zawiera dodatkowych FDD; host używa dla nich osobnej,
ograniczonej transakcji `DIAG FDD`. Domyślny preset aranżuje dwie grupy 4× FDD.

## DVD: cztery kanały i profile

Cztery wpisy `sled:1`…`sled:4` odpowiadają wyjściom Q16–Q31 i modułom DRV1–4.
Każdy używa własnego wpisu czteroelementowych tablic wygenerowanych profili.
Nie ma dodatkowych kanałów ani fallbacku parametrów DVD. ENABLE nie rozpoczyna
ruchu; PLAY, DIR, PROFILE i STOP zachowują dotychczasowe zasady. Identyfikatory
poza zakresem 1–4 są odrzucane przez host i firmware.

Zwykły STATUS raportuje wszystkie cztery DVD i zachowuje 17 rekordów.
ALL STOP oraz watchdog zatrzymują całą czwórkę i zerują wolne Q32–Q39.
Kaskada pozostaje sześciobajtowa, a HDD zachowują Q40–Q47.

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
| Ataki nut | Minimum 203 ms między zachowanymi NOTE_ON na stację; ton trwa 200 ms | Globalny eksperyment muzyczny z przerwą 3 ms, niezależny od częstotliwości STEP |

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
Po utracie odniesienia wymagany jest HOME; licznik nie jest enkoderem.
Play w REAL automatycznie kalibruje potrzebne, niewyciszone FDD bez `homed=1`
przed uruchomieniem zegara utworu. STOP może przerwać oczekiwanie. Błąd homingu
blokuje start muzyki. Ręczny HOME w Settings pozostaje dostępny; Laboratory wykonuje HOME wybranej FDD automatycznie przed testem.
Wartości wspólne czterem stacjom nie oznaczają indywidualnej kalibracji każdej.
Długie gate'y i powroty karetki nadal mogą wpływać na brzmienie.

## DVD stepper

W aktywnym trybie ciągłym `travelSteps=0`, bez limitu drogi i bez whitelisty
pasm. `−1` oznacza nieznany profil, nie ciągły obrót. Aranżacja ma niezależny
sufit **600 Hz akustycznych**, składając wyższe nuty o oktawy. Lab nie stosuje
tego foldingu i nie daje przez to uprawnienia do dowolnie wysokich testów.

`pitchRatio = acousticHz / stepsPerSecond`: DVD1–3 mają 0,5 (hipoteza tunera),
DVD4 ma osobną korekcję 0,5 z odczytu użytkownika 440 → około 220 Hz
przy poprzednim ratio 1,0 (2026-10-19, HYPOTHESIS/LOW).
Dla 440 Hz DVD1–4 otrzymują 880 kroków/s.
Różny silnik DVD1 nadal wymaga osobnego sprawdzenia; wspólne ratio nie dowodzi
jego poprawnego strojenia.
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
Użytkownik zgłasza poprawną pracę przy **VM 5 V i dobrym odprowadzaniu ciepła**,
np. do metalowej obudowy VHS, która jest również pudłem rezonansowym.
Nie określono zmierzonego prądu, temperatury ani limitu ciągłej pracy.
Warunki montażu i zasilania:
[schemat zasilania](HARDWARE_WIRING.md#zasilanie).

## HDD VCM

Aktualnie zgłoszone zasilanie to **VM 5 V z dobrym odprowadzaniem ciepła**,
np. przez metalową obudowę VHS. Użytkownik opisuje poprawną pracę tego montażu;
prąd i temperatura obecnych cewek wymagają pomiarów.

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

Główny speaker ma `transpose: 0`, FX również `0`, przed foldingiem profilu.
Główny kanał obniżono o oktawę względem wcześniejszego `+12`; FX pozostaje bez zmian.
Profil hosta `VHS` dopuszcza 20–2000 Hz; protokół przyjmuje pulse do 20 kHz.
Granice protokołu nie są pomiarem akustycznym. GPIO25 i GPIO26 są sterowane
sprzętowym LEDC, kanały 0 i 2 mają osobne timery. Nie ma programowego generatora
próbek ani callbacku audio 20 kHz. Dostępny jest wyłącznie prostokąt / impuls.

`/settings` → **Brzmienie PC Speaker**: osobny gain VIRTUAL i modulacja
wypełnienia prostokąta, wspólna dla REAL/VIRTUAL, dla każdego speakera.
Oba suwaki mają skalę 0–100%. Modulacja mapuje ją na `realAmplitude` 0–128;
nie podnosi dotychczasowego maksimum. 100% nastawy oznacza przewodzenie przez
50% okresu (symetryczny kwadrat). Niższe wypełnienie zmienia barwę i poziom,
nie jest niezależną regulacją głośności REAL. Wypełnienie = `AMP/256` czasu
przewodzenia PNP (LOW na GPIO); **AMP 50 = 19,53125%**, nie 50% głośności.

Przy modulacji 0% host wysyła STOP dla danego speakera zamiast kolejnych tonów;
podniesienie poziomu w trwającej nucie przywraca jej aktualną częstotliwość.
VIRTUAL 0% wycisza aktywne i zaplanowane głosy natychmiast. Jego gain 0–2,5
jest oddzielny od wypełnienia (dawny gain 1 odpowiada 40% nowej skali).
Zapisane wcześniej inne fale są przy odczycie ustawień zastępowane `pulse`,
z zachowaniem poziomów obu kanałów. API odrzuca inne przebiegi.

Pulse VIRTUAL to pasmoograniczony szereg 64 harmonicznych. REAL to odwrócony
PWM dla S8550 PNP; HIGH wyłącza tranzystor. Boot, STOP, watchdog i POWER OFF
wyłączają oba kanały. Nie ma timera audio ani mutexu do próbek.
Obsługa drugiego kanału wymaga `speaker_fx=1`. STATUS zachowuje pole
`speaker_waves=0`; zgodnościowa komenda WAVE przyjmuje tylko `pulse`.
Połączenia i ograniczenia sprzętowe: [dwa speakery](HARDWARE_WIRING.md#dwa-pc-speakery).

## Mostki bez sterowania nSLEEP

Firmware nie ma `map::sleep`, `wake()` ani zastępczego wyjścia usypiania.
Moduły według użytkownika pracowały z niepodłączonym pinem, ale nie ustalono
ich wariantu i wewnętrznych połączeń. Ta obserwacja nie jest zweryfikowanym
zabezpieczeniem układów mocy. STOP sprowadza wejścia mostków do LOW (coast),
a nie odłącza VM. Przy flashowaniu i diagnostyce logiki wyłącz/odłącz moc
silników i sygnały do urządzeń. SR6 steruje HDD1–4; Q32–Q39 na SR5 są wolne.
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

## ATX: zakres potwierdzenia

GPIO19 steruje PS_ON# przez osobny S8050; [połączenia i domeny zasilania](HARDWARE_WIRING.md#sterowanie-atx-przez-ps_on).
ON/OFF są wyłącznie stanami logicznymi. Bez PWR_OK/ADC nie potwierdzamy napięć,
rozładowania, poprawnego startu szyn ani bezpieczeństwa termicznego silników.
Firmware domyślnie OFF, blokuje ruch przy OFF i unieważnia HOME po wyłączeniu.
ALL STOP/watchdog nie wyłączają zasilacza. Opóźnienia 100 ms po ON i 1 s po OFF
są roboczą polityką programową, bez kwalifikacji elektrycznej tej instalacji.
