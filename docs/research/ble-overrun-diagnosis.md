# BLE realtime overrun — diagnoza 2026-10-26

Punkt wejścia: `524fb85`. [Dane i pełny ślad pomiarowy](../../reports/ble-overrun-diagnosis-2026-10-26.json).
Badano sporadyczne przerwania z komunikatem `253 ms delivery lag, 4 queued`.
Odczyt działającej aplikacji wskazał późniejszy błąd `252 ms, 0 queued` w
`badapple!!midifull-1.mid`, preset `fdd_legato`, pozycja 102,292 s.
W tym stanie wyciszone były FDD2–8; poziomy speakerów REAL wynosiły 128.

## Co zmierzono

Przed próbą zatrzymano kontener aplikacji, aby drugi klient nie konkurował o BLE.
Przeładowano natywną bramkę z pomiarem etapów zapisu. Probe wysyłał wyłącznie
`PING` oraz skorelowany `ALL STOP`: bez PLAY, HOME, HIT, poleceń POWER i uploadu.
Nie uruchomiono instrumentów ani dźwięku. Ustawień ATX nie zmieniano.

Planowano 120 s / 1200 PING przy nominalnym odstępie 100 ms. **Próba przerwała
się po pierwszym błędzie, po 26,372 s i 248 poprawnych PONG.** Nie ponawiano jej.
Wynegocjowany payload potwierdzanego zapisu wynosił 252 bajty; błędny zapis miał
tylko 5 bajtów: `PING\n`.

| Pomiar | Wynik | Zakres interpretacji |
| --- | ---: | --- |
| Średnie RTT | 63,860 ms | 248 poprawnych PING/PONG, razem z odpowiedzią notify |
| RTT p50 / p95 / p99 | 59,658 / 105,655 / 168,768 ms | Wyłącznie udane odpowiedzi |
| Maksymalne poprawne RTT | 228,236 ms | Nie obejmuje nieudanego 249. zapisu |
| Kolejka przy błędzie | 0 linii | Nie wystąpiła lawina oczekujących poleceń |
| Oczekiwanie na worker | 0,132 ms | Kolejka executora bramki |
| Oczekiwanie na pętlę BLE | 0,213 ms | Od zlecenia zapisu do wejścia w coroutine |
| Oczekiwanie na write lock | 0,007 ms | Przed zapisem GATT |
| Oczekiwanie na `write_gatt_char(..., response=True)` | **250,959 ms** | Stos CoreBluetooth/OS, transmisja i stos peryferium; bez ich dalszego rozdzielenia |
| Opóźnienie obserwatora bramki | 0,421 ms | Maksimum całej tej sesji: 2,013 ms |
| Wiek komendy wykryty przez guard | około 252 ms | Próg pozostaje 250 ms |

Początkowy `ALL STOP token` otrzymał `STOPPED token`. Końcowy skorelowany STOP
**nie został potwierdzony**, ponieważ sesję zakończył błąd. Bramka wykonała
istniejącą próbę awaryjnego ALL STOP; nie utożsamiamy jej z potwierdzeniem.
Żaden instrument nie dostał w tej próbie polecenia startu.

## Wniosek i niepewności

Odtworzony błąd nie wymaga MIDI, komend instrumentów ani przepełnionej kolejki.
Większość opóźnienia przypada na zakończenie pojedynczego zapisu GATT. Limit
250 ms zadziałał prawidłowo; podniesienie go dopuściłoby większe spóźnienia.
Nie znaleziono dowodu, że wszystkie wcześniejsze błędy miały tę samą przyczynę.

Nie ustalono jeszcze, która część tego etapu opóźnia odpowiedź: radio/retransmisje,
stos ESP32, CoreBluetooth czy obsługa callbacku w lokalnym wątku BLE. W próbie
mierzono responsywność pętli **bramki**, a nie responsywność pętli **wątku BLE
podczas trwania await**. Ta druga obserwacja została dodana po próbie; przyszły
`BLE_TIMING` zawiera `transportWrites.bleLoop`. Nie jest pomiarem już wykonanej próby.
Nie zmierzono RSSI, connection interval, peripheral latency ani HCI. Nie badano
wpływu pracujących silników, zakłóceń od ich zasilania czy długiej sesji koncertowej.

