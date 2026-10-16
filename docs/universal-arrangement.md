# Universal — adaptacyjna aranżacja fraz

Wybór: **Settings → Aranżacja → Preset aranżacji → Universal · adaptacyjny**
(`universal`). Zmiana potwierdza STOP i przebudowuje wspólny ExecutionTimeline,
bez autoplay. Domyślne `balanced` w JSON i dotychczasowe presety są zachowane.

Preset używa czterech FDD, czterech DVD, PC Speaker, PC Speaker FX i perkusyjnych
HDD zgodnie z zadeklarowaną dostępnością. Obie tacki są jawnie wykluczone.
Nie ma specjalnych reguł dla nazw utworów ani generowanych nut harmonii.

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

## Decyzje muzyczne

- Lokalny kontekst śledzi niepokrywające się głosy w obrębie track/channel.
  Ruchomy riff nie zmienia stabilnego dolnego głosu w „szybki riff”.
- Na wspólnym ataku lead i bas mają priorytet. W obrębie roli pierwsze tony
  poszczególnych partii poprzedzają kolejne tony ich akordów. Preferowane są
  skrajne głosy, dłuższe warstwy i velocity; nie wszystkie dźwięki jednego
  wielkiego akordu muszą wypchnąć inną partię.
- Przed wyborem FDD kandydat uwzględnia najwcześniejszy dozwolony kolejny atak
  (domyślnie 120 ms). Zajęta stacja nie wygrywa nuty, którą dopiero końcowy pass
  musiałby usunąć. Inny FDD, DVD lub dozwolony speaker może przejąć źródłowy atak.
  Pozostają istniejące okna mikroopóźnień; nuty nie trafiają do bezterminowej kolejki.
- FDD zachowuje eksperyment oktawy w dół, gate do 400 ms oraz ograniczenie przed
  kolejnym atakiem tego samego głosu. DVD preferuje długi sustain; jego gate nie
  jest ograniczany globalnym budżetem krótkich akompaniamentów.
- Wokal preferuje główny speaker. Nakładające się gate'y legato kończą się na
  następnym ataku źródłowej partii, zamiast powodować pominięcie kolejnej sylaby.
  Dodatkowy równoczesny głos może użyć FX lub silników.
- Źródłowe ataki wokalu i rozpoznanych FX rezerwują oba speakery także przed
  przyszłym wejściem. Krótkie, wyższe partie melodyczne mogą korzystać z wolnego
  speakera poza rezerwacjami; nie dotyczy to niskiego basu ani długich padów.
  Jeśli track sklasyfikowany jako bas zawiera równoczesne głosy akordu, górny
  ton co najmniej oktawę ponad aktywnym dolnym głosem może użyć FX (od MIDI 55).
  Sama sekwencyjna zmiana rejestru monofonicznego basu nie spełnia tej reguły.
- Preferencja ostatniego urządzenia dla głosu i koszt przesunięcia oktawowego
  ograniczają przerzucanie barwy oraz niepotrzebne składanie rejestru. Koszt
  oktawy liczy się po jawnej transpozycji urządzenia (główny speaker +12,
  FDD −12). Zmiany oktaw wynikające z zakresów nadal są możliwe.

Klasyfikacja GM/lyrics i normalizacja duplikatów są wspólne. Jawne efekty szumowe
pozostają pominięte. Perkusja zachowuje dotychczasową kolejność i komendy HIT.
Opcjonalny dowolny UNISON FDD jest wyłączony na rzecz niezależnych głosów.

## Artykulacja i wykonanie

Universal korzysta z istniejącego sustainu tła Instrument Roles: chronione
mostkowanie DVD do 350 ms, po dynamicznym passie do 200 ms. Pauzy, niezależne
partie, akcenty powtórzeń, skrócone gate'y i obce rezerwacje mogą je zablokować.
Każda zmiana przechodzi pełną chronologię mechaniczną.

Sufit DVD 600 Hz akustycznych, pitchRatio, przyspieszenie firmware, limity STEP,
TRACK0, potwierdzany STOP i watchdog są zachowane. Końcowy wspólny pass FDD jest
nadal aktywny jako zabezpieczenie planu. REAL i VIRTUAL nie aranżują oddzielnie.
`plan.hardware.universal` opisuje trasy, odroczonych kandydatów ataku FDD i
fallbacki; są to decyzje planowania, nie pomiar ruchu lub dźwięku.

## Benchmark

Poniższe porównanie 31 MIDI opisuje pierwszą wersję Universal (`98bad14`).
Rozszerzenie o pełną bibliotekę i późniejszy etap odzyskiwania opisano dalej;
historycznego raportu nie nadpisujemy.

Zestaw obejmuje wszystkie 31 wskazanych MIDI. Manifest z nazwami i SHA-256:
[universal-corpus.json](../reports/universal-corpus.json). Pełne metryki:
[universal-arrangement.json](../reports/universal-arrangement.json).

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
i komend tacek. Wszystkie 31 osi baseline zgadza się z kopią kodu sprzed zmiany.

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

