# Virtual Orchestra: DVD stepper i DVD tray

## Implementacja i sposób testowania

- Domyślnie: 4 FDD, 4 DVD_SLED, 4 HDD_VCM, 1 VHS, 2 DVD_TRAY. DVD mają identyfikatory DVD_STEPPER_1..4, tacki DVD_TRAY_1..2.
- Przed zmianą były już 4 DVD. Nie dodano kolejnych czterech. Zmiana domyślnego składu dodaje FDD4, HDD4 i dwie tacki.
- DVD pozostają niezależne; dynamic reinforcement działa na liście urządzeń dowolnej długości. Sprawdzono także pięć głosów.
- Tacki są reinforcement-only: wykluczone z tonalnej i głównej perkusyjnej puli. Pass kopiuje wyłącznie zagrane zdarzenia kanału 9 z nutami 49/55/57/59/46. Renderer nie wybiera routingu.
- Priorytet Crash/Splash > Ride > Open Hi-Hat. Sortowanie velocity, niezależne busy/recovery, 150 ms cooldown. Ride: velocity ≥75, odstęp ≥800 ms; hat: velocity ≥100, odstęp ≥1200 ms. Lookahead pomija ride/hat blokujący zbliżający się crash.
- Motion SHORT 80–120 ms, MEDIUM 140–200 ms, STRONG 200–300 ms; velocity steruje czasem i głośnością. Brzmienie: rozruch DC, whine/buzz, przekładnia/pasek i końcowy clack; deterministyczne różnice między silnikami.
- UI: ORCHESTRA → DVD mode oraz DVD tray mechanical accents. Statusy idle/moving/recovery, LED, GM/velocity/czas/strength w rozwiniętej karcie. DEVICE/SIMULATION VIEW: przerywany obrys kopii tray; SOURCE VIEW i licznik MIDI bez kopii.
- Zapisane jawne listy urządzeń zachowują własne identyfikatory i skład. Domyślny skład ma nowe nazwy; można używać Add/Duplicate/Remove i presetów. Liczby konfiguruje default_orchestra(dvd_count=5, tray_count=3, hdd_count=4) lub JSON devices.

## Metoda

Cały dostępny zbiór: 31 plików / 19 unikalnych SHA-256. Normalizacja duplikatów wewnątrz MIDI identyczna we wszystkich wariantach. Parametry allocatora i articulation identyczne.

- BEFORE: poprzedni skład 3 FDD / 4 DVD / 3 HDD / VHS, bez tacek.
- AFTER: docelowy skład 4 FDD / 4 DVD / 4 HDD / VHS / 2 tacki.
- Izolowane 3→4 DVD: docelowy skład, tylko liczba DVD zmieniona. Pozwala ocenić czwarty DVD, choć istniał już przed tym zadaniem.
- Tray ON/OFF: identyczne wszystkie normalne zdarzenia (pełne as_dict: urządzenie, start, duration, outcome, velocity itd.) i tonalne reinforcement. played/dropped nie zmieniają się.
- Utilization DVD = (normalny czas + reinforcement) / długość utworu. Tray = czas ruchu / długość utworu (bez recovery). Tacki mogą wydłużyć sam koniec podglądu o ogon ruchu; licznik nut pozostaje bez zmian.

## Cały zbiór: tonal

| Wariant | Requested | Played | Dropped | Drop rate | DVD reinforcement | Reinforcement s |
|---|---:|---:|---:|---:|---:|---:|
| before | 63143 | 58493 | 4650 | 7.36% | 10425 | 1655.890 |
| threeDvd | 63143 | 58489 | 4654 | 7.37% | 5012 | 765.095 |
| after | 63143 | 60266 | 2877 | 4.56% | 8380 | 1256.793 |
| afterTrayOff | 63143 | 60266 | 2877 | 4.56% | 8380 | 1256.793 |

### DVD utilization całego zbioru

| Wariant | DVD1 | DVD2 | DVD3 | DVD4 |
|---|---:|---:|---:|---:|
| before | 47.20% | 42.47% | 38.62% | 38.49% |
| after | 37.72% | 33.98% | 28.63% | 28.64% |

## Wyniki wszystkich unikalnych MIDI

Tonal: played/dropped/drop rate w BEFORE i AFTER; DVD utilization i duble w AFTER. Δ DVD to dodatkowe zagrane nuty w izolowanym 3→4 DVD.

