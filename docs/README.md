# Dokumentacja projektu

[README projektu](../README.md) jest krótkim punktem wejścia.
Poniższe pięć dokumentów wraz z tym indeksem stanowią bieżącą dokumentację.
Audyt obejmuje wszystkie 31 śledzonych wcześniej plików Markdown, w tym AGENTS,
raporty w `benchmarks/`, diagnostykę oraz badanie teoretyczne.
Stan zweryfikowany względem lokalnego `main` po `cf51be4`, z uwzględnieniem
`8b6724f`, `98bad14`, `bc03c79`; nie tylko kodu dostępnego na GitHubie.

## Bieżące instrukcje

| Dokument | Właściciel informacji |
| --- | --- |
| [HARDWARE_WIRING.md](HARDWARE_WIRING.md) | Połączenia ESP32, 74HC595, pełne Q0–Q39, DRV8833, napędy, dwa S8050 i zasilanie |
| [HARDWARE_DEVICES.md](HARDWARE_DEVICES.md) | Inventory, profile, zakresy, kalibracja, mechanika i ograniczenia dowodów |
| [HARDWARE_TESTING.md](HARDWARE_TESTING.md) | Kontrola przewodów, boot, BLE, HOME, lab, STOP i diagnostyka awarii |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Jeden runtime MIDI → REAL/VIRTUAL, obsługa UI/API, uruchamianie i testy |
| [ARRANGEMENT.md](ARRANGEMENT.md) | Wspólna klasyfikacja, osiem presetów, Source Continuity, UNISON, sustain i recovery |

Czytaj schemat → urządzenia → testy przy budowie układu. Nie zastępuj brakujących
wartości zasilania/rezystorów parametrami znalezionymi w archiwum. Topologia jest
opisana od ESP32 do obciążeń, ale identyfikacja modeli FDD/modułów i elementów
mocy speakerów pozostaje konieczna do bezpiecznego uruchomienia całości.

## Źródła prawdy i rozstrzygnięte sprzeczności

Kod i aktywna konfiguracja mają pierwszeństwo przed opisem i historycznym raportem.
Nie zmieniono ich podczas refaktoryzacji dokumentacji.

