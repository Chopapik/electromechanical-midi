# Orkiestra elektromechaniczna

Lokalny odtwarzacz MIDI: Python/FastAPI, React/TypeScript i ESP32-WROOM-32.
14 urządzeń: **4 FDD, 4 DVD stepper, PC Speaker, PC Speaker FX, 4 HDD VCM**.
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
Pary Dwugłos, FDD Quality, FDD Quality Adaptive, DVD Lead + Low FDD.
Wybór zatrzymuje odtwarzanie i przebudowuje plan. Opisy i kompromisy:
[aranżacja](docs/ARRANGEMENT.md).

## Dokumentacja

- [Indeks, źródła prawdy, badania i archiwum](docs/README.md)
- [Połączenia i zasilanie](docs/HARDWARE_WIRING.md)
- [Urządzenia, zakresy i kalibracja](docs/HARDWARE_DEVICES.md)
- [Uruchamianie sprzętu, testy i awarie](docs/HARDWARE_TESTING.md)
- [Architektura, obsługa aplikacji i środowisko developerskie](docs/ARCHITECTURE.md)

DVD: proponowane **3,3 V na VM DRV8833**, wymagające pomiaru prądu i temperatury.
Zasilanie i rezystory obu sterowników speakerów pozostają do ustalenia.
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
