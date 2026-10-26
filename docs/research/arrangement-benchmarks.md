# Historyczne porównania aranżacji

> **Wyniki historyczne, nie obecne instrukcje ani nowe pomiary.** Każda tabela
> zachowuje własny baseline, MIDI i inventory (część ma trzy DVD i starszy
> rejestr FDD). Wymienione wdrożenia i liczby testów dotyczą tamtej wersji.
> Bieżące algorytmy są opisane tylko w [ARRANGEMENT.md](../ARRANGEMENT.md).
> Nie przeliczono raportów podczas refaktoryzacji dokumentacji.

Surowe dane pozostają w `reports/` w katalogu repozytorium; nie zmieniamy
ścieżek używanych przez skrypty ani archiwalnych hashy. Parametry i wyniki
z różnych tabel nie mogą służyć jako jedno wspólne A/B.

## FDD Expressive — cztery głosy i kopie akcentów, 2026-10-25

Nowy preset `fdd_expressive` jest osobnym wariantem do odsłuchu; domyślny
`instrument_roles_unison4` pozostaje dostępny. Źródło danych:
[fdd-expressive-comparison.json](../../reports/fdd-expressive-comparison.json).
Porównanie wykorzystuje to samo lokalne inventory 8 FDD, 4 DVD, 2 aktywne HDD
i 2 speakery oraz ten sam eksperymentalny wspólny limit 8 HIT/s HDD.
Rejestr DVD to 200–800 Hz, FDD nadal używają −12 / 100–205 Hz.
Firmware i jego limity nie były zmieniane.

Wariant A to dwa głosy, każdy grany przez cztery FDD, ze stałym gate 200 ms.
Wariant B ma cztery głosy w parach. Zwykły atak gra jedna stacja, a akcent
może dołączyć krótszą kopię na drugiej. Gate wynika ze źródła, tempa i kadencji.
Mocny akcent może nadal uruchomić wszystkie osiem stacji.

| MIDI | Źródłowe nuty FDD A → B | Różne pary wysokość/onset A → B | Ataki wszystkich 8 FDD A → B |
| --- | ---: | ---: | ---: |
| Bodysnatchers | 1283 → 3779 | 1012 → 2375 | 99,53% → 10,59% |
| Jigsaw Falling into Place | 1124 → 3046 | 1019 → 2239 | 47,31% → 2,53% |
| Airbag | 1077 → 2064 | 1016 → 1719 | 22,95% → 0,45% |

Źródłowe nuty liczymy bez fizycznych kopii. „Ataki wszystkich 8” to udział
momentów rozpoczęcia nut FDD, w których jednocześnie startuje osiem napędów;
nie oznacza ośmiu jednakowych wysokości. Różne pary pitch/onset nie są oceną
jakości muzycznej. Liczba zachowanych nut tonalnych całej orkiestry wzrosła
odpowiednio 4033 → 5770, 3579 → 4971 i 3227 → 3375.
W tych trzech porównaniach nie stracono żadnego wcześniej zachowanego ID
leadu/basu, komendy HDD są identyczne i nie ma konfliktów mechanicznych,
overlapów ani naruszeń odstępu ataków FDD. Bas ma pierwszeństwo przed
utrzymaniem właściciela partii akompaniamentu.

W B liczba krótszych kopii akcentów to 1169 / 497 / 321. Główne gate'y
obejmują około 31–161 / 32–159 / 32–180 ms; kopie mogą być jeszcze krótsze,
z zachowaniem minimum modelu. Wszystkie FDD NOTE_ON pozostają na źródłowym
onsecie, bez losowych opóźnień, nowych dźwięków i poślizgów częstotliwości.

Powtórzenie porównania (ścieżki MIDI należy wskazać lokalnie):

```sh
.venv/bin/python scripts/benchmark_universal.py \
  /path/to/0080-02-radiohead_2007-bodysnatchers-[k].mid \
  /path/to/0087-09-radiohead_2007-jigsaw_falling_into_place.mid \
  /path/to/0032-01-radiohead_1997-airbag-[k].mid \
  --presets instrument_roles_unison4 fdd_expressive --workers 3 \
  --output /tmp/fdd-expressive-comparison.json

.venv/bin/python scripts/benchmark_orchestra_library.py \
  --midi-root /path/to/MIDI --preset fdd_expressive --workers 4 \
  --output /tmp/fdd-expressive-library.json
```

Końcowy przebieg biblioteki: **141 poprawnie odczytanych MIDI**, zero konfliktów
mechanicznych, overlapów i naruszeń odstępu ataków FDD; maksymalnie 8 HIT/s HDD.
Łącznie 226676 źródłowych ataków FDD i 45033 kopie akcentów. `touhou4.mid`
zatrzymuje się na znanym `MidiSourceError: list index out of range` przed
aranżacją i nie jest liczony jako zaliczony. Skrót walidacji oraz fingerprint
implementacji są w raporcie porównawczym.
**803 testy hosta i 123 testy frontendu OK**, build frontendu zakończony sukcesem.
Kontener przebudowano; zdrowie, API oraz nowy preset w serwowanym bundle zweryfikowano.

**Wyłącznie planowanie offline i wyjścia mock. Bez odsłuchu VIRTUAL/REAL,
flashowania, ruchu urządzeń ani pomiarów cieplnych.** Parametry artykulacji
są propozycją do odsłuchu, nie zweryfikowanymi granicami bezpieczeństwa.
Próba w REAL jest potrzebna do oceny ataku, nawrotów i barwy konkretnej stacji.

### Rozszerzone A/B — cała lokalna biblioteka, 2026-10-25

Źródło: [fdd-expressive-expanded.json](../../reports/fdd-expressive-expanded.json).
Zebrano 443 ścieżki z `~/Music/MIDI` i aplikacyjnego `midi/`, a następnie
usunięto kopie według SHA-256 całego pliku: **158 różnych plików MIDI**.
Zestaw obejmuje również dwa fixture'y techniczne; różne zapisy tego samego
utworu mogą mieć różne hashe. Nie jest to 158 niezależnych kompozycji.
Względem biblioteki Music dołączono 16 innych plików z aplikacji, m.in.
Avicii, Queen, Black Sabbath, Bastille i Pet Shop Boys.

**157 plików przeszło oba pełne przebiegi `arrange` → `compile_plan`.**
`touhou4.mid` zgłosił `MidiSourceError: list index out of range` podczas
odczytu, przed aranżacją. Nie został policzony jako zaliczony test.
Porównano lokalny stan implementacji wraz z niezacommitowanymi zmianami;
fingerprint produkcyjnego Python/JSON zapisano w raporcie i sprawdzono po
benchmarku. Oba warianty mają identyczne inventory i ustawienia poza presetem:
8 FDD, 4 DVD, 2 aktywne HDD, 2 speakery oraz wspólny eksperyment **8 HIT/s HDD**.
Nie jest to porównanie ze stanem ostatniego commita ani eksperyment 8 vs 12 HIT/s.

