> **Zapis badania, nie aktualna instrukcja.** Wyniki, liczby testów, UI,
> ścieżki i parametry dotyczą opisanego przebiegu. Polecenia mogą wymagać
> wskazanego commita i lokalnych MIDI; pliki w `/tmp` nie są trwałymi artefaktami.
> Obecne zasady: [indeks dokumentacji](../README.md).

# Universal — wyniki i odtwarzanie benchmarków

## Status weryfikacji: wyłącznie VIRTUAL i testy software

**BRAK TESTÓW TEGO PRESETU NA FIZYCZNYCH INSTRUMENTACH W REAL.**
Odsłuch dotyczy wyłącznie syntezy VIRTUAL. Użytkownik zgłosił pozytywny odsłuch
Let Down i No Surprises; Let Down nie należy do opisanego niżej benchmarku 31 MIDI.
Ocena odsłuchowa jest subiektywna i nie oznacza odsłuchania całego korpusu.

Testy automatyczne i benchmark sprawdzają plan oraz model mechaniczny offline.
Nie wykonano prób silników, pomiarów prądu/temperatury ani odsłuchu REAL w ramach
tej zmiany. Wspólny ExecutionTimeline nie potwierdza zgodności akustycznej,
wykonania fizycznego ani bezpieczeństwa pracy. Przed uznaniem presetu za
zweryfikowany w REAL potrzebne są osobne testy sprzętowe.


## Benchmark

Poniższe porównanie 31 MIDI opisuje pierwszą wersję Universal (`98bad14`).
Rozszerzenie o pełną bibliotekę i późniejszy etap odzyskiwania opisano dalej;
historycznego raportu nie nadpisujemy.

Zestaw obejmuje wszystkie 31 wskazanych MIDI. Manifest z nazwami i SHA-256:
[universal-corpus.json](../../reports/universal-corpus.json). Pełne metryki:
[universal-arrangement.json](../../reports/universal-arrangement.json).

```sh
.venv/bin/python scripts/benchmark_universal.py \
  --manifest reports/universal-corpus.json \
  --midi-dir /path/to/radiohead-midi --midi-dir /path/to/Downloads \
  --presets instrument_roles universal --workers 3
```

Oba warianty używają tego samego inventory i profili oraz oktawy FDD w dół;
różni się wyłącznie preset. Baseline to niezależne **FDD Riffs + DVD Tło**,
które zachowuje więcej źródłowych głosów niż warianty par. Wskaźniki nie są
oceną odsłuchu. Retencja dotyczy nut po wspólnej normalizacji; efekty nietonalne
nie trafiają do mianownika. Coverage długości jest przecięciem wykonania z
oryginalnym gate'em, więc dodatkowy sustain nie zawyża wyniku. Okno partii to
2 s z co najmniej jednym źródłowym NOTE_ON danej pary track/channel; zachowanie
jednej nuty w oknie nie oznacza odtworzenia całego jego wielogłosu.

W całym zestawie liczba pominiętych nut tonalnych spadła z **20392 do 5687**.
Zachowano **107793 → 122498** źródłowych nut tonalnych.
Poprawa liczby ataków dotyczy 29 utworów; pozostałe 2 zachowują tę samą liczbę.
Nie utracono żadnego wcześniej granego ID leadu/basu. Wszystkie 31 porównań
ma identyczne komendy perkusji, zero konfliktów, overlapów, naruszeń odstępu FDD
. Wszystkie 31 osi baseline zgadza się z kopią kodu sprzed zmiany.

