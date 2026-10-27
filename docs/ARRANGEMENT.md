# Aranżacja MIDI i presety

Aktualny opis algorytmów dla **zestawu z ośmioma FDD i czterema DVD**.
FDD1–8 są aktywne w aranżacji, VIRTUAL i REAL oraz zadeklarowane jako podłączone.
Architektura wykonania jest w
[ARCHITECTURE.md](ARCHITECTURE.md), zakresy i parametry mechaniczne w
[HARDWARE_DEVICES.md](HARDWARE_DEVICES.md). Historyczne wyniki porównań
są w [badaniach aranżacji](research/arrangement-benchmarks.md) oraz
[benchmarkach Universal](research/universal-arrangement.md).

## Wspólna analiza i alokacja

AUTO parsuje tempo, metrum, program/bank na NOTE_ON, kanały i lyrics, normalizuje
double-tracking z zachowaniem proweniencji, następnie klasyfikuje partie.
[analysis.py](../host/playback/analysis.py), [semantic.py](../host/playback/semantic.py),
[sound_roles.py](../host/playback/sound_roles.py) korzystają z nazw, GM,
rejestru, monofonii, rytmu i zgodności lyrics. To deterministyczne heurystyki,
nie rozpoznawanie nagrania ani prawdopodobieństwa modelu ML.

Role semantyczne obejmują VOCAL, BACKING_VOCAL, BASS, GUITAR, KEYS, STRINGS,
PAD_SYNTH, PERCUSSION, UNPITCHED_EFFECT i OTHER; alokacja korzysta z funkcji
lead/bass/harmony/percussion. Wokal może zastąpić heurystyczny lead przy
wyniku ≥0,75 i przewadze ≥0,12. Silne dopasowanie lyrics (≥85%), minimum
20 nut i nakładanie ≤15% wzmacniają rozpoznanie melodii wokalnej; nazwa tracka
sama nie wymusza routingu. Analiza Type 0 rozróżnia kanały mimo jednego tracka.

Jawne nietonalne efekty GM w banku 0/0 (programy liczone od zera:
119, 120, 121, 122, 125, 126, 127) nie stają się nutami FDD/DVD/speakera.
Stan programu/banku jest kanałowy także między trackami i zapamiętywany
na NOTE_ON. Takie zdarzenia mają powód `UNPITCHED_EFFECT_UNSUPPORTED`, nie
są przenoszone na HDD i nie wchodzą do tonalnego mianownika retencji.
Bird Tweet, Telephone oraz wszystkie Synth FX nie są automatycznie szumem.
Ozdobnik tonalny na FX to inna kategoria niż efekt nietonalny.

[hardware_arranger.py](../host/playback/hardware_arranger.py) ocenia kandydatów
w granicach profilu, preferencji i transpozycji urządzenia. Folding jest oktawowy;
nie wprowadza dowolnej częstotliwości ani nowej harmonii. Przydział DVD zachowuje
dotychczasowy pułap 600 Hz, żeby nie zmieniać wyboru nut ani rezerwacji. Na końcu
runtime stosuje [rejestr DVD](../host/playback/dvd_register.py): **200–800 Hz
akustycznych**, przed przeliczeniem `pitchRatio`, we wszystkich presetach AUTO.
Preferuje +1 oktawę całej już przydzielonej frazy. Jeśli nie mieści się ona w tym
zakresie, wybiera najbliższe wspólne przesunięcie oktawowe; dopiero gdy takie
przesunięcie nie istnieje, składa poszczególne nuty. Głosy śledzi osobno w ramach
track/channel, również przy zmianach docelowego DVD, a pauzy źródłowe rozdzielają
frazy według lokalnego tempa. Nie zmienia liczby nut, NOTE_ON, gate, sustainu,
przypisań urządzeń ani komend pozostałych rodzin. Obejmuje także DVD reinforcement
i odzyskane ogony FDD; aktualizuje ich krzywe częstotliwości, zachowując pozostałą
ekspresję. Skrajny pitch bend, którego nie da się pomieścić jednym przesunięciem,
jest składany oktawowo próbka po próbce (możliwy skok rejestru). Raport
`hardware.dvdRegister` podaje przesunięcia, wyjątki i końcowe projekcje mechaniczne;
pełna chronologia DVD jest ponownie sprawdzana bez usuwania nut.
Jest to wybór brzmieniowy, nie potwierdzenie bezpiecznej pracy fizycznego silnika.
Laboratory zachowuje osobny zakres profilu/protokołu. FDD używają
obecnego eksperymentu −12 / 80–200 Hz, niezależnie od presetu.
Zajętość jest monofoniczna na fizyczną lane, z pełnymi rezerwacjami extras.
Profil sprawdza również przejścia i przyszłą chronologię, nie samą pojedynczą nutę.

Zdarzenie źródłowe zachowuje MIDI pitch, onset, duration i ID; plan zapisuje
osobno wykonane Hz/czas/urządzenie oraz wynik i przyczynę pominięcia.
Nie należy utożsamiać liczby fizycznych kopii UNISON z retencją źródłowych nut.
Arpeggiowane ratowanie i późniejsze odzyskiwanie mają jawny wykonany onset;
nie są dowodem odtworzenia każdej nuty w jej źródłowym momencie.

## Presety

Wybór: `/settings` → **Aranżacja → Preset aranżacji**. Jest sesyjny;
restart wczytuje `arrangementPreset` z JSON (aktualnie `instrument_roles_unison4`).
Zmiana potwierdza STOP i przelicza plan, bez autoplay.