| MIDI | BEFORE played/drop/rate | AFTER played/drop/rate | DVD1/2/3/4 % | DVD duble | Δ DVD 3→4 |
|---|---|---|---|---:|---:|
| 0002-02-radiohead_1993-creep-[k] (2).mid | 3259/0/0.00% | 3259/0/0.00% | 3.5/3.2/3.0/3.2 | 114 | 0 |
| 0031-12-radiohead_1995-street_spirit_(fade_out)-[k].mid | 1829/0/0.00% | 1829/0/0.00% | 7.5/2.7/3.6/1.3 | 59 | 0 |
| 0032-01-radiohead_1997-airbag-[k].mid | 3635/12/0.33% | 3637/10/0.27% | 5.8/4.5/2.4/3.2 | 120 | 2 |
| 0036-05-radiohead_1997-let_down-[k].mid | 4318/939/17.86% | 4624/633/12.04% | 76.0/70.4/62.8/65.3 | 746 | 306 |
| 0041-10-radiohead_1997-no_surprises-[k] (2).mid | 4092/600/12.79% | 4374/318/6.78% | 64.4/60.1/58.9/59.0 | 618 | 282 |
| 0054-02-radiohead_2001-pyramid_song.mid | 1876/45/2.34% | 1921/0/0.00% | 82.0/78.6/34.3/34.8 | 364 | 45 |
| 0063-01-radiohead_2003-2+2=5-[k].mid | 4275/570/11.76% | 4465/380/7.84% | 44.6/40.0/37.8/37.1 | 863 | 190 |
| 0071-09-radiohead_2003-there_there-[k].mid | 3746/288/7.14% | 3877/157/3.89% | 44.2/39.1/34.3/33.6 | 316 | 131 |
| 0080-02-radiohead_2007-bodysnatchers-[k] (2).mid | 7327/163/2.18% | 7396/94/1.26% | 48.5/42.4/38.5/37.2 | 979 | 69 |
| 0081-03-radiohead_2007-nude.mid | 1861/174/8.55% | 1973/62/3.05% | 31.1/29.9/29.5/29.2 | 239 | 112 |
| 0087-09-radiohead_2007-jigsaw_falling_into_place (2).mid | 4997/382/7.10% | 5194/185/3.44% | 69.3/65.0/58.9/60.9 | 1425 | 197 |
| Mitski - Washing Machine Heart (cover) [MIDIfind.com].mid | 927/0/0.00% | 927/0/0.00% | 0.0/0.0/0.0/0.0 | 0 | 0 |
| Pink - Try [MIDIfind.com].mid | 5477/463/7.79% | 5614/326/5.49% | 81.1/72.3/63.3/62.0 | 999 | 140 |
| Pink_Floyd_-_Time.mid | 3046/296/8.86% | 3115/227/6.79% | 14.0/12.5/12.1/12.0 | 540 | 69 |
| Queen - Bohemian Rhapsody (2).mid | 4348/463/9.62% | 4501/310/6.44% | 23.7/20.9/18.4/19.1 | 671 | 154 |
| Radiohead — Sail to the Moon [MIDIfind.com] (1) (2).mid | 1477/14/0.94% | 1491/0/0.00% | 34.6/27.0/24.8/24.1 | 211 | 14 |
| Stay_Shakespears_Sister.mid | 1876/241/11.38% | 1942/175/8.27% | 15.9/13.4/12.7/12.8 | 116 | 66 |
| range-test.mid | 73/0/0.00% | 73/0/0.00% | 0.0/0.0/0.0/0.0 | 0 | 0 |
| test.mid | 54/0/0.00% | 54/0/0.00% | 0.0/0.0/0.0/0.0 | 0 | 0 |

### Perkusja / tacki, AFTER