| MIDI | Pominięte tonalne przed | Universal | Pokrycie długości przed → po | Najdłuższy DVD po (s) |
| --- | ---: | ---: | ---: | ---: |
| 0001-01-radiohead_1993-you.mid | 1451 | 958 | 63.1% → 70.6% | 24.809 |
| 0002-02-radiohead_1993-creep-[k].mid | 985 | 39 | 62.2% → 77.5% | 28.677 |
| 0005-05-radiohead_1993-thinking_about_you.mid | 1858 | 1090 | 44.0% → 60.7% | 18.459 |
| 0022-03-radiohead_1995-high_and_dry-[k].mid | 945 | 176 | 62.0% → 82.2% | 41.353 |
| 0023-04-radiohead_1995-fake_plastic_trees-[k].mid | 154 | 42 | 89.1% → 94.8% | 136.195 |
| 0024-05-radiohead_1995-bones.mid | 59 | 13 | 80.9% → 91.3% | 8.070 |
| 0025-06-radiohead_1995-(nice_dream)-[k].mid | 952 | 334 | 69.3% → 87.3% | 10.451 |
| 0026-07-radiohead_1995-just-[k].mid | 1726 | 537 | 60.1% → 77.8% | 19.145 |
| 0032-01-radiohead_1997-airbag-[k].mid | 800 | 10 | 71.7% → 82.3% | 36.057 |
| 0033-02-radiohead_1997-paranoid_android-[k].mid | 1126 | 227 | 64.7% → 84.5% | 48.375 |
| 0037-06-radiohead_1997-karma_police-[k].mid | 404 | 176 | 68.3% → 76.4% | 19.222 |
| 0038-07-radiohead_1997-fitter_happier.mid | 37 | 0 | 70.8% → 73.9% | 69.476 |
| 0041-10-radiohead_1997-no_surprises-[k].mid | 552 | 200 | 65.4% → 73.9% | 15.588 |
| 0042-11-radiohead_1997-lucky-[k].mid | 867 | 593 | 59.3% → 65.2% | 69.866 |
| 0045-02-radiohead_2000-kid_a.mid | 14 | 0 | 74.0% → 77.7% | 67.759 |
| 0046-03-radiohead_2000-the_national_anthem.mid | 2 | 0 | 94.1% → 98.5% | 79.336 |
| 0060-11-radiohead_2001-life_in_a_glass_house-[k].mid | 154 | 0 | 77.1% → 79.7% | 65.836 |
| 0062-08-radiohead_2001-true_love_waits_(live).mid | 920 | 104 | 64.4% → 83.5% | 18.177 |
| 0063-01-radiohead_2003-2+2=5-[k].mid | 1053 | 429 | 63.0% → 78.2% | 64.621 |
| 0064-02-radiohead_2003-sit_down_stand_up-[k].mid | 233 | 48 | 67.8% → 84.0% | 43.187 |
| 0068-06-radiohead-2003-where_i_end_and_you_begin.mid | 1489 | 89 | 56.3% → 70.0% | 90.274 |
| 0071-09-radiohead_2003-there_there-[k].mid | 336 | 186 | 73.1% → 89.5% | 51.217 |
| 0072-10-radiohead_2003-i_will.mid | 0 | 0 | 80.7% → 83.7% | 28.883 |
| 0079-01-radiohead_2007-15_step-[k].mid | 28 | 0 | 87.6% → 89.8% | 31.912 |
| 0080-02-radiohead_2007-bodysnatchers-[k].mid | 2675 | 103 | 65.2% → 90.1% | 16.974 |
| 0081-03-radiohead_2007-nude.mid | 163 | 25 | 61.2% → 68.6% | 42.710 |
| 0082-04-radiohead_2007-weird_fishes-arpegi.mid | 0 | 0 | 95.7% → 99.9% | 16.178 |
| 0083-05-radiohead_2007-all_i_need.mid | 15 | 1 | 72.6% → 73.9% | 23.997 |
| 0087-09-radiohead_2007-jigsaw_falling_into_place.mid | 394 | 137 | 66.9% → 74.7% | 22.587 |
| Avicii_Levels.mid | 552 | 20 | 71.6% → 82.7% | 38.091 |
| One_Republic_Counting_stars.mid | 448 | 150 | 65.4% → 63.3% | 38.811 |

Counting Stars pokazuje kompromis: więcej zachowanych ataków przy nieco mniejszym
pokryciu gate'ów. True Love Waits wymaga rozróżnienia niskiego basu od górnych
równoczesnych głosów partii oznaczonej jako bas; bez tej reguły globalna suma nut
maskowała utratę 16 wcześniejszych ID. Testy obejmują oba przypadki.

Najdłuższy ciągły okres DVD w zestawie to **136.195 s**
(0023-04-radiohead_1995-fake_plastic_trees-[k].mid). Jest to plan, nie zmierzony czas bezpiecznej pracy silnika.


## Pełna biblioteka — druga wersja

### Odtworzenie benchmarku biblioteki

