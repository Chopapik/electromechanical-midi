# Orkiestra elektromechaniczna

Lokalny odtwarzacz MIDI: Python/FastAPI, React/TypeScript i ESP32-WROOM-32.
Katalog hosta: **18 urządzeń — 8 FDD, 4 DVD stepper, 4 HDD VCM, 2 PC Speakery**.
Aktywne jest **18: 8 FDD, 4 DVD, 4 HDD i oba speakery**.
Docelowe okablowanie i firmware: **8 FDD + 4 DVD + 4 HDD + 2 speakery / 6 × SN74HC595N / 6 wykorzystywanych DRV8833**;
Q32–Q39 pozostają wolne, HDD zachowują Q40–Q47. FDD5–8 uczestniczą w aranżacji i są zadeklarowane
jako podłączone; REAL wymaga homingu i potwierdzenia TRACK0.
ATX: `/settings` → **Zasilanie ATX**, domyślnie OFF po restarcie ESP32; status jest logiczny, bez pomiaru napięcia.
REAL steruje przez BLE, VIRTUAL gra przez Web Audio. Oba wykonują jeden
`ExecutionTimeline`; brzmienie symulacji nie jest pomiarem sprzętu.

```text
MIDI → Arranger → PerformancePlan → ExecutionTimeline → Player → Router → REAL / VIRTUAL
```

## Uruchomienie

```sh
docker compose up -d --build orchestra
docker compose ps orchestra
```

Otwórz <http://localhost:5173>. Na macOS uruchom również natywną
[bramkę BLE](docs/ARCHITECTURE.md#uruchamianie).
Do odsłuchu bez kontrolera uruchom Compose z `ORCHESTRA_OFFLINE=1`, następnie
wybierz `/settings` → **Output → Virtual debug · Web Audio**.
Aplikacja startuje w REAL również offline; samo offline nie przełącza wyjścia.

Presety wybierasz w `/settings` → **Aranżacja → Preset aranżacji**:
Universal, Balanced / Mechanical-Aware, FDD Riffs + DVD Tło, Pary Unisono,
Pary Dwugłos, **2×4 FDD Unisono · eksperymentalny**, FDD Quality, FDD Quality Adaptive, DVD Lead + Low FDD.
Domyślnie uruchamia się **2×4 FDD Unisono · eksperymentalny**: dwa logiczne głosy FDD,
dobór partii Universal, długie tło DVD, osobne wokal/FX i preferowane role HDD.
Porównanie całej lokalnej biblioteki: [benchmark](docs/research/universal-arrangement.md#biblioteka-8-fdd-2026-10-21).
Główny PC Speaker
ma transpozycję 0, czyli oktawę niżej niż wcześniejsze +12, niezależnie od presetu.
Wybór zatrzymuje odtwarzanie i przebudowuje plan. Opisy i kompromisy:
[aranżacja](docs/ARRANGEMENT.md).

## Dokumentacja

- [Indeks, źródła prawdy, badania i archiwum](docs/README.md)
- [Połączenia i zasilanie](docs/HARDWARE_WIRING.md)
- [Urządzenia, zakresy i kalibracja](docs/HARDWARE_DEVICES.md)
- [Uruchamianie sprzętu, testy i awarie](docs/HARDWARE_TESTING.md)
- [Architektura, obsługa aplikacji i środowisko developerskie](docs/ARCHITECTURE.md)

DVD i HDD: użytkownik zgłasza poprawną pracę przy **5 V na VM DRV8833**
z dobrym odprowadzaniem ciepła, np. do metalowej obudowy VHS pełniącej też
rolę pudła rezonansowego. To obserwacja tego montażu; prąd, temperatura
i dopuszczalny czas ciągłej pracy wymagają pomiarów.
Speakery: zgłoszone połączenie S8550 PNP, 3,3 V, baza 330 Ω z pull-up 10 kΩ
i szeregowo 56 Ω; moc rezystorów i impedancja głośników wymagają potwierdzenia.
Szczegóły oraz status dowodów znajdują się w dokumentacji sprzętowej.

## Sprawdzenie oprogramowania

```sh
.venv/bin/python -m unittest discover -s host/tests -q
npm --prefix web test
npm --prefix web run build
.venv/bin/python scripts/generate_hardware_profiles.py --check
```

Zależności i alternatywa testów w Dockerze: [architektura](docs/ARCHITECTURE.md#testy).
Firmware ESP32: `pio run -d firmware/controller -e esp32`.

<a id="fizyczna-kalibracja-fdd"></a>
Zachowany odnośnik proweniencji kalibracji: [wyniki pomiarów FDD](docs/research/hardware-measurements.md#fdd).

Upload ESP32 wyłącznie przez Settings → Serwis albo
`.venv/bin/python scripts/safe_upload.py`: wspólna procedura wymaga potwierdzonego
POWER OFF. Stary firmware wymaga osobno zatwierdzonego ręcznego bootstrapu;
[procedura i ograniczenia zasilania](docs/HARDWARE_TESTING.md#firmware-i-sama-logika).
