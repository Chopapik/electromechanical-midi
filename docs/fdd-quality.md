# FDD QUALITY — eksperymentalny preset aranżacji

## Wybór i bezpieczeństwo

W istniejącym widoku **Arrangement · PerformancePlan** można wybrać **Balanced** albo **FDD Quality · eksperymentalny**. Domyślnie aplikacja startuje w Balanced. Wybór obowiązuje dla kolejnych plików w bieżącej sesji backendu; nie zapisuje konfiguracji użytkownika na dysku.

Zmiana przechodzi przez akcję WebSocket `arrangement_preset`. `Application.set_preset` sprawdza nazwę i zajętość DeviceService, zatrzymuje Player oraz potwierdza STOP REAL / anulowanie Web Audio, a dopiero potem generuje plan. Zwiększa revision i nie wznawia odtwarzania. Błąd STOP blokuje zmianę; błąd planowania przywraca wcześniejszy preset, pozostawiając wykonanie zatrzymane.

Oba wyjścia wykonują ten sam PerformancePlan i skompilowaną oś czasu. Router oraz firmware nie podejmują decyzji selekcyjnych.

## Strategia

Nowy moduł `playback/fdd_quality.py` dodaje ocenę kandydatów w istniejącym `allocate_hardware`. Nie tworzy drugiego allocatora. Gałęzie jakościowe uruchamiają się wyłącznie przy `arrangementPreset=fdd_quality`.

Wartość muzyczna 0–1 uwzględnia rolę, velocity, wejście frazy, pozycję na bicie i początku taktu, podstawowy ton akordu na mocnej części taktu oraz ruch wysokości w lokalnym motywie. Tempo i metrum pochodzą z MIDI. Normalizacja istniejących duplikatów pozostaje aktywna. Lead i bas oraz wejścia fraz/motywy nie podlegają opcjonalnemu odrzuceniu tylko ze względu na koszt FDD.

Koszt konkretnej głowicy uwzględnia docelową częstotliwość po dotychczasowym foldingu, liczbę kroków, dotychczasowe `away_steps` i kierunek, przewidywane zawrócenia, opóźnienie zawrócenia, kroki w lokalnym oknie frazy, ciągłość aktywności, gęstość i odpoczynek. Krótka nuta przy końcu zakresu może zawracać. To estymacja przestrzeni poleceń, nie pomiar fizycznej pozycji głowicy.

Koszt obniża wynik FDD. Wolny DVD może wygrać jako alternatywa; nie ma stałego przypisania ścieżek. Mniej istotna nuta o wartości poniżej 0.65 i koszcie powyżej 0.85 może nie dostać FDD, ale nadal próbuje DVD. Ważne nuty zachowują możliwość użycia FDD pomimo wysokiego kosztu. Istniejące reguły konkurencji o DVD i ochrony leadu/basu obowiązują nadal.

Długość FDD powyżej preferowanych 350 ms skraca się miękko: zachowujemy preferowaną część plus 70% nadmiaru dla ważnej nuty lub 20% dla opcjonalnej. Nie jest to twardy limit 350 ms. Późniejsza mechaniczna artykulacja i source continuity nie przedłużają FDD w tym presecie. DVD/VHS zachowują dotychczasową artykulację. Końcowe czasy w planie, symulacji i sterowaniu są identyczne.

## Parametry istniejącej polityki orkiestry

| Parametr | Wartość początkowa |
|---|---:|
| `arrangementPreset` | `balanced` / `fdd_quality` |
| `fddQualityPreferredNoteMs` | 350 |
| `fddQualityPhraseSteps` | 240 |
| `fddQualityReversalCost` | 0.35 |
| `fddQualityDensity` | 0.55 |
| `fddQualityWindowMs` | 2000 |
| `fddQualityRestMs` | 120 |
| `fddQualityCostWeight` | 0.65 |
| `fddQualityExtensionPenalty` | 0.4 |
| `fddQualityOptionalPriority` | 0.65 |
| `fddQualityOptionalCost` | 0.85 |
| `fddQualityUnisonPriority` | 0.8 |
| `fddQualityUnisonDuty` | 0.12 |

Parametry należą do `OrchestraConfig.policy`; można je ustawić w `config/devices.json` → `parameters`. Gęstość, kroki i odpoczynek są składnikami oceny, nie sztywnymi limitami liczby nut/s.

UNISON zachowuje dowolną parę FDD, dokładną wysokość/start/długość oraz pełną walidację rezerwacji. Wymaga dodatkowo wartości ≥0.8 i niskiego kosztu docelowego FDD. Łączny czas opcjonalnych zdwojeń jest ograniczony do 12% długości utworu. Rezerwacje niezależnych głosów są ustalane wcześniej i nie są zmieniane.

## Diagnostyka

`report.fddQuality` podaje nuty, czas, średnią długość, kroki, zawrócenia, pominięcia, przejęcia przez DVD i UNISON. Czas aktywności i estymacja kroków/zawróceń obejmują UNISON; `fddPrimarySeconds` i średnia odnoszą się do nut podstawowych. Liczba nut FDD oznacza niezależne nuty, nie dodatkowe zdwojenia.

Przejęcie DVD w UI oznacza lokalną decyzję, w której dostępna alternatywa FDD miałaby wyższy wynik bez kary jakościowej. Nie zaliczamy automatycznie wszystkich długich nut DVD jako przejęć. Koszt i wartość każdej rozważanej nuty są dostępne w `event.hardware.candidates[device].musical.fddQuality` oraz w wyborze końcowym. Wartości fizyczne pozostają oznaczone jako estymacje.

Nie zmieniono pitchRatio DVD 1–3 (0.5, hipoteza LOW), ciągłego obrotu, ramp, STOP, watchdoga, parametrów elektrycznych ani GPIO. Nie wprowadzono obniżenia oktawy FDD ani DVD Lead.

## Weryfikacja i A/B

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

## Wyniki lokalnego porównania A/B

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