| Metryka, suma dla 157 MIDI, chyba że zaznaczono inaczej | 2×4 Unisono | FDD Expressive |
| --- | ---: | ---: |
| Zachowane źródłowe nuty tonalne całej orkiestry | 375918 | 435646 |
| Pominięte źródłowe nuty tonalne | 97960 | 38232 |
| Źródłowe ataki FDD, bez kopii | 132305 | 251644 |
| Fizyczne komendy tonu FDD, z kopiami | 529220 | 302155 |
| Mediana udziału ataków wszystkich 8 FDD | 34,05% | 0,52% |
| Niereprezentowane okna partii, spośród 58632 | 747 | 84 |
| Mediana zachowania źródłowego wybrzmienia, z kontynuacjami | 77,129% | 76,571% |
| Konflikty mechaniczne / overlapy / naruszenia odstępu ataków FDD | 0 / 0 / 0 | 0 / 0 / 0 |
| Maksymalny szczyt HDD w przesuwanym oknie 1 s | 8 | 8 |

Okno partii to 2 s aktywności źródłowego track/channel, oceniane po atakach.
Brak pustego okna nie oznacza zachowania wszystkich jego głosów. Mediana
ataku ośmiu napędów jest liczona po plikach, nie po wszystkich atakach razem.
Suma źródłowych nut tonalnych jest identyczna: 473878. Liczby nie obejmują
perkusji i rozpoznanych efektów nietonalnych. Więcej nut oraz mniej kopii nie
stanowi samo w sobie dowodu lepszego brzmienia.

Expressive zachowuje więcej nut w **130** plikach, tyle samo w **24**, mniej
w **3**: Desert Island Disk (−2), Identikit (−20) i Rabbit in Your Headlights
(−1). Pokrycie źródłowego wybrzmienia rośnie w 66 plikach, spada w 88,
pozostaje takie samo w 3. Krótsze gate'y FDD są zamierzone, ale nie każdy
ubytek sustainu musi być muzycznie korzystny: Myxomatosis traci 13,744 punktu
procentowego tego pokrycia, Black Sabbath — Paranoid 11,604, Identikit 7,442.

#### Regresje ważnych partii

Nie utracono wcześniej zachowanego źródłowego ID sklasyfikowanego jako `lead`.
Utracono **176 ID z rolą `bass` w 19 plikach**, przy równoczesnym odzyskaniu
8671 innych ID lead/bass. Klasyfikacja jest heurystyczna: `bass` bywa również
polifoniczną partią fortepianu lub jej górnym głosem.

Dodatkowy audyt sprawdził dla każdego utraconego ID, czy przy oryginalnym
NOTE_ON gra dźwięk tej samej klasy wysokości z tego samego track/channel.
**76 ID ma taki oktawowy odpowiednik**, w tym wszystkie 68 z Last Flowers
i wszystkie 4 z aplikacyjnego Sail to the Moon. To reprezentacja częściowa:
nie potwierdza zgodności oktawy wykonawczej, czasu trwania ani barwy.
Pozostaje **100 ID bez takiego odpowiednika w 16 MIDI**; 67 było najniższym
dźwiękiem danej partii w otoczeniu ±15 ms. Nie oznacza to 100 różnych,
słyszalnie brakujących dźwięków całej orkiestry — inne partie mogą je dublować.

| Przykład regresji | ID bez odpowiednika tej samej partii | Przykładowy czas źródłowego ataku |
| --- | ---: | --- |
| touhou1.mid | 24 | 2:54,432 — MIDI 39 |
| True Love Waits (live), 2001 | 19 | 1:10,875 — MIDI 51 |
| touhou3.mid | 16 | 1:10,993 — MIDI 57 |
| A Punchup at a Wedding | 10 | Szczegółowe czasy w raporcie |
| Pet Shop Boys — Always on My Mind | 7 | 3:27,444 — MIDI 26 |
| Coldplay — The Scientist | 5 | 3:47,915 — MIDI 36 |
| No Surprises | 4 | 3:00,743 — MIDI 41 i 29 w dwóch partiach basu |
| Pink Floyd — Time | 3 | 5:17,371 — MIDI 40 |

W osobnych **33 przypadkach** źródłowe ID pozostało grane, lecz jego atak
przesunął się o około 8,681–86,805 ms; test zgodności oryginalnego onsetu
używa tolerancji 1 µs. Takie przesunięcie nie jest pominięciem nuty.
Szczegóły obejmują wcześniejsze/nowe urządzenie, przyczynę, velocity,
pitch i czas. To konkretna lista do poprawy ochrony ważnych partii, a nie
podstawa do uznania nowego presetu za bezwarunkowo lepszy dla każdego MIDI.

#### Kontrole wykonawcze i ograniczenia

W obu wariantach nie wykryto konfliktów modeli mechanicznych, overlapów,
ataków FDD poniżej 120 ms, FDD poza 100–205 Hz ani DVD poza 200–800 Hz,
także w próbkach krzywych częstotliwości. FDD zachowują źródłowe NOTE_ON;
kopie akcentów mają właściwą parę, źródło, onset i wysokość oraz nie są
dłuższe od głównego tonu. HDD3–4 nie dostają aktywnych komend.
**Harmonogramy HIT są identyczne dla wszystkich 157 porównań.**

Najdłuższy ciągły odcinek DVD w planie wynosi **366,997 s w Ful Stop**,
identycznie w obu presetach; kolejne to Planet Telex 266,666 s i Videotape
255,574 s. Modele software'owe nie potwierdzają bezpieczeństwa termicznego
tak długiej pracy. Nie wykonano pomiaru temperatury ani prądu silników.

Ponownie uruchomiono **803 testy hosta — OK**, w tym deterministyczność
Expressive i zgodność harmonogramu REAL/VIRTUAL na atrapach transportu.
Benchmark nie uruchamiał dźwięku, BLE, zasilacza ani urządzeń. Nie zmieniano
aranżera, firmware ani ustawień aplikacji w ramach tego rozszerzenia testów.
Podczas odczytu stanu aplikacja grała w REAL z `instrument_roles_unison4`;
nie przełączano jej na Expressive i nie restartowano podczas odsłuchu.

Późniejszy odsłuch użytkownika w REAL: Expressive wypada korzystnie przy
dostatecznie długich nutach, ale szybkie fragmenty Bodysnatchers eksponują
mechaniczne ruszenie i zatrzymanie głowicy zamiast satysfakcjonującego tonu.
To subiektywne zgłoszenie, bez nagrania ani pomiaru akustycznego. Kolejny
eksperyment ma osobno porównać wariant z krótkimi kopiami akcentów i bez nich;
w opisanym tutaj stanie kopie pozostają włączone. Wyniki offline nie
rozstrzygają tej oceny brzmienia.

Podstawowe A/B można powtórzyć istniejącym skryptem, pomijając plik z błędem
parsera i wskazując oba lokalne katalogi do odszukania MIDI według SHA-256:

```sh
.venv/bin/python - <<'PY'
import json
from pathlib import Path
report = json.loads(Path('reports/fdd-expressive-expanded.json').read_text())
valid = {'songs': [s for s in report['songs'] if 'comparison' in s]}
Path('/tmp/fdd-expressive-valid-midi.json').write_text(json.dumps(valid))
PY
.venv/bin/python scripts/benchmark_universal.py \
  --manifest /tmp/fdd-expressive-valid-midi.json \
  --midi-dir "$HOME/Music/MIDI" --midi-dir midi \
  --presets instrument_roles_unison4 fdd_expressive --workers 4 \
  --output /tmp/fdd-expressive-repeat.json
```

### Krok 1 — Expressive bez kopii akcentów, 2026-10-25

