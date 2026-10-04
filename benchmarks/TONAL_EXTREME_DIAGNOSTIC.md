# TONAL EXTREME — diagnostyka końcowego toru audio

## Zakres

Trzeci, tymczasowy tryb TONAL EXTREME jest dostępny w ORCHESTRA → Tonal sound.
To celowo przesadzona diagnostyka, bez strojenia docelowego brzmienia.
EXTREME nadpisuje tylko gotową decyzję tonalnej artykulacji PLUCKED w ostatnim
passie przygotowania audio. CONTINUOUS pozostaje bez zmian.

Nie zmieniono kodu allocatora, PerformancePlan, routingu, source/actual timestamps,
fizycznych rezerwacji ani reguł reinforcement. Zrzut całego planu (także extras)
jest identyczny przed i po każdym z trzech renderów. PRIMARY Creep pozostaje
4525 played / 0 dropped. Zmiana długości ogona audio może uruchomić istniejące
reguły retrigger/suppress extras, ale nie zmienia ich logiki ani planu.

## EXTREME

Dla zwykłych PLUCKED notes:
- attack 25–40 ms (zależny od velocity),
- decay 250–350 ms, liczony diagnostycznie jako czas spadku do około 2% różnicy
  między peak a sustain — w wykładniku używany jest decay/4,
- sustain 10–20%,
- release 300–500 ms,
- velocity silnie i nieliniowo zmienia mechanical transient i brightness,
- wyraźny burst mechaniczny wokół szczytu attack; nie sample gitary.

Dla gate krótszego od 120 ms czasy są skalowane, a release ograniczony do połowy
gate. Nowy PRIMARY nadal ucina poprzedni ogon przez istniejący fade 6 ms.
RAW oraz ARTICULATED zachowują dotychczasową matematykę. Ich końcowe WAV-y bez
wspólnego diagnostycznego wzmocnienia są bitowo identyczne z zapisami wykonanymi
przed dodaniem EXTREME.

## Solo Guitar 1 offline

Plik źródłowy: `0002-02-radiohead_1993-creep-[k] (2).mid`.
Wszystkie trzy WAV-y obejmują dokładnie 0–60 s oryginalnej osi czasu i te same
155 normalnych tonalnych zdarzeń Guitar 1.

Najpierw wykonywana jest normalna alokacja całej orkiestry i pełny scheduling
per actuator. Dopiero po tym filtrowane są wiersze audio Guitar 1. Nie ma ponownej
alokacji ani oddawania mu czasu zarezerwowanego dla innych tracków.
W odsłuchu nie ma HDD, innych gitar, basu, perkusji, VHS, reversal noise ani
jakiegokolwiek reinforcement (także Guitar 1). To świadomy, węższy izolowany test.

Wspólny mixCount=1, zachowane device volume i pan, identyczny gain ×4 dla każdego
pliku. Brak normalizacji peak/RMS/LUFS i brak adaptacyjnego limitera. Analiza
używa odczytanych z plików końcowych stereo próbek PCM16, nie tylko parametrów
ani floatowego bufora sprzed zapisu. Częstotliwość próbkowania: 22050 Hz.

## Wyniki końcowego PCM

| Tryb | Nuty | RMS PCM | Peak PCM | Średni attack / decay / release ms | Ucięte ogony |
|---|---:|---:|---:|---|---:|
| RAW | 155 | 0.012294 | 0.147008 | 1.00 / 0.00 / 2.00 | 1 |
| ARTICULATED | 155 | 0.007587 | 0.137700 | 3.55 / 79.38 / 45.00 | 1 |
| EXTREME | 155 | 0.009553 | 0.161504 | 29.70 / 281.36 / 437.28 | 67 |

Wszystkie pliki mają 0 przesterowanych próbek. Ucięte ogony wynikają z istniejących
kolejnych PRIMARY na tym samym actuatorze lub końca 60-sekundowego okna. Zostają
zachowane całe normalne gate'y, source IDs i onsety.

| Porównanie | RMS różnicy / RMS RAW | Korelacja PCM | Reszta po dopasowaniu jednej stałej głośności / RMS RAW | Zmienione próbki |
|---|---:|---:|---:|---:|
| raw_vs_articulated | 46.03% | 0.9439 | 19.81% | 897334 / 2646000 |
| raw_vs_extreme | 79.47% | 0.6105 | 60.62% | 1375602 / 2646000 |

Wniosek techniczny: **artykulacja dociera do finalnego PCM/WAV.** EXTREME nie jest
ani identycznym RAW, ani RAW pomnożonym przez jedną inną głośność. Nie wykryto
spłaszczenia obwiedni w sprawdzanym rendererze, miksie i zapisie WAV. To nie jest
subiektywne potwierdzenie odsłuchu na konkretnych głośnikach ani test DSP systemu
operacyjnego. Normalny tor aplikacji zapisuje te same próbki i odtwarza je afplay;
after-write nie ma normalizacji, afplay otrzymuje jedynie Master Volume.

## Weryfikacja cache działającej aplikacji

