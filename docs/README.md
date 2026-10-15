# Dokumentacja projektu

Aktualny punkt wejścia: [README projektu](../README.md). Kod i konfiguracja są
źródłem prawdy. Instrukcje poniżej opisują bieżący runtime; raporty pomiarowe,
benchmarki i archiwalne UI zachowujemy z kontekstem ich powstania. Liczebności
testów i wyniki tabel w starszych raportach nie opisują automatycznie tej wersji.

## Urządzenia i wykonanie

- [ESP32, GPIO, Q0–Q39, zasilanie, USB i BLE](esp32-orchestra.md)
- [Profile fizyczne, walidacja i niepewności](hardware-first.md)
- [Laboratory: aktualna obsługa](instrument-lab.md)
- [PC Speaker i PC Speaker FX: routing, głośność, wypełnienie, fale](pc-speaker-fx.md)
- [DVD pitchRatio: hipoteza i obserwacje tunera](dvd-pitch-calibration.md)

## Aranżacja i analiza MIDI

Wybór wszystkich siedmiu presetów: `/settings` → **Aranżacja → Preset aranżacji**.
AUTO ma wspólną normalizację i klasyfikację oraz jeden plan dla REAL/VIRTUAL.
STRICT_TRACKS to osobny tryb JSON, a nie ósmy preset.

- [Balanced / Mechanical-Aware oraz dynamiczny UNISON](mechanical-arrangement.md)
- [FDD Riffs + DVD Tło i sustain tła](instrument-roles.md)
- [Pary FDD: Unisono i Dwugłos](fdd-pairs.md)
- [FDD Quality](fdd-quality.md)
- [FDD Quality Adaptive](fdd-quality-adaptive.md)
- [DVD Lead + Low FDD](dvd-lead-low-fdd.md)
- [Wspólne ograniczenie szybkich ataków FDD, regresja Airbag](fdd-attack-rate.md)
- [Zapisany eksperyment FDD o oktawę niżej](fdd-octave-experiment.md)
- [DVD Continuous Sustain](dvd-continuous-sustain.md)
- [Efekty nietonalne, regresja Levels](unpitched-effects.md)

Klasyfikacja (`host/playback/semantic.py`, `analysis.py`) korzysta z nazw,
programów GM, lyrics, rejestru, monofonii i zachowania nut. Role semantyczne to
VOCAL, BACKING_VOCAL, BASS, GUITAR, KEYS, STRINGS, PAD_SYNTH, PERCUSSION,
UNPITCHED_EFFECT i OTHER. Wagi dowodów nie są prawdopodobieństwami.
VOCAL może zastąpić heurystyczny lead dopiero przy wyniku ≥0,75 i przewadze ≥0,12;
sam napis „vocal” nie gwarantuje przydziału. Ozdobniki tonalne FX nie są szumem.
[Opis speakerów](pc-speaker-fx.md) wyjaśnia lyrics i dodatkową pulę FX;
[efekty nietonalne](unpitched-effects.md) opisują interpretację programów/banków.

Normalizacja double-trackingu jest w `host/playback/duplicates.py`; zachowuje
proweniencję źródłowych nut. Zdarzenia pominięte i ich powody zostają w planie.
Source Continuity (`articulation.py`) wypełnia dopuszczalne wolne fragmenty;
nie może odtworzyć skradzionej końcówki ani zająć rezerwacji innej nuty.
Presety Quality i Instrument Roles chronią własne krótkie gate'y FDD.
UNISON oraz idle reinforcement to jawne dodatkowe rezerwacje, a nie ukryta
polifonia urządzenia. Końcowy pass FDD może usunąć ataki także tych kopii.

## Benchmarki, badania i historia

- [Dane sprzętu, wcześniejsze UI/CLI i eksperymenty](hardware-and-history.md)
- [Model teoretyczny i źródła producentów](research/orkiestra-model-teoretyczny.md)
- [Historyczny raport wdrożenia hardware-first](hardware-first-implementation-report.md)
- [Historyczna weryfikacja ESP32 z 2026-10-06](esp32-verification.md)
- [Historyczny redesign workstation](workstation-redesign.md)
- [Audyt dryfu przed poprawką](diagnostics/mechanical-drift/REPORT.md)
- [Raport poprawki dryfu](diagnostics/mechanical-drift/FIX_REPORT.md)
- [Benchmark Source Continuity](../benchmarks/SOURCE_CONTINUITY_CREEP.md)
- [Artykulacja tonalna](../benchmarks/TONAL_ARTICULATION_REPORT.md),
  [Extreme](../benchmarks/TONAL_EXTREME_DIAGNOSTIC.md),
  [Extreme v2](../benchmarks/TONAL_EXTREME_V2_DIAGNOSTIC.md),
  [artykulacja HDD](../benchmarks/HDD_ARTICULATION_REPORT.md)

Surowe wyniki są w `reports/` i `benchmarks/`; polecenia odtwarzania są przy
konkretnych algorytmach. Wyniki zachowują ówczesny inventory (czasem trzy DVD),
politykę i hash MIDI. Obecny wspólny limit ataków, czwarty DVD oraz eksperyment
oktawy FDD mogą zmienić rezultat ponownego uruchomienia.
Nie regenerujemy dawnych raportów pod nową konfigurację podczas porządkowania
dokumentacji. Eksperyment oktawy FDD jest zapisany razem z jego konfiguracją
i testami; opis zawiera sposób powrotu do poprzedniego rejestru.