## Obciążenie Bad Apple — wyłącznie offline

Rozwinięto istniejący ExecutionTimeline przez produkcyjne formatowanie RealOutput
na atrapie linku, z odczytanymi wyciszeniami i poziomami. Nie wysyłano tych komend.
Zarejestrowano 10 385 linii wykonawczych w całym utworze. Maksima: 14 linii / 10 ms,
15 / 100 ms i 95 / 1 s. W przedziale ±1 s wokół błędu było 54 linie, czyli około
27/s. Liczby nie uwzględniają okresowego PING, pakowania TCP/GATT ani rzeczywistego
harmonogramu systemu. To nie benchmark przepustowości radia i nie dowód braku
przeciążenia we wszystkich fragmentach; pojedynczy PING również odtworzył problem.

## Dodane narzędzia

- `ble_diagnostics.WriteTrace/WriteHistory`: ostatnie 64 zapisy, etapy dispatch,
  worker, pętla BLE, mutex i await GATT. Podgląd maksymalnie 8 komend zapisu;
  pamięć i liczba pól są ograniczone. `LoopTiming` wykrywa również zatrzymanie
  pętli BLE, zanim zdąży ona ponownie wykonać obserwator.
- `BLE_TIMING`: jeden rekord JSON przy błędzie sesji, z ostatnimi zapisami,
  kolejką i opóźnieniami pętli. Logi natywnej bramki mają datę i czas. Brak
  logowania w callbacku odbioru danych i brak zmian callbacków firmware.