| MIDI | Percussion events | Tray candidates | Played | Busy/cooldown | Sampled | Source dropped | Tray1/2 % | GM: events |
|---|---:|---:|---:|---:|---:|---:|---|---|
| 0002-02-radiohead_1993-creep-[k] (2).mid | 1266 | 120 | 35 | 12 | 73 | 0 | 1.15/1.08 | 49: 20, 57: 15 |
| 0031-12-radiohead_1995-street_spirit_(fade_out)-[k].mid | 1793 | 17 | 9 | 0 | 1 | 7 | 0.33/0.27 | 55: 4, 57: 4, 49: 1 |
| 0032-01-radiohead_1997-airbag-[k].mid | 3669 | 171 | 6 | 0 | 37 | 128 | 0.24/0.20 | 49: 5, 57: 1 |
| 0036-05-radiohead_1997-let_down-[k].mid | 2033 | 20 | 16 | 0 | 0 | 4 | 0.42/0.45 | 57: 16 |
| 0041-10-radiohead_1997-no_surprises-[k] (2).mid | 740 | 28 | 21 | 0 | 7 | 0 | 1.04/0.95 | 49: 21 |
| 0054-02-radiohead_2001-pyramid_song.mid | 582 | 17 | 17 | 0 | 0 | 0 | 0.49/0.44 | 49: 17 |
| 0063-01-radiohead_2003-2+2=5-[k].mid | 1569 | 138 | 130 | 0 | 8 | 0 | 3.86/3.86 | 57: 130 |
| 0071-09-radiohead_2003-there_there-[k].mid | 4471 | 13 | 7 | 0 | 1 | 5 | 0.22/0.19 | 49: 7 |
| 0080-02-radiohead_2007-bodysnatchers-[k] (2).mid | 1874 | 7 | 4 | 0 | 2 | 1 | 0.15/0.15 | 49: 4 |
| 0081-03-radiohead_2007-nude.mid | 784 | 16 | 11 | 0 | 5 | 0 | 0.42/0.35 | 49: 6, 57: 4, 59: 1 |
| 0087-09-radiohead_2007-jigsaw_falling_into_place (2).mid | 2082 | 16 | 10 | 0 | 0 | 6 | 0.43/0.45 | 49: 7, 55: 2, 57: 1 |
| Mitski - Washing Machine Heart (cover) [MIDIfind.com].mid | 0 | 0 | 0 | 0 | 0 | 0 | 0.00/0.00 | — |
| Pink - Try [MIDIfind.com].mid | 1167 | 354 | 22 | 0 | 332 | 0 | 0.90/0.90 | 57: 11, 49: 11 |
| Pink_Floyd_-_Time.mid | 2802 | 71 | 58 | 0 | 12 | 1 | 2.06/2.06 | 46: 58 |
| Queen - Bohemian Rhapsody (2).mid | 1114 | 175 | 108 | 1 | 66 | 0 | 4.77/4.77 | 49: 65, 46: 28, 57: 13, 55: 2 |
| Radiohead — Sail to the Moon [MIDIfind.com] (1) (2).mid | 466 | 11 | 8 | 2 | 1 | 0 | 0.27/0.27 | 55: 6, 49: 2 |
| Stay_Shakespears_Sister.mid | 1238 | 117 | 83 | 2 | 18 | 14 | 4.28/4.18 | 57: 8, 49: 4, 46: 66, 55: 5 |
| range-test.mid | 0 | 0 | 0 | 0 | 0 | 0 | 0.00/0.00 | — |
| test.mid | 0 | 0 | 0 | 0 | 0 | 0 | 0.00/0.00 | — |

## Ocena

1. Izolowane 3→4 DVD: 1777 dodatkowych normalnych nut, drop rate 7,37%→4,56% (−2,81 pp). Reinforcement 5012→8380 zdarzeń, 765,095→1256,793 s. Faktyczny BEFORE miał już cztery DVD, więc żadnej poprawy BEFORE→AFTER nie przypisujemy nowemu DVD.
2. Największa korzyść czwartego DVD: 0036-05-radiohead_1997-let_down-[k].mid (+306); 0041-10-radiohead_1997-no_surprises-[k] (2).mid (+282); 0087-09-radiohead_2007-jigsaw_falling_into_place (2).mid (+197); 0063-01-radiohead_2003-2+2=5-[k].mid (+190); Queen - Bohemian Rhapsody (2).mid (+154).
3. Tacki: 1291 kandydatów, 545 kopii, 17 odrzuconych busy/cooldown, 563 pominiętych samplingiem, 166 niezagranych przez normalny routing. 27 650 normalnych perkusyjnych zdarzeń. Małe utilization (~1,25% każdy motor) jest zgodne z rolą akcentów.
4. Jedna tacka 499 kopii, dwie 545: +46 (+9.22%). Rozkład dwóch: 276/269 ruchów, 55,685/54,523 s. Druga pomaga w bliskich akcentach, korzyść jest umiarkowana.
5. Najlepsze w tym modelu: 57 Crash 2 (203), 49 Crash 1 (170), 55 Splash (19). 46 tylko próbkowane mocne akcenty (152); 59 sporadyczny ride (1). To wynik selekcji programowej, nie pomiar fizycznego dźwięku.
6. Czasy zgodne z zadanym eksperymentem, wszystkie ESTIMATED. Nie zostały potwierdzone pomiarem fizycznego napędu. Przed hardware trzeba skalibrować czas impulsu, kierunek, recovery i dźwięk. Model nie symuluje pełnej geometrii i położenia tacki.
7. Liczba DVD/tray pochodzi z konfiguracji/listy instancji; logika nie wymaga dokładnie czterech. Normalna polifonia pozostaje niezależna od akcentów.

