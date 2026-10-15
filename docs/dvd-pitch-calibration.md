# Kalibracja wysokości DVD 1–3 — hipoteza 2026-10-11

Tuner gitarowy wskazał około 100 Hz przy zadanych 200 Hz i około 250 Hz przy zadanych 500 Hz. To sugeruje stosunek akustycznych Hz do kroków/s równy 0.5. Tuner może jednak rozpoznawać oktawę lub harmoniczną: nie jest to precyzyjny pomiar widmowy ani potwierdzenie indywidualnej charakterystyki każdego silnika.

W `config/hardware-profiles/instances.json` instancje `SLED:1`, `SLED:2`, `SLED:3` mają `pitchRatio=0.5`, `evidenceType=HYPOTHESIS`, `confidence=LOW`. Profil ogólny i DVD 4 pozostają przy 1.0. FDD oraz inne instrumenty pozostają bez zmian.

## Interpretacja

`pitchRatio = acousticHz / stepsPerSecond`, więc `stepsPerSecond = acousticHz / pitchRatio`.

| Żądane Hz akustyczne | pitchRatio | Docelowe kroki/s | Okres kroku |
|---:|---:|---:|---:|
| 200 | 0.5 | 400 | 2500 µs |
| 500 | 0.5 | 1000 | 1000 µs |

Przepływ:

1. PerformancePlan i kompilator zachowują akustyczne Hz.
2. `RealOutput.configure()` wysyła `SLED n PROFILE 0 5000 0.5` dla DVD 1–3. Zero oznacza ciągły obrót; 5000 to zachowana rampa w krokach/s².
3. `RealOutput.dispatch()` wysyła nieprzeskalowane `SLED n PLAY 200.00` lub `500.00`.
4. ESP32 `Sled::play()` wykonuje jedno dzielenie przez `pitchRatio`. Rampa dochodzi do docelowych 400 lub 1000 kroków/s.
5. Ocena hardware hosta używa tego samego dzielenia; symulacja ruchu odtwarza akustyczne Hz jako `abs(currentStepRate) * pitchRatio`. Wyjście Web Audio otrzymuje żądane akustyczne Hz, nie częstotliwość kroków.

Nie zmieniono kodu aranżacji muzycznej, alokacji, UNISON, transpozycji, UI ani GPIO. Limit 100 µs / 10 000 kroków/s nadal obowiązuje; dla ratio 0.5 odpowiada maksymalnym 5000 Hz akustycznych w reprezentacji timera. Aktualny allocator ma niezależny, znacznie niższy sufit muzyczny 600 Hz akustycznych i składa wyższe tony o oktawy. Żaden z tych limitów nie jest pomiarem termicznym. Historyczne 140 kroków i pasma nie są aktywowane. STOP, watchdog i rampa pozostają bez zmian.

## Zastosowanie

Po przebudowie i restarcie Dockera aplikacja wczyta nowe profile. Przy następnym przygotowaniu urządzeń do odtwarzania lub testu wyśle konfigurację ratio przez istniejące polecenie `PROFILE`. Dla już zainstalowanego firmware obsługującego profile sprzętowe i ciągły obrót **ponowne flashowanie nie jest wymagane**.

Nagłówek `hardware_profiles_generated.h` został zregenerowany, aby przyszłe buildy firmware miały takie same wartości domyślne. Bez aplikacji starszy firmware zachowa dotychczasowe wartości aż do otrzymania `PROFILE`; w takim użyciu trzeba wysłać konfigurację albo wgrać nowy build.

Weryfikacja offline: 501 testów backendu, w tym produkcyjny rdzeń C++ z atrapą zegara/GPIO; kontrola zgodności wygenerowanego nagłówka; kompilacja ESP32 przez PlatformIO — wszystkie poprawne. Nie wykonano flashowania ani ruchowych testów sprzętu.