Źródło: [fdd-expressive-solo-comparison.json](../../reports/fdd-expressive-solo-comparison.json).
Punkt odniesienia: pełne `fdd_expressive` z commita `4e1f709`.
Nowy wariant runtime `fdd_expressive_solo` usuwa wyłącznie dodatkowe
`FDD_ACCENT` z całkowicie zaplanowanej aranżacji. Zwolnione miejsca nie są
ponownie przydzielane. To porównanie jednej zmiennej; nie wprowadza jeszcze
minimalnego czasu satysfakcjonującego tonu ani kalibracji odsłuchowej.

W 12 MIDI / 24 pełnych przebiegach zachowano dokładną zgodność wszystkich
podstawowych zdarzeń, pozostałych extras i komend nie-FDD, weryfikowaną
fingerprintami. Sprawdzono Bodysnatchers, Jigsaw, Airbag, No Surprises,
True Love Waits (live), Myxomatosis, Last Flowers, Identikit, Levels,
Counting Stars, Always on My Mind oraz Pink Floyd — Time.
Usunięto łącznie **6307 kopii**, bez dodatkowych pominięć podstawowych nut,
konfliktów modeli mechanicznych, overlapów i naruszeń odstępu ataków FDD.

| MIDI | Komendy tonu FDD z kopiami → bez kopii | Źródłowe nuty tonalne całej orkiestry |
| --- | ---: | ---: |
| Bodysnatchers | 4948 → 3779 | 5770 → 5770 |
| Jigsaw Falling into Place | 3543 → 3046 | 4971 → 4971 |
| Airbag | 2385 → 2064 | 3375 → 3375 |
| Counting Stars | 3715 → 3179 | 4669 → 4669 |

**808 testów hosta, 124 testy frontendu i build frontendu OK.**
Ruch po usunięciu kopii jest ponownie oceniany pełną chronologią FDD;
nie poprawia się jej przez przesuwanie, skracanie ani odrzucanie głównych nut.
Nowy wariant otrzymują wspólnie REAL i VIRTUAL. Firmware, impulsy STEP,
zakresy częstotliwości, limit HDD i pozostałe presety nie zostały zmienione.
To testy offline/mock, bez uruchamiania urządzeń i bez oceny akustycznej.

W `/settings` → Aranżacja → Preset aranżacji porównać
**FDD Expressive · 4 partie + akcenty** oraz
**FDD Expressive · bez kopii akcentów**, na tym samym MIDI i fragmencie,
przy jednakowych poziomach i wyjściu REAL. Zmiana presetu zatrzymuje grę;
wznowienie wymaga osobnego Play. Krótkie główne nuty pozostają krótkie —
eksperyment ma ustalić udział dodatkowych kopii w mechanicznym klikaniu.

Powtórzenie na lokalnie dostępnych plikach, np.:

```sh
.venv/bin/python scripts/benchmark_universal.py \
  'midi/0080-02-radiohead_2007-bodysnatchers-[k].mid' \
  'midi/0087-09-radiohead_2007-jigsaw_falling_into_place.mid' \
  --presets fdd_expressive fdd_expressive_solo --workers 2 \
  --output /tmp/fdd-expressive-solo-repeat.json
```

### FDD Legato — frazowe przeorganizowanie FDD, 2026-10-25

Poniższy pomiar zachowuje pierwszą wersję Legato, bez wzmocnień partnerem.
Aktualna wersja dodaje etap opisany w następnym podrozdziale.

Źródła: [A/B 12 MIDI](../../reports/fdd-legato-comparison.json) oraz
[pełna biblioteka](../../reports/fdd-legato-library.json). Baseline to
`fdd_expressive_solo`, experiment to `fdd_legato`, z identycznym inventory,
rejestrem FDD 100–205 Hz / −12, DVD 200–800 Hz i wspólnym limitem HDD 8 HIT/s.
Oba warianty zachowują dokładnie te same komendy DVD, HDD i speakerów oraz
ich extras w 12 porównaniach. Nowy pass przebudowuje tylko pulę głównych FDD.

| MIDI | Skompilowane STOP FDD przed → po | Najdłuższy odcinek FDD bez STOP po zmianie |
| --- | ---: | ---: |
| Bodysnatchers | 3779 → 529 | 175,708 s |
| Jigsaw Falling into Place | 3046 → 456 | 17,644 s |
| Airbag | 2064 → 359 | 23,199 s |
| Counting Stars | 3179 → 318 | 33,299 s |
| No Surprises | 2129 → 421 | 24,067 s |

STOP pochodzi z `ExecutionTimeline`, a ciągły odcinek kończy rzeczywista
komenda STOP. Nie utożsamiamy go z jedną wysokością: wewnątrz odcinka
mogą występować kolejne PLAY zmieniające częstotliwość. Wybrzmienie nie
przerywa się na granicy stykających się nut z powodu błędu float do 1 ns.
Ta tolerancja jest ograniczona do DVD i jawnego nowego passu FDD Legato;
zwykłe release'y oraz granice innych presetów pozostają bez zmian.

W Bodysnatchers czas pracy sumowany po FDD rośnie **369,985 → 758,084 s**.
Ataki źródłowe FDD maleją 3779 → 1486: **1893 powtórzenia** zastępuje
podtrzymany pitch, **76** ataków pominięto na rzecz ciągłości właściciela,
**298** krótkich wejść nie miało miejsca na pełny ton, a **26** pominięto
podczas wyboru wolniejszego przebiegu. Żaden zachowany NOTE_ON nie został
przesunięty. Wszystkie osiem FDD ma komendy w tym planie; jedna fraza
pozostaje na jednym członku pary, przy kolejnych frazach obciążenie jest
rozdzielane. Liczenie zachowanych źródłowych ID nie mierzy tutaj wierności
muzycznej: scalone powtórzenie traci osobny atak, ale jego wysokość nadal brzmi.

**158 różnych plików po SHA-256, 157 poprawnie odczytanych planów.**
`touhou4.mid` nadal kończy się błędem parsera `list index out of range`
przed aranżacją. Nie wykryto konfliktów modeli mechanicznych, overlapów,
naruszeń odstępu FDD ani przekroczeń 8 HIT/s; HDD3–4 pozostają nieaktywne.
Żaden plik z niepustą bazową pulą FDD nie utracił całej tej rodziny.
Najdłuższy ciągły odcinek FDD w bibliotece: **302,614 s w The National Anthem**.
To znaczący wzrost czasu pracy. Parametry fraz i długości nie są pomiarami
akustycznymi ani termicznymi; testy nie kwalifikują takiej pracy jako bezpiecznej.

**819 testów hosta, 128 frontendu oraz build frontendu OK.** Testy obejmują
powtórzenia, prawdziwe pauzy, wejście innej partii, długi historyczny NOTE_OFF,
jawny cap użytkownika, brak członka pary, STRICT_TRACKS, deterministyczność,
brak pośredniego STOP i identyczne komendy przekazywane do REAL/VIRTUAL na mockach.
VIRTUAL utrzymuje w tym presecie bufor mechaniczny przez stykające się nuty,
zmieniając wysokość bez glissanda i ponownego ataku; STOP i epoka nadal go anulują.
Firmware, GPIO, TRACK0, generowanie STEP oraz istniejące zabezpieczenia nie były zmieniane.
Nie flashowano, nie włączano ATX ani nie wykonywano fizycznego odsłuchu w tych testach.

Powtórzenie podstawowego porównania:

```sh
.venv/bin/python scripts/benchmark_universal.py \
  'midi/0080-02-radiohead_2007-bodysnatchers-[k].mid' \
  'midi/0087-09-radiohead_2007-jigsaw_falling_into_place.mid' \
  --presets fdd_expressive_solo fdd_legato --workers 2 \
  --output /tmp/fdd-legato-repeat.json
```