Dla Creep w wybranym w UI trybie EXTREME skopiowano rzeczywisty WAV workera.
Ponowny render z pełną bieżącą konfiguracją urządzeń dał bitowo identyczny plik:
9 927 098 próbek stereo PCM16, 0 różniących się próbek. SHA-256:
`f53d010f4d8e3bd2c2a5490a5dbf8a35b9048f6874bd0706aa17ae2ac2d3bca6`.
To obejmuje przełącznik, konfigurację, renderer i cache aplikacji. Pierwsze
porównanie używało skróconej listy urządzeń z `/api/orchestra`, bez volume/profili;
poprawne porównanie używa pełnych urządzeń z konfiguracji virtual.

## Pojedyncza nuta z tego samego MIDI

Wybrano normalną nutę `1:57`, FDD, velocity 96, onset 23.478192 s. Source duration
2.589666 s; istniejący performed gate tylko 190 ms.

| Tryb | Gate ms | Rzeczywisty czas audio ms | RMS pierwszych 10 ms | RMS 80–120 ms | RMS 100–150 ms po gate |
|---|---:|---:|---:|---:|---:|
| RAW | 190.00 | 191.97 | 0.008761 | 0.018821 | 0.000000 |
| ARTICULATED | 190.00 | 234.97 | 0.008583 | 0.009898 | 0.000000 |
| EXTREME | 190.00 | 641.18 | 0.000354 | 0.008693 | 0.001164 |

EXTREME ma attack 28.66 ms, decay 274.41 ms, sustain 17.56%, release 451.18 ms.
Na wykresie rzeczywisty PCM pokazuje narastanie, silny burst przy szczycie attack,
spadek i długi cichy ogon. RAW ma prosty gate zakończony około 192 ms; ART kończy
się około 235 ms; EXTREME około 641 ms.

## Dlaczego zwykłe A/B może być mało czytelne

To hipotezy wspierane kodem/miarami, nie ocena odsłuchowa:
- source Guitar 1 ma medianę około 633 ms, ale istniejący allocator skraca medianę
  performedDuration do 190 ms; obwiednia ma mniej czasu na rozwinięcie,
- regularny attack około 3.55 ms jest bardzo krótki wobec impulsów steppera,
- brzmienie bazowe i source CC/frequency curves są celowo takie same w RAW i ART,
- pełna orkiestra może maskować decay oraz krótkie ogony Guitar 1,
- następne PRIMARY mogą legalnie skrócić release na tym samym actuatorze.

Żaden z tych parametrów nie został teraz dostrojony. Dalszy odsłuch diagnostyczny
powinien zacząć się od izolowanych trzech WAV-ów, nie pełnej orkiestry.

## Odtwarzanie / powtórzenie testu

WAV-y:
- `/tmp/tonal-extreme/creep-guitar1-raw.wav`
- `/tmp/tonal-extreme/creep-guitar1-articulated.wav`
- `/tmp/tonal-extreme/creep-guitar1-extreme.wav`

Render: `.venv/bin/python scripts/diagnose_tonal_extreme.py`.
Opcjonalny `--baseline-dir /tmp` porównuje RAW/ART z lokalnymi wcześniejszymi
snapshotami; bez niego skrypt nadal weryfikuje plan, IDs, onsety i końcowy PCM.
Wykres: `scripts/plot_tonal_extreme.py` wymaga opcjonalnego Matplotlib.
Biblioteka do tego jednorazowego wykresu została zainstalowana tylko w
`/tmp/tonal-plot-deps`; zależności aplikacji pozostały bez zmian.

## Testy i pliki

393 testy backendu, 71 frontendowych, typecheck i build: PASS. Dodatkowe testy
sprawdzają EXTREME PLUCKED, nieliniową velocity, niezmieniony CONTINUOUS,
krótkie nuty, mono retrigger, pełną niezmienność planu, końcowy WAV przez
WavePreview.render (ten sam entry point co worker aplikacji), istotną różnicę
po usunięciu stałego gainu, ogon po NOTE_OFF i zgodność Python/NumPy.
Selector test obejmuje wysłanie extreme przy zachowanym HDD/routingu.

Zmiany: tonal_articulation.py, virtual.py, test_tonal_articulation.py,
VirtualOrchestra.tsx, VirtualOrchestra.test.tsx, types.ts; nowe skrypty
`diagnose_tonal_extreme.py`, `plot_tonal_extreme.py`, JSON, ten raport oraz PNG.
Brak zmian allocatora/PerformancePlan/engine/reinforcement. Brak commita.

## Kolejna poprawka: sztuczne stukanie FDD

Po powyższym pomiarze wyłączono w WavePreview._plan dodatkowy syntetyczny
stuk 1700 Hz generowany przez zdarzenia reversal. Zdarzenia mechaniczne i licznik
zmian kierunku pozostają zachowane. Dotyczy to wszystkich trybów tonalnych.
WAV-y solo i powyższe pomiary nadal są aktualne, bo diagnostyka solo już pomijała
reversal noise. Weryfikacja cache pełnej orkiestry powyżej dotyczy wersji przed
wyłączeniem stuków. Test PCM potwierdza, że obecny podgląd pojedynczego FDD jest
identyczny z renderem tych samych nut bez zdarzeń reversal. Po tej poprawce
13 testów virtual i 21 tonal articulation: PASS.