- [probe_ble_ping.py](../../scripts/probe_ble_ping.py): test bez komend ruchu
  ani zasilania; blokuje start przy otwartym porcie aplikacji, wymaga początkowego
  STOP ACK, przerywa po pierwszym błędzie i nie uznaje go za końcowy STOP ACK.
  [Procedura](../HARDWARE_TESTING.md#cichy-test-ble-pingpong).

Na etapie powyższej diagnozy nie zmieniono aranżera, częstotliwości, motor timing, firmware, progu 250 ms,
limitu 512 linii, `response=True`, priorytetu STOP ani zasad reconnect.
**To diagnoza i narzędzia pomiarowe, nie naprawa ani gwarancja niezawodności BLE.**

## Kolejny krok

1. Odczytać rzeczywiste connection interval / latency / RSSI i porównać je ze
   śladem pętli BLE. W obecnym firmware tych danych nie raportujemy; samo MTU
   nie odpowiada na to pytanie. Nie zgadywać parametrów na podstawie RTT.
2. W oddzielnej, kontrolowanej próbie porównać warunki radiowe i profil połączenia.
   Apple opisuje zależności parametrów i zaznacza, że central decyduje o ich
   akceptacji: [QA1931](https://developer.apple.com/library/archive/qa/qa1931/index.html),
   [wyjaśnienie Apple](https://developer.apple.com/forums/thread/822187).
3. Jeżeli pomimo dostrojenia występują takie przerwy, odporność wykonania wymaga
   rozważenia bufora poleceń ze znacznikami czasu w ESP32 lub transportu przewodowego.
   Bufor wymaga osobnego projektu synchronizacji i zachowania natychmiastowego
   STOP, watchdoga, ograniczonej pojemności i kasowania starej sesji. Nie jest
   równoważny zwiększeniu dopuszczalnego wieku spóźnionej komendy.

## Weryfikacja oprogramowania

931 testów hosta PASS, w tym testy etapów pomiaru, ograniczonej pamięci,
rozpoznawania BLE ERROR, priorytetu STOP, pakowania ATT i cichego probe. Guard
architektury obejmuje 57 modułów i przeszedł. Kod firmware, konfiguracja urządzeń
i frontend nie zostały zmienione. Przebudowa aplikacji i restart natywnej bramki
służą wdrożeniu pomiarów; nie stanowią naprawy opóźnienia GATT.

Po wdrożeniu kontener jest healthy, a hashe wdrożonych modułów są identyczne
z lokalnymi. Przywrócono Bad Apple, preset FDD Legato, wyciszenia FDD2–8 i
wstrzymaną pozycję 102,292 s. Odtwarzania nie wznawiano. ExecutionTimeline
jest identyczny przed i po wdrożeniu; fingerprint znajduje się w raporcie.

## Poprawka transportu — 2026-10-27

Przed przeładowaniem bramki istniejący heartbeat aplikacji zarejestrował jeszcze
przerwanie w trybie legacy: PING miał 168,570 ms oczekiwania na pętlę BLE i
86,598 ms w GATT (guard zgłosił 264 ms). Maksymalny lag pętli BLE w tej sesji
wyniósł 162,696 ms. To dodatkowy dowód udziału lokalnego harmonogramu OS,
obok wcześniejszego przypadku dominującego oczekiwania GATT. Nie uruchamiano
w tym celu osobnej próby instrumentów. Nowa ścieżka nie eliminuje zatrzymań OS.

Przygotowano nową ścieżkę w host i firmware: ograniczona grupa komend z
końcową barierą `SYNC <token>`, write without response oraz osobny notify
`SYNCED <token>` po przetworzeniu wcześniejszych bajtów przez dispatcher ESP32.
Nie wystarcza samo przyjęcie danych przez CoreBluetooth. Następna grupa czeka
na zgodny ACK; brak odpowiedzi w 250 ms oznacza przerwanie sesji, jedną próbę
awaryjnego STOP i brak ponawiania nut. Guard bramki nadal obejmuje całkowity
wiek komendy od jej przyjęcia, włącznie z czekaniem w kolejce.

Przy MTU=23 grupa z footerem zajmuje najwyżej sześć slotów RX z istniejących
ośmiu. Większe batch'e dzielą się na pełnych liniach; nie zmieniają kolejności
ani treści komend muzycznych. Jedna blokada obejmuje wszystkie grupy batcha.
ACK ma odrębną charakterystykę i ograniczoną kolejkę, obsługiwaną między
fragmentami STATUS, więc nie wstawia się do środka linii NUS. ACK powstaje
w loopTask, nie w callbacku RX. RX overflow unieważnia ACK do nowej sesji.
SYNC nie steruje instrumentami, nie odświeża watchdoga i nie zastępuje
STOPPED/POWER ani odpowiedzi ERR. Zachowano mapę GPIO, timing impulsów,
aranżację, limit 512 linii, próg 250 ms i brak automatycznego wznowienia.

Nowy host wybiera ścieżkę dopiero po odkryciu charakterystyki ACK i sprawdzeniu
pustej bariery. Starsze firmware zachowuje ATT response; bramka loguje wybrany
tryb. Reklamowana, ale niesprawna charakterystyka kończy połączenie błędem;
nie przełączamy wtedy w tryb bez potwierdzeń. Anulowanie oczekującego zapisu
przy disconnect nie pozostawia zadań w zamykanej pętli BLE.

**Zakres potwierdzenia:** testy offline symulują opóźnione ATT Write Response
przy dostępnym ACK peryferium; nowa ścieżka nie czeka na to ATT response.
Sprawdzają również brak/błędny/duplikowany ACK, MTU=23, niezależny limit NR,
fragmentację STATUS, RX overflow, reconnect, STOP i nieodświeżanie watchdoga.
944 testy hosta (w tym produkcyjny C++/protokół/adapter) PASS; 34 skupione
testy BLE PASS; guard architektury 57 modułów PASS; build PlatformIO ESP32 PASS.
[Raport walidacji poprawki](../../reports/ble-execution-ack-validation-2026-10-27.json).

**Nie przeprowadzono jeszcze próby nowego trybu na fizycznym ESP32 i nie
stwierdzamy, że wszystkie zaniki radiowe zostały usunięte.** Fizyczne ESP32
nie zostało w tym etapie flashowane; wymaga osobnej zgody, USB i safe upload.
Usunięto zależność od zmierzonego miejsca oczekiwania ATT; nie dowiedziono,
że ACK będzie terminowy w tych samych warunkach radiowych. Po uploadzie
należy najpierw porównać cichy PING/PONG w `delivery=execution-ack`, z tym samym
limitem 250 ms. Dopiero później oceniać odtwarzanie muzyki. Instrumentów ani ATX
nie uruchamiano w ramach weryfikacji tej poprawki.