### FDD Legato — wzmocnienie mocnych fragmentów ośmioma stacjami, 2026-10-25

Pierwsza wersja używała wszystkich napędów w całym utworze, lecz maksymalnie
czterech jednocześnie. Wzmocnienia `FDD_LEGATO_REINFORCEMENT` dołączają wolnych
partnerów do istniejących linii w mocniejszych fragmentach. Nie przywracają
krótkich `FDD_ACCENT`: partner podąża za wysokością bez STOP wewnątrz bloku.
Cichsza lub rzadsza partia nie wymusza ośmiu napędów.

Źródła: [12 porównań w obrębie tego samego planowania](../../reports/fdd-legato-reinforcement.json)
oraz [pełna biblioteka](../../reports/fdd-legato-reinforcement-library.json).
`benchmark_universal.py` dla `fdd_legato` zapisuje stan tuż przed dodaniem
wzmocnień w `legatoBeforeReinforcement`; sprawdza identyczność wszystkich
głównych zdarzeń, pozostałych extras i komend innych rodzin po tym etapie.
To porównanie tego samego presetu, konfiguracji i MIDI, bez ponownej alokacji.
Metryki aktywności liczą przedziały skompilowanych tonów, a nie jednoczesne NOTE_ON:
stacja trzymająca ton także jest aktywna. Czas pracy sumuje sekundy wszystkich FDD.

| Bodysnatchers | Legato bez wzmocnień | Legato ze wzmocnieniami |
| --- | ---: | ---: |
| Maksimum aktywnych FDD jednocześnie | 4 | 8 |
| Czas z ośmioma aktywnymi FDD | 0 s | 81,589 s |
| Czas z co najmniej pięcioma aktywnymi FDD | 0 s | 180,639 s |
| Wybrane główne ataki FDD | 1486 | 1486 |
| Dodatkowe tony partnerów | 0 | 1194 w 239 blokach |
| Łączny czas pracy FDD | 758,084 s | 1442,595 s |
| STOP FDD z ExecutionTimeline | 529 | 768 |
| Najdłuższy odcinek jednego FDD bez STOP | 175,708 s | 175,708 s |

Wzrost liczby STOP wynika z pracy dodatkowych stacji: główne linie mają
niezmieniony harmonogram, a partner kończy każdy dodatkowy blok. Nie dodaje
STOP między jego stykającymi się wysokościami. Ten kompromis zwiększa obsadę
i czas pracy, nie jest próbą minimalizacji samej liczby komend.

| MIDI kontrolne | Sekundy z ośmioma FDD po zmianie |
| --- | ---: |
| Jigsaw Falling into Place | 103,683 |
| Airbag | 23,023 |
| No Surprises | 57,038 |
| Counting Stars | 122,506 |
| True Love Waits (live) | 0 — brak kwalifikujących mocnych okien |

W 12 porównaniach oraz wszystkich **157 poprawnie odczytanych MIDI** z biblioteki
wszystkie główne nuty, pozostałe extras oraz komendy DVD, speakerów i HDD są
identyczne. Osiem FDD pracuje równocześnie w 118 plikach; pozostałe nie są do
tego zmuszane. Jeden z 158 plików, `touhou4.mid`, zachowuje wcześniejszy błąd
parsera. Brak konfliktów modeli, nakładających się rezerwacji i naruszeń odstępu
ataków FDD; wspólny limit HDD nadal wynosi 8 HIT/s. Najdłuższa ciągła praca FDD
w bibliotece nadal wynosi **302,614 s — The National Anthem**.
**825 testów hosta, 128 frontendu i build frontendu: OK.** Testy obejmują
pracę ośmiu stacji, łagodne fragmenty, włączenie partnera w trakcie tonu,
ochronę przyszłych rezerwacji, weto profilu, deterministyczność oraz zgodność
REAL/VIRTUAL na mockach. Algorytm nie był oceniany słuchowo
ani termicznie przez te narzędzia; wzrost wypełnienia nie potwierdza bezpieczeństwa
ciągłej pracy. Firmware, częstotliwości STEP, GPIO i watchdog pozostały bez zmian.

Powtórzenie z lokalnych MIDI:

```sh
.venv/bin/python scripts/benchmark_universal.py \
  'midi/0080-02-radiohead_2007-bodysnatchers-[k].mid' \
  --presets fdd_legato --output /tmp/fdd-legato-reinforcement-repeat.json
```

## DVD Continuous Sustain — pierwszy eksperyment

Źródło: [dvd-sustain-comparison.json](../../reports/dvd-sustain-comparison.json).
4 FDD, **3 aktywne DVD**, 1 speaker i 4 HDD; Balanced, Source Continuity,
UNISON bez zmian, tylko przełącznik dynamicznego sustainu inny. Mostek do 200 ms.
STOP pochodzi z ExecutionTimeline z extras; praca i cisza są sumą po silnikach,
najdłuższy odcinek dotyczy jednej lane, bez początkowej/końcowej ciszy.

| Metryka | Bodysnatchers przed → po | Every Breath You Take przed → po |
| --- | ---: | ---: |
| Nuty DVD | 925 → 925 | 442 → 442 |
| STOP DVD | 897 → 791 | 380 → 376 |
| Praca DVD (s) | 372,338392 → 373,147914 | 479,375288 → 479,562204 |
| Cisza między nutami (s) | 251,213683 → 250,404161 | 158,434675 → 158,247759 |
| Najdłuższy ciągły odcinek (s) | 9,994024 → 9,994024 | 13,434588 → 13,434588 |
| Odrzucone nuty | 169 → 169 | 0 → 0 |
| Konflikty | 0 → 0 | 0 → 0 |

Raport potwierdza identyczność decyzji primary, pozostałych urządzeń i extras
oraz poprawną chronologię modelu. Odtworzenie dla bieżącej konfiguracji:
`.venv/bin/python scripts/compare_dvd_sustain.py`. Nowe wyniki mogą różnić się
od snapshotu. Bez pomiarów termicznych i kwalifikacji ciągłej pracy REAL.

## Balanced / Mechanical-Aware

### Historyczne porównanie MIDI

Wyniki poniżej zachowują ówczesne trzy DVD i starszą politykę; nie są aktualnym
benchmarkiem czterech DVD z końcowym limitem ataków FDD.

Baseline zapisano przed zmianą kodu, z commita `da1af20`. Oba przebiegi mają ten sam zestaw 4 FDD + 3 DVD oraz dotychczasowe VHS/HDD. Porównanie obejmuje całą rzeczywistą ścieżkę `arrange`, normalizację i końcową artykulację.

| Utwór | Zagrane stare → nowe | Odrzucone stare → nowe | FDD stare → nowe | DVD stare → nowe |
|---|---:|---:|---:|---:|
| Every Breath You Take | 3536 → 3538 | 2 → 0 | 1013 → 1751 | 1193 → 457 |
| Message in a Bottle | 7388 → 7531 | 229 → 86 | 2665 → 3146 | 1624 → 1286 |
| Bodysnatchers | 9193 → 9195 | 171 → 169 | 5824 → 6085 | 1185 → 926 |
| Jigsaw Falling Into Place | 6856 → 7174 | 605 → 287 | 2844 → 3197 | 1620 → 1585 |