## Weryfikacja

- Backend: 340 testów, OK, bez pominięć po udostępnieniu lokalnego zbioru MIDI.
- Frontend: 67 testów, OK. Typecheck OK. Build OK.
- Lint: npm run lint próbowano; Missing script: lint. Repo nie ma skonfigurowanego lintera. git diff --check OK.
- Istniejące scripts/benchmark.py i benchmark_dvd.py uruchomione na wszystkich 31 plikach; benchmark_dvd_reinforcement.py na 19 unikalnych. Wszystkie zakończone kodem 0. benchmark_dvd zachowuje historyczny skład 7/11 przez jawne parametry.
- Dodatkowy benchmark_tray.py: pełny zbiór, BEFORE/AFTER, tray ON/OFF, 3/4 DVD, 1/2 tacki. JSON zawiera wszystkie metryki per utwór.
- Przeglądarka http://127.0.0.1:8001/: widoczne urządzenia, przełączniki, wybór dynamic reinforcement zweryfikowany. Podgląd uruchomiony z --no-hardware.
- Bez zmian firmware/protokołu i bez commita.

## Zmienione pliki

| Plik | Zmiana |
|---|---|
| `host/playback/orchestra.py` | Konfigurowalne liczby i domyślny skład/IDs, trayEnabled. |
| `host/playback/capabilities.py` | Tray jako reinforcement-only, bez articulation tonalnej. |
| `host/playback/allocator.py` | Wykluczenie tray z normalnych slotów, wywołanie małego passu. |
| `host/playback/tray.py` | Selekcja GM, busy/cooldown/sampling/lookahead, deterministyczny model dźwięku. |
| `host/playback/performance.py` | Osobne TrayEvent i raport; kopie nie liczą się jako nuty MIDI. |
| `host/playback/virtual.py` | Profil, renderer audio, activity/statusy; tray tylko virtual; DVD bez ograniczenia do 4. |
| `host/playback/engine.py` | Utrwalenie toggle, osobne trayNotes i trayStatus. |
| `web/src/types.ts` | Pola config/status/notes dla UI. |
| `web/src/components/VirtualOrchestra.tsx` | Konfigurowalny DVD mode, checkbox tray, statusy i czytelny raport. |
| `web/src/components/ArrangementEditor.tsx` | Kopie tylko device/simulation; normalne destination bez tray. |
| `web/src/components/PianoRoll.tsx` | Przerywany obrys kopii. |
| `web/src/App.test.tsx` | Test przełącznika i danych ruchu; etykieta DVD. |
| `host/tests/test_tray.py` | 8 nowych testów inwariantów, sound, engine i konfiguracji. |
| `host/tests/test_dvd_experiment.py` | Historyczne testy 3 FDD/3 HDD, nowe DVD IDs i zmienna liczba. |
| `host/tests/test_auto_arranger.py` | Oczekiwany docelowy skład. |
| `scripts/benchmark_tray.py` | Reprodukowalny pełny benchmark. |
| `scripts/benchmark_dvd.py` | Jawny historyczny skład, nadal porównanie 7/11. |
| `benchmarks/dvd-tray.json` | Wszystkie warianty i unikalne MIDI. |
| `benchmarks/dvd-reinforcement-target.json` | Istniejący A/B na nowym składzie. |
| `benchmarks/auto-arranger-target.txt` | Wyniki istniejącego suite. |
| `benchmarks/dvd-7-vs-11-rerun.json` | Powtórzony historyczny benchmark. |
