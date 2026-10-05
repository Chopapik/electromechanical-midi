# Redesign workstation — raport

Zmiany lokalne na `main`, bez commita. Aplikacja uruchomiona pod http://127.0.0.1:5173/; backend pod http://127.0.0.1:8000/.

## Architektura i zachowane funkcje

1. `App` pokazuje jeden monitor: niski transport, Current Musical Event, Device Activity, Event Stream, Orchestra Load i dolny status. Konfigurację otwiera prawy Settings drawer o szerokości 440 px.
2. Główne zakładki PLAYER / ORCHESTRA / ARRANGEMENT, duży nagłówek, subtitle, dawne formularze i timeline zniknęły z głównego ekranu. Nie ma nawigacyjnego sidebara, napisu LIVE ani zdrowego statusu „backend connected”. Błąd połączenia backendu nadal jest widoczny.
3. Stare kontrolki PLAYER znajdują się w Settings → Advanced / Manual hardware: tracki FDD/VHS/HDD, transpozycja, strategia, filtr nut HDD, gęstość, manualny DrumPanel, reconnect/home i szczegóły HardwareStatus.
4. ArrangementEditor i PianoRoll pozostają w repozytorium. Reguły, auto arranger, importer i dotychczasowe API pozostają. Nie ma zwykłej zakładki Arrangement ani nowego Developer View. Import Arrangement JSON jest dostępny w Advanced.
5. Settings zachowuje wszystkie tryby tonalne RAW, ARTICULATED, EXTREME v1, EXTREME 1.5, EXTREME v2 oraz trzy warianty długości nut. Zachowane są HDD RAW/ARTICULATED, master volume 0–2000%, dynamic DVD reinforcement i tray enable.
6. Globalny Virtual instruments mode wysyła istniejące `set_virtual` z `config.enabled`. Per-device virtual / real / hybrid pozostają osobnymi ustawieniami. Reguły dostępności, w tym tylko virtual dla tray, są zachowane. Backendowe ograniczenie wyłączenia preview podczas gry bez podłączonego sprzętu również pozostaje.
7. Devices zachowuje Add / Duplicate / Remove, Save / Load preset, nazwę, rolę, track, volume, pan, mute, solo, transpose, gate, profile, mode i overrides wraz z provenance/source. Podsumowania urządzeń są zwartymi disclosure rows. Hardware lanes i pełny Simulation Report nadal są dostępne w Settings.
8. Samo otwarcie/zamknięcie Settings nie wysyła komend playback. Zmiany ustawień używają dotychczasowych akcji; UI nie dopisuje stop/seek ani nie resetuje pozycji.

## Źródła danych i wydajność

9. Dodano wyłącznie odczytowy `GET /api/telemetry`. Projekcja korzysta z już wygenerowanych AcousticEvent, PerformancePlan, artykulacji tonalnej/HDD, interwałów aktywności i raportu. Nie inicjalizuje ani nie zmienia planu, nie renderuje ponownie WAV i nie alokuje nut.
10. `useTelemetry` pobiera dane po zmianie pliku, revision lub trybu brzmienia. Nie pobiera pełnego planu przy każdym ticku pozycji. Stare odpowiedzi są odrzucane, a nieaktualne żądania anulowane. Brak danych daje `—` lub komunikat niedostępności.
11. Zdarzenia są indeksowane raz na zmianę danych: osobna posortowana lista na lane i wspólna lista onsetów. Aktywny event i pozycja w strumieniu są wyszukiwane binarnie.
12. Current Musical Event wybiera PRIMARY lead, potem ważniejszy PLUCKED PRIMARY (velocity ≥80, duration ≥250 ms, poza basem), HDD PRIMARY, pitch bend, reinforcement, tray i pozostałe zdarzenia. Remisy rozstrzyga velocity, długość i stabilny identyfikator. To wyłącznie heurystyka prezentacji.
13. Nuta pochodzi z faktycznego `hz` renderera, również dla reinforcement; nie jest surową nutą MIDI sprzed folding/transpozycji. Frequency curve jest interpolowana z jej rzeczywistych punktów. Monitor odświeża lokalnie pozycję i wskaźniki 20 razy/s, z limitem extrapolacji 200 ms. Settings i reszta aplikacji pozostają przy aktualizacjach WS.
14. Device Activity korzysta z aktualnego config i interwałów zdarzeń. PRIMARY i reinforcement są rozróżniane. HDD pokazuje istniejące SOFT_TAP, MEDIUM_HIT, HARD_HIT, DOUBLE_TAP, BUZZ_ROLL oraz GM note/velocity. Tray pokazuje faktyczny phase z player state, w tym MOVING/RECOVERY; recovery nie udaje ruchu. Pause/stop usuwa aktywność. Real lane wymaga rzeczywistego połączenia i przypisania sprzętowego.
15. Event Stream pokazuje maksymalnie 16 znaczących onsetów, najnowsze na górze. To zdarzenia zaplanowane w rendererze, nie osobny log potwierdzeń Arduino ani mikropróbki audio. Seek wstecz od razu przewija historię; stop czyści widoczny strumień.
16. Orchestra Load pokazuje statyczne wykorzystanie dla całego MIDI, opisane w UI. Dla tonalnych urządzeń używa raportowanego `activeTime`, dla HDD `busyTime`, podzielonych przez duration. Grupy są średnią po urządzeniach z ograniczeniem 0–100%. Brak raportu nie daje fikcyjnego zera. Metryka tonalna bazuje na normalnym czasie z istniejącego raportu, a nie dodaje czasu reinforcement. Reinforcement jest osobnym licznikiem zaplanowanych extras. Coverage = 1 − dropRate; played/drop pochodzą z istniejących totals.
17. Transport pokazuje dokładnie ▶ PLAYING / Ⅱ PAUSED / ■ STOPPED według `player.state`. Arduino status korzysta z `hardware.connected`, `connecting`, `pendingPlay`, portu i błędu. Bez podłączonego Arduino rzeczywista aplikacja pokazuje disconnected. Connected/homing/waiting są sprawdzone także w testach bez sprzętu.
18. Semantic classification, duplicate detection, allocator, articulation, PerformancePlan, reinforcement, routing, played/dropped i ścieżka audio nie zostały zmienione. Nowe API tylko czyta ich wynik. Source continuity i obecne domyślne ustawienia pozostają.