| Utwór | DVD średnio (s), stare → nowe | DVD maks. (s), stare → nowe | FDD ≥2 s, stare → nowe | UNISON: liczba / czas (s) | Skrócone DVD w nowym planie |
|---|---:|---:|---:|---:|---:|
| Every Breath You Take | 0.316 → 1.052 | 4.246 → 13.435 | 10 → 0 | 87 / 23.256 | 10 |
| Message in a Bottle | 0.422 → 0.571 | 3.192 → 15.992 | 12 → 12 | 1 / 0.192 | 369 |
| Bodysnatchers | 0.317 → 0.402 | 11.423 → 9.994 | 1 → 1 | 1 / 0.190 | 28 |
| Jigsaw Falling Into Place | 0.310 → 0.336 | 2.822 → 5.646 | 5 → 4 | 0 / 0 | 851 |

W każdym utworze włączenie UNISON daje **identyczne podstawowe zdarzenia** jak ten sam nowy arranger bez UNISON: zero dodatkowych odrzuceń. Nie wykryto konfliktów interwałów. Pełny raport JSON zawiera wykorzystanie każdego urządzenia, oceny sprzętowe oraz oba warianty UNISON.

Więcej rozpoczętych nut nie oznacza automatycznie lepszego odsłuchu. W gęstych fragmentach nowy arranger częściej oddaje końcówkę sustainu następnej partii (szczególnie Jigsaw). Pozostają składanie oktaw, opóźnienia i fizyczne niepewności profili. Te kompromisy trzeba ocenić słuchowo.

W czasie tego badania Glass Eyes i All I Need nie były dostępne lokalnie. Małe fixture'y sprawdzają sześciosekundowy akord sustainowy oraz rozdzielenie długiego tonu od wyzwalania perkusji na kanale 10. Nie rekonstruują tych utworów. Sama długość NOTE_OFF nie ujawnia czasu wybrzmienia próbki; nieznane brzmienie próbki na kanale tonalnym wymaga informacji o instrumencie i odsłuchu.

Raport można odtworzyć poleceniem:

```sh
.venv/bin/python scripts/compare_mechanical_arrangement.py
```

Pliki: `reports/mechanical-arrangement-baseline.json` i `reports/mechanical-arrangement-comparison.json`.

### Weryfikacja

- Testy backendu: 497.
- Testy frontendu: 43.
- Build frontendu: poprawny; istniejące ostrzeżenie o dużym bundle pozostaje.
- Testy pokrywają mieszane frazy na jednej ścieżce, powtórzenia, fallback, konkurencję, ochronę basu, dowolne pary FDD, przyszłe rezerwacje, gęstą polifonię, deterministyczność, API i identyczne komendy przekazywane do REAL/VIRTUAL z atrapami transportu.
- Firmware i GPIO nie zostały zmienione. Nie wykonywano flashowania ani testowego uruchamiania silników.
- Pełne chronologie czterech MIDI, wraz z UNISON, przeszły ponowną ocenę profili sprzętowych. Nieznane obciążenie fizyczne i degradacje jakości są jawnie zapisane w `physicalChronology` raportu.
- Docker przebudowany i uruchomiony ponownie; healthcheck `healthy`, API pokazuje trzy aktywne DVD, a UI serwuje nowy bundle z podglądem PerformancePlan. Odtwarzacz pozostaje zatrzymany.

## FDD Quality

### Weryfikacja i A/B

Baseline Balanced pochodzi z commita `6754ea2`. Dla czterech identycznych lokalnych MIDI skrypt sprawdza SHA-256 nut, zdwojeń i skompilowanych komend: decyzje Balanced muszą pozostać identyczne. Pomija pliki, których nie ma lokalnie. Zestaw instrumentów jest identyczny: 4 FDD, 3 DVD oraz dotychczasowy VHS/HDD.

```sh
.venv/bin/python -m unittest discover -s host/tests -q
.venv/bin/python scripts/compare_fdd_quality.py
cd web
npm test -- --run
npm run build
```

Raporty: `reports/fdd-quality-balanced-baseline.json` i `reports/fdd-quality-comparison.json`. Skrypt sprawdza pełną chronologię sprzętową i identyczność podstawowych nut FDD Quality z UNISON i bez niego.

Preset jest eksperymentalny. Zachowanie liczby leadów/basów i niższa liczba kroków nie potwierdzają lepszego brzmienia. Skrócenie fraz może zmniejszyć ich wybrzmienie, a ocena ważności opiera się na istniejącej klasyfikacji MIDI. Potrzebny jest odsłuch A/B; nie wykonano fizycznych testów silników ani flashowania.

### Wyniki lokalnego porównania A/B

| Utwór | Nuty FDD B → Q | Aktywność FDD (s) B → Q | Kroki B → Q | Zawrócenia B → Q | Średnia nuta FDD (s) B → Q |
|---|---:|---:|---:|---:|---:|
| Thinking About You | 2899 → 2838 | 604.9 → 374.6 | 197089 → 120045 | 2736 → 1665 | 0.209 → 0.132 |
| Creep (acoustic) | 2836 → 2268 | 1028.6 → 550.4 | 316734 → 166475 | 4397 → 2310 | 0.363 → 0.243 |
| Where I End and You Begin | 3862 → 3575 | 733.5 → 258.2 | 215466 → 73178 | 2990 → 1013 | 0.189 → 0.072 |
| Jigsaw Falling Into Place | 3201 → 2536 | 826.2 → 641.2 | 236819 → 182072 | 3287 → 2527 | 0.258 → 0.253 |

| Utwór | Nuty DVD B → Q | Aktywność DVD (s) B → Q | Odrzucone razem B → Q | UNISON B → Q | Dodatkowo utracone lead/bas |
|---|---:|---:|---:|---:|---:|
| Thinking About You | 1877 → 1912 | 436.7 → 439.3 | 2338 → 2364 | 0 → 0 | 0 |
| Creep (acoustic) | 744 → 1312 | 279.1 → 586.8 | 0 → 0 | 0 → 0 | 0 |
| Where I End and You Begin | 327 → 610 | 677.0 → 664.5 | 246 → 250 | 11 → 0 | 0 |
| Jigsaw Falling Into Place | 1581 → 2076 | 532.5 → 642.9 | 287 → 457 | 0 → 0 | 0 |

We wszystkich czterech utworach zachowane są wszystkie nuty leadu i basu z Balanced. Dotychczasowa klasyfikacja przypisuje dużą część Creep acoustic do roli bass; raport nie traktuje tej etykiety jako zweryfikowanej analizy muzykologicznej. Harmony: Thinking 4205 → 4179, Where I End 3182 → 3178, Jigsaw 4104 → 3934. W Creep liczba odrzuceń pozostaje zerowa. Wybrzmienie części basów jest krótsze — zachowanie onsetów nie gwarantuje zachowania pełnego sustainu.

UNISON w FDD Quality nie wystąpił w tych czterech planach: konserwatywna ocena wartości, kosztu i przyszłych rezerwacji go nie dopuściła. Fixture testowy potwierdza aktywację na ważnych nutach przy wolnej pojemności. Podstawowe zdarzenia z włączonym i wyłączonym UNISON są identyczne. Wszystkie chronologie Quality przeszły ocenę wykonalności modeli profili; nie jest to weryfikacja fizycznej jakości dźwięku.

Weryfikacja końcowa: 515 testów backendu, 45 testów frontendu, poprawny build aplikacji. Docker przebudowany i zrestartowany; dostępność nowej wersji oraz healthcheck sprawdzane po wdrożeniu.

## FDD Quality Adaptive

### Diagnosis before implementation

