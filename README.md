# Orkiestra elektromechaniczna

Python / FastAPI + React / TypeScript. Docelowy kontroler: ESP32 przez istniejący BLE.

## Uruchamianie

```sh
docker compose up --build
```

Aplikacja: http://localhost:5173. Zawsze startuje w **REAL**. Gdy ESP32 jest offline,
import MIDI i planowanie działają, ale Play jest zablokowany. Połączenie BLE jest
ponawiane bez wznowienia utworu i bez automatycznego homingu.

Uruchomienie lokalne bez prób połączenia ze sprzętem (nadal startuje REAL):

```sh
.venv/bin/python -m host.web.server --offline --port 8000
```

Bez prób połączenia BLE w Dockerze: `ORCHESTRA_OFFLINE=1 docker compose up --build`.
Start nadal jest REAL; wyłączenie zmiennej przy następnym uruchomieniu przywraca próby BLE.

Virtual można włączyć ręcznie w Settings. Przeglądarka wykonuje te same komendy
przez Web Audio; nie ma WAV, ffplay ani wyjścia audio kontenera. Play wymaga
interakcji w przeglądarce. Zamknięcie karty lub utrata synchronizacji wycisza audio.

## Rdzeń

`MIDI → MidiSource → arrange → PerformancePlan → compile_plan → ExecutionTimeline
→ Player → Router → RealOutput / VirtualOutput`

- `host/runtime/arranger.py`: zachowane algorytmy allocatora, normalizacji,
  STRICT_TRACKS, artykulacji i profili; planowanie nie zależy od połączenia ani wyjścia.
- `compiler.py`: czyste uporządkowanie komend z czasem i stabilnym deviceId.
- `player.py`: jeden zegar monotoniczny, stan i właściciel wykonania; odrzucanie
  przeterminowanych nut, zatrzymanie i unieważnianie kolejek.
- `router.py`: dokładnie jedno wyjście oraz mute. STOP przechodzi także dla mute.
- `outputs.py`: adapter istniejącego protokołu BLE i pakiety Web Audio.
- `web/src/virtualOutput.ts`: planowanie z wyprzedzeniem 150 ms i synchronizacja
  zegara AudioContext z Playerem; unieważnianie epok i potwierdzane anulowanie.
- `laboratory.py`: skończone testy przez ten sam Player/Router i te same profile.
- `device_service.py`: wyłączny dostęp po STOP; firmware przez istniejący uploader
  USB, homing `FDD ALL HOME`. Reset przez BLE nie jest obsługiwany i jest niedostępny.

Aktywny REAL wymaga rzeczywistego `ALL STOP <token>` / `STOPPED <token>`.
Brak potwierdzenia lub utrata aktywnego połączenia oznacza nieznany stan sprzętu
oraz błąd przełączenia. Offline bez wcześniejszego wykonania nie wymaga STOP.
Zmiana wyjścia, właściciela, seek i STOP nie wznawiają automatycznie odtwarzania.

## Skład i kalibracje

Jedynym składem runtime jest `config/devices.json`: 4 FDD, 4 DVD, VHS, 4 HDD,
2 tacki. Stabilne ID i kolejność istniejących linii są zachowane. Tacki bez
potwierdzonej obecności pozostają widoczne i niedostępne. Kalibracje są odczytywane
z niezmienionych `config/hardware-profiles/theoretical.json` i `instances.json`.
Nie przenosimy wartości kalibracji do registry. Edycja składu i parametrów tylko
w JSON, po czym restart aplikacji. Mute jest wyłącznie bramką wykonania i nie
przepisuje planu. Zmiana JSON może zmienić plan.

`routing.mode` w JSON może mieć wartość `AUTO` lub `STRICT_TRACKS`; pole `tracks`
to cztery indeksy ścieżek FDD. Zachowano algorytm eksperymentu, usunięto jego panel.
Orkiestra i Laboratory używają tego samego registry również offline.

[Historyczne dane sprzętu, okablowania i kalibracji](docs/hardware-and-history.md).

## Weryfikacja

```sh
.venv/bin/python -m unittest discover -s host/tests -q
cd web
npm test
npm run build
```

Testy nowego runtime używają atrap BLE i zegara. Zachowano regresje algorytmów,
profili i protokołu; testy starego silnika/UI zastąpiono testami nowych kontraktów.
`host/tests/reference_audio.py` jest wyłącznie testowym wzorcem dawnych obliczeń
akustycznych, bez API odtwarzania. Nie jest importowany przez aplikację.

Diagnostyka: `/api/state`, `/api/plan`, `/api/timeline`, `/api/monitor/raw`.
Wizualizacja pokazuje planowane wykonanie, nie pomiar dźwięku ani ruchu sprzętu.
Komunikacja z fizycznym ESP32 BLE, homing i upload wymagają osobnej weryfikacji
sprzętowej. Migracja nie zmienia firmware, sterowników ani ich limitów mechanicznych.