## Rozszerzenie na pełną bibliotekę MIDI

Istniejący preset `universal` otrzymał końcowy etap
`host/playback/universal_recovery.py`, po wspólnym ograniczeniu ataków FDD.
Wcześniej zagrane zdarzenia, ich urządzenia, wysokości, gate'y, artykulacje
i istniejące reinforcement pozostają identyczne. Pozostałe presety nie używają
tego etapu. Firmware i konfiguracja sprzętu pozostają bez zmian.

Etap działa wyłącznie w rzeczywiście wolnych rezerwacjach:

- Pominięta nuta tonalna może odzyskać oryginalny atak, jeśli cały przebieg
  urządzenia pozostaje wykonalny. Używa tego samego doboru ról i rezerwacji
  wokalu/FX co pierwsza alokacja. Nie przesuwa wcześniejszych nut.
- Pominięte, długie tło harmoniczne może wejść później na DVD: najwyżej
  pół beatu i nie więcej niż 350 ms od źródłowego ataku, przy dodatniej
  lokalnej skłonności do sustainu. Koniec nadal ogranicza oryginalny NOTE_OFF.
  Krótkie riffy i pominięte ataki basu/wokalu nie trafiają do takiej kolejki.
- Długi źródłowy bas lub harmonia, którego FDD wykonuje tylko krótki początek,
  może kontynuować na wolnym DVD. Źródłowy gate musi trwać co najmniej 800 ms
  i dwa beaty; kontynuacja co najmniej 250 ms. Ma to samo ID źródła i dokładnie
  tę samą wykonaną częstotliwość, bez dodatkowej harmonii lub transpozycji.
  Dopuszczalna przerwa w przejęciu wynosi najwyżej pół beatu / 350 ms.
  Koniec ogranicza źródłowy NOTE_OFF, następny atak śledzonego głosu i przyszła
  rezerwacja DVD. Już brzmiący na DVD ten sam ton blokuje zbędne zdwojenie.
- Jawne reguły, artykulacje, ręczne pominięcia i celowo skrócone/skradzione
  nuty nie są przywracane przez kontynuację. Efekty nietonalne i perkusja nie
  są kandydatami. Nie ma nut generowanych według tonacji ani nazwy utworu.

Każdy zaakceptowany dodatek przechodzi pełną chronologię razem z wcześniejszymi
i późniejszymi rezerwacjami. DVD musi mieć również czas na istniejącą rampę
oraz minimalny odcinek docelowej częstotliwości; sam wolny moment ataku nie
wystarcza. FDD zachowuje odstęp 120 ms w obie strony. Nie dodajemy sterownika
silników ani osobnego planu VIRTUAL. Ekspresja CC/pitch bend w kontynuacji
pochodzi z całego oryginalnego gate'u, również z czasu po zakończeniu FDD.

Kontynuacje są jawnymi `ReinforcementEvent(kind='CONTINUATION')` i trafiają
do tego samego kompilatora co pierwotne nuty. Diagnostyka
`plan.hardware.universal.recovery` rozróżnia odzyskane zdarzenia, późne wejścia,
kontynuacje i weta mechaniczne. Nie są to pomiary fizycznego wykonania.

Kompromis: przejęcie FDD → DVD zmienia barwę i może mieć słyszalny nowy atak
lub krótką przerwę. Nie obiecujemy bezstratnego odtworzenia każdej polifonii.
Odzyskany późno pad nie jest zachowanym oryginalnym atakiem. Liczbę takich wejść
raportujemy osobno; większa liczba nut ani dłuższa praca DVD nie dowodzą
lepszego odsłuchu.

### Odtworzenie benchmarku biblioteki

Manifest [universal-library-corpus.json](../reports/universal-library-corpus.json)
opisuje snapshot 316 ścieżek, 149 unikalnych plików i 659053 źródłowych nut.
Wszystkie pliki zostały poprawnie odczytane. Dodatkowe identyczne kopie nie
zwiększają liczby przykładów. Nie kopiujemy biblioteki MIDI do raportu.
Podział to 120 plików rozwojowych i 29 odłożonych do końcowej kontroli.
Znane wersje tej samej kompozycji i warianty o identycznej reprezentacji nut
trafiają do jednej grupy; wcześniejszy korpus 31 MIDI pozostaje rozwojowy.
Grupowanie nazw służy tylko organizacji eksperymentu, nie aranżacji utworu.

Baseline to Universal z `98bad14`, a nie starszy Instrument Roles. Oba przebiegi
mają identyczną konfigurację. Raport
[universal-library-arrangement.json](../reports/universal-library-arrangement.json)
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
| Konflikty / overlapy / naruszenia odstępu FDD / komendy tacek | 0 | 0 |

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