Canonical available files used:
- `0005-05-radiohead_1993-thinking_about_you.mid`
- `0041-10-radiohead_1997-no_surprises-[k].mid`
- `0032-01-radiohead_1997-airbag-[k].mid`

Raw / normalized counts: 7322 / 7322, 5432 / 5432, 7316 / 7316 respectively.
Normalization is unchanged; these files do not lose note events at this stage.
Quality's global accompaniment gate caps are 132.2, 363.5 and 163.7 ms.
It shortens 1165, 758 and 393 played FDD notes, respectively, before any Adaptive
change. In Airbag all 16 omitted tonal notes have long source gates (2.128–8.469 s),
not short riff gates. No event has FDD_QUALITY_OPTIONAL_COST as its final top-level
drop reason, although some individual candidates are rejected by that policy;
DEVICE_BUSY is often the first reported reason. Inspect candidate diagnostics
as well as aggregate drop reasons. This is why simply lowering a note-selection
threshold cannot recover nonexistent missing short notes in this file.

The JSON comparison contains final source and performed timing, original versus
normalized counts, gate restorations, recovered IDs, roles, per-FDD counts, actual
activity intervals, primary and including-UNISON 0–4 distributions and estimated
mechanical work. Exclusive zero-FDD silence buckets distinguish composition rests,
Quality gate/selection silence, unsuitable FDD material, material on other devices,
and remaining allocation/mechanical conflicts. These overlap-based classifications
are diagnostic estimates; silence can have multiple simultaneous musical causes.
The one-FDD opportunity duration is limited to valuable short recovery candidates
that pass full-lane chronology, not an exhaustive claim about every hypothetical
arrangement. It is reported separately for Quality and Adaptive.


### Verification

`reports/fdd-adaptive-baseline.json` records exact event/reinforcement/compiled-command
SHA256 fingerprints from commit 1cee5c0 for all three existing presets and all three
MIDI files. `scripts/compare_fdd_adaptive.py` checks them, physical combined chronology,
UNISON-on/off primary equality and identical DVD primary events. It exports
`reports/fdd-adaptive-comparison.json` with the full interval diagnostics.

Backend: 536 tests pass; 11 new Adaptive tests cover calm/dense/strum fragments,
smoothing, MIDI tempo/meter changes, natural rests, recovery across idle FDD,
source note-off including delayed attacks, conflicts, DVD preservation, duplicate
normalization, independent voices versus UNISON, determinism and safe REAL/VIRTUAL
switching. Frontend: 49 tests pass, including selection and diagnostic presentation.
TypeScript/Vite build passes (existing large-bundle warning).

Docker is rebuilt with `docker compose up -d --build orchestra`. Verify healthy,
served current frontend and offline generation through Application.set_preset.
There is no flashing or physical motor test, and firmware upload is unnecessary.

### Limits

Density and motif importance are heuristics. Activity, steps and reversals are planned
estimates, with no measured physical head position or acoustic noise measurement.
Recovering no omitted short notes in Airbag is a valid result: its short source riffs
were already represented. Improvement there comes from recovering source gate time,
not inventing attacks or taking sustained parts away from DVD. Whether the change
sounds sufficiently fuller requires listening. Other MIDI editions may differ.

### Verified comparison

| MIDI | FDD notes Quality / Adaptive | Primary activity seconds | Steps including UNISON | Reversals including UNISON | Restored gates | Recovered attacks |
|---|---|---|---|---|---|---|
| Thinking About You | 2838 / 2838 | 374.583 / 374.583 | 120045 / 120045 | 1665 / 1665 | 0 | 0 |
| No Surprises | 2211 / 2211 | 529.435 / 529.435 | 159183 / 159183 | 2208 / 2208 | 0 | 0 |
| Airbag | 2431 / 2431 | 246.105 / 258.502 | 69265 / 72319 | 961 / 1003 | 118 | 0 |

| MIDI | Active independent FDD 0 / 1 / 2 / 3 / 4 — Quality | Adaptive |
|---|---|---|
| Thinking About You | 37.55% / 1.70% / 1.05% / 1.92% / 57.77% | 37.55% / 1.70% / 1.05% / 1.92% / 57.77% |
| No Surprises | 22.68% / 15.36% / 7.92% / 16.87% / 37.18% | 22.68% / 15.36% / 7.92% / 16.87% / 37.18% |
| Airbag | 41.31% / 35.65% / 18.33% / 3.88% / 0.83% | 40.37% / 34.28% / 19.64% / 4.74% / 0.97% |

All three previous presets match their original fingerprints on all three files. All Adaptive lanes, including reinforcements, pass full chronology. UNISON does not change primary decisions. No previously accepted primary event is lost; all DVD primary events are identical. Thinking About You and No Surprises have identical event/compiled-command fingerprints to Quality.

Airbag gains 12.397 seconds of primary FDD gate time (+5.0%). Its zero-primary-FDD share falls from 41.31% to 40.37%; time with 2–4 independent FDD grows from 23.04% to 25.35%. Total FDD steps rise by 4.4%. UNISON falls from 11 to 7 events. No new attacks are recovered in these source files; the Airbag improvement is 118 restored source gates. This is a modest planned improvement, not a claim of verified better sound.

### Changed files

- `host/playback/fdd_adaptive.py`: tempo/meter density map, smoothing and interval diagnostics.
- `host/playback/hardware_arranger.py`: Adaptive reference, recovery and gate refinement using the existing physical allocator/validator.
- `host/playback/mechanical_arrangement.py`: independent-voice priority over dynamic UNISON.
- `host/playback/orchestra.py`, `host/runtime/application.py`: new preset validation and existing safe switching.
- `host/playback/performance.py`: Adaptive report.
- `web/src/runtime.ts`, `web/src/components/ArrangementPreview.tsx`: selector, activity/density timeline and recovery diagnostics.
- `host/tests/test_fdd_adaptive.py`, `web/src/App.test.tsx`, `web/src/components/ArrangementPreview.test.tsx`: unit/integration/UI coverage.
- `scripts/compare_fdd_adaptive.py`, `reports/fdd-adaptive-baseline.json`, `reports/fdd-adaptive-comparison.json`: reproducible comparisons and regression fingerprints.
- `docs/fdd-quality-adaptive.md`: algorithm, diagnosis, evidence and limits.

Final Docker container is healthy. The served bundle is `index-DtXfZyOA.js` and contains the selector and `meanActiveFdd` diagnostic. An offline Application in the container successfully selects Adaptive, remains stopped and has no transport attached. No flashing or motor tests.

## DVD Lead + Low FDD

### Diagnostics and comparison

UI displays DVD/FDD note counts, octave-lowered FDD notes, performed original-pitch
fallbacks due to range, estimated FDD steps/reversals (including UNISON), omissions,
shortened notes and UNISON use. The report also contains individual frequencies,
role counts/durations and per-device physical counters.

Run `.venv/bin/python scripts/compare_dvd_lead.py --baseline reports/dvd-lead-baseline.json`.
The baseline fingerprints were generated from commit ba2681b for Balanced and
FDD Quality. The script verifies exact events/reinforcements/compiled commands,
combined physical chronology, unchanged primary decisions with UNISON disabled,
and at most three DVD voices. Reports contain melody/bass and harmony retention,
additional important losses relative to Balanced, frequency summaries, DVD duty,
drops and movement estimates. Salience/classification are heuristics, not an
acoustic judgment of preserved melody or chords.

