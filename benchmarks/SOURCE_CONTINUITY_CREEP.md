# SOURCE CONTINUITY — test Creep

## Cel i przełącznik

ORCHESTRA → Note length → SOURCE CONTINUITY · sustain in free gaps.
Poprzedni BALANCED jest zachowany; nowy tryb jest opcjonalny i niezależny od
Tonal sound. Porównanie używa EXTREME v2 po obu stronach.

## Wykonanie

Po normalnej alokacji i dotychczasowym sustain FDD, przed reinforcement,
pass przedłuża actual_duration do oryginalnego source NOTE_OFF, jeśli actuator
ma wolne miejsce. Granica to kolejny PRIMARY minus max(3 ms, retrigger urządzenia),
a dla tego samego pitch także minimalna przerwa ARTICULATION_S.
Explicit SHORTENED pozostaje nietknięte. Nie skraca istniejącego gate, nie
przenosi nuty między urządzeniami, nie zmienia NOTE_ON/pitch/outcome/source danych.
To rzeczywiste wydłużenie wykonania w PerformancePlan: audio i sprzęt czytają
te same długości. Nie jest to dodatkowy reverb/tail ani ukryta polifonia.
Reinforcement liczy się ponownie z aktualnych wolnych miejsc istniejącym kodem.
Zmiana przełącznika przebudowuje plan z keep_position=True.

## Creep: wyniki

| Partia | Mediana gate BALANCED / CONTINUITY ms | Suma voice-time BALANCED / CONTINUITY s | Pokrycie źródłowego czasu aktywności |
|---|---:|---:|---:|
| Guitar 1 | 190.00 / 323.09 | 128.39 / 539.63 | 45.05% → 98.39% |
| Guitar 2 | 69.52 / 69.52 | 121.54 / 245.58 | 51.33% → 100.00% |

Pokrycie mierzy przecięcie unii wykonanych gate'ów z unią aktywnych nut źródłowych,
nie poziom głośności ani pełną zgodność wszystkich głosów akordu. 98% ciągłości
partii nie oznacza zachowania 98% source voice-time: ograniczona polifonia nadal
skraca część poszczególnych głosów. Łączny voice-time liczy równoległe głosy
oddzielnie, więc może przekroczyć długość utworu. Guitar 2 zachowuje wcześniejsze
mechaniczne wydłużenia krótkich nut, dlatego wykonany czas może przekraczać
źródłowy. Nowy pass sam nie wydłuża poza oryginalny NOTE_OFF.

W obu planach PRIMARY: 4525 played, 0 dropped. Skrypt porównuje wszystkie pola
normalnych zdarzeń poza actual_duration/sustain_added: identyczne IDs, routing,
pitch, onsety, outcomes i dane źródłowe. Sprawdza brak kolizji normalnych gate'ów
na actuatorze i brak mutacji planu przez renderer. To poprawa mierzonej ciągłości;
muzyczne odczucie należy ocenić odsłuchem.

## WAV A/B

Ten sam pełny przedział czasu, identyczny gain×1, EXTREME v2 i skład orkiestry.
Zero indywidualnej normalizacji i zero clippingu. Solo jest filtrowane po pełnym
scheduling actuatorów, bez oddawania wolnych głosów; tylko normalna dana gitara.

- Guitar 1 balanced: /tmp/source-continuity/creep-guitar1-balanced.wav
- Guitar 2 balanced: /tmp/source-continuity/creep-guitar2-balanced.wav
- full balanced: /tmp/source-continuity/creep-full-balanced.wav
- Guitar 1 continuity: /tmp/source-continuity/creep-guitar1-continuity.wav
- Guitar 2 continuity: /tmp/source-continuity/creep-guitar2-continuity.wav
- full continuity: /tmp/source-continuity/creep-full-continuity.wav

Powtórzenie: `.venv/bin/python scripts/benchmark_source_continuity.py`.
Szczegóły i porównanie końcowego PCM: `benchmarks/source-continuity-creep.json`.
400 testów backendu i 71 frontendowych: PASS; build z typecheck: PASS.
Testy nowego passu obejmują granicę następnego PRIMARY, source end przy delay,
SHORTENED/drop/percussion, idempotencję oraz zachowanie pozycji podczas zmiany.
Aplikacja została zrestartowana. Bez commita.

## Wersja 1.5 i ustawienia startowe

Dodano SOURCE CONTINUITY 1.5 (sourceContinuityAmount=0.5): wykonany gate dostaje
połowę możliwego dodatkowego wydłużenia, z tą samą granicą kolejnego PRIMARY.
Dla Creep mediana Guitar 1 wynosi 256.543 ms, suma voice-time 334.009 s;
normalne przypisania, onsety i outcomes są identyczne, PRIMARY 4525 played / 0 dropped.
Pełne SOURCE CONTINUITY (amount=1) pozostaje dostępne.

TONAL EXTREME 1.5 interpoluje attack/decay/sustain/release/brightness/transient
po 50% pomiędzy v1 i v2. Renderer używa jednej pośredniej obwiedni z mieszaniną
50/50 istniejących mechanicznych carrierów v1/v2. Nie zmienia fizycznego gate.

Zgodnie z zatwierdzonym zrzutem ekranu domyślny start webowej aplikacji używa:
masterVolume=19.5, tonalMode=extreme_v15, sourceContinuity=true,
sourceContinuityAmount=1, hddMode=articulated, dvdMode=reinforcement,
trayEnabled=true, idleReinforcement.enabled=false, enabled=true.
To pełna ciągłość oraz brzmienie 1.5; skrócona ciągłość 1.5 jest opcją ręczną.
Domyślne wartości pochodzą z web_startup_config i są aplikowane w server.main;
jawne presety oraz ręczne zmiany pozostają możliwe. Testy końcowe:
404 backendu, 71 frontendowych, build/typecheck PASS.
