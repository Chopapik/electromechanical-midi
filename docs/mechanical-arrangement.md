# Balanced / Mechanical-Aware Arrangement

> Aktualna aplikacja: wybór presetu w **Settings → Aranżacja**; cztery aktywne DVD,
> dwa PC Speakery. Wszystkie presety mają wspólny [limit ataków FDD](fdd-attack-rate.md).
> Tabele benchmarków i liczby testów poniżej są zapisami wersji wskazanej przy
> pomiarze, nie gwarancją bieżących wyników. [Pełny indeks](README.md).

## Rzeczywista ścieżka wykonania

`runtime.arranger.arrange → allocate(hardware_context) → allocate_hardware → PerformancePlan → compile_plan → Router → REAL/VIRTUAL`.

Polityka znajduje się w istniejącym `OrchestraConfig.policy`, a zapisane ustawienia aplikacji w `config/devices.json` (`parameters`). Aktualny registry włącza cztery FDD, cztery DVD, PC Speaker i PC Speaker FX oraz cztery HDD; dwie tacki pozostają wyłączone. Typ/protokół VHS oznacza teraz PC Speaker. Wybór: **Settings → Aranżacja → Preset aranżacji → Balanced**.

## Wybór głosu

- DVD dostaje miękką premię za długość względem progu 500 ms, dłuższe sąsiednie nuty, powtarzanie wysokości i stabilny bas.
- FDD dostaje premię za krótsze nuty i częste zmiany wysokości. Ocena nadal uwzględnia zakres, zawracanie głowicy, gotowość, ewentualne składanie oktaw i opóźnienie.
- Kontekst liczy sąsiednie zdarzenia tej samej ścieżki i kanału. Równoczesne tony akordu nie są traktowane jako szybkie zmiany. Premia za poprzednie urządzenie ogranicza zbędne przerzucanie partii. Instrument nie jest przypisany na stałe do ścieżki.
- Preferencja jest miękka: wolny DVD może przejąć krótką nutę, a FDD dłuższą. Główny PC Speaker (typ VHS) jest dedykowany leadowi; osobny FX dostaje tonalne ozdobniki.
- DVD w trybie ciągłym zachowuje długość źródłową, nawet przy ustawionym `maxNoteSeconds` lub wyliczonym limicie adaptacyjnym.
- Gdy wszystkie odpowiednie głosy są zajęte, sustain DVD może zostać skrócony do początku konkurującej partii. Porównujemy priorytety; lead i bas są chronione dotychczasowym `stealMargin`. Dla pozostałych partii tolerancja 8 punktów pozwala oddać głos porównywalnie ważnej krótkiej nucie. Nie odtwarzamy skróconej końcówki w późniejszym passie artykulacji.

W ciągłym obrocie nie egzekwujemy historycznej drogi ani pasm DVD1; aktualny allocator składa tony powyżej 600 Hz akustycznych o oktawy. Ograniczenia czasu kroku, ocena przyspieszenia i STOP pozostają aktywne. Wynik modelu nie potwierdza stabilności akustycznej konkretnego silnika.

## Dynamiczny UNISON ×2

UNISON jest `ReinforcementEvent(kind='UNISON')` z `source_id` i `source_device`. Ma dokładnie wysokość, start, velocity i końcową długość źródłowej nuty FDD.

Domyślnie wymaga velocity ≥90 i długości wykonawczej 40–800 ms. Ważniejsze role mają pierwszeństwo przy wyborze akcentów. Dowolny wolny FDD może być drugim głosem; nie ma stałej pary.

Najpierw kończymy aranżację niezależnych nut. Następnie rezerwujemy cały interwał zdwojenia w tym samym planie. Każdy kandydat jest sprawdzany w pełnej chronologii urządzenia, wraz z wcześniejszymi zdwojeniami i przyszłymi nutami podstawowymi. Odrzucamy konflikt, brak fizycznej gotowości i pogorszenie wyniku jakości mechanicznej przyszłej nuty. W gęstym fragmencie wolnych rezerwacji zwykle nie ma. Nie powstają późne ani częściowe impulsy UNISON.

Parametry polityki:

| Parametr | Domyślnie |
|---|---:|
| `mechanicalAware` | true |
| `dvdSustainThresholdMs` | 500 |
| `mechanicalPhraseWindowMs` | 1500 |
| `mechanicalPreferenceWeight` | 0.8 |
| `partContinuityWeight` | 0.12 |
| `sustainCompetitionTolerance` | 8 |
| `fddUnisonEnabled` | true |
| `fddUnisonMaxVoices` | 2 (dopuszczalne 1 lub 2) |
| `fddUnisonMinVelocity` | 90 |
| `fddUnisonMaxDurationMs` | 800 |

## Podgląd i diagnostyka

W **Settings (`/settings`) → Aranżacja** rozwiń **Arrangement · PerformancePlan**. Tabela pokazuje źródłową partię, nutę po transpozycji/foldingu, instrument, start, długość wykonania, parę UNISON i decyzję. Dane są pobierane po rozwinięciu widoku; tabela jest stronicowana po 100 nut.

`GET /api/plan` udostępnia nuty, reinforcements i raport. `event.hardware.selection` opisuje kontekst i miękką ocenę muzyczną; `event.hardware.candidates` zawiera oceny kandydatów. `report.mechanicalArrangement` zawiera statystyki sustainu, wielosekundowych FDD i UNISON. Liczniki odrzuceń kandydatów w `hardware.counters` nie są liczbą odrzuconych nut utworu; właściwe odrzucenia są w `report.totals`.

## Historyczne porównanie MIDI

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

Glass Eyes i All I Need nie są dostępne lokalnie. Małe fixture'y sprawdzają sześciosekundowy akord sustainowy oraz rozdzielenie długiego tonu od wyzwalania perkusji na kanale 10. Nie rekonstruują tych utworów. Sama długość NOTE_OFF nie ujawnia czasu wybrzmienia próbki; nieznane brzmienie próbki na kanale tonalnym wymaga informacji o instrumencie i odsłuchu.

Raport można odtworzyć poleceniem:

```sh
.venv/bin/python scripts/compare_mechanical_arrangement.py
```

Pliki: `reports/mechanical-arrangement-baseline.json` i `reports/mechanical-arrangement-comparison.json`.

## Weryfikacja

- Testy backendu: 497.
- Testy frontendu: 43.
- Build frontendu: poprawny; istniejące ostrzeżenie o dużym bundle pozostaje.
- Testy pokrywają mieszane frazy na jednej ścieżce, powtórzenia, fallback, konkurencję, ochronę basu, dowolne pary FDD, przyszłe rezerwacje, gęstą polifonię, deterministyczność, API i identyczne komendy przekazywane do REAL/VIRTUAL z atrapami transportu.
- Firmware i GPIO nie zostały zmienione. Nie wykonywano flashowania ani testowego uruchamiania silników.
- Pełne chronologie czterech MIDI, wraz z UNISON, przeszły ponowną ocenę profili sprzętowych. Nieznane obciążenie fizyczne i degradacje jakości są jawnie zapisane w `physicalChronology` raportu.
- Docker przebudowany i uruchomiony ponownie; healthcheck `healthy`, API pokazuje trzy aktywne DVD, a UI serwuje nowy bundle z podglądem PerformancePlan. Odtwarzacz pozostaje zatrzymany.