| ID / nazwa | Decyzje muzyczne | Kompromis |
| --- | --- | --- |
| `balanced` — Balanced / Mechanical-Aware | Lokalna gęstość i sustain: krótkie zmienne frazy preferują FDD, dłuższe DVD; ochrona leadu/basu; opcjonalny dynamiczny UNISON | Preferencje miękkie, więc długi głos może pozostać na FDD przy braku miejsca |
| `universal` — Universal | Dobór głosów fraz, pokrycie partii przed dodatkowymi nutami akordu, rezerwy wokalu/FX, długie DVD, odzyskiwanie wolnej pojemności | Uproszczenia wielogłosu i jawne późniejsze wejścia; pozytywny odsłuch VIRTUAL nie kwalifikuje REAL |
| `fdd_expressive` — FDD Expressive · 4 partie + akcenty | Cztery logiczne głosy Universal w parach FDD1–2, 3–4, 5–6, 7–8; zwykła nuta na jednej stacji, akcent z krótszą kopią; gate z MIDI, tempa i następnego ataku | Do czterech głosów, zależnie od dostępności par; więcej źródłowych nut kosztem liczby równoległych kopii. Parametry wymagają odsłuchu REAL |
| `fdd_expressive_solo` — FDD Expressive · bez kopii akcentów | Porównanie A/B z pełnym Expressive: identyczne główne nuty, ich urządzenia, pitch, onset i gate; na końcu usuwane tylko dodatkowe `FDD_ACCENT` | Zwolniona pojemność pozostaje niewykorzystana, aby porównanie izolowało kopie. Krótkie główne nuty pozostają krótkie; efekt akustyczny wymaga odsłuchu |
| `adaptive_legato` — Adaptive Legato · ochrona rytmu | Lokalny wybór artykulacji źródłowej partii: ochrona krótkich rytmicznych ataków, legato w płynnych fragmentach; cztery stałe pary grające unisono | Partner powtarza dokładnie wysokość, start i gate każdej zachowanej nuty, także w spokojnych fragmentach. Kopie podlegają ustawieniom unisono i walidacji mechanicznej; DVD, speakery i HDD zachowują plan Expressive |
| `fdd_legato` — FDD Legato · ciągłe frazy | Frazowe przeorganizowanie puli FDD z Expressive: jedna stacja na frazę, ciągłe zmiany wysokości, scalanie powtórzeń i wybór ważniejszych ataków | Cztery logiczne głosy w parach; pozostałe instrumenty identyczne jak w Expressive. Celowo mniej ataków MIDI i dłuższa ciągła praca; jakość i temperatura wymagają oceny fizycznej |
| `instrument_roles` — FDD Riffs + DVD Tło | Krótkie riffy FDD, stabilne długie głosy DVD i sustain tła; bez dowolnego dodatkowego UNISON FDD | Krótsze FDD i skończona polifonia mogą pomijać część akordu |
| `instrument_roles_unison` — Pary Unisono | FDD1+2 jedna partia, FDD3+4 druga; w parze ta sama nuta jednocześnie | Dwie partie zamiast czterech niezależnych; więcej kopii nie oznacza więcej zachowanych nut |
| `instrument_roles_unison4` — 2×4 FDD Unisono · eksperymentalny | Dwa logiczne głosy od początku alokacji Universal: FDD1–4 i FDD5–8; cztery stacje w grupie mają identyczne Hz, onset i gate. DVD preferują długie tło, speakery wokal/FX, HDD role rytmiczne | Dwie linie zamiast ośmiu niezależnych; mogą wykonać dwa różne głosy jednej partii. Gęste MIDI nadal wymaga redukcji |
| `instrument_roles_duet` — Pary Dwugłos | Te same pary, do dwóch istniejących nut jednej partii; monofoniczna fraza przechodzi w unisono | Nie dopisuje harmonii i nie robi echa 100 ms; w gęstym MIDI nadal możliwe straty partii |
| `fdd_quality` — FDD Quality | Ważność frazy/akcentu kontra koszt kroków, zawróceń, duty i rest; skracanie gate i ograniczenie extras | Zachowany atak może mieć krótszy sustain |
| `fdd_quality_adaptive` — FDD Quality Adaptive | Quality jako referencja, lokalna gęstość i tempo sterują odzyskiwaniem wartościowych nut i krótkich gate | Większa aktywność przy szybkich frazach; wspólny limit ataków może ponownie zredukować wynik |
| `dvd_lead_low_fdd` — DVD Lead + Low FDD | DVD preferowane dla głosów tonalnych; FDD próbuje kolejnej niższej oktawy tylko w efektywnym zakresie, inaczej wraca do kandydata | Może tracić melodię/bas; dodatkowa próba nie gwarantuje −24 dla każdej nuty |

Szczegóły istotne dla porównań:

- Globalny eksperyment odsłuchowy `fddFixedToneMs: 200` ustawia każdą zachowaną
  nutę FDD i każdą kopię FDD na dokładnie 200 ms w pozostałych presetach oraz
  STRICT_TRACKS. Końcowy filtr wymaga dodatkowo 3 ms release, więc onsety na
  jednej stacji muszą być oddalone co najmniej o 203 ms. Gęstsze ataki są
  pomijane bez przesuwania NOTE_ON; DVD, speakery i HDD nie zmieniają gate.
