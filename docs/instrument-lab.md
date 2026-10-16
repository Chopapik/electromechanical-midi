# Instrument Laboratory

Wejście: **Settings (`/settings`) → Laboratory → Laboratory · debug**.
Aplikacja wraca na `/` i przełącza właściciela wspólnego Playera na `lab`.
Nie trzeba ładować MIDI. **Wróć do Orkiestry** kończy sesję bez autoplay.

1. Wybierz włączone urządzenie z zatwierdzonym profilem.
2. Podaj Hz i czas: domyślnie 1 s, zakres 0,1–10 s. UI startuje z 200 Hz,
   po wyborze urządzenia proponuje początek widocznego pasma, jeśli istnieje.
3. Kliknij **Uruchom test**. Test trafia do wspólnego ExecutionTimeline/Playera,
   Routera i aktualnego wyjścia REAL lub VIRTUAL. REAL wymaga BLE, konfiguracji
   oraz HOME dla FDD. Odrzucenie przez profil nie jest składane oktawowo przez lab.
4. **Stop** przerywa test. Samo upłynięcie zadanej długości tonu też wysyła STOP.

Źródło: `host/runtime/laboratory.py` i `web/src/App.tsx`. Nie ma obecnie panelu
ocen NORMAL/RESONANCE, historii ocen ani eksportu JSON dawnego Instrument Lab.

## Ograniczenia i sesja

FDD korzysta z aktywnego profilu i TRACK0. DVD1–4 używają ciągłego obrotu,
rampy i pitchRatio; historyczny limit drogi 140 kroków ani whitelist sweepu
DVD1 nie obowiązują w tym trybie. Sufit 600 Hz to polityka automatycznej
aranżacji, nie folding ręcznego testu. PC Speaker/FX korzystają z ustawień
fali oraz gain/duty. HDD test to pojedynczy HIT, nie ton: historię hitów i
odstęp sprawdza profil, czas impulsów wyznacza firmware.

Lab nie otwiera drugiego transportu. Tylko aktualna sesja WebSocket może
uruchomić test; heartbeat `sync` odnawia lease 3 s (przeglądarka wysyła go co
200 ms). Utrata sesji, wygaśnięcie lease lub zmiana właściciela kończy wykonanie.
DeviceService przejmuje wyłączne sterowanie po STOP. Potwierdzany STOP REAL i anulowanie Web Audio pozostają wspólne.

Skończony test i STATUS nie są pomiarem dźwięku ani bezpieczeństwa ciągłej pracy.
Zmierz temperaturę/prąd i sprawdź faktyczny układ przed długimi próbami;
[zasilanie i niepewności](esp32-orchestra.md#power-supplies-and-evidence).

## Historyczna weryfikacja poprzedniego Lab

Poniższy zapis dotyczy wcześniejszej implementacji, która egzekwowała pasma
DVD1 i miała inny panel sesji; odmowa 220 Hz nie jest regułą obecnego trybu ciągłego.

## Test na podłączonym ESP32 (2026-10-08)

Przez istniejący runtime BLE sprawdzono DVD1 392 Hz / 3 s, automatyczny STOP,
wcześniejszy STOP, odmowę 220 Hz, pojedynczy HDD1 HIT, zamknięcie sesji podczas
pracy i ponowne wejście bez autoplay. ESP32 potwierdził uruchomienie DVD i
zatrzymanie przez istniejące ALL STOP z tokenem. Końcowy stan dotarł przez
WebSocket po około 3,25 s od kliknięcia testu 3 s (obejmuje BLE i publikację UI).
To weryfikacja komend/statusu rzeczywistego kontrolera, nie pomiar akustyczny.
Nie wgrywano firmware, ponieważ nie zostało zmienione.