Manifest [universal-library-corpus.json](../../reports/universal-library-corpus.json)
opisuje snapshot 316 ścieżek, 149 unikalnych plików i 659053 źródłowych nut.
Wszystkie pliki zostały poprawnie odczytane. Dodatkowe identyczne kopie nie
zwiększają liczby przykładów. Nie kopiujemy biblioteki MIDI do raportu.
Podział to 120 plików rozwojowych i 29 odłożonych do końcowej kontroli.
Znane wersje tej samej kompozycji i warianty o identycznej reprezentacji nut
trafiają do jednej grupy; wcześniejszy korpus 31 MIDI pozostaje rozwojowy.
Grupowanie nazw służy tylko organizacji eksperymentu, nie aranżacji utworu.

Baseline to Universal z `98bad14`, a nie starszy Instrument Roles. Oba przebiegi
mają identyczną konfigurację. Raport
[universal-library-arrangement.json](../../reports/universal-library-arrangement.json)
zawiera osobne wyniki każdego MIDI oraz obu części korpusu. Kontrola obejmuje
hash całej osi przed nowym etapem, niezmienność wcześniejszych zagranych
zdarzeń i ich sidecarów, reinforcement, perkusji i konfiguracji, brak utraty
wcześniej zachowanych ID basu/wokalu oraz końcową chronologię wszystkich urządzeń.

Nowa miara długości liczy sumę przedziałów primary + CONTINUATION w obrębie
oryginalnego gate'u każdego ID, bez podwójnego liczenia. Stara miara primary
pozostaje w raporcie. Średnie pokrycia są średnimi po utworach. STOP i ciągłą
pracę DVD liczymy ze skompilowanego ExecutionTimeline. Czasy planowania pochodzą
z równoległych przebiegów i nie są kontrolowanym pomiarem wydajności aplikacji.

```sh
# Inwentaryzacja lokalnej biblioteki; niczego nie modyfikuje w MIDI.
.venv/bin/python scripts/build_midi_corpus.py /path/to/Music/MIDI midi \
  --output /tmp/universal-inventory.json

# Zamrożony kod baseline, bez zmiany bieżącej gałęzi.
mkdir -p /tmp/orchestra-universal-before
git archive 98bad14 host config | tar -x -C /tmp/orchestra-universal-before

.venv/bin/python scripts/benchmark_universal.py \
  --manifest reports/universal-library-corpus.json \
  --midi-dir /path/to/Music/MIDI --midi-dir midi --presets universal \
  --code-root /tmp/orchestra-universal-before --workers 3 \
  --output /tmp/universal-library-before.json
.venv/bin/python scripts/benchmark_universal.py \
  --manifest reports/universal-library-corpus.json \
  --midi-dir /path/to/Music/MIDI --midi-dir midi --presets universal \
  --workers 3 --output /tmp/universal-library-after.json
.venv/bin/python scripts/compare_universal_library.py \
  --corpus reports/universal-library-corpus.json \
  --baseline /tmp/universal-library-before.json \
  --experiment /tmp/universal-library-after.json \
  --output /tmp/universal-library-comparison.json
```

Wyszukiwanie jest rekurencyjne i sprawdza SHA-256; kilka identycznych kopii
nie powoduje niejednoznaczności. Inny plik o tej samej nazwie nie zastąpi
przykładu z manifestu. Warianty przebadane na części odłożonej nie były potem
używane do strojenia tych heurystyk. Nadal nie jest to odsłuch ani niezależny
test wszystkich możliwych plików MIDI.

### Wyniki pełnego korpusu

| Metryka, 149 MIDI | Universal `98bad14` | Universal z odzyskiwaniem |
| --- | ---: | ---: |
| Zagrane źródłowe nuty tonalne | 428599 | 428620 |
| Pominięte źródłowe nuty tonalne | 17339 | 17318 |
| Średnie pokrycie źródłowych długości | 84,4084% | 84,6813% |
| Komendy DVD STOP | 40937 | 41546 |
| Łączny planowany czas DVD (s) | 93458,301 | 94097,483 |
| Najdłuższy ciągły odcinek DVD (s) | 366,997 | 366,997 |
| Konflikty / overlapy / naruszenia odstępu FDD | 0 | 0 |

