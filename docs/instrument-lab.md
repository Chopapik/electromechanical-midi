# Instrument Lab

Otwórz `http://127.0.0.1:5173/` i wybierz **INSTRUMENT LAB** w nagłówku.
Nie trzeba ładować MIDI. Powrót do **ORKIESTRA** kończy test.

1. Wybierz fizyczne, włączone urządzenie.
2. Dla FDD/DVD/VHS podaj Hz i czas (domyślnie 3 s, maksymalnie 30 s).
3. Kliknij PLAY. `starting` oznacza oczekiwanie na STATUS firmware;
   `playing` pojawia się dopiero po potwierdzeniu. STOP działa również podczas startu.
4. Po odsłuchu zapisz NORMAL, RESONANCE lub STRONG_RESONANCE.
   Historia jest lokalna dla przeglądarki (`instrument-lab-ratings-v1`);
   przycisk JSON eksportuje device, Hz, czas, ocenę i datę.

## Urządzenia i ograniczenia

- FDD1–4: istniejący fizyczny profil Hz i stan HOME. W razie braku HOME wróć
  do ustawień orkiestry i użyj istniejącej funkcji Home.
- DVD1–4: istniejący Sled::tick(), rampy, odbicia i limit 140 kroków.
  Po restarcie firmware mechanizm trzeba ręcznie ustawić w pozycji początkowej.
  Licznik nie mierzy położenia fizycznego. DVD1 respektuje measured allowedBandsHz;
  zakazana częstotliwość jest odrzucana, a nie składana oktawowo w teście ręcznym.
- VHS: AMP 0–255 i dotychczasowy hostowy zakres 20–2000 Hz.
  To częstotliwość sterowania, nie pomiar wysokości dźwięku.
- HDD1–4: pojedynczy HIT, bez generatora tonalnego. PARK/SETTLE/STRIKE oraz
  regeneracja pozostają w istniejącym firmware/profilu. Backend dodatkowo
  zachowuje historię uderzeń i respektuje nominalStartToStartMs oraz limity gęstości.
- TRAY: PULSE FWD/REV tylko dla zadeklarowanego, włączonego sprzętu.
  Maksimum wynika z istniejącego strongMaxMs profilu, dodatkowo ograniczone
  protokołem; respektowany jest cooldown. Obecny inventory nie deklaruje TRAY,
  więc pola tych urządzeń pozostają niedostępne.

## Bezpieczeństwo i transport

Lab używa tego samego PlaybackEngine, WebSocketu oraz połączenia ESP32 co player.
Nie otwiera drugiego połączenia BLE/Serial. Identyfikator sesji nadaje backend.
Jedna sesja i jeden test mogą sterować sprzętem. MIDI, zmiany konfiguracji oraz
upload firmware są blokowane w trakcie sesji Lab.

Backend trzyma deadline w zegarze monotonicznym. STOP używa istniejącego
potwierdzanego ALL STOP i priorytetu BLE, który usuwa zaległe komendy.
Wyjście z widoku, zamknięcie WebSocketu, utrata kontrolera i shutdown kończą test.
Heartbeat sesji jest wysyłany co 2 s; po 6 s bez niego backend kończy sesję.
Ponowne wejście nie uruchamia poprzedniego testu.

Dla krótkiego HDD HIT / TRAY PULSE czas impulsu kontroluje firmware. Backend
czeka na pełny STATUS po komendzie; zakończony już impuls nie oznacza błędu PLAY.
Dodatkowy deadline (minimum 3 s) ogranicza oczekiwanie na potwierdzenie przez BLE.
Dla tonu deadline odlicza się od wysłania komendy. Opóźnienie transportu i
potwierdzenia STOP może powodować różnicę między zadanym czasem i czasem
odebrania końcowego statusu przez UI; nie jest to pomiar fizycznej długości tonu.

Nie zmieniono firmware, arrangera, alokatora ani algorytmów ruchu.

## Zmienione pliki

- Backend: `host/playback/instrument_lab.py`, `host/playback/engine.py`,
  `host/orchestra_link.py`, `host/web/server.py`.
- Frontend: `web/src/components/InstrumentLab.tsx`, `web/src/App.tsx`,
  `web/src/usePlayer.ts`, `web/src/types.ts`, `web/src/styles.css`,
  `web/package.json`, `web/package-lock.json`.
- Testy: `host/tests/test_instrument_lab.py`,
  `web/src/components/InstrumentLab.test.tsx`.
- Dokumentacja: `docs/instrument-lab.md`.

## Test na podłączonym ESP32 (2026-10-08)

Przez istniejący runtime BLE sprawdzono DVD1 392 Hz / 3 s, automatyczny STOP,
wcześniejszy STOP, odmowę 220 Hz, pojedynczy HDD1 HIT, zamknięcie sesji podczas
pracy i ponowne wejście bez autoplay. ESP32 potwierdził uruchomienie DVD i
zatrzymanie przez istniejące ALL STOP z tokenem. Końcowy stan dotarł przez
WebSocket po około 3,25 s od kliknięcia testu 3 s (obejmuje BLE i publikację UI).
To weryfikacja komend/statusu rzeczywistego kontrolera, nie pomiar akustyczny.
Nie wgrywano firmware, ponieważ nie zostało zmienione.