| Temat | Wynik audytu | Źródło implementacji |
| --- | --- | --- |
| Skład | 14 aktywnych urządzeń, w tym cztery DVD i dwa speakery | [devices.json](../config/devices.json) |
| FDD | Aranżacja −12 / 100–205 Hz; profil 100–410 Hz; wejście firmware 40–500 Hz; osobny STEP ≥2439 µs | [profile](../config/hardware-profiles/instances.json), [stałe firmware](../firmware/controller/include/hardware_profiles_generated.h) |
| DVD | Ciągły obrót, bez dawnego limitu 140 kroków i whitelisty; muzyczny sufit 600 Hz | [interpretacja profili](../host/playback/hardware_profiles.py), [allocator](../host/playback/hardware_arranger.py) |
| Zasilanie DVD | 3,3 V to robocza propozycja na **VM silników**, bez potwierdzonej kwalifikacji termicznej | [obserwacje](research/hardware-measurements.md#dvd) |
| HDD | Fizyczny profil HDD_PERCUSSION i 40/40/4 ms; nazwa profilu brzmienia nie oznacza innego impulsu REAL | [profile](../config/hardware-profiles/theoretical.json), [firmware](../firmware/controller/include/orchestra_core.h) |
| UI i wyjście | `/` i `/settings`, ESP32 BLE, wspólny ExecutionTimeline, VIRTUAL Web Audio | [runtime](../host/runtime/application.py), [UI](../web/src/App.tsx) |
| DIAG BIT | Wyłącznie bez podłączonych urządzeń; reset logiki przy odłączonej mocy przywraca także wolne Q | [dispatcher](../firmware/controller/include/orchestra_protocol.h) |

Wycofano powtarzane instrukcje z `esp32-orchestra.md`, `hardware-first.md`,
`pc-speaker-fx.md`, `instrument-lab.md` i osobnych opisów presetów.
Ich aktualne treści są w pięciu dokumentach powyżej. Zachowane wyniki i hipotezy
mają osobne miejsce poniżej. AGENTS.md pozostaje instrukcją pracy w repozytorium.

## Badania i zachowane wyniki

- [Pomiary FDD, obserwacja grzania DVD, hipoteza pitchRatio, HDD i speakery](research/hardware-measurements.md)
- [Eksperyment FDD o oktawę niżej](research/fdd-octave-experiment.md)
- [Porównania presetów, sustain Bodysnatchers, Airbag i Levels](research/arrangement-benchmarks.md)
- [Universal: 31 MIDI oraz pełna biblioteka 149 unikalnych plików](research/universal-arrangement.md)
- [Model teoretyczny i źródła producentów](research/orkiestra-model-teoretyczny.md)
- [Dryf wykonania: diagnoza](research/diagnostics/mechanical-drift/REPORT.md)
  i [raport poprawki](research/diagnostics/mechanical-drift/FIX_REPORT.md)
- [Source Continuity / Creep](research/benchmarks/SOURCE_CONTINUITY_CREEP.md)
- [Artykulacja tonalna](research/benchmarks/TONAL_ARTICULATION_REPORT.md),
  [Extreme](research/benchmarks/TONAL_EXTREME_DIAGNOSTIC.md),
  [Extreme v2](research/benchmarks/TONAL_EXTREME_V2_DIAGNOSTIC.md)
- [Artykulacja HDD](research/benchmarks/HDD_ARTICULATION_REPORT.md)

Surowe JSON/PNG pozostają pod dotychczasowymi ścieżkami `reports/`, `benchmarks/`
i `docs/diagnostics/`, używanymi przez generatory. Nie duplikujemy ani nie
regenerujemy danych w ramach porządkowania Markdown. Raporty mają poprawione
odnośniki do tych artefaktów. Hash starego przebiegu i dawna liczba testów opisują
snapshot; ponowne uruchomienie na nowym inventory nie jest tym samym pomiarem.
Pliki audio `/tmp` i lokalne biblioteki MIDI mogą być niedostępne w innym checkout.

## Archiwum

- [Dawny monolityczny README: Arduino UNO, dawne GPIO, UI/CLI i eksperymenty](archive/hardware-and-history.md)
- [Wdrożenie hardware-first](archive/hardware-first-implementation-report.md)
- [Weryfikacja ESP32 z 2026-10-06](archive/esp32-verification.md)
- [Historyczny redesign workstation](archive/workstation-redesign.md)

Archiwum zachowuje kontekst, wyniki i wcześniejsze decyzje. Nie jest instrukcją
montażu ani opisem bieżącego API. Informacje o wcześniejszym zasilaniu występują
wyłącznie jako kontekst badań/archiwum, nie zalecenia w głównym schemacie.

## Kontrola odnośników

Sprawdzono lokalne cele Markdown, kotwice i odnośniki do kodu/artefaktów oraz
podjęto próbę otwarcia wszystkich 32 unikalnych URL zewnętrznych. Aktualne karty
TI/Espressif są dostępne. Nie potwierdzono automatycznie sześciu historycznych
adresów: repozytorium PlayfulCreations/react-piano-roll, dwóch pakietów npm
(@tonejs/midi, @minagishl/react-piano-roll), projektu HDD na Hackaday i patentów
US8451564B2 / 6567232. Narzędzie zwróciło błąd pobrania, co nie dowodzi 404.
Załącznik Minebea na Parallax nie udostępnił czytelnego PDF w tej kontroli.
Zachowano te cytowania w badaniach/archiwum z tym zastrzeżeniem; nie są podstawą
bieżących nastaw ani instrukcji montażu.