Reduced steps do not prove better sound. Existing octave folding in Balanced
already puts FDD into 200–410 Hz, so the new octave preference often cannot lower
its performed frequency further. Much of the reduction comes from DVD takeover
and fewer harmony voices. Physical listening is still needed, especially for
Thinking About You, which already sounded good, and Creep/2+2=5 where some
important events can be lost. No physical motor tests or flashing are performed.

### Verification and deployment

Backend: 525 tests pass. Frontend: 47 tests pass. TypeScript/Vite build passes
(existing large-bundle warning). Docker was rebuilt and restarted; healthcheck
passes and the served frontend contains the third preset. A separate offline
Application in the container generates this preset with playback stopped.
No firmware, BLE protocol, GPIO, calibration or motor-control changes; reflashing
is unnecessary.

### Verified A/B/C results

A = Balanced, B = FDD Quality, C = DVD Lead + Low FDD. Estimates include UNISON. Exact A/B fingerprints match commit ba2681b on all six songs.

| Song | FDD steps A / B / C | Reversals A / B / C | FDD notes A / B / C | DVD notes A / B / C | C lowered / range fallback | C additional melody/bass losses |
|---|---|---|---|---|---|---|
| Thinking About You | 197089 / 120045 / 153796 | 2736 / 1665 / 2134 | 2899 / 2838 / 2152 | 1877 / 1912 / 1854 | 3 / 2149 | 0 |
| Creep (Acoustic) | 316734 / 166475 / 190648 | 4397 / 2310 / 2645 | 2836 / 2268 / 1657 | 744 / 1312 / 2031 | 24 / 1633 | 64 |
| Where I End and You Begin | 215466 / 73178 / 61428 | 2990 / 1013 / 850 | 3862 / 3575 / 981 | 327 / 610 / 3082 | 368 / 613 | 0 |
| Jigsaw Falling Into Place | 236819 / 182072 / 136879 | 3287 / 2527 / 1900 | 3201 / 2536 / 1357 | 1581 / 2076 / 2413 | 152 / 1205 | 0 |
| Airbag | 174833 / 69265 / 60614 | 2427 / 961 / 839 | 2980 / 2431 / 578 | 473 / 1018 / 2549 | 289 / 289 | 0 |
| 2+2=5 | 155654 / 108150 / 102573 | 2160 / 1500 / 1422 | 2918 / 2382 / 1184 | 1012 / 1565 / 2638 | 70 / 1114 | 2 |

All C plans remain physically feasible in the configured model. UNISON on/off keeps primary events identical. Peak DVD polyphony never exceeds three. Melody/bass loss counts refer to IDs played in Balanced and missing in C, not just differences in aggregate counts. Creep labels most notes as bass, so the 64 losses are classified bass events; all classified lead events remain. In 2+2=5, two additional previously played lead events are lost despite the same aggregate lead count. Many harmony/motif events are also lost; the JSON separately lists musicallyImportantLostVsBalanced using the C salience heuristic. This preset is not established as musically better.

## FDD Riffs + DVD Tło

### Software comparison

Reproduce with `.venv/bin/python scripts/compare_instrument_roles.py`.
Full results and MIDI hashes: `reports/instrument-roles.json`.

| Song / metric | Balanced | New preset |
| --- | ---: | ---: |
| Bodysnatchers: longest FDD hold | 7.676 s | 0.173 s |
| Bodysnatchers: dropped tonal notes | 169 | 159 |
| Every Breath You Take: long source notes assigned to DVD | 248 | 280 |
| Every Breath You Take: longest FDD hold | 3.949 s | 0.275 s |
| Every Breath You Take: dropped tonal notes | 0 | 0 |
| Overlapping reservations, either song | 0 | 0 |

Compiled speaker and percussion commands are identical across presets in
both comparisons. In that allocation-refinement comparison (before the stronger
background articulation below), longest planned continuous DVD periods are 11.780 s for
Bodysnatchers (previously 9.994 s) and 13.435 s for Every Breath You Take.
These measurements describe software schedules, not measured motor behavior.

### Background-tail regression

`reports/instrument-roles-refinement.json` compares the previous preset with
this refinement using the same three enabled DVD devices. DVD4 was disabled
when these measurements were recorded. The current registry enables all four;
the historical comparison below still describes three voices.

At 188.570976 s in Bodysnatchers, the shorter 5.708 s Thom guitar layer used
to occupy DVD1–3, while the 11.423 s Ed background became short FDD attacks.
The three Ed notes now hold on DVD1–3 until 199.993568 s. Compiled execution
commands cover the previously missing tail around 3:14–3:20.

After 2:00, silence of all DVDs while at least one long accompaniment note
exists in the source decreases from 16.333 s to 12.756 s. This is an aggregate
occupancy measure, not a guarantee that every background voice is represented.
Three enabled DVD voices still have finite polyphony. Real source pauses are
preserved, and independent FDD phrases remain short.


### Background sustain — porównanie

W tym porównaniu komendy FDD, perkusji i speakerów były identyczne. Oba
wyjścia korzystały ze wspólnego timeline, a firmware zmieniał cel Hz bez STOP.

Reproduce with `.venv/bin/python scripts/compare_dvd_background_sustain.py`.
Results: `reports/dvd-background-sustain.json`. Both columns use the same refined
Instrument Roles allocation with three enabled DVD devices at measurement time;
only the DVD articulation differs. The current registry enables DVD4 as well.

| Metric | Previous dynamic sustain | Background sustain |
| --- | ---: | ---: |
| Bodysnatchers: compiled DVD STOPs | 775 | 499 |
| Bodysnatchers: longest continuous DVD run | 11.780 s | 17.494 s |
| Bodysnatchers: dropped notes | 159 | 159 |
| Every Breath You Take: compiled DVD STOPs | 430 | 212 |
| Every Breath You Take: longest continuous DVD run | 13.435 s | 28.814 s |
| Every Breath You Take: dropped notes | 0 | 0 |
| Overlapping reservations, either song | 0 | 0 |

Work/silence metrics sum across DVD actuators, while the longest run is for one
actuator. These longer continuous periods require physical thermal verification;
the software comparison does not establish safe unlimited motor duty.

### FDD grace attacks over DVD beds

Reproduce with `.venv/bin/python scripts/compare_dvd_grace_sustain.py`;
results are in `reports/dvd-grace-sustain.json`. This comparison uses four
enabled DVDs and the previous committed background policy (`f7bd18e`) against
the grace-attack refinement, with identical allocation and configuration.

| Metric | Previous background sustain | Grace-aware background sustain |
| --- | ---: | ---: |
| Bodysnatchers: DVD STOPs at 2:15–2:18 | 11 | 3 |
| Bodysnatchers: total DVD STOPs | 542 | 426 |
| Bodysnatchers: DVD notes | 949 | 949 |
| Bodysnatchers: DVD work, sum across motors | 466.432 s | 487.836 s |
| Bodysnatchers: silence between DVD notes, sum across motors | 266.400 s | 244.995 s |
| Bodysnatchers: longest continuous DVD run | 17.137 s | 17.137 s |
| Bodysnatchers: dropped notes | 94 | 94 |
| Every Breath You Take: total DVD STOPs | 284 | 284 |
| Every Breath You Take: longest continuous DVD run | 28.814 s | 28.814 s |
| Every Breath You Take: dropped notes | 0 | 0 |
| Overlapping reservations, either song | 0 | 0 |