**To poprawa przyrostowa, nie kolejny skok jak w porównaniu pierwszego Universal
z Instrument Roles.** 82 MIDI zyskały pokrycie długości; pozostałe 67 zachowały
wynik. Dodano 591 kontynuacji o łącznej długości 623,037 s i 21 późnych wejść
harmonii w 8 MIDI. Wszystkie odzyskane zdarzenia w tym korpusie były późnymi
wejściami DVD; wariant odzyskania dokładnego ataku nie znalazł dodatkowych
kandydatów przy tej konfiguracji. Zwiększenie liczby STOP o 609 wynika
z dodatkowych odcinków wykonania, a nie ze skrócenia istniejących nut.
Nie traktujemy tego rozszerzenia jako redukcji STOP.

W części odłożonej 21/29 MIDI zyskało pokrycie długości, a średnia wzrosła
z 82,4778% do 82,7630%. Dodano 97 kontynuacji (111,531 s) i 8 późnych wejść.
W obu częściach wszystkie kontrole przeszły: zero utraconych wcześniej granych
ID basu/wokalu, niezmienione wcześniejsze nuty, sidecary i reinforcement,
identyczna konfiguracja oraz perkusja. W tym przebiegu wszystkie dodatki
trafiły na DVD; komendy FDD i obu speakerów także pozostały identyczne.

| Przykład | Pokrycie przed → po | Kontynuacje DVD |
| --- | ---: | ---: |
| Rabbit in Your Headlights | 61,80% → 68,39% | 44 |
| How Do You | 73,82% → 76,54% | 18 |
| Counting Stars | 63,29% → 64,88% | 33 |
| No Surprises | 73,86% → 74,02% | 3 |
| Let Down (część odłożona) | 67,36% → 67,41% | 5 |
| Bodysnatchers | 90,14% → 90,20% | 1 |

Najdłuższy odcinek pozostaje w **Ful Stop: 366,997 s**, już obecny w baseline.
To około sześć minut planowanego ciągłego wykonania, nie potwierdzony bezpieczny
czas pracy. Testy obejmują 650 przypadków backendu, w tym niezmienność planu,
źródłowe granice, reartykulację, rezerwacje, rampę, CC/bend w późniejszej
kontynuacji, determinizm i izolację korpusu. Pełny benchmark przechodzi 149/149.
Nowy etap sprawdzono offline; wcześniejsze pozytywne odsłuchy Let Down i
No Surprises dotyczyły pierwszej wersji. **Brak weryfikacji nowego etapu na
fizycznych instrumentach REAL i brak pomiarów temperatury/prądu.**

## Ograniczenia fizyczne i muzyczne

Osiem silników i dwa monofoniczne speakery nie odtworzą bez strat dowolnej
polifonii. Priorytety mogą zmienić wybór konkretnych nut akordu, podział barw,
rejestr i gate'y. Nazwy/GM/lyrics są dowodami heurystycznymi, nie odsłuchem;
błędna klasyfikacja w źródle nadal może skierować niewłaściwą partię do wokalu.
Mniejsze dropy nie są dowodem lepszego brzmienia.

Najdłuższe ciągłe okresy DVD raportujemy ze skompilowanej osi. Ciągły obrót nie
potwierdza bezpiecznej pracy termicznej. Proponowane VM 3,3 V wymaga pomiarów
prądu i temperatury; przy 5 V obserwowano nadmierne grzanie. Testy nie uruchamiają
silników ani nie zastępują pomiarów fizycznego układu.

<a id="biblioteka-8-fdd-2026-10-21"></a>
## Biblioteka 8 FDD — 2026-10-21

Ten przebieg dotyczy aktualnej konfiguracji: **8 FDD jako dwie grupy unisono,
4 aktywne DVD, 4 HDD i 2 speakery**. DVD5–6 pozostają wyłączone. Nie należy
porównywać tych liczb bezpośrednio z historycznym benchmarkiem 149 MIDI powyżej:
zmieniły się biblioteka, skład oraz preset. W aktualnym folderze
`/Users/krzysztof/Music/MIDI` znaleziono rekurencyjnie **134 pliki / 134 różne
SHA-256**; każdy został przeliczony, także pliki poza `radiohead-midi`.
Nie kopiowano MIDI do repozytorium.