## Weryfikacja

| Sprawdzenie | Wynik |
|---|---|
| Frontend — `npm run test` | 105 testów, PASS |
| Frontend — `npm run typecheck` | PASS |
| Frontend — `npm run build` | PASS |
| Backend — `.venv/bin/python -m unittest discover -s host/tests` | 411 testów, PASS |
| `git diff --check` | PASS |
| Przeglądarka | 1280, 1440, 1920 px i tablet 768 px; bez poziomego overflow |

Istniejący test kliknięcia bloku PianoRoll czeka teraz na narysowanie mapy kliknięć, zamiast zależeć od tempa renderu. Sam PianoRoll i ArrangementEditor nie zostały zmienione.

Nie dodano lintera: projekt nie ma skonfigurowanego skryptu lint. Po restarcie przywrócono utwór, konfigurację i stan transportu; przeglądarka korzysta z uruchomionej nowej wersji.

## Zmienione i nowe pliki

- `host/playback/engine.py` — read-only telemetry projection.
- `host/web/server.py` — GET endpoint.
- `host/tests/test_web.py` — projekcja, rzeczywista krzywa pitch bend i brak mutacji planu/transportu.
- `web/src/App.tsx` — nowa kompozycja jednego ekranu.
- `web/src/App.test.tsx` — monitor, drawer, transport i zachowane akcje ustawień/manual controls.
- `web/src/styles.css` — workstation, drawer i responsive layout.
- `web/src/types.ts` — DTO telemetrii.
- `web/src/telemetry.ts` — indeksy, wyszukiwanie, interpolacja i wybór focusu.
- `web/src/telemetry.test.tsx` — rzeczywiste nuty, HDD, tray, seek, load i Arduino.
- `web/src/useTelemetry.ts` — pobieranie tylko przy zmianie planu.
- `web/src/useTelemetry.test.tsx` — cadence, stale responses i błędy odczytu.
- `web/src/components/TelemetryMonitor.tsx` — centralny event, tabela, strumień, load i statusbar.
- `web/src/components/SettingsDrawer.tsx` — prawy drawer, zamknięcie Escape i powrót focusu.
- `web/src/components/LegacyControls.tsx` — przeniesione dotychczasowe kontrolki.
- `web/src/components/MidiFileSelector.tsx` — kompaktowy wariant select/upload.
- `web/src/components/ProgressBar.tsx` — czas z dokładnością do dziesiątej sekundy; seek zachowany.
- `web/src/components/VirtualOrchestra.tsx` — sekcje Settings i zwarta lista urządzeń.
- `web/src/components/ArrangementEditor.test.tsx` — synchronizacja testu canvas.
- `docs/workstation-redesign.md` — ten raport.

## Synchronizacja wirtualnego audio

Wirtualny preview używa dostępnego lokalnie `ffplay` i jego zegara audio, uwzględniającego kolejkę wyjściową. Do pierwszego odczytu zegara po starcie/seek UI pozostaje na zadanej pozycji. Pozycja transportu i monitor korzystają z tego samego czasu; pauza zamraża wskazania. Jeśli `ffplay` nie jest dostępny, pozostaje dotychczasowy fallback `afplay` bez dokładnego zegara wyjścia.

`audioEvents` są projekcją końcowego planu WAV: uwzględniają release, skrócenia i tłumienie reinforcement. Zwykły PerformancePlan, routing, nuty i waveform nie są zmieniane. Telemetria jest odświeżana także po zakończeniu nowego renderu, bez cache HTTP; odpowiedzi z niezgodną wersją są ponawiane do trzech razy.

Dodatkowe pliki: `host/tests/test_audio_clock.py`, `web/src/usePlaybackPosition.ts`, `web/src/usePlaybackPosition.test.tsx`. Zmiany synchronizacji obejmują także `host/playback/virtual.py`, zegar i projekcję w engine oraz hook telemetrii i monitor. Podczas odtwarzania Jigsaw potwierdzono zgodność pozycji silnika i zegara audio oraz aktywne nuty, pitch bend i strumień zdarzeń w przeglądarce. Sprzętu fizycznego nie testowano.