- FDD Expressive w AUTO wyłącza sztywne 200 ms **wyłącznie w swoim planie**.
  Universal od początku ma cztery logiczne sloty FDD zamiast ośmiu fizycznych;
  revoicing śledzi właściciela frazy i preferuje różne partie przed kolejnymi
  głosami tej samej partii. Wszystkie dźwięki pochodzą ze źródła MIDI; folding
  i obecna transpozycja −12 / 80–200 Hz pozostają bez zmian.
  [fdd_expression.py](../host/playback/fdd_expression.py) dobiera gate z minimum
  długości źródłowej, 180 ms, 0,45 ćwierćnuty oraz 80% odstępu do następnego
  ataku tego głosu. Robocze minimum to 6 cykli tonu oraz minimum profilu;
  może nieco wydłużyć bardzo krótki ornament, ale nie zajmuje następnego ataku
  z pominięciem przerwy release (co najmniej 3 ms). Niedające się zmieścić
  zdarzenie zostaje pominięte, bez przesuwania NOTE_ON.
  Zwykłe ataki rozkładane są między członków pary, z zachowaniem minimum 120 ms
  między atakami każdej fizycznej stacji. Akcent to wejście frazy, mocna część
  taktu lub velocity ≥10 powyżej mediany partii, przy velocity ≥64.
  Dostępna druga stacja gra tę samą nutę w tym samym momencie przez około 55%
  gate'u głównego, z minimum profilu i 4 cykli. To obwiednia liczby napędów 2→1,
  nie regulacja napięcia ani szerokości STEP. Odrzucenie kopii nie usuwa głównego
  ataku; osierocone kopie są usuwane. Brak członka pary nie zmienia numeracji.
  Recovery korzysta z DVD i speakerów, nie dopisuje FDD poza budżetem czterech
  głosów. Raport `hardware.fddExpressive` ujawnia grupy, nuty solo, kopie i gate'y.
  Ręczne przypisania FDD w AUTO wymagają wyjścia z tego eksperymentu;
  STRICT_TRACKS zachowuje wcześniejsze reguły i 200 ms.
  Wszystkie liczby artykulacji są parametrami do odsłuchu, nie zmierzonymi limitami
  bezpieczeństwa. Inspiracja obwiednią liczby napędów:
  [opis autora Floppotronu](https://silent.org.pl/home/2022/06/13/the-floppotron-3-0/).
- Wariant `fdd_expressive_solo` korzysta w runtime z dokładnie tego samego
  planowania, artykulacji, recovery i rejestru DVD co `fdd_expressive`.
  Dopiero po tych etapach usuwa dodatkowe kopie `FDD_ACCENT`; nie dobiera
  nowych nut i nie wydłuża istniejących. Wszystkie podstawowe zdarzenia,
  pozostałe extras i komendy DVD/HDD/speakerów pozostają identyczne.
  Wewnętrzne powiązania artykulacji z dodatkowymi zdarzeniami zachowują tożsamość;
  indeksy `extra:N` są tylko zgodną projekcją API. Pozostała chronologia FDD jest
  ponownie sprawdzana, ponieważ usunięcie kroków zmienia model pozycji/nawrotów.
  Przy niewykonalności plan kończy się błędem zamiast pomijać kolejne nuty.
  `hardware.fddExpressive` raportuje `accentCopies: 0`, liczbę
  `suppressedAccentCopies` i `allocationPreserved: true`. Liczniki wykonanych
  tonów i końcowe stany FDD są odświeżane; decyzje głównych nut zachowują
  diagnostykę alokacji wariantu bazowego. STRICT_TRACKS nadal stosuje 200 ms.
  Domyślny preset i wersja z akcentami pozostają dostępne.
- FDD Legato (`fdd_legato`) działa po gotowym wariancie bez kopii w AUTO.
  Nie zmienia źródłowych danych MIDI, przydziałów DVD/speakerów/HDD ani ich
  komend i sidecarów. Przeorganizowuje tylko wcześniej wybrane główne FDD.
  W każdej dotychczasowej parze stabilizuje track/channel przez frazę;
  utrzymuje właściciela przez krótki wtręt, jeżeli zbliża się jego kolejne
  wejście, a lead/bas może przerwać mniej ważną partię. Próg luki źródłowej
  wynosi roboczo 0,9 ćwierćnuty, ograniczone do 180–450 ms. Wyraźniejsza
  pauza lub zmiana partii zamyka frazę. Głosy różnych partii nie są sklejane.
  Przy kolejnej frazie wybierany jest mniej obciążony członek tej samej pary.
  Mocniejsze fragmenty wzmacnia wolny partner: cztery linie mogą grać na
  ośmiu stacjach naraz, z unisono wewnątrz pary i różnymi partiami między parami.
  To dłuższe kopie przebiegu legato, bez krótkich kopii akcentów.
  Selekcja zachowuje wejście frazy i maksymalizuje wagę velocity oraz akcentów
  ćwierćnutowych przy wymaganym czasie na wysokości. Roboczy cel to połowa
  ćwierćnuty ograniczona do **140–220 ms**, z zachowaniem większego minimum
  profilu i skonfigurowanego odstępu ataków (domyślnie co najmniej 120 ms).
  To nie skalibrowany próg satysfakcjonującego tonu ani limit bezpieczeństwa.
  Zachowane NOTE_ON zostają w źródłowych chwilach, bez kolejki opóźnień;
  pitch pochodzi z MIDI po obecnej transpozycji/foldingu 80–200 Hz.
  Powtórzenia tej samej wykonanej wysokości współdzielą ton. Pozostałe zbyt
  szybkie nuty są pomijane muzycznie; powody `FDD_LEGATO_*` rozróżniają
  podtrzymany pitch, redukcję, ciągłość partii, brak miejsca na ton i weto profilu.
  Gate sięga dokładnie następnego wybranego ataku. Ostatni ton zachowuje
  koniec ostatniej nuty danej frazy lub czas potrzebny na ton; granica kolejnej
  partii pozostawia co najmniej 3 ms release. Jawny użytkowy `maxNoteSeconds`
  jest respektowany; automatyczny cap krótkich ataków z alokatora nie ogranicza
  frazowych wybrzmień. Długie historyczne NOTE_OFF nie kasują pauzy po późniejszej
  nucie tej linii. Pełna chronologia FDD jest oceniana ponownie, bez podnoszenia
  limitów STEP, zakresów, zmiany firmware, TRACK0 ani zachowania STOP/watchdoga.
  Wzmocnienie analizuje źródłowe ataki wybranej puli FDD przed scaleniem
  powtórzeń. Roboczo wymaga ≥3 ataków z ≥2 głosów w ostatniej ćwierćnucie
  (tolerancja strumu 15 ms), velocity ≥80 oraz akcentu ćwierćnutowego lub
  velocity ≥100. Sąsiednie okna z podtrzymaniem dwóch ćwierćnut łączą się.
  Nie jest to rozpoznawanie głośności nagrania. W obrębie takiego okna partner
  podąża za już graną wysokością, również wchodząc na źródłowym akcencie
  podczas długiej nuty właściciela; nie tworzy dodatkowej melodii.
  Blok trwa co najmniej ćwierćnutę i 350 ms, a każdy jego ton spełnia te same
  minima pobytu na wysokości i profilu co główny FDD. Kopia kończy się przy
  pauzie właściciela, końcu okna lub rezerwacji partnera, z ochroną 3 ms release.
  Wszystkie przyszłe nuty partnera, odstęp ataków i pełna chronologia mają
  pierwszeństwo; przy wecie pomijana jest tylko kopia. Użytkowe
  `fddUnisonEnabled: false` lub `fddUnisonMaxVoices < 2` wyłącza te wzmocnienia.
  Inne presety zachowują dotychczasowe zachowanie.
  `hardware.fddLegato` zapisuje liczbę fraz, zachowanych ataków i przyczyny
  redukcji; `reinforcement` podaje okna, bloki, dodatkowe tony, czas pracy i weta.
  Liczba odrzuconych ID obejmuje też scalone powtórzenia: nie oznacza
  wtedy braku tonu, ale rezygnację z osobnego ataku. STRICT_TRACKS zachowuje 200 ms.
- Mechanical-Aware (`mechanical_arrangement.py`): roboczy próg sustainu 500 ms,
  kontekst tej samej partii track/channel; profil i ochrona istotnych głosów
  ograniczają kradzież. To preferencja przy alokacji, nie globalny gate.
- Instrument Roles (`instrument_roles.py`): preferencja DVD szczególnie dla
  źródłowych nut ≥650 ms, krótkich FDD poniżej 450 ms; długi fallback FDD ma
  gate do 400 ms. Gdy DVD reprezentuje długą nutę, FDD może zachować jej
  krótki atak do 80 ms. Wybór stabilnych głosów akordu chroni tło przed riffem.
- Pary (`fdd_pairs.py`): właściciel track/channel, lookahead 750 ms,
  rezerwacja pickup 120 ms, tolerancja strumów 15 ms. Dwa realne głosy muszą
  pozostać różnymi wykonanymi nutami po foldingu, inaczej to unisono.
- 2×4 FDD Unisono korzysta z tego samego wyboru właściciela frazy co pary:
  FDD1–4 oraz FDD5–8 są dwiema niezależnymi grupami. Nie grają stałych 440 Hz:
  każda grupa wspólnie wykonuje wybraną sekwencję nut źródłowych, a aktywne grupy
  preferują różne partie. Przy braku drugiej partii mogą wybrać dwa różne
  istniejące głosy jednej partii; ta sama wykonana wysokość nie zajmuje obu grup
  w tej partii. W pauzie właściciela mogą przejąć inną partię, bez zmiany NOTE_ON
  i bez wymyślania nut. Referencją jest `universal` z budżetem dwóch logicznych
  głosów FDD już podczas pierwszej alokacji, zamiast ośmiu niezależnych stacji
  redukowanych dopiero na końcu. Fizyczne kopie nadal sprawdzają każdy profil.
  Stały gate 200 ms jest uwzględniany przed wyborem nut, a nie dopiero po nim.
  DVD/speakery/HDD zachowują rezerwacje tej referencji podczas revoicingu FDD;
  późniejszy recovery może dodać źródłowe nuty w wolnych oknach DVD/speakerów.
  Długie pady mają pierwszeństwo przed dodatkowymi krótkimi tonami akordu;
  krótka harmonia nie skraca długiego tła. DVD odrzuca kandydatów, których
  przejście rampy plus minimalny gate przekracza długość nuty.
  Po wspólnym ograniczaniu ataków dodatkowa synchronizacja usuwa niekompletne
  grupy i ponownie sprawdza wspólny gate wobec wszystkich profili. Weto pojedynczej
  stacji usuwa atak jej całej czteroosobowej grupy, ale nie usuwa poprawnego ataku
  drugiej grupy. Domyślny odstęp ataków FDD 120 ms, transpozycja i zakresy pozostają
  obowiązujące. Wyłączona stacja nie jest automatycznie zastępowana urządzeniem
  z drugiej grupy; pozostałe człony jej grupy nadal grają wspólnie. Mute pozostaje
  niezależną bramką wykonania.
  Tryb dotyczy AUTO; ręczne przypisania do FDD są odrzucane z komunikatem,
  ponieważ mogłyby wymusić niezależne nuty. Ręczne pominięcia i przydziały innych
  rodzin zachowują znaczenie. `hardware.fddUnison4.groups` raportuje obie grupy i liczbę
  wspólnych nut/kopii po filtrze; są to plany, nie pomiary ruchu czy głośności.
  Wybór kolejnych nut unisono utrzymuje zweryfikowany stan mechaniczny każdego
  FDD zamiast odtwarzać całą historię przy każdym kandydacie; brak przyszłych
  stałych rezerwacji jest warunkiem tej ścieżki. Pokrycie przez tło DVD korzysta
  z indeksu wysokości i czasów. Sustain DVD zachowuje dokładne migawki niezmienionego
  początku chronologii, a każdą zmienioną nutę i cały dalszy ciąg weryfikuje ponownie.
  Cache jest lokalny dla jednego profilu i przebiegu aranżacji, bez współdzielenia
  pomiędzy utworami i bez pomijania końcowej walidacji.
- Quality (`fdd_quality.py`): preferowany gate 350 ms jest punktem oceny,
  nie sztywnym limitem każdej ważnej nuty. Opcjonalny UNISON wymaga wysokiej
  wartości i wolnego budżetu; nie może wypchnąć primary.
- Adaptive (`fdd_adaptive.py`): analiza tempa/metrum w lokalnym oknie,
  wygładzanie attack/release 0,75/1,5 beat. Sam rozłożony akord nie aktywuje
  trybu dynamicznego; wymagane są gęste, kolejne onsety. W spokojnych oknach
  wynik referencyjnego Quality zostaje zachowany. Najpierw usuwa kosztowne
  opcjonalne kopie; odtwarzany gate nie wychodzi poza źródłowy NOTE_OFF.
- DVD Lead (`dvd_lead.py`): jawna transpozycja urządzenia poprzedza `fdd_pitch`.
  Druga próba −12 jest przyjmowana wyłącznie w efektywnym oknie. Brak
  reprezentowalnej nuty może oznaczać pominięcie, a nie przycięcie częstotliwości.

## Speakery i perkusja

Główny PC Speaker preferuje rozpoznany wokal/lead, bez dodatkowej transpozycji (0; oktawę niżej niż wcześniejsze +12).
FX (bez tej transpozycji) reprezentuje osobną wysoką monofoniczną linię ozdobników.
W starszych presetach reguła FX wymaga leadu, co najmniej 8 nut, średniego pitch
76–96, gęstości do 3 nut/s i odpowiedniego programu Pipe/Synth Effects/Synth Lead,
bez wokalu/basu. Przykład: Counting Stars, okolice 34,5–36,5 s,
830,61 → 987,77 → 830,61 → 739,99 Hz; [raport](../reports/counting-stars-speakers.json).

Universal, 2×4 FDD Unisono oraz FDD Expressive rezerwują również przyszłe wejścia wokalu/FX; poza nimi speakery
mogą ratować krótkie melodie za szybkie dla silników. Główny wokal może użyć
FX/motorów podczas polifonii. Długie pady i niskie basy nie zajmują tej puli;
wyjątek analizy wielogłosu basu dotyczy równoczesnego górnego głosu, nie
sekwencyjnego skoku linii basowej. Kolejny źródłowy atak może zakończyć gate
poprzedniej sylaby bez sztucznego blokowania wokalu.

HDD zachowują osobną pulę perkusyjną z możliwością użycia wolnego kanału;
semantyka GM kanału 10 i pitched percussion poza tym kanałem są rozróżniane.
Artykulacja wirtualnego hitu nie zmienia faz fizycznego cyklu.
Model HDD w VIRTUAL ma dwukrotnie większe wzmocnienie (+6 dB); zachowuje dynamikę
velocity i artykulację. Nie zmienia to impulsów ani poziomu sterowania REAL.
W **każdym presecie** obowiązuje wspólny limit **8 komend HDD HIT w dowolnym
ruchomym oknie `[t, t + 1 s)`**, łącznie dla wszystkich HDD. To budżet muzyczny,
nie zmierzony bezpieczny limit cewek. Selekcja przed alokacją chroni stopę i werbel,
następnie tomy, talerze i hi-hat; drobna perkusja (np. tamburyn i marakasy)
ma osobną, najniższą kategorię `aux`. Słabsze wcześniejsze dodatki mogą ustąpić
ważniejszemu późniejszemu akcentowi. Selekcja nie przesuwa NOTE_ON ani nie
dopisuje uderzeń. Odrzucenia mają powód `HDD_RATE_LIMIT`.
Końcowy plan uwzględnia też ręczne przypisania i kopie HDD z reinforcement;
kompilator odrzuca harmonogram przekraczający limit. REAL i VIRTUAL wykonują
ten sam wybór HIT. Dodatkowe impulsy artykulacji VIRTUAL, np. podwójne uderzenie
werbla, nie są dodatkowymi komendami HIT i nie wchodzą do tego budżetu.
W Universal, 2×4 FDD Unisono i FDD Expressive [percussion_routing.py](../host/playback/percussion_routing.py)
preferuje role według fizycznej kolejności: HDD1 stopa, HDD2 werbel,
HDD3 hi-hat, HDD4 tomy/talerze. To miękkie preferencje, nie wyłączne kanały.
Przy wyłączonych HDD role są przydzielane kolejno dostępnym kanałom.
Przy równoczesnym przeciążeniu najpierw zachowuje stopę i werbel; zapowiedź
ich bliskiego wejścia ogranicza pożyczanie ich kanałów. Nie dopisuje uderzeń,
nie przesuwa źródłowych onsetów i nie zwiększa energii impulsów ani limitów
resetu/termiki. Wybór perkusji może się zmienić względem starszych wersji.

Domyślna konfiguracja używa **dwóch HDD: HDD1 i HDD2**. HDD3–4 pozostają
w katalogu, profilach i firmware, ale mają `enabled:false`. Wszystkie presety
pomijają je, a router odrzuca ich HIT również ze starego harmonogramu; STOP jest
nadal przekazywany. Dla dwóch aktywnych HDD preferowane role to stopa i werbel.
Pozostała perkusja wykorzystuje wolne miejsca, jeśli symulacja istniejącego
cyklu i budżetów kanału potwierdza, że nie zablokuje jego nadchodzącego głównego
akcentu. Stopa i werbel mogą pożyczać oba kanały; rezerwacja dotyczy dodatków.
Bez stopy lub werbla oba HDD mogą reprezentować pozostałe źródłowe uderzenia.
Nie dopisujemy rytmu ani nie zwiększamy impulsów. Limit 8 HIT/s pozostaje
wspólnym sufitem; dotychczasowe ograniczenia pojedynczych kanałów mogą wymagać
niższej gęstości. Brzmienie na sprzęcie wymaga osobnego odsłuchu.

## Source Continuity, UNISON i reinforcement

[articulation.py](../host/playback/articulation.py) może przedłużyć wykonany gate
w wolnej przestrzeni ku źródłowemu NOTE_OFF, z ochroną następnego primary,
reartykulacji i rezerwacji. Nie odtwarza skradzionej/SHORTENED końcówki i nie
nadpisuje jawnej artykulacji. `sourceContinuityAmount` określa część możliwego
przedłużenia (bieżąco 1). Quality i Instrument Roles zachowują własne krótkie FDD.
To zmiana rezerwacji, nie pogłos audio.

Dynamiczny UNISON jest opcjonalnym zdwojeniem tej samej nuty na wolnym FDD
(max 2 w konfiguracji), sprawdzanym po primary wraz z przyszłą chronologią.
Nie ma prawa zmienić podstawowej alokacji. Stałe pary mają własną regułę unisono.
Idle reinforcement to osobne kopie w wolnych oknach, domyślnie wyłączone.
Wszystkie kopie zajmują fizyczny czas i są uwzględniane przez sustain i końcowy
pass FDD. Równoległe kopie nie dodają polifonii jednej lane.

## DVD Continuous Sustain

[dvd_sustain.py](../host/playback/dvd_sustain.py) jest niewielkim etapem artykulacji
po alokacji, po poznaniu końcowych rezerwacji Source Continuity/UNISON/extras,
z oceną pełnej chronologii przed przyjęciem wydłużenia. Błąd propozycji zostawia
poprzednią nutę; sam mostek nie ma generować nowych pominięć.

Bieżące ustawienia: `dvdContinuousSustain: true`, `dvdDynamicAware: true`,
`dvdMaxBridgeMs: 200`. 200 ms jest wartością eksperymentalną.
Pass dotyczy DVD w ciągłym obrocie: wydłuża **wykonany NOTE_OFF dokładnie do
kolejnego NOTE_ON**, zachowując onset, pitch, urządzenie i dane źródłowe.
Compiler usuwa pośredni STOP, a firmware zmienia cel istniejącej rampy.

Tryb dynamiczny wymaga tej samej partii track/channel, zmiany pitch, braku
jawnej artykulacji, skradzionego gate i ingerujących nut/rezerwacji.
Co najmniej 3 unikalne ataki w odległości do dwóch beatów od bieżącej nuty
wyznaczają kadencję;
przy dynamic-aware musi wynosić ≤400 ms i ≤1,05 beat. Odstęp pary nie przekracza
1,5 lokalnej mediany, źródłowa przerwa 55% odstępu ani 0,6 beat.
Nuty dłuższe niż dwa beaty i powtórzenia wymagające reartykulacji są chronione.
Wyłączenie dynamic-aware usuwa wymóg szybkiej kadencji, pozostawiając osłony frazy.

Instrument Roles, obie pary oraz Universal dodatkowo korzystają z tła
`dvdBackgroundMaxBridgeMs: 350`. Zachowują poprawne mostki dynamiczne,
a potem dopuszczają stabilne handoffy głosów tej samej partii oraz nieakcentowane
powtórzenia. Różnica velocity ≥24 chroni akcent powtórzenia. Źródłowy gate
musi wypełniać ≥40% odstępu onsetów; przerwa ≤350 ms, ≤0,9 beat i ≤60% odstępu.
Krótki, już wykonywany ornament FDD (≤30 ms oraz ≤1/8 beat), w całości w luce
źródłowej, może pozostać nad ciągłym DVD. Dłuższy/pominięty atak, jawna
artykulacja, zajęta lane lub celowa pauza nadal blokują mostek.
Nie łączy niezależnych tracków/kanałów. `dvdContinuousSustain: false` wyłącza
oba warianty. STRICT_TRACKS nie używa DVD.

Większy sustain nie jest celem samym w sobie: reartykulacja i pauzy mają
pozostać czytelne. Brak czujników temperatury oznacza, że długie połączenia
wymagają kwalifikacji na silniku. Benchmarki raportują czas pracy/ciszy sumowany
po DVD i najdłuższy ciągły odcinek **jednego** motoru z ExecutionTimeline.

## Wspólny limit ataków FDD

Każdy preset i STRICT_TRACKS dostaje runtime pass
[fdd_attack_rate.py](../host/playback/fdd_attack_rate.py):
`fddMinAttackIntervalMs` domyślnie 120, można zwiększyć do 1000.
To odstęp NOTE_ON, nie częstotliwość tonu ani rating bezpieczeństwa.
Pierwszy atak zostaje, zbyt bliskie kolejne są pomijane bez przesuwania w kolejkę.

Powtórzenie tego samego pitch i partii z przerwą gate ≤40 ms może dołączyć do
poprzedniego gate, z limitem 400 ms i ochroną następnej nuty, pauzy i jawnej
artykulacji. Zmiennych pitch nie zamienia w nową melodię. Pass obejmuje primary,
reinforcement i kopie par; aktualizuje ich sidecary i ponownie ocenia mechanikę,
ponieważ usunięcie ataku zmienia fazę karetki. Niedopuszczalne wydłużenie wraca
do poprzedniego gate, niedopuszczalny atak może zostać pominięty.
`FDD_ATTACK_RATE` i `articulation.fddAttackRate` ujawniają redukcję.
Pozostałe urządzenia zachowują wykonanie. Koszt muzyczny to uproszczenie riffów;
regresja Airbag 1:34 jest w [benchmarkach](research/arrangement-benchmarks.md).

## Universal, 2×4 FDD i Expressive: odzyskiwanie po redukcji FDD

[universal.py](../host/playback/universal.py) wybiera głosy według ciągłości fraz,
rozłożenia akordów i pokrycia partii, z rezerwacjami przyszłych pickupów.
FDD odstęp i krótkie gate są brane pod uwagę już przy wyborze, DVD preferują
źródłowy sustain. Późniejszy [universal_recovery.py](../host/playback/universal_recovery.py)
pracuje **po** wspólnym ograniczeniu ataków FDD i nie zmienia wcześniej zagranych
primary, istniejących extras ani ich ekspresji. Każdy dodatek sprawdza z pełną przyszłą
chronologią i źródłowym końcem, bez nazw utworów w regułach.
W 2×4 FDD recovery używa wyłącznie DVD i speakerów: nie dodaje niezależnej nuty
na pojedynczym FDD i nie rozbija zgodności grup unisono.

1. Pominięte tonalne lead/bass/harmony mogą wrócić na wolne urządzenie w oryginalnym
   onset, jeśli spełnią wymagany gate/cykle, zakres, ataki i przyszłe rezerwacje.
2. Tylko długa harmonia (≥max(650 ms, 1 beat), sustain affinity ≥0,35) może
   wejść później na DVD, najwyżej o min(350 ms, pół beat), do source NOTE_OFF.
   To jawne późniejsze wejście, nie odtworzony oryginalny atak.
3. Długa nuta bass/harmony wykonana krótko na FDD może kontynuować na wolnym DVD
   **te same wykonane Hz**, bez nowej transpozycji: źródło ≥max(800 ms, 2 beat),
   pozostały gate ≥250 ms. Wejście po FDD lub po luce do min(350 ms, pół beat);
   koniec przed source NOTE_OFF, następnym głosem źródłowym lub rezerwacją DVD
   (guard 3 ms). Nie dotyczy jawnej artykulacji, SHORTENED/STOLEN ani już
   pokrytej kontynuacji. Zachowuje źródłowe CC/bend.

Deterministyczność i retencja ataków/długości są sprawdzalne programowo;
„idealne” odtworzenie dowolnej liczby partii na skończonym zestawie monofonicznym
nie jest możliwe. Historyczny benchmark zachowuje development/holdout;
nowe porównanie wszystkich 134 plików jest testem regresji pełnej dostępnej
biblioteki, bez osobnej części odłożonej. Oba zachowują hashe wejść i baseline,
a nie tylko sumę nut. Raporty wyraźnie oddzielają
pozytywny odsłuch VIRTUAL od braku walidacji całego algorytmu na REAL.

## TODO

- [ ] **Settings — osobna zakładka „Aranżer” z dokładną regulacją i przeliczeniem utworu.**
  Umożliwić użytkownikowi samodzielne dostrajanie aranżacji z poziomu aplikacji,
  bez konieczności każdorazowej zmiany kodu. Umieścić te opcje w osobnej zakładce
  ustawień, z sekcjami dla FDD, DVD, HDD, PC Speakera i PC Speakera FX,
  aby nie zaśmiecać pozostałych ustawień. Dla każdej rodziny przewidzieć kilka
  do kilkunastu przydatnych parametrów, z precyzyjnymi polami liczbowymi,
  jednostkami, suwakami oraz krótkim wyjaśnieniem wpływu na brzmienie.
  Przykładowy zakres: preferowane partie i rejestry, transpozycja/folding,
  długości nut, ataki, odstępy i sustain; dla HDD także maksymalna gęstość
  uderzeń, selekcja akcentów, priorytety klas perkusji i podział ról kanałów.
  Dokładną listę dobrać do istniejących mechanizmów oraz odsłuchów użytkownika.
  Dodać przycisk **„Przerenderuj aktualnie wybrany utwór”**, który przelicza
  jego aranżację i wspólny harmonogram REAL/VIRTUAL z bieżącymi ustawieniami,
  bez ponownego wgrywania MIDI i bez automatycznego uruchamiania odtwarzania.
  Pokazać stan przeliczania i błędy, zachowywać wybrane wartości oraz umożliwić
  przywrócenie domyślnych ustawień presetu. Zmiana parametrów ma wpływać na
  świadomie uruchomione przeliczenie, bez niespodziewanej podmiany granego planu.
  Oddzielić parametry muzyczne od kalibracji i ograniczeń sprzętu; kontrolki
  aranżera nie mogą zwiększać energii impulsów, omijać limitów wykonawczych ani
  włączać nieaktywnych urządzeń. To plan funkcji, bez obecnej zmiany UI lub logiki.

- [ ] **PC Speaker — poprawić przydział partii i wprowadzić minimum muzyczne 250 Hz.**
  Użytkownik zgłasza, że PC Speaker bywa przypisywany do niewłaściwej partii.
  Konkretne utwory, fragmenty, tryb REAL/VIRTUAL i ewentualny udział kanału FX
  wymagają ustalenia. Porównać źródłowe partie z klasyfikacją i przydziałem
  do głównego speakera, zanim zostaną zmienione reguły routingu.
  Wymaganie użytkownika: główny PC Speaker nie powinien grać poniżej **250 Hz**.
  Traktować tę wartość jako ograniczenie muzyczne aranżacji, nie zmierzony limit
  sprzętu; uwzględnić transpozycję i folding oraz zgodność REAL/VIRTUAL.
  Nie rozszerzać automatycznie tego wymagania na PC Speaker FX bez ustalenia
  zakresu. Na razie jest to TODO, bez zmian kodu i konfiguracji.

- [ ] **Import MIDI — obsłużyć błędne SysEx w Pink Floyd — Echoes.**
  Plik odniesienia: `Feuneuleu_Prod_Echoes__Pink_Floyd.mid` z Downloads,
  SHA-256: `b961663092017453181dae040204ee072955fa1ea15e77a4291db6bf3df1f5f2`.
  Potwierdzono dwa zdarzenia F0 SysEx przy offsetach pliku 28 i 46 (licząc od 0),
  zawierające odpowiednio niedozwolone bajty `C5` (197) i `C6` (198).
  Parser `mido` zgłasza `data byte must be in range 0..127` przed aranżacją.
  Diagnostyczny odczyt tolerancyjny ograniczony do SysEx pozwolił ściśle
  sparsować pozostałe zdarzenia: 22 ścieżki i 18 427 ataków nut.
  Opracować kontrolowaną obsługę takich komunikatów z czytelnym ostrzeżeniem;
  zachować oryginał, nuty, velocity, NOTE_OFF oraz mapę tempa i czasy zdarzeń.
  Nie włączać globalnego `clip=True`, które może zmieniać także dane nut.
  Dodać testy wadliwego i poprawnego SysEx oraz zachowania pozostałych zdarzeń.
  Nie zmieniono dotąd importera ani pliku MIDI; diagnoza była wyłącznie offline.

- [ ] **FDD — zachować różnorodność Jigsaw Falling into Place, ograniczyć monotonię Bodysnatchers (VIRTUAL).**
  Według odsłuchu użytkownika FDD w **Jigsaw Falling into Place** brzmią dobrze:
  słychać różnorodne sekwencje i ciekawe zróżnicowanie partii. W **Bodysnatchers**
  jednoczesne ataki wszystkich stacji dają irytujące wrażenie monotonii
  i powtarzalności. To subiektywna obserwacja wyłącznie z **VIRTUAL**;
  **nie przeprowadzono odsłuchu REAL**. Przyczyna pozostaje niezweryfikowana.
  Pliki odniesienia: `0087-09-radiohead_2007-jigsaw_falling_into_place.mid`
  oraz `0080-02-radiohead_2007-bodysnatchers-[k].mid`.
  Porównać źródłowe partie, powtarzalność sekwencji i synchronizację ataków
  obu grup FDD w planie i harmonogramie, uwzględniając działanie unisono.
  Wykorzystać Jigsaw jako pozytywny punkt odniesienia przy poprawie różnorodności;
  nie uznawać wrażenia jednoczesnej gry wszystkich stacji za potwierdzony błąd.

- [ ] **FDD Expressive — ochrona ważnych partii po rozszerzonym A/B.**
  W porównaniu 157 poprawnie odczytanych MIDI ze starym 2×4 Unisono
  nowy preset zachowuje więcej nut w 130 plikach, ale w 16 plikach gubi
  100 wcześniej granych ID z rolą `bass`, bez oktawowego odpowiednika tej
  samej partii na oryginalnym onsecie. Sprawdzić m.in. True Love Waits (live)
  około 1:10,875, No Surprises około 3:00,743, The Scientist około 3:47,915
  oraz touhou1.mid około 2:54,432. Rola `bass` jest heurystyką; nie każde
  ID oznacza osobny, słyszalny ubytek całej orkiestry. Uchronić ważne wejścia
  podczas wyboru czterech głosów i odzyskiwania nut, bez zwiększania tempa
  ataków FDD ani zajmowania cudzych rezerwacji. Osobno ocenić skrócenie
  wybrzmienia Myxomatosis i ubytek 20 nut w Identikit. Szczegóły i hashe:
  [rozszerzony benchmark](research/arrangement-benchmarks.md#rozszerzone-ab--cała-lokalna-biblioteka-2026-10-25).
  To wyniki planowania offline; brak potwierdzenia odsłuchem VIRTUAL/REAL.

- [ ] **Let Down — zbędne impulsy PC Speakera po około 2:55 (175 s).**
  Użytkownik zgłasza niepotrzebne impulsy i podejrzewa błędny przydział partii
  pomiędzy którymś DVD a PC Speakerem. Zgłoszenie pozostaje niezweryfikowane;
  numer DVD, główny speaker/FX oraz tryb REAL/VIRTUAL wymagają ustalenia.
  Plik odniesienia: `0036-05-radiohead_1997-let_down-[k].mid`.
  Odtworzyć okolice 2:50–3:10, zaczynając od bieżącego domyślnego presetu
  `instrument_roles_unison4` i gate FDD 200 ms. Porównać źródłowe nuty/partie
  z przydziałami `PerformancePlan`, artykulacją i komendami `ExecutionTimeline`
  dla obu speakerów oraz DVD1–4. Ustalić pochodzenie impulsów i zweryfikować
  podejrzenie zamiany partii przed zmianą routingu.

- [ ] **Weird Fishes/Arpeggi — zbyt małe wykorzystanie DVD.**
  Użytkownik zgłasza wyraźnie za mało grania na DVD; przyczyna pozostaje
  niezweryfikowana. Plik odniesienia: `0082-04-radiohead_2007-weird_fishes-arpegi.mid`.
  Sprawdzić aktywność DVD1–4 w całym utworze i porównać źródłowe partie tła
  z alokacją na FDD/speakery oraz powodami pominięcia nut DVD. Zweryfikować,
  czy dobór głosów, zajętość lub ocena przejść nie ograniczają nadmiernie tła.

- [ ] **PC Speaker i PC Speaker FX — zbyt ciche w każdym utworze.**
  Obserwacja użytkownika; przyczyna pozostaje nieustalona. Podczas odczytu
  aplikacja pracowała w REAL, oba kanały miały `realAmplitude: 128`, a ostatnie
  wysłane komendy potwierdzały `VHS AMP 128` i `VHS2 AMP 128` przed `FREQ`.
  To maksymalna nastawa aplikacji: symetryczny kwadrat, 50% przewodzenia PNP.
  Log hosta nie potwierdza rzeczywistego przebiegu ani głośności na głośniku.
  Osobne poziomy VIRTUAL nie wpływają na REAL. Nie potwierdzono błędu kodu
  obniżającego nastawę REAL. Porównać samodzielny ton w laboratorium z grą
  w orkiestrze; sprawdzić tor S8550 / 56 Ω / zasilanie oraz wpływ niskiego
  rejestru i maskowania przez pozostałe instrumenty. Ocenić osobno VIRTUAL.

- [ ] **Radiohead — Jigsaw Falling into Place: HDD nadal brzmią źle w REAL przez cały utwór.**
  Obserwacja użytkownika po zmianie na dwa aktywne HDD i wprowadzeniu limitu
  12 HIT/s; problem dotyczy całego utworu, nie pojedynczego fragmentu.
  Plik odniesienia: `0087-09-radiohead_2007-jigsaw_falling_into_place.mid`.
  Przyczyna pozostaje nieustalona; porównać wykonanie REAL ze źródłową perkusją
  i harmonogramem HIT. Wyniki testów offline nie potwierdzają jakości brzmienia.

- [ ] **HDD — zachować rytmiczne akcenty, ograniczyć nadmierną gęstość uderzeń.**
  Według odsłuchu użytkownika krótkie uderzenia w rytm brzmią bardzo dobrze
  w **0:48–1:17**. Zbyt częste uderzenia brzmią źle w **0:34–0:41** oraz
  **po 1:36**. Według późniejszego wskazania użytkownika prawdopodobnie chodzi
  o **OneRepublic — Counting Stars**; tytuł nie jest ostatecznie potwierdzony,
  a tryb wyjścia pozostaje nieznany.
  Dodatkowy pozytywny przykład: **The Police — Message in a Bottle, od 0:36**.
  Według użytkownika HDD grają tam gęsto, ale rytmicznie i przyjemnie.
  Wykorzystać ten fragment jako odniesienie przy doborze reguł selekcji;
  sama duża gęstość uderzeń nie powinna automatycznie oznaczać ich redukcji.
  Porównać te fragmenty, gęstość kolejnych/równoczesnych hitów i źródłowe
  klasy perkusji. Dopracować selekcję akcentów oraz lokalną gęstość HDD,
  zachowując dobre rytmiczne fragmenty. Analiza offline wskazanego MIDI wykazała
  dominację drobnych dodatków i częste zmiany ról HDD w gęstych fragmentach.
  Wprowadzono wspólny limit 12 HIT/s i niższy priorytet `aux`; ocena brzmienia
  po zmianie nadal wymaga odsłuchu, osobno w REAL i VIRTUAL.


### Adaptive Legato — ochrona rytmu

Preset `adaptive_legato` korzysta z tej samej alokacji Expressive i walidacji
fizycznej co FDD Legato. Domyślny preset nie zmienia się. STRICT_TRACKS zachowuje
poprzednie działanie. Analiza obejmuje wybraną pulę FDD, nie wszystkie odrzucone
wcześniej głosy MIDI; nie zmienia automatycznie przypisania melodii do speakera.

Dla każdego ataku analizuje sąsiedztwo dwóch ćwierćnut wstecz i dwóch naprzód
w obrębie tej samej logicznej grupy FDD, track i channel. Tempo pochodzi z MIDI.
Krótka nuta (≤0,6 ćwierćnuty) jest chroniona, jeżeli istnieją przynajmniej dwa
lokalne odstępy ataków nie większe niż ćwierćnuta oraz co najmniej połowa z nich:

- ma źródłowy gate ≤80% odstępu do następnego ataku albo
- jest powtórzeniem tej samej źródłowej wysokości.

To jawne heurystyki rytmiczności, nie wykrywanie rozpoznawalnego motywu ani
skalibrowane parametry akustyczne. Długie dźwięki nie stają się staccato tylko
z powodu obecności krótkich dźwięków w okolicy.

Chroniony atak zachowuje źródłowy czas wejścia. Gate jest możliwie zbliżony do
źródła, ale nigdy krótszy niż obowiązujące minimum tonu 140–220 ms, profilu
sprzętowego oraz odstępu ataków. Selekcja rezerwuje dodatkową separację:
0,08 ćwierćnuty ograniczone do 30–60 ms (lub większy skonfigurowany release).
Zbyt szybkie ataki nadal mogą zostać pominięte; nie obniżamy limitów, żeby
uzyskać korzystniejszy wynik. Płynne fragmenty zachowują ciągłe zmiany wysokości.

Nowy profil zachowuje wszystkie powtórzenia jako kandydatów do selekcji.
Dzięki temu późniejszy powrót do wysokości nadal jest dostępny, nawet jeśli
pierwszy powrót następuje za szybko. Scalanie wybranych powtórzeń jest dozwolone
dopiero po selekcji, wyłącznie gdy nie są chronione. Stare Legato pozostaje
punktem odniesienia A/B.

Każdy głos ma stałą parę FDD1–2, 3–4, 5–6 lub 7–8. Partner powtarza dokładnie
wybraną wysokość, czas wejścia i gate nuty głównej; dotyczy to spokojnych i mocnych
fragmentów. Nie tworzymy niezależnej melodii ani kopii wchodzącej w połowie nuty.
Przerwy chronionych ataków pozostają takie same na obu stacjach. To zastępuje
opcjonalne wzmocnienie wyłącznie mocnych fragmentów używane przez stare Legato.
Wyłączony partner, `fddUnisonEnabled=false`, `fddUnisonMaxVoices<2` lub weto
profilu/chronologii pozostawiają nutę główną bez kopii; nie pożyczamy stacji z innej
pary i nie usuwamy nut podstawowych, aby uzyskać unisono. Zwiększona aktywność
mechaniczna wymaga oddzielnej oceny odsłuchowej i termicznej na REAL.

`hardware.adaptiveLegato` raportuje liczbę ataków chronionych, płynnych i
zachowanych. Nie jest to procent jakości muzycznej. Raport obejmuje tylko
pulę po alokacji. Redukcje i fizyczne weta pozostają w `hardware.fddLegato`.
`hardware.adaptiveLegato.pairUnison` zapisuje liczbę kopii, nut bez partnera,
przyczyny odrzucenia i liczbę dodatkowych odrzuconych nut podstawowych (zawsze 0).
Kopie mają rodzaj `FDD_PAIR_UNISON`. Wcześniejszy benchmark poniżej opisuje wersję
z opcjonalnym wzmocnieniem; jego liczby STOP i czasu pracy nie są pomiarem wersji
ze stałym unisono w parach.

Benchmark offline: `scripts/benchmark_adaptive_legato.py --midi-dir ~/Music/MIDI`
porównuje oba presety na plikach deduplikowanych SHA-256, zapisuje błędy parsera,
STOP z ExecutionTimeline, najdłuższy ciągły czas FDD, konflikty i zgodność
komend pozostałych instrumentów. Odsłuch REAL jest konieczny do oceny kompromisu
między czytelnością rytmu a odgłosami ruszania głowicy. Testy nie potwierdzają
bezpieczeństwa termicznego ciągłej pracy.

Wyniki całej biblioteki i kompromisy: [benchmark Adaptive Legato](research/arrangement-benchmarks.md#adaptive-legato--2026-10-26-offline).


### Kontrakt etapów planowania

Publiczne `runtime.arranger.arrange` deleguje do nazwanych kroków w
`runtime.planning_pipeline`: alokacja, ekspresja, ograniczenia FDD, opcjonalne
recovery z ponowną walidacją oraz rejestr DVD i artykulacja presetu. Wybrany
preset i współdzielona strategia alokacji są osobnymi danymi. Refaktoryzacja
zachowuje kolejność i liczby muzyczne; nie dostraja parametrów.

`PlanningContext` przechowuje grupy FDD i flagę łączenia stykających się tonów.
Raport `hardware.fddLegato` opisuje wynik, a jego obecność nie włącza zachowania
kompilatora. Artykulacja extras ma stabilne wewnętrzne powiązania także po
filtrowaniu lub zmianie indeksów. Publiczne `executionArticulation['extra:N']`
pozostaje zgodne ze starszym API. Historyczne raporty opisują ówczesne wersje;
[plan i dziennik refaktoryzacji](REFACTORING_PLAN.md) zawiera wyniki porównań.