The eight removed stops in the target window were caused by 8.929 ms FDD
ornaments interrupting 184.523 ms DVD release gaps. The remaining three stops
are preserved source-part handoffs. All primary allocations, non-DVD execution
commands and optional reservations remain identical. Full physical chronologies
pass for both songs; thermal safety still requires physical measurements.

## Pary FDD

### Initial comparison, four enabled FDD and four DVD

| Song / metric | Existing preset | Pairs Unison | Pairs Duet |
| --- | ---: | ---: | ---: |
| Bodysnatchers: physical FDD attacks | 6137 | 3972 | 3972 |
| Bodysnatchers: distinct selected FDD source notes | 6137 | 1986 | 3064 |
| Bodysnatchers: FDD1 / FDD2 attacks | 1956 / 1586 | 1069 / 1069 | 1069 / 1069 |
| Bodysnatchers: FDD3 / FDD4 attacks | 1490 / 1105 | 917 / 917 | 917 / 917 |
| Bodysnatchers: all omitted source notes | 94 | 4245 | 3167 |
| Bodysnatchers: DVD STOPs | 426 | 426 | 426 |
| Every Breath You Take: physical FDD attacks | 1582 | 2522 | 2512 |
| Every Breath You Take: all omitted source notes | 0 | 321 | 250 |
| Every Breath You Take: DVD STOPs | 284 | 284 | 284 |
| Overlapping reservations, either song | 0 | 0 | 0 |

A unison copy increases the number of physical attacks but does not preserve
an additional source note. Thus the paired presets deliberately omit more
MIDI voices in dense music; they are alternate arrangements, not a way to
retain all four independent FDD voices. On Bodysnatchers, duet retains 1078
more FDD source notes than unison at the same number of physical attacks.
The non-FDD compiled commands are identical in all three variants for both
songs. DVD's longest continuous run remains 17.137 s on Bodysnatchers and
28.814 s on Every Breath You Take; thermal safety is unmeasured.

## Airbag — ograniczenie ataków FDD

### Airbag regression

The supplied MIDI has repeated A notes from 94.285620 s, with attacks as close
as 44.643 ms and source gates around 29.762 ms. The old physical model emitted
a soft `NOTE_CHANGE_RATE` quality penalty; that did not prevent rapid attacks.

Run `.venv/bin/python scripts/compare_fdd_attack_rate.py /path/to/Airbag.mid`.
Add `--all-presets` to benchmark every available preset. The default compares
Balanced and the reported Pairs Duet preset using their complete, unchanged
allocations before/after the shared final pass. Results and MIDI hash:
`reports/fdd-attack-rate-airbag.json`.

| Airbag 1:34–1:40 | Before | After |
| --- | ---: | ---: |
| Pairs Duet: FDD attacks, sum across four drives | 284 | 152 |
| Pairs Duet: intervals below 120 ms | 206 | 0 |
| Pairs Duet: shortest attack interval per drive | 44.643 ms | 133.928 ms |
| Balanced: FDD attacks, sum across four drives | 175 | 105 |
| Balanced: intervals below 120 ms | 108 | 0 |
| Balanced: shortest attack interval per drive | 29.762 ms | 133.928 ms |

Both complete-song comparisons have zero intervals below 120 ms after the pass,
valid full FDD physical chronologies and identical non-FDD execution commands.
Tests also exercise all presets and strict routing, repeated/variable pitches,
real rests, unison copies, source immutability and mechanical extension vetoes.
Listening on the real drives remains necessary to tune the musical threshold.

## Levels — oddzielenie efektów nietonalnych

### Recorded comparison

`reports/levels-unpitched-effects.json` records the supplied Levels file and
its SHA-256. With the same default Balanced / Mechanical-Aware inventory:

| Levels metric | Before | After |
| --- | ---: | ---: |
| Compiled tones originating from GM noise | 80 | 0 |
| Played tonal notes, excluding noise triggers | 3310 | 3312 |
| Dropped tonal notes, excluding noise triggers | 40 | 38 |
| Played percussion hits | 1050 | 1050 |
| Overlapping device reservations | 0 | 0 |

The 261.626 Hz event at 34.285680 s and 130.813 Hz events at 40.476150 s
and 41.904720 s are now explicitly omitted. All 581 noise triggers are
accounted for, including the 500-note Breath Noise layer previously hidden
by tonal duplicate normalization. No previously played tonal note is lost
in this Levels comparison.

Every Breath You Take has no recognized noise programs and produces an
identical compiled timeline. Counting Stars loses 14 spurious noise tones;
its greedy allocator also changes some late accompaniment choices: tonal
drops become 166 instead of 165 (three previously retained notes are lost,
two previously dropped notes are recovered). All device reservations remain
non-overlapping. This is reported explicitly; removing a competing source
does not guarantee globally optimal allocation by the existing allocator.

## Adaptive Legato — 2026-10-26 (offline)

New opt-in `adaptive_legato`, compared with unchanged `fdd_legato` using the
same registry and source files. The union of `~/Music/MIDI` and repository
`midi/` contained 470 paths / 161 SHA-256-unique files. All paths were inventoried;
identical content was planned once per preset. 160 files completed both plans.
`touhou4.mid` failed source parsing (`list index out of range`); it was not
counted as a successful arrangement. No song-name-specific rules were used.

Reproduce with:

```sh
.venv/bin/python scripts/benchmark_adaptive_legato.py \
  --midi-dir ~/Music/MIDI --midi-dir midi
```

[Full per-file results and aliases](../../reports/adaptive-legato-library.json).
The script asserts complete compiled non-FDD timeline equality, no overlapping
reservations, no modeled mechanical conflicts and no FDD onset-spacing violations.
All 160 readable files passed those checks. It does not measure sound quality.

| MIDI | Primary FDD attacks: Legato → Adaptive | Compiled FDD STOP: Legato → Adaptive | Longest continuous FDD, s: Legato → Adaptive |
| --- | ---: | ---: | ---: |
| Bodysnatchers | 1486 → 2270 | 768 → 1781 | 175.708 → 11.423 |
| Let Down | 1300 → 1690 | 873 → 1289 | 39.832 → 39.832 |
| No Surprises | 804 → 1275 | 628 → 1164 | 24.067 → 12.762 |
| Somebody That I Used to Know | 1980 → 2014 | 1378 → 1606 | 27.766 → 27.407 |
| Popcorn | 1676 → 2047 | 329 → 688 | 136.000 → 31.875 |

Across the readable corpus, primary FDD attacks increased from 108,623 to
158,067; compiled STOPs including partner reinforcement increased from 54,012
to 117,430. These are different populations: primary counts exclude copies,
STOP counts include them. More retained attacks are not proof of better motif
recognition, and more stops may reintroduce objectionable mechanical noise.
The longest continuous run decreased from 302.614 s (The National Anthem) to
231.544 s (Dollars and Cents). Neither duration is a thermally verified limit.

The new profile keeps later repeated source pitches eligible during selection,
protects locally detached/repeated short attacks, and uses legato for flowing
material. It operates on the already allocated FDD pool; omitted source voices,
lead identification, speaker routing and octave folding are not solved by this
experiment. No automatic "MIDI suitability percentage" is claimed. No MIDI was
used as an acoustic validation set: this run checks software and explicitly
requires subsequent REAL listening before judging improvement.

Validation: 836 host tests, 129 frontend tests, frontend production build passed.
Docker `orchestra` rebuilt and healthy; served bundle includes the new preset.
No firmware changes, uploads, power commands or actuator tests were performed.