**Snapshot pomiarowy:** poniższe wyniki oraz raport wykorzystania DVD powstały
przy gate FDD 200 ms. Krótki późniejszy eksperyment ze 100 ms został wycofany;
bieżące ustawienie ponownie wynosi 200 ms. Pełnego korpusu nie przeliczano
dla 100 ms.

Baseline to lokalne `main` **`ce6b2b3`**. Oba przebiegi używają tego samego
`instrument_roles_unison4`, tych samych aktywnych urządzeń, profili, transpozycji
FDD −12 / 100–205 Hz oraz stałego gate 200 ms. Zapisane ustawienia głośności
użytkownika są izolowane. Nowy algorytm nie zawiera nazw ani hashy utworów
w regułach. Ten korpus służył do analizy i regresji; nie stanowi niezależnego
holdoutu ani odsłuchu VIRTUAL/REAL.

### Co zmieniono

- Dwie logiczne rezerwacje FDD już podczas alokacji Universal, zamiast ośmiu
  niezależnych głosów redukowanych później. Wspólny gate oraz odstęp ataków
  obowiązują przed wyborem kandydatów. Każda fizyczna kopia nadal przechodzi
  walidację, a wyłączone urządzenia nie są samoczynnie aktywowane.
- Grupy preferują różne partie, lecz mogą zagrać dwa istniejące głosy jednej
  partii. Nie dublują tej samej źródłowej nuty między grupami. Wewnątrz grupy
  wszystkie komendy pozostają zgodne.
- Rezerwy wokalu/FX, pierwszeństwo długiego tła nad krótkimi dodatkami akordu,
  ochrona trzymanego DVD przed krótką harmonią i kontrola kosztu rampy.
  Recovery odzyskuje wolne okna DVD/speakerów bez niezależnych nut na FDD.
- HDD preferują stałe role rytmiczne i zachowują stopę/werbel przed dodatkowymi
  równoczesnymi uderzeniami. Mogą pożyczać wolny kanał. Energia impulsów,
  mechanika i limity firmware pozostają bez zmian.
- Indeks rezerwacji DVD i wyznaczanie najbliższego sąsiada HDD po sortowaniu
  zastępują powtarzane skanowanie całego planu. Optymalizacja nie ma prawa
  zmieniać skompilowanych komend. Osobny pełny przebieg z indeksem DVD
  potwierdził identyczne fingerprinty ExecutionTimeline oraz wszystkie metryki
  muzyczne dla 134/134 MIDI; różnią się wyłącznie czasy obliczeń.

### Wyniki

| Metryka, 134 MIDI | Baseline | Nowa wersja |
| --- | ---: | ---: |
| Zagrane źródłowe nuty tonalne | 201709 | 320851 |
| Pominięte źródłowe nuty tonalne | 203819 | 84677 |
| Średnie pokrycie długości głosów źródłowych | 62,3016% | 75,8681% |
| Średnie pokrycie ataków sklasyfikowanego leadu | 97,8034% | 100,0000% |
| Średnie pokrycie ataków sklasyfikowanego basu | 72,2867% | 85,3740% |
| Okna aktywnej partii bez zachowanego ataku | 3175 | 540 |
| Źródłowe uderzenia HDD | 171466 | 171433 |
| Komendy DVD STOP z ExecutionTimeline | 30108 | 45689 |
| Łączny planowany czas DVD (s) | 77122,261 | 92090,117 |
| Najdłuższy ciągły odcinek DVD (s) | 283,405 | 366,997 |
| Konflikty / overlapy / naruszenia ataków FDD | 0 | 0 |
| Niezgodne grupy unisono w nowym ExecutionTimeline | — | 0 |

Pokrycie długości sumuje unię primary i kontynuacji wewnątrz oryginalnego gate,
bez zawyżania przez sustain poza NOTE_OFF ani fizyczne kopie unisono. Średnie
w tabeli są średnimi po plikach. Okna partii to 2 s na track/channel, z głosem
oddawanym przez źródłowe ataki; nie mierzą pełnej polifonii. Lead/bass oznacza
wynik heurystycznej klasyfikacji, nie potwierdzony odsłuchem wokal/bas.

