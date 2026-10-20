# Aranżacja MIDI i presety

Aktualny opis algorytmów dla **aktywnego zestawu z czterema FDD i czterema DVD**.
Katalog hosta zawiera także FDD5–8 i DVD5–6, ale wszystkie te kanały pozostają
wyłączone, z `present:false`; nie zwiększają dostępnej polifonii aranżacji. Zmian MIDI, presetów ani alokatora w tej aktualizacji
nie wykonywano. Architektura wykonania jest w
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
nie wprowadza dowolnej częstotliwości ani nowej harmonii. Dla DVD sufit muzyczny
wynosi 600 Hz akustycznych przed przeliczeniem `pitchRatio`. FDD używają
obecnego eksperymentu −12 / 100–205 Hz, niezależnie od presetu.
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
| `instrument_roles` — FDD Riffs + DVD Tło | Krótkie riffy FDD, stabilne długie głosy DVD i sustain tła; bez dowolnego dodatkowego UNISON FDD | Krótsze FDD i skończona polifonia mogą pomijać część akordu |
| `instrument_roles_unison` — Pary Unisono | FDD1+2 jedna partia, FDD3+4 druga; w parze ta sama nuta jednocześnie | Dwie partie zamiast czterech niezależnych; więcej kopii nie oznacza więcej zachowanych nut |
| `instrument_roles_unison4` — 4 FDD Unisono · eksperymentalny | FDD1–4 tworzą jeden instrument: kolejne nuty jednej partii grają jednocześnie z identycznym Hz i gate; DVD/speakery/HDD zachowują alokację Instrument Roles | Jedna linia zamiast czterech; świadoma redukcja polifonii, bez gwarancji pełnego MIDI |
| `instrument_roles_duet` — Pary Dwugłos | Te same pary, do dwóch istniejących nut jednej partii; monofoniczna fraza przechodzi w unisono | Nie dopisuje harmonii i nie robi echa 100 ms; w gęstym MIDI nadal możliwe straty partii |
| `fdd_quality` — FDD Quality | Ważność frazy/akcentu kontra koszt kroków, zawróceń, duty i rest; skracanie gate i ograniczenie extras | Zachowany atak może mieć krótszy sustain |
| `fdd_quality_adaptive` — FDD Quality Adaptive | Quality jako referencja, lokalna gęstość i tempo sterują odzyskiwaniem wartościowych nut i krótkich gate | Większa aktywność przy szybkich frazach; wspólny limit ataków może ponownie zredukować wynik |
| `dvd_lead_low_fdd` — DVD Lead + Low FDD | DVD preferowane dla głosów tonalnych; FDD próbuje kolejnej niższej oktawy tylko w efektywnym zakresie, inaczej wraca do kandydata | Może tracić melodię/bas; dodatkowa próba nie gwarantuje −24 dla każdej nuty |

Szczegóły istotne dla porównań:

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
- 4 FDD Unisono korzysta z tego samego wyboru właściciela frazy co pary, lecz
  ma jedną grupę FDD1–4. Nie gra stałych 440 Hz przez utwór: wspólnie wykonuje
  wybraną sekwencję nut źródłowych. W pauzie właściciela może przejąć inną partię,
  bez zmiany NOTE_ON i bez wymyślania nut. Inne urządzenia zachowują rezerwacje
  referencyjnego `instrument_roles`; pozostałe presety nie zmieniają zachowania.
  Po wspólnym ograniczaniu ataków dodatkowa synchronizacja usuwa niekompletne
  grupy i ponownie sprawdza wspólny gate wobec wszystkich profili. Weto pojedynczej
  stacji usuwa atak całej grupy, nie pozostawia samotnych kopii. Domyślny odstęp
  ataków FDD 120 ms, transpozycja i zakresy pozostają obowiązujące. Wyłączona stacja
  nie jest automatycznie włączana ani zastępowana przez FDD5–8; pozostałe człony
  grupy nadal grają wspólnie. Mute pozostaje niezależną bramką wykonania.
  Tryb dotyczy AUTO; ręczne przypisania do FDD są odrzucane z komunikatem,
  ponieważ mogłyby wymusić niezależne nuty. Ręczne pominięcia i przydziały innych
  rodzin zachowują znaczenie. `hardware.fddUnison4` raportuje członków i liczbę
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

Universal rezerwuje również przyszłe wejścia wokalu/FX; poza nimi speakery
mogą ratować krótkie melodie za szybkie dla silników. Główny wokal może użyć
FX/motorów podczas polifonii. Długie pady i niskie basy nie zajmują tej puli;
wyjątek analizy wielogłosu basu dotyczy równoczesnego górnego głosu, nie
sekwencyjnego skoku linii basowej. Kolejny źródłowy atak może zakończyć gate
poprzedniej sylaby bez sztucznego blokowania wokalu.

HDD zachowują osobną pulę perkusyjną z możliwością użycia wolnego kanału;
semantyka GM kanału 10 i pitched percussion poza tym kanałem są rozróżniane.
Artykulacja wirtualnego hitu nie zmienia faz fizycznego cyklu.

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

## Universal: odzyskiwanie po redukcji FDD

[universal.py](../host/playback/universal.py) wybiera głosy według ciągłości fraz,
rozłożenia akordów i pokrycia partii, z rezerwacjami przyszłych pickupów.
FDD odstęp i krótkie gate są brane pod uwagę już przy wyborze, DVD preferują
źródłowy sustain. Późniejszy [universal_recovery.py](../host/playback/universal_recovery.py)
pracuje **po** wspólnym ograniczeniu ataków FDD i nie zmienia wcześniej zagranych
primary, istniejących extras ani ich ekspresji. Każdy dodatek sprawdza z pełną przyszłą
chronologią i źródłowym końcem, bez nazw utworów w regułach.

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
nie jest możliwe. Benchmark pełnej biblioteki zachowuje development/holdout,
hashe wejść i baseline, a nie tylko sumę nut. Raporty wyraźnie oddzielają
pozytywny odsłuch VIRTUAL od braku walidacji całego algorytmu na REAL.