**134/134 MIDI zyskały pokrycie długości, 127 zyskało liczbę ataków, 6 zachowało
liczbę, jedno straciło część ataków.** Nie ma regresji pokrycia leadu.
Mimo wzrostu średniej, pokrycie ataków basu spadło w 11 plikach; lista jest
w raporcie porównawczym. To jawne kompromisy przy dwóch logicznych FDD,
a nie dowód idealnego odtworzenia każdej linii.

| MIDI | Źródłowe nuty przed → po | Pokrycie długości przed → po |
| --- | ---: | ---: |
| Bodysnatchers | 1743 → 4033 | 43,34% → 74,85% |
| No Surprises | 1851 → 3046 | 46,12% → 58,29% |
| Let Down | 2907 → 3851 | 46,21% → 57,28% |
| Counting Stars | 2689 → 3554 | 57,10% → 62,44% |
| Every Breath You Take | 2051 → 2374 | 75,88% → 80,60% |
| Pyramid Song | 1786 → 1712 | 66,67% → 68,18% |

W Pyramid Song spada liczba ataków sklasyfikowanego basu (1435 → 1351),
a rośnie lead (202 → 208) i harmonia (149 → 153). Dłuższe zachowane głosy
podnoszą pokrycie czasu, ale odsłuch musi ocenić koszt utraconych ataków.
Nie wybieramy osobnego algorytmu na podstawie nazwy utworu.

HDD tracą netto 33 uderzenia na 171466; inny wybór jednoczesnych uderzeń
może zmienić reset i dostępność następnego kanału. Spadki występują w
Paranoid Android (24), Climbing Up the Walls (1) i Talk Show Host (25),
częściowo równoważone odzyskanymi uderzeniami w innych plikach. Priorytety
rytmu nie znoszą fizycznej zajętości ani nie podnoszą limitów.

**To nie jest optymalizacja samej liczby STOP.** W Bodysnatchers DVD wykonują
1923 nuty zamiast 205; STOP rośnie 126 → 1093, czas pracy 320,321 → 693,452 s,
a najdłuższy ciągły odcinek 17,137 → 22,851 s. Więcej reprezentowanych
rytmicznych głosów oznacza więcej reartykulacji. Nie wydłużamy ich wszystkich
bezwarunkowo. Najdłuższe 366,997 s w całym korpusie przypada na Ful Stop;
nie jest to zmierzony bezpieczny czas pracy silnika ani kwalifikacja VM 3,3 V.

### Artefakty i odtworzenie

- [Baseline: pełne metryki i hashe MIDI](../../reports/library-8fdd-baseline.json)
- [Nowa wersja: pełne metryki i hashe MIDI](../../reports/library-8fdd-experiment.json)
- [Porównanie, listy regresji i kontrole](../../reports/library-8fdd-comparison.json)
- [Runner biblioteki](../../scripts/benchmark_orchestra_library.py)
  i [komparator](../../scripts/compare_orchestra_library.py)

```sh
mkdir -p /tmp/orchestra-arranger-baseline
git archive ce6b2b3 | tar -x -C /tmp/orchestra-arranger-baseline
.venv/bin/python scripts/benchmark_orchestra_library.py \
  --midi-root /Users/krzysztof/Music/MIDI \
  --code-root /tmp/orchestra-arranger-baseline --output /tmp/library-before.json
.venv/bin/python scripts/benchmark_orchestra_library.py \
  --midi-root /Users/krzysztof/Music/MIDI --output /tmp/library-after.json
.venv/bin/python scripts/compare_orchestra_library.py \
  --baseline /tmp/library-before.json --experiment /tmp/library-after.json \
  --output /tmp/library-comparison.json
```

Komparator wymaga kompletnego, identycznego zestawu ścieżek i SHA-256,
identycznej konfiguracji oraz zera konfliktów, nakładania i naruszeń FDD.
`planningSeconds` obejmuje parsowanie, aranżację, kompilację i dodatkowy audyt
benchmarku; nie jest pomiarem samego ładowania w przeglądarce. Porównywanie
czasów przy różnym obciążeniu komputera nie daje gwarancji opóźnienia UI.
Testy obejmują 757 przypadków Python/C++ oraz 120 frontendowych; build Web
przechodzi. Nową aranżację zweryfikowano offline, bez uruchamiania ATX,
silników i bez flashowania firmware. Odsłuch oraz pomiary termiczne pozostają
osobną weryfikacją.
